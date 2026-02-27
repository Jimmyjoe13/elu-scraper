import json
import re
import aiohttp
import asyncio
import logging
from typing import List, Optional

from src.parsers.base import BaseParser
from src.parsers.factory import ParserFactory

logger = logging.getLogger(__name__)

@ParserFactory.register("paris_lutece_v1")
class ParisLuteceV1Parser(BaseParser):
    """
    Parser pour les élus de la ville de Paris.
    Plutôt que scraper le HTML, Paris utilise l'index Algolia 'Elected_production_v4'.
    On intercepte l'appel pour requêter Algolia.
    """
    
    async def fetch(self, session: aiohttp.ClientSession) -> Optional[str]:
        # Déterminer la Mairie concernée (global = Paris, ou chiffre pour l'arrondissement)
        mairie_id = "global"
        m = re.search(r'mairie(\d+)\.paris\.fr', self.url)
        if m:
            mairie_id = str(int(m.group(1))) # ex: 08 -> 8
            
        algolia_url = "https://L53ZNZVW5W-dsn.algolia.net/1/indexes/Elected_production_v4/query"
        headers = {
            'X-Algolia-Application-Id': 'L53ZNZVW5W',
            'X-Algolia-API-Key': 'f9594bd99919b6e18613111b3d2c1b7c',
        }
        data = {
            "params": f"hitsPerPage=1000&facetFilters=mairie_id:{mairie_id}"
        }
        
        max_retries = 3
        base_delay = 2

        for attempt in range(max_retries):
            try:
                async with session.post(algolia_url, headers=headers, json=data, ssl=False) as response:
                    if response.status in (429, 500, 502, 503, 504):
                        logger.warning(f"Status {response.status} for {self.url} via Algolia (att {attempt+1})")
                        await asyncio.sleep(base_delay ** attempt)
                        continue
                    
                    response.raise_for_status()
                    # On stocke le JSON en tant que texte pour que get_content_hash() fonctionne
                    self.html_content = await response.text()
                    return self.html_content
                    
            except aiohttp.ClientError as e:
                logger.warning(f"Client error for {self.url} via Algolia (att {attempt+1}): {e}")
                await asyncio.sleep(base_delay ** attempt)
        
        logger.error(f"Echec du téléchargement {self.url} via Algolia après {max_retries} tentatives.")
        return None

    def extract(self) -> List[dict]:
        if not self.html_content:
            return []
            
        try:
            data = json.loads(self.html_content)
        except json.JSONDecodeError:
            logger.error("Failed to decode JSON from Algolia")
            return []
            
        results = []
        hits = data.get("hits", [])
        
        for hit in hits:
            nom_complet = hit.get("title", "")
            if not nom_complet:
                continue
            
            parts = nom_complet.split(" ", 1)
            prenom = parts[0]
            nom = parts[1] if len(parts) > 1 else ""
            
            # Application de la règle métier stricte : 1 ligne de sortie = 1 mandat/fonction
            mandates = hit.get("mandates", [])
            lead_text = hit.get("lead_text", "")
            
            all_fonctions = []
            if lead_text:
                all_fonctions.append(lead_text.strip())
            
            if mandates:
                all_fonctions.extend([m.strip() for m in mandates if m.strip()])
            
            # Dedup
            seen = set()
            fonctions = []
            for f in all_fonctions:
                if f and f not in seen:
                    fonctions.append(f)
                    seen.add(f)
            
            if not fonctions:
                fonctions = ["Conseiller"]
                
            for fonction in fonctions:
                results.append({
                    "nom": nom,
                    "prenom": prenom,
                    "fonction": fonction
                })

        return results
