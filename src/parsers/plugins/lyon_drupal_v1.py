import re
import logging
from typing import List, Optional
import aiohttp
from bs4 import BeautifulSoup

from ..base import BaseParser
from ..factory import ParserFactory

logger = logging.getLogger(__name__)

@ParserFactory.register("lyon_drupal_v1")
class LyonDrupalV1Parser(BaseParser):
    """
    Parser pour les élus de la ville de Lyon et de ses arrondissements (Drupal).
    Gère trois structures distinctes:
    - Structure Trombinoscope : h1.elu-content-desktop (Maire) + .nom/.fonction (élus)
    - Structure Arrondissement : .organigramme-main + .organigramme__item
    
    Si la page cible ne contient aucun élu mais un lien vers le trombinoscope,
    le parser suit automatiquement ce lien (auto-redirect).
    """
    
    async def fetch(self, session: aiohttp.ClientSession) -> Optional[str]:
        """Surcharge de fetch pour gérer l'auto-redirect vers le trombinoscope."""
        html = await super().fetch(session)
        if not html:
            return None
        
        # Vérifier si la page contient des élus directement
        soup = BeautifulSoup(html, 'html.parser')
        has_elus = (
            soup.select('.views-row') or
            soup.select('.organigramme-main') or
            soup.select('.organigramme__item')
        )
        
        if has_elus:
            return html
        
        # Aucun élu trouvé : rechercher un lien vers le trombinoscope
        trombinoscope_link = soup.select_one('a[href*="trombinoscope"]')
        if trombinoscope_link:
            trombi_href = trombinoscope_link.get('href', '')
            if trombi_href:
                # Construire l'URL absolue si nécessaire
                if trombi_href.startswith('/'):
                    from urllib.parse import urlparse
                    parsed = urlparse(self.url)
                    trombi_url = f"{parsed.scheme}://{parsed.netloc}{trombi_href}"
                elif trombi_href.startswith('http'):
                    trombi_url = trombi_href
                else:
                    trombi_url = self.url.rstrip('/') + '/' + trombi_href
                
                logger.info(f"🔄 Auto-redirect vers le trombinoscope : {trombi_url}")
                self.url = trombi_url
                html = await super().fetch(session)
                return html
        
        logger.warning(f"Aucun élu ni trombinoscope trouvé sur {self.url}")
        return html
    
    def _extract_name_parts(self, full_name: str) -> tuple:
        """Sépare un nom complet en (prénom, nom)."""
        parts = full_name.split(" ", 1)
        prenom = parts[0]
        nom = parts[1] if len(parts) > 1 else ""
        return prenom.strip(), nom.strip()
    
    def _clean_fonction(self, raw_fonction: str) -> str:
        """Nettoie la chaîne de fonction en retirant le bruit structurel Drupal.
        
        La structure DOM du trombinoscope mélange l'ordinal, le label "Type de mandat CM"
        et la vraie fonction dans un seul div.fonction. Ex:
            "1 er(e) Type de mandat CM Adjointe" → "Adjointe"
            "19 e Type de mandat CM Adjointe"    → "Adjointe"
            "Type de mandat CM Conseiller municipal" → "Conseiller municipal"
        """
        f = raw_fonction
        # Retirer les ordinaux en début (1er(e), 2e, 19e, etc.)
        f = re.sub(r'^\d+\s*e(?:r(?:\(e\))?|e|ème)?\s*', '', f, flags=re.IGNORECASE).strip()
        # Retirer le label "Type de mandat CM" ou "Type de mandat"
        f = re.sub(r'Type\s+de\s+mandat\s*(?:CM)?\s*', '', f, flags=re.IGNORECASE).strip()
        return f if f else "Conseiller"
    
    def extract(self) -> List[dict]:
        if not self.html_content:
            return []
            
        soup = BeautifulSoup(self.html_content, 'html.parser')
        results = []
        
        # 1. Structure Trombinoscope (.views-row)
        views_rows = soup.select('.views-row')
        if views_rows:
            for elu in views_rows:
                # 1a. Structure Maire : h1.elu-content-desktop + .secFocusNew-desc
                name_tag = elu.select_one('h1.elu-content-desktop')
                if name_tag:
                    full_name = " ".join(name_tag.get_text(separator=' ', strip=True).split())
                    if not full_name:
                        continue
                    
                    prenom, nom = self._extract_name_parts(full_name)
                    
                    func_tag = elu.select_one('.secFocusNew-desc')
                    main_fonction = " ".join(func_tag.get_text(separator=' ', strip=True).split()) if func_tag else "Conseiller"
                    
                    fonctions = [main_fonction]
                    other_mandates = elu.select('.field--name-field-content p')
                    for p in other_mandates:
                        f = p.get_text(separator=' ', strip=True).strip()
                        if f and f not in fonctions:
                            fonctions.append(f)
                            
                    for fonction in fonctions:
                        results.append({
                            "nom": nom,
                            "prenom": prenom,
                            "fonction": fonction.strip()
                        })
                    continue
                    
                # 1b. Structure Trombinoscope standard : .nom + .fonction
                nom_tag = elu.select_one('.nom')
                if not nom_tag:
                    continue
                    
                full_name = " ".join(nom_tag.get_text(separator=' ', strip=True).split())
                if not full_name:
                    continue
                
                prenom, nom = self._extract_name_parts(full_name)
                
                func_tag = elu.select_one('.fonction')
                if func_tag:
                    raw_fonction = " ".join(func_tag.get_text(separator=' ', strip=True).split())
                    fonction = self._clean_fonction(raw_fonction)
                else:
                    fonction = "Conseiller"
                
                results.append({
                    "nom": nom,
                    "prenom": prenom,
                    "fonction": fonction
                })
        
        # 2. Structure type Arrondissement (.organigramme-main et .organigramme__item)
        else:
            # Le Maire principal de l'arrondissement
            mains = soup.select('.organigramme-main')
            for elu in mains:
                name_tag = elu.select_one('.organigramme-main__name')
                if not name_tag:
                    continue
                full_name = " ".join(name_tag.get_text(separator=' ', strip=True).split())
                
                prenom, nom = self._extract_name_parts(full_name)
                
                cats = elu.select('.organigramme-main__category')
                for cat in cats:
                    fonction = " ".join(cat.get_text(separator=' ', strip=True).split())
                    if fonction:
                        results.append({
                            "nom": nom,
                            "prenom": prenom,
                            "fonction": fonction.strip()
                        })
            
            # Les autres élus
            items = soup.select('.organigramme__item')
            for elu in items:
                name_tag = elu.select_one('.organigramme__name')
                if not name_tag:
                    continue
                full_name = " ".join(name_tag.get_text(separator=' ', strip=True).split())
                if not full_name:
                    continue
                
                prenom, nom = self._extract_name_parts(full_name)
                
                func_tag = elu.select_one('.organigramme__description')
                fonction = " ".join(func_tag.get_text(separator=' ', strip=True).split()) if func_tag else "Conseiller"
                
                teaser_tag = elu.select_one('.organigramme__teaser')
                if teaser_tag:
                    teaser = " ".join(teaser_tag.get_text(separator=' ', strip=True).split())
                    if teaser:
                        fonction += " - " + teaser
                        
                results.append({
                    "nom": nom,
                    "prenom": prenom,
                    "fonction": fonction.strip()
                })
                
        return results
