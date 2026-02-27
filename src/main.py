import asyncio
import aiohttp
import logging
import os
import aiosqlite
from typing import List, Dict

from src.parsers.factory import ParserFactory
from src.utils.cache import DiffCacheManager
from src.models.mandate import ElectedOfficialMandate

# Initialisation des parsers pour enregistrement dans la Factory
import src.parsers.plugins.paris_lutece_v1
import src.parsers.plugins.lyon_drupal_v1
import src.parsers.plugins.marseille_html_v1
import src.parsers.plugins.generic_html_v1

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

WEBHOOK_URL = "https://n8n.media-start.fr/webhook/a14f3c73-e1ce-4700-8113-7ab035a9ae16"

async def send_to_n8n(session: aiohttp.ClientSession, payloads: List[dict]):
    """Envoi du flux sortant vers N8N."""
    if not payloads:
        return
        
    try:
        async with session.post(WEBHOOK_URL, json=payloads) as response:
            if response.status != 200:
                logger.error(f"Erreur N8N: Code {response.status}")
            else:
                logger.info(f"[{len(payloads)} objets] envoyés avec succès vers N8N.")
    except Exception as e:
        logger.error(f"Erreur réseau lors de l'envoi à N8N: {e}")

import csv
import unicodedata
from src.utils.url_finder import find_city_website

def normalize_string(s: str) -> str:
    """Normalise une chaîne (minuscule, sans accents) pour un matching robuste."""
    if not s:
        return ""
    s = unicodedata.normalize('NFKD', str(s)).encode('ASCII', 'ignore').decode('utf-8')
    return s.strip().lower()

def load_photo_a(csv_path: str) -> dict:
    """Charge l'état actuel (Photo A) depuis le CSV Salesforce."""
    photo_a = {}
    if not os.path.exists(csv_path):
        logger.warning(f"Fichier Salesforce {csv_path} introuvable.")
        return photo_a
        
    with open(csv_path, encoding='cp850', errors='replace') as f:
        reader = csv.reader(f, delimiter=';')
        try:
            next(reader) # skip headers
        except StopIteration:
            return photo_a
            
        for row in reader:
            if len(row) < 12:
                continue
                
            ville = normalize_string(row[8])
            elu_nom = normalize_string(row[10])
            fonction = row[11].strip()
            
            key = f"{ville}---{elu_nom}"
            photo_a[key] = {
                "fonction": fonction,
                "raw_nom": row[10],
                "raw_ville": row[8]
            }
    return photo_a

def get_villes_cp_map(csv_path: str) -> dict:
    """Récupère le mapping Ville -> Code Postal depuis le CSV."""
    vmap = {}
    if not os.path.exists(csv_path):
        return vmap
        
    with open(csv_path, encoding='cp850', errors='replace') as f:
        reader = csv.reader(f, delimiter=';')
        try:
            next(reader)
        except StopIteration:
            pass
        for row in reader:
            if len(row) > 8:
                v = row[8].strip()
                cp = row[7].strip()
                if v and cp:
                    vmap[v] = cp
    return vmap

def generate_validation_alerts(photo_a: dict, mandates: List[ElectedOfficialMandate]) -> List[dict]:
    """Génère les alertes métier en comparant Photo A (CSV Salesforce) et Photo B (Scraping Web)."""
    alerts = []
    
    for m in mandates:
        nom_complet = f"{m.prenom} {m.nom}"
        nom_complet_norm = normalize_string(nom_complet)
        nom_reverse_norm = normalize_string(f"{m.nom} {m.prenom}")
        ville_norm = normalize_string(m.ville_ou_secteur)
        
        statut_trouve = m.fonction
        
        # On cherche l'élu dans Photo A
        found_a = photo_a.get(f"{ville_norm}---{nom_complet_norm}") or photo_a.get(f"{ville_norm}---{nom_reverse_norm}")
        
        if found_a:
            statut_actuel = found_a["fonction"]
            # Ex: si la fonction diffère
            if normalize_string(statut_actuel) != normalize_string(statut_trouve):
                alerts.append({
                    "alerte_type": "MODIFICATION_FONCTION",
                    "elu": nom_complet,
                    "commune": m.ville_ou_secteur,
                    "statut_salesforce_actuel": statut_actuel,
                    "statut_trouve_web": statut_trouve,
                    "source_url_trouvee": m.source_url,
                    "niveau_confiance": "HIGH"
                })
        else:
            alerts.append({
                "alerte_type": "NOUVEL_ELU_DETECTE",
                "elu": nom_complet,
                "commune": m.ville_ou_secteur,
                "statut_salesforce_actuel": "Inconnu en base",
                "statut_trouve_web": statut_trouve,
                "source_url_trouvee": m.source_url,
                "niveau_confiance": "MEDIUM"
            })
            
    return alerts

async def process_url(session: aiohttp.ClientSession, row: Dict, cache: Dict, map_cp: dict) -> tuple:
    url = row.get("url")
    template = row.get("parser_template")
    ville = row.get("ville_ou_secteur")

    # Découverte d'URL si elle est vide
    if not url or url.strip() == "":
        code_postal = map_cp.get(ville, "")
        logger.info(f"Recherche dynamique d'URL pour {ville} ({code_postal})...")
        found_url = await find_city_website(session, ville, code_postal)
        if not found_url:
            logger.error(f"Impossible de trouver le site de {ville}.")
            return ville, []
        url = found_url
        logger.info(f"URL découverte pour {ville}: {url}")
        
        # Par défaut, si l'URL est découverte dynamiquement, on utilise le parser générique
        if not template or template == "":
            template = "generic_html_v1"

    try:
        parser = ParserFactory.get_parser(template, url, ville)
    except ValueError as e:
        logger.error(f"Skip {url}: {e}")
        return ville, []

    logger.info(f"Analyse de {ville} ({url}) via {template}")
    html = await parser.fetch(session)
    if not html:
        return ville, []

    content_hash = parser.get_content_hash()
    
    # Stratégie d'optimisation : Diffing
    if cache.get(url) == content_hash:
        logger.info(f"⏭️ Skip {ville} ({url}) : AUCUNE MODIFICATION MD5 DÉTECTÉE.")
        # On passe, mais on traitera les mandats depuis l'extraction
        pass
        
    mandates = parser.normalize()
    if mandates:
        cache[url] = content_hash
        
    return ville, mandates

async def load_urls_from_db(db_path: str) -> List[Dict]:
    urls = []
    if not os.path.exists(db_path):
        logger.error(f"Base de données introuvable : {db_path}")
        return urls
        
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT url, parser_template, ville FROM source_urls WHERE is_active = 1") as cursor:
            async for row in cursor:
                urls.append({
                    "url": row["url"] if row["url"] else "",
                    "parser_template": row["parser_template"] if row["parser_template"] else "generic_html_v1",
                    "ville_ou_secteur": row["ville"]
                })
    return urls

async def main():
    root_dir = os.path.dirname(os.path.dirname(__file__))
    db_path = os.path.join(root_dir, 'elus_sources.db')
    csv_path = os.path.join(root_dir, 'Fichier forgeron3 test mandat contrat.csv')
    
    dispatcher_tasks = await load_urls_from_db(db_path)
    if not dispatcher_tasks:
        logger.warning("Aucune URL active à traiter. Fin du script.")
        return

    # Chargement de la Photo A et mapping des CP
    logger.info("Chargement du CSV Salesforce (Photo A)...")
    photo_a = load_photo_a(csv_path)
    map_cp = get_villes_cp_map(csv_path)

    cache = await DiffCacheManager.load()
    new_mandates: List[ElectedOfficialMandate] = []

    connector = aiohttp.TCPConnector(limit=10, ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [process_url(session, row, cache, map_cp) for row in dispatcher_tasks]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for res in results:
            if isinstance(res, tuple):
                ville, mandates = res
                new_mandates.extend(mandates)
            elif isinstance(res, Exception):
                logger.error(f"Erreur d'exécution concurrente asynchrone: {res}")
                
        # Dédoublonnage sur la Photo B
        deduped = {}
        for m in new_mandates:
            if m.id_technique not in deduped:
                deduped[m.id_technique] = m
        new_mandates = list(deduped.values())

        # Validation métier : Photo A VS Photo B
        alerts = generate_validation_alerts(photo_a, new_mandates)

        # Bulk Upload des alertes vers l'interface de validation
        if alerts:
            logger.info(f"Opération terminée. {len(alerts)} alertes de validation transmises vers N8N.")
            await send_to_n8n(session, alerts)
            await DiffCacheManager.save(cache)
        else:
            logger.info("Fin du script. Aucun changement détecté entre Salesforce et le Web.")

if __name__ == "__main__":
    asyncio.run(main())
