import re
import logging
import urllib.parse
from typing import List, Optional, Tuple
import aiohttp
from bs4 import BeautifulSoup

from ..base import BaseParser
from ..factory import ParserFactory

logger = logging.getLogger(__name__)

# ───────────────────────────────────────────────────────────────────────
# Constantes pour le Deep Fetch (découverte automatique de sous-pages)
# ───────────────────────────────────────────────────────────────────────

_DEEP_FETCH_KEYWORDS = ['elu', 'elus', 'equipe', 'conseil-municipal', 'conseil_municipal',
                         'organigramme', 'trombinoscope', 'adjoints']

_DEEP_FETCH_EXCLUSIONS = ['police', 'assainissement', 'salle', 'cimetiere',
                           'urbanisme', 'jeunes', 'enfance', 'periscolaire']

# ───────────────────────────────────────────────────────────────────────
# Regex compilées pour l'extraction sémantique (agnostique au DOM)
# ───────────────────────────────────────────────────────────────────────

# Ancres sémantiques : mots-clés qui signalent la présence d'une fonction élective
_ANCHOR_RE = re.compile(
    r'\b(maire|adjoint|conseill)', re.IGNORECASE
)

# Filtre prépositionnel : "maire" précédé de ces prépositions = complément, pas titre
_PREP_MAIRE_RE = re.compile(
    r'\b(?:du|au|de la|[aà] la|par le|par la|aupr[eè]s du|aupr[eè]s de la|'
    r'd[eé]l[eé]gation du|pr[eé]sence du|convocation du)\s+maire\b',
    re.IGNORECASE
)

# Suppression de _FUNC_RE rigide, remplacé par une méthode _extract_fonction agnostique et gloutonne.

# Pattern 1 : Prénom NOM (NOM tout en majuscules, au moins 2 lettres)
_UP = "A-ZÉÈÊËÀÂÎÏÔÙÛÜÇÑ"
_LO = "a-zéèêëàâîïôùûüçñ"
_NAME_PRENOM_NOM_RE = re.compile(
    rf'(?:(?:M\.|Mme|M|Monsieur|Madame)\s+)?'
    rf'([{_UP}][{_LO}]+(?:[\s-][{_UP}][{_LO}]+)*)'     # Prénom(s)
    rf'\s+'
    rf'([{_UP}]{{2,}}(?:[\s-][{_UP}]{{2,}})*)',           # NOM (2+ majuscules par mot)
    re.UNICODE
)

# Pattern 2 : Prénom Nom (les deux en Title Case — sites qui ne mettent pas en majuscules)
_NAME_TITLE_RE = re.compile(
    rf'(?:(?:M\.|Mme|M|Monsieur|Madame)\s+)?'
    rf'([{_UP}][{_LO}]+(?:[\s-][{_UP}][{_LO}]+)*)'    # Prénom(s)
    rf'\s+'
    rf'([{_UP}][{_LO}]+(?:[\s-][{_UP}][{_LO}]+)*)',    # Nom (Title Case)
    re.UNICODE
)

# Anti faux-positifs : mots qui ressemblent à des noms mais n'en sont pas
_NAME_BLACKLIST = frozenset({
    "MAIRE", "ADJOINT", "ADJOINTE", "CONSEILLER", "CONSEILLERE", "MUNICIPAL",
    "MUNICIPALE", "VILLE", "COMMUNE", "MAIRIE", "DELEGUE", "DELEGUEE",
    "BUDGET", "MARCHES", "PUBLICS", "INTERCOMMUNALITE", "RECRUTEMENT",
    "DELIBERATIONS", "NOUVELLE", "CONSEIL", "NOUVELLE", "ACCUEIL",
    "URBANISME", "PATRIMOINE", "CULTURE", "EDUCATION", "JEUNESSE",
    "ENFANCE", "SPORTS", "SECURITE", "SERVICES", "COMMUNICATION",
    "HOTEL", "CEDEX", "PARIS", "FRANCE", "MONSIEUR", "MADAME",
    "TYPE", "MANDAT", "DELEGATION", "ARRONDISSEMENT", "SECTEUR",
    "CONTACT", "INFOS", "PRATIQUES", "MENU", "ACCÈS", "RAPIDE",
})

# Taille minimale d'un bloc de texte pertinent (filtre les menus de navigation)
_MIN_BLOCK_LENGTH = 10


@ParserFactory.register("generic_html_v1")
class GenericHtmlV1Parser(BaseParser):
    """
    Parser générique 100% agnostique au DOM.
    
    Fonctionne comme un scanner optique basé sur la sémantique et les regex,
    sans aucune dépendance à la structure HTML du site cible.
    
    Architecture :
    1. Deep Fetch : si la page racine est vide, suit automatiquement les liens internes
    2. Fragmentation DOM : découpe le HTML en blocs de texte (<tr>, <li>, <div>, <p>)
    3. Ancre sémantique : chaque bloc est scanné pour les mots-clés (maire, adjoint, conseiller)
    4. Capture regex : extraction du nom et de la fonction par pattern matching multi-stratégie
    5. Appariement par proximité : si le nom n'est pas dans le même bloc, scan des voisins
    """

    # ─── Deep Fetch (inchangé) ────────────────────────────────────────

    async def fetch(self, session: aiohttp.ClientSession) -> Optional[str]:
        """Surcharge de fetch avec Deep Fetch récursif à 2 niveaux."""
        html = await super().fetch(session)
        if not html:
            return None
        
        # 1. Vérification de la page racine
        test_results = self._extract_from_html(html)
        if test_results:
            logger.info(f"✅ Deep Fetch inutile pour {self.url} : {len(test_results)} élus trouvés sur la racine.")
            return html
        
        logger.info(f"🔍 Deep Fetch NIVEAU 1 activé pour {self.url}...")
        
        # 2. Découverte des liens candidats sur la racine
        candidates_lvl1 = self._discover_elus_urls(html)
        
        for url_lvl1 in candidates_lvl1[:3]:  # On teste max 3 liens prioritaires
            logger.info(f"  → Test L1: {url_lvl1}")
            try:
                async with session.get(url_lvl1, ssl=False, timeout=aiohttp.ClientTimeout(total=15)) as response:
                    if response.status == 200:
                        html_lvl1 = await response.text()
                        
                        # Test d'extraction sur L1
                        if self._extract_from_html(html_lvl1):
                            logger.info(f"✅ Succès Deep Fetch L1 : {url_lvl1}")
                            self.html_content = html_lvl1
                            self.url = url_lvl1
                            return html_lvl1
                        
                        # Échec sur L1, on fouille cette sous-page (Niveau 2)
                        candidates_lvl2 = self._discover_elus_urls(html_lvl1)
                        for url_lvl2 in candidates_lvl2[:2]: # Max 2 sous-liens pour éviter l'explosion
                            # Ne pas boucler à l'infini
                            if url_lvl2 in candidates_lvl1 or url_lvl2 == self.url:
                                continue
                                
                            logger.info(f"    → Test L2: {url_lvl2}")
                            async with session.get(url_lvl2, ssl=False, timeout=aiohttp.ClientTimeout(total=15)) as res_lvl2:
                                if res_lvl2.status == 200:
                                    html_lvl2 = await res_lvl2.text()
                                    if self._extract_from_html(html_lvl2):
                                        logger.info(f"✅ Succès Deep Fetch L2 : {url_lvl2}")
                                        self.html_content = html_lvl2
                                        self.url = url_lvl2
                                        return html_lvl2

            except Exception as e:
                logger.warning(f"❌ Erreur sur {url_lvl1}: {e}")
        
        # Si rien ne marche, on garde la page racine par défaut
        logger.warning(f"⚠️ Échec du Deep Fetch, retour à la page racine pour {self.url}")
        return html
    
    def _discover_elus_urls(self, html: str) -> List[str]:
        """Scanne les liens <a> et retourne une liste triée par pertinence."""
        soup = BeautifulSoup(html, 'html.parser')
        
        candidates = set()
        for a_tag in soup.find_all('a', href=True):
            href = a_tag.get('href', '').strip()
            text = a_tag.get_text(strip=True)
            
            if not href or href.startswith('#') or href.startswith('mailto:') or href.startswith('tel:'):
                continue
            
            combined = (href + ' ' + text).lower()
            
            has_keyword = any(kw in combined for kw in _DEEP_FETCH_KEYWORDS)
            has_exclusion = any(excl in combined for excl in _DEEP_FETCH_EXCLUSIONS)
            
            if has_keyword and not has_exclusion:
                full_url = self._resolve_url(href)
                if full_url and full_url.rstrip('/') != self.url.rstrip('/'):
                    candidates.add((full_url, combined))
        
        # Fonction de tri pour donner la priorité aux URL/textes contenant "elu"
        def score_link(item):
            url, text = item
            score = 0
            if 'elu' in text or 'élu' in text: score += 10
            if 'equipe' in text or 'équipe' in text: score += 5
            return -score # Négatif pour tri décroissant
            
        ranked_urls = [url for url, _ in sorted(list(candidates), key=score_link)]
        return ranked_urls

    
    def _resolve_url(self, href: str) -> Optional[str]:
        """Convertit un href relatif ou absolu en URL complète."""
        if href.startswith('http'):
            return href
        parsed_base = urllib.parse.urlparse(self.url)
        base = f"{parsed_base.scheme}://{parsed_base.netloc}"
        if href.startswith('/'):
            return base + href
        base_path = parsed_base.path.rstrip('/')
        return base + base_path + '/' + href

    # ─── Extraction (point d'entrée) ──────────────────────────────────

    def extract(self) -> List[dict]:
        """Point d'entrée standard appelé par BaseParser.normalize()."""
        return self._extract_from_html(self.html_content)

    # ─── Moteur d'extraction agnostique ───────────────────────────────

    def _extract_from_html(self, html: str) -> List[dict]:
        """Extraction 100% agnostique au DOM par scan sémantique.
        
        Trois stratégies complémentaires exécutées en cascade :
        1. Scan des conteneurs structurels (tr, li, div.item, article)
        2. Scan des blocs de texte individuels (p, div, span, td, h1-h6)
        3. Appariement par proximité (fonction dans un bloc, nom dans le voisin)
        """
        if not html:
            return []

        soup = BeautifulSoup(html, 'html.parser')
        
        # Nettoyage du bruit HTML (inclut nav/footer/header pour éviter les faux positifs des menus)
        for el in soup(["script", "style", "nav", "footer", "header", "menu", "aside", "iframe", "noscript", "svg"]):
            el.extract()
        
        results = []
        seen = set()
        
        # ── Stratégie 1 : Conteneurs structurels ──
        # Les élus sont souvent dans des <tr>, <li>, ou des <div> avec une classe
        containers = soup.select('tr, li, [class*="item"], [class*="elu"], [class*="member"], '
                                  '[class*="person"], [class*="team"], article')
        
        for container in containers:
            try:
                text = self._clean_text(container.get_text(separator=' ', strip=True))
                if not text or len(text) < _MIN_BLOCK_LENGTH or len(text) > 500 or not _ANCHOR_RE.search(text):
                    continue
                
                pairs = self._extract_pairs_from_text(text)
                for prenom, nom, fonction in pairs:
                    self._add_result(results, seen, prenom, nom, fonction)
            except Exception:
                continue
        
        # ── Stratégie 2 : Blocs de texte individuels ──
        # Parcours général du DOM pour les structures non couvertes par la stratégie 1
        if soup.body:
            for tag in soup.body.descendants:
                try:
                    if not tag.name or tag.name in ["html", "body", "head"]:
                        continue
                    
                    text = self._clean_text(tag.get_text(separator=' ', strip=True))
                    if not text or len(text) < _MIN_BLOCK_LENGTH or len(text) > 500 or not _ANCHOR_RE.search(text):
                        continue
                    
                    pairs = self._extract_pairs_from_text(text)
                    for prenom, nom, fonction in pairs:
                        self._add_result(results, seen, prenom, nom, fonction)
                    
                    # Si on a trouvé une fonction mais pas de nom, on cherche dans les voisins
                    if not pairs:
                        fonction = self._extract_fonction(text)
                        if fonction:
                            name = self._search_name_in_neighbors(tag)
                            if name:
                                prenom, nom = name
                                self._add_result(results, seen, prenom, nom, fonction)
                except Exception:
                    continue
        
        return results

    def _extract_pairs_from_text(self, text: str) -> List[Tuple[str, str, str]]:
        """Extrait les couples (nom, fonction) de manière infaillible (Proof of Fail)."""
        pairs = []
        
        fonction = self._extract_fonction(text)
        if not fonction:
            return pairs
        
        names = self._extract_names(text)
        
        if names:
            for prenom, nom in names:
                pairs.append((prenom, nom, fonction))
        else:
            # Fallback Ultime : si aucune Regex de nom n'a marché, on garde TOUT le bloc.
            # La donnée ne sera jamais perdue, le main.py s'en occupera!
            pairs.append(("", text.strip()[:100], fonction))
        
        return pairs
    
    def _extract_fonction(self, text: str) -> Optional[str]:
        """Extrait la fonction en ciblant le titre fonctionnel, pas la description."""
        
        # 1. Nettoyage du bruit : adresses e-mail (souvent dans les blocs de contact)
        text_clean = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b.*$', '', text).strip()
        
        # 2. Règle : Tronquer au premier chiffre long (téléphone, etc)
        text_clean = re.sub(r'\s+\d[\d\s\.]{5,}.*$', '', text_clean).strip()
        
        # 3. Règle : Tronquer à la première virgule ou point-virgule (la délégation suit souvent)
        text_clean = re.split(r'[,;]', text_clean)[0].strip()
        
        # 4. Nettoyage final des résidus de ponctuation en fin de chaîne
        text_clean = text_clean.rstrip(".-: ")

        # 5. Limiter à 60 caractères max avec ancre sémantique
        if len(text_clean) > 60:
            pattern = re.compile(
                r'(.{0,30}\b(?:maire|adjoint|conseill)\w*(?:\s+\w+){0,6})',
                re.IGNORECASE
            )
            match = pattern.search(text_clean)
            if match:
                candidate = match.group(1).strip()
            else:
                return None
        else:
            # Si le bloc ne contient pas d'ancre sémantique → ne pas retourner
            if not _ANCHOR_RE.search(text_clean):
                return None
            candidate = text_clean

        # 6. Filtre prépositionnel : si "maire" est précédé d'une préposition
        #    (du, au, auprès du, etc.) et qu'il n'y a pas d'autre ancre en position
        #    de TITRE (adjoint/conseiller au début), c'est un complément, pas un titre
        if candidate and _PREP_MAIRE_RE.search(candidate):
            # Vérifier si adjoint/conseiller apparaît AVANT "maire" (= titre réel)
            other_match = re.search(r'\b(?:adjoint|conseill)', candidate, re.IGNORECASE)
            maire_match = re.search(r'\bmaire\b', candidate, re.IGNORECASE)
            if not other_match or (maire_match and other_match.start() > maire_match.start()):
                return None

        return candidate if candidate else None
    
    def _extract_names(self, text: str) -> List[Tuple[str, str]]:
        """Extrait les noms avec une tolérance maximale."""
        names = []
        
        # Stratégie 1 : Prénom NOM (majuscules)
        for match in _NAME_PRENOM_NOM_RE.finditer(text):
            prenom = match.group(1).strip()
            nom = match.group(2).strip()
            if self._is_valid_name(prenom, nom):
                names.append((prenom, nom))
        
        if names:
            return names
        
        # Stratégie 2 : Prénom Nom (Title Case)
        # BUGFIX: Ne plus tester si ça chevauche `_FUNC_RE` car ça faisait crasher le parseur!
        for match in _NAME_TITLE_RE.finditer(text):
            prenom = match.group(1).strip()
            nom = match.group(2).strip()
            if self._is_valid_name(prenom, nom):
                names.append((prenom, nom))
        
        if names:
            return names
            
        # Stratégie 3 : Suite de majuscules brutes (ex: "DUPONT JEAN")
        caps = re.findall(rf'\b([{_UP}]{{3,}}(?:[\s-][{_UP}]{{3,}})*)\b', text, re.UNICODE)
        for c in caps:
            if c not in _NAME_BLACKLIST:
                names.append(("", c.strip()))
        
        return names
    
    def _is_valid_name(self, prenom: str, nom: str) -> bool:
        """Vérifie qu'un nom n'est pas un mot du dictionnaire ou de navigation."""
        if not nom or len(nom) < 2:
            return False
            
        # Si un prénom est fourni, on le limite (évite de matcher des phrases entières)
        if prenom:
            if len(prenom) > 30 or len(prenom.split()) > 3:
                return False
        
        if len(nom) > 60:
            return False
        
        if prenom and prenom.upper() in _NAME_BLACKLIST:
            return False
        if nom.upper() in _NAME_BLACKLIST:
            return False
        
        nom_lower = nom.lower()
        if any(kw in nom_lower for kw in ['maire', 'adjoint', 'conseill', 'municipal', 'delegue']):
            return False
        
        return True
    
    def _search_name_in_neighbors(self, tag) -> Optional[Tuple[str, str]]:
        """Cherche un nom dans les éléments DOM voisins (frères et parent)."""
        # Frère précédent
        prev = tag.find_previous_sibling()
        if prev:
            text = self._clean_text(prev.get_text(separator=' ', strip=True))
            if text and len(text) < 200:
                names = self._extract_names(text)
                if names:
                    return names[0]
        
        # Frère suivant
        next_sib = tag.find_next_sibling()
        if next_sib:
            text = self._clean_text(next_sib.get_text(separator=' ', strip=True))
            if text and len(text) < 200:
                names = self._extract_names(text)
                if names:
                    return names[0]
        
        # Parent direct (si compact)
        if tag.parent:
            text = self._clean_text(tag.parent.get_text(separator=' ', strip=True))
            if text and len(text) < 400:
                names = self._extract_names(text)
                if names:
                    return names[0]
        
        return None
    
    def _add_result(self, results: list, seen: set, prenom: str, nom: str, fonction: str):
        """Ajoute un résultat dédoublonné."""
        unique_key = f"{prenom.lower()}-{nom.lower()}-{fonction.lower()}"
        if unique_key not in seen:
            seen.add(unique_key)
            results.append({
                "nom": nom.strip(),
                "prenom": prenom.strip(),
                "fonction": fonction.strip()
            })

    @staticmethod
    def _clean_text(text: str) -> str:
        """Nettoyage agressif du bruit textuel."""
        if not text:
            return ""
        # Remplacement des retours à la ligne et tabulations par des espaces
        text = re.sub(r'[\n\r\t]+', ' ', text)
        # Collapse des espaces multiples
        text = re.sub(r'\s+', ' ', text)
        return text.strip()
