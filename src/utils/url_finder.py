import aiohttp
import logging
import re
import unicodedata
import urllib.parse
from bs4 import BeautifulSoup
from typing import Optional

logger = logging.getLogger(__name__)

def _clean_commune_name(nom: str) -> str:
    """Nettoyage agressif du nom de commune avant appel API.
    
    Exemples:
        'LILLE CEDEX'               → 'LILLE'
        'SAINT ´┐¢TIENNE CEDEX 01' → 'SAINT ETIENNE'
        'PARIS L'H´┐¢PITAL'        → 'PARIS L HOPITAL'
        'FILLI´┐¢RE'               → 'FILLIERE'
        'TOULOUSE CEDEX 6'          → 'TOULOUSE'
    """
    if not nom:
        return ""
    s = nom.strip()
    # 1. Remplacement de l'artefact d'encodage cp850 (´┐¢) par 'E'
    s = s.replace('\udce9', 'E').replace('´┐¢', 'E')
    # 2. Normalisation Unicode : décomposition + suppression des diacritiques
    s = unicodedata.normalize('NFKD', s).encode('ASCII', 'ignore').decode('utf-8')
    # 3. Couper dès l'apparition de CEDEX (et tout ce qui suit)
    s = re.sub(r'\s+CEDEX.*$', '', s, flags=re.IGNORECASE)
    # 4. Remplacement des apostrophes, tirets et caractères spéciaux par des espaces
    s = re.sub(r"[^a-zA-Z0-9\s]", ' ', s)
    # 5. Collapse des espaces multiples
    s = re.sub(r'\s+', ' ', s).strip()
    return s

async def find_city_website(session: aiohttp.ClientSession, nom_commune: str, code_postal: str) -> Optional[str]:
    """
    Trouve l'URL officielle d'une mairie à partir de son nom et code postal.
    Utilise l'API geo.api.gouv.fr puis etablissements-publics.api.gouv.fr (Annuaire de l'Administration),
    avec un fallback sur l'API non-officielle DuckDuckGo HTML en cas d'échec.
    """
    # Nettoyage agressif du nom de commune avant tout appel API
    nom_clean = _clean_commune_name(nom_commune)
    if not nom_clean:
        logger.warning(f"Nom de commune vide après nettoyage: {nom_commune!r}")
        return None
    logger.debug(f"Nettoyage commune: {nom_commune!r} → {nom_clean!r}")
    
    url = None
    try:
        # Étape 1 : Obtenir le code INSEE
        # Tentative avec code postal, puis sans si aucun résultat (les codes CEDEX sont souvent invalides)
        geo_urls = [
            f"https://geo.api.gouv.fr/communes?nom={urllib.parse.quote_plus(nom_clean)}&codePostal={code_postal}&limit=1",
            f"https://geo.api.gouv.fr/communes?nom={urllib.parse.quote_plus(nom_clean)}&limit=1",
        ]
        
        code_insee = None
        for geo_url in geo_urls:
            async with session.get(geo_url) as geo_res:
                if geo_res.status == 200:
                    geo_data = await geo_res.json()
                    if geo_data and len(geo_data) > 0:
                        code_insee = geo_data[0]['code']
                        break
        
        if code_insee:
            # Étape 2 : API Annuaire de l'Administration
            api_pub_url = f"https://etablissements-publics.api.gouv.fr/v3/communes/{code_insee}/mairie"
            async with session.get(api_pub_url) as pub_res:
                if pub_res.status == 200:
                    pub_data = await pub_res.json()
                    if pub_data and "features" in pub_data and len(pub_data["features"]) > 0:
                        props = pub_data["features"][0].get("properties", {})
                        url = props.get("url")
    except Exception as e:
        logger.error(f"Erreur API gouvernementale pour {nom_commune}: {e}")
        
    if url:
        return url

    # Étape 3 : Fallback DuckDuckGo HTML Lite (sans clé API)
    logger.info(f"Fallback : Recherche d'URL pour {nom_clean} ({code_postal}) via DuckDuckGo...")
    try:
        # Recherche précise demandée
        query = urllib.parse.quote_plus(f"site officiel mairie {nom_clean}")
        ddg_url = f"https://html.duckduckgo.com/html/?q={query}"
        async with session.get(ddg_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}) as ddg_res:
            if ddg_res.status == 200:
                html = await ddg_res.text()
                soup = BeautifulSoup(html, "html.parser")
                
                for a in soup.select(".result__url"):
                    text = a.get_text(strip=True).replace(" ", "")
                    # Exclusion stricte des annuaires et sites d'info
                    exclusions = [
                        "wikipedia.", "facebook.", "service-public.fr", "annuaire-", 
                        "lannuaire.service", "mon-maire.fr", "mon-maire.", "pagesjaunes.fr",
                        "linternaute.com", "ville-data.com"
                    ]
                    
                    if any(excl in text.lower() for excl in exclusions):
                        continue
                    
                    if not text.startswith("http"):
                        text = "https://" + text
                        
                    return text
    except Exception as e:
        logger.error(f"Erreur lors de la recherche DuckDuckGo pour {nom_commune}: {e}")

    return None
