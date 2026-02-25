import asyncio
import aiohttp
import logging
from typing import List, Dict

from src.parsers.factory import ParserFactory
from src.utils.cache import DiffCacheManager
from src.models.mandate import ElectedOfficialMandate

# Initialisation des parsers pour enregistrement dans la Factory
import src.parsers.plugins.paris_lutece_v1
# import src.parsers.plugins.lyon_drupal_v1  # Ajouter les autres templates ici

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

WEBHOOK_URL = "https://n8n.votredomaine.com/webhook/elus"

async def send_to_n8n(session: aiohttp.ClientSession, mandates: List[ElectedOfficialMandate]):
    """Envoi du flux sortant (1 ligne = 1 mandat) vers N8N."""
    if not mandates:
        return
        
    payload = [m.model_dump(mode="json") for m in mandates]
    
    try:
        # Retry logic & exponential backoff s'implémente généralement via un décorateur (ex: tenacity)
        # Mais ici en approche directe asynchrone pour N8N :
        async with session.post(WEBHOOK_URL, json=payload) as response:
            if response.status != 200:
                logger.error(f"Erreur N8N: Code {response.status}")
            else:
                logger.info(f"[{len(mandates)} mandats] envoyés avec succès vers N8N.")
    except Exception as e:
        logger.error(f"Erreur réseau lors de l'envoi à N8N: {e}")

async def process_url(session: aiohttp.ClientSession, row: Dict, cache: Dict) -> List[ElectedOfficialMandate]:
    url = row.get("url")
    template = row.get("parser_template")
    ville = row.get("ville_ou_secteur")

    try:
        parser = ParserFactory.get_parser(template, url, ville)
    except ValueError as e:
        logger.error(f"Skip {url}: {e}")
        return []

    logger.info(f"Analyse de {ville} ({url}) via {template}")
    html = await parser.fetch(session)
    if not html:
        return []

    content_hash = parser.get_content_hash()
    
    # Stratégie d'optimisation : Diffing
    if cache.get(url) == content_hash:
        logger.info(f"⏭️ Skip {ville} : AUCUNE MODIFICATION MD5 DÉTECTÉE.")
        return []
        
    # Extraction et validation par la Factory et le modèle Pydantic
    mandates = parser.normalize()
    
    if mandates:
        cache[url] = content_hash
        
    return mandates

async def main():
    # Simulation d'un dispatcher (lecture CSV/DB/Dict de configuration)
    dispatcher_tasks = [
        {
            "url": "https://www.paris.fr/pages/les-elus", 
            "parser_template": "paris_lutece_v1", 
            "ville_ou_secteur": "Paris"
        },
        # {"url": "https://lyon.fr/elus", "parser_template": "lyon_drupal_v1", "ville_ou_secteur": "Lyon"},
    ]

    cache = await DiffCacheManager.load()
    new_mandates: List[ElectedOfficialMandate] = []

    # Limitation du nombre de connexions TCP parallèles concurrentes
    connector = aiohttp.TCPConnector(limit=10, ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        # Traitement asynchrone parallèle
        tasks = [process_url(session, row, cache) for row in dispatcher_tasks]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for res in results:
            if isinstance(res, list):
                new_mandates.extend(res)
            elif isinstance(res, Exception):
                logger.error(f"Erreur d'exécution concurrente asynchrone: {res}")
                
        # Bulk Upload
        if new_mandates:
            logger.info(f"Opération terminée. {len(new_mandates)} nouveaux mandats modélisés.")
            await send_to_n8n(session, new_mandates)
            await DiffCacheManager.save(cache)
        else:
            logger.info("Fin du script. Aucun nouveau mandat à traiter.")

if __name__ == "__main__":
    asyncio.run(main())
