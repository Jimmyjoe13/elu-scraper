from typing import List
from bs4 import BeautifulSoup

from ..base import BaseParser
from ..factory import ParserFactory

@ParserFactory.register("lyon_drupal_v1")
class LyonDrupalV1Parser(BaseParser):
    """
    Parser pour les élus de la ville de Lyon et de ses arrondissements (Drupal).
    Gère deux structures distinctes:
    - .views-row pour la ville
    - .organigramme-main / .organigramme__item pour les arrondissements
    """
    
    def extract(self) -> List[dict]:
        if not self.html_content:
            return []
            
        soup = BeautifulSoup(self.html_content, 'html.parser')
        results = []
        
        # 1. Structure type Ville Centrale (.views-row)
        views_rows = soup.select('.views-row')
        if views_rows:
            for elu in views_rows:
                name_tag = elu.select_one('h1.elu-content-desktop')
                if not name_tag:
                    continue
                    
                full_name = " ".join(name_tag.get_text(separator=' ', strip=True).split())
                if not full_name:
                    continue
                
                parts = full_name.split(" ", 1)
                prenom = parts[0]
                nom = parts[1] if len(parts) > 1 else ""
                
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
                        "nom": nom.strip(),
                        "prenom": prenom.strip(),
                        "fonction": fonction.strip()
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
                
                parts = full_name.split(" ", 1)
                prenom = parts[0]
                nom = parts[1] if len(parts) > 1 else ""
                
                cats = elu.select('.organigramme-main__category')
                for cat in cats:
                    fonction = " ".join(cat.get_text(separator=' ', strip=True).split())
                    if fonction:
                        results.append({
                            "nom": nom.strip(),
                            "prenom": prenom.strip(),
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
                
                parts = full_name.split(" ", 1)
                prenom = parts[0]
                nom = parts[1] if len(parts) > 1 else ""
                
                func_tag = elu.select_one('.organigramme__description')
                fonction = " ".join(func_tag.get_text(separator=' ', strip=True).split()) if func_tag else "Conseiller"
                
                teaser_tag = elu.select_one('.organigramme__teaser')
                if teaser_tag:
                    teaser = " ".join(teaser_tag.get_text(separator=' ', strip=True).split())
                    if teaser:
                        fonction += " - " + teaser
                        
                results.append({
                    "nom": nom.strip(),
                    "prenom": prenom.strip(),
                    "fonction": fonction.strip()
                })
                
        return results
