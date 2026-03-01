import asyncio
import aiohttp
import logging
import os
import aiosqlite
import csv
import unicodedata
import re
from typing import List, Dict

from src.parsers.factory import ParserFactory
from src.utils.cache import DiffCacheManager
from src.models.mandate import ElectedOfficialMandate
from src.utils.url_finder import find_city_website

# Initialisation des parsers pour enregistrement dans la Factory
import src.parsers.plugins.paris_lutece_v1
import src.parsers.plugins.lyon_drupal_v1
import src.parsers.plugins.marseille_html_v1
import src.parsers.plugins.generic_html_v1

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

WEBHOOK_URL = "https://n8n.media-start.fr/webhook/a14f3c73-e1ce-4700-8113-7ab035a9ae16"

async def send_to_n8n(session: aiohttp.ClientSession, payloads: List[dict]):
    """Envoi du flux sortant vers N8N avec Micro-Batching (50 par lot)."""
    if not payloads:
        return
        
    chunk_size = 50
    chunks = [payloads[i:i + chunk_size] for i in range(0, len(payloads), chunk_size)]
    total_chunks = len(chunks)
    
    for idx, chunk in enumerate(chunks, 1):
        try:
            logger.info(f"Envoi du lot {idx}/{total_chunks} ({len(chunk)} alertes) vers N8N...")
            async with session.post(WEBHOOK_URL, json=chunk) as response:
                if response.status != 200:
                    logger.error(f"Erreur N8N sur le lot {idx}: Code {response.status}")
                else:
                    logger.debug(f"Lot {idx} envoyé avec succès.")
        except Exception as e:
            logger.error(f"Erreur réseau lors de l'envoi du lot {idx} à N8N: {e}")
            
        if idx < total_chunks:
            await asyncio.sleep(0.5)

def normalize_string(s: str) -> str:
    """Normalise une chaîne (minuscule, sans accents) pour un matching robuste."""
    if not s:
        return ""
    s = unicodedata.normalize('NFKD', str(s)).encode('ASCII', 'ignore').decode('utf-8')
    return s.strip().lower()

class SalesforceProvider:
    def __init__(self, root_dir: str):
        self.root_dir = root_dir
        self.csv_files = [
            "Fichier forgeron3 test mandat contrat.csv",
            "Fichier forgeron3 test mandat prospect.csv"
        ]

    def _clean_header(self, header: str) -> str:
        """Nettoie une clé d'en-tête CSV pour un accès déterministe."""
        if not header:
            return ""
        # Enlèvement des accents
        h = unicodedata.normalize('NFKD', str(header)).encode('ASCII', 'ignore').decode('utf-8')
        # On ne garde que les lettres et chiffres
        h = re.sub(r'[^a-zA-Z0-9]', '', h)
        return h.lower()

    def _find_key(self, keys: List[str], keywords: List[str]) -> str:
        """Trouve la clé correspondante basée sur une liste de mots-clés."""
        for k in keys:
            if not k:
                continue
            for kw in keywords:
                if kw in k:
                    return k
        return ""

    async def get_photo_a(self) -> dict:
        """Charge l'état actuel (Photo A) depuis les CSV Salesforce."""
        # TODO (PROD): Remplacer la lecture CSV par un call API SOQL vers Salesforce
        photo_a = {}
        
        for filename in self.csv_files:
            csv_path = os.path.join(self.root_dir, filename)
            if not os.path.exists(csv_path):
                logger.warning(f"Fichier Salesforce {csv_path} introuvable.")
                continue
                
            with open(csv_path, encoding='cp850', errors='replace') as f:
                reader_obj = csv.reader(f, delimiter=';')
                try:
                    headers = next(reader_obj)
                except StopIteration:
                    continue
                    
                cleaned_headers = [self._clean_header(h) for h in headers]
                
                # Ciblages basés sur les headers nettoyés
                col_ville = self._find_key(cleaned_headers, ["ville", "commune"])
                col_nom = self._find_key(cleaned_headers, ["elunom", "lunom", "nom", "elu"])
                col_fonction = self._find_key(cleaned_headers, ["fonction", "fonctionelective"])
                col_mandat = self._find_key(cleaned_headers, ["mandatname", "mandat"])
                
                reader = csv.DictReader(f, fieldnames=cleaned_headers, delimiter=';')
                for row in reader:
                    ville = row.get(col_ville, "") if col_ville else ""
                    elu_nom = row.get(col_nom, "") if col_nom else ""
                    fonction = row.get(col_fonction, "") if col_fonction else ""
                    mandat_id = row.get(col_mandat, "") if col_mandat else ""
                    
                    if not ville or not elu_nom:
                        continue
                        
                    v_norm = normalize_string(ville)
                    elu_nom_norm = normalize_string(elu_nom)
                    
                    # Génération des deux clés : Ville---Nom Prenom et Ville---Prenom Nom
                    # En inversant les mots, on couvre la permutation nom/prenom
                    words = elu_nom_norm.split()
                    elu_nom_reversed = " ".join(reversed(words))
                    
                    key_1 = f"{v_norm}---{elu_nom_norm}"
                    key_2 = f"{v_norm}---{elu_nom_reversed}"
                    
                    val = {
                        "fonction": fonction.strip(),
                        "id_salesforce": mandat_id.strip(),
                        "raw_nom": elu_nom.strip(),
                        "raw_ville": ville.strip()
                    }
                    
                    photo_a[key_1] = val
                    photo_a[key_2] = val
                    
        return photo_a

    async def get_villes_cp_map(self) -> dict:
        """Récupère le mapping Ville -> Code Postal depuis l'ensemble des CSV."""
        vmap = {}
        for filename in self.csv_files:
            csv_path = os.path.join(self.root_dir, filename)
            if not os.path.exists(csv_path):
                continue
                
            with open(csv_path, encoding='cp850', errors='replace') as f:
                reader_obj = csv.reader(f, delimiter=';')
                try:
                    headers = next(reader_obj)
                except StopIteration:
                    continue
                    
                cleaned_headers = [self._clean_header(h) for h in headers]
                col_ville = self._find_key(cleaned_headers, ["ville", "commune"])
                col_cp = self._find_key(cleaned_headers, ["codepostal", "cp"])
                
                reader = csv.DictReader(f, fieldnames=cleaned_headers, delimiter=';')
                for row in reader:
                    v = row.get(col_ville, "").strip() if col_ville else ""
                    cp = row.get(col_cp, "").strip() if col_cp else ""
                    if v and cp:
                        vmap[v] = cp
                        
        return vmap

def get_strate_priorite(ville: str) -> str:
    """Déduit la taille de la commune (Strate) pour prioriser l'alerte."""
    v_norm = normalize_string(ville)
    grandes_villes = ["paris", "lyon", "marseille", "toulouse", "nice", "nantes", "montpellier", "strasbourg", "bordeaux", "lille", "rennes"]
    
    if any(gv in v_norm for gv in grandes_villes):
        return "1 - Plus de 100k hab"
        
    return "Non définie"

def generate_validation_alerts(photo_a: dict, mandates: List[ElectedOfficialMandate]) -> List[dict]:
    """Génère les alertes métier en comparant Photo A (CSV Salesforce) et Photo B (Scraping Web)."""
    alerts = []
    
    for m in mandates:
        nom_complet = f"{m.prenom} {m.nom}"
        nom_complet_norm = normalize_string(nom_complet)
        nom_reverse_norm = normalize_string(f"{m.nom} {m.prenom}")
        ville_norm = normalize_string(m.ville_ou_secteur)
        
        statut_trouve = m.fonction
        strate = get_strate_priorite(m.ville_ou_secteur)
        
        # On cherche l'élu dans Photo A
        found_a = photo_a.get(f"{ville_norm}---{nom_complet_norm}") or photo_a.get(f"{ville_norm}---{nom_reverse_norm}")
        
        if found_a:
            statut_actuel = found_a["fonction"]
            if normalize_string(statut_actuel) != normalize_string(statut_trouve):
                alerts.append({
                    "alerte_type": "MODIFICATION_FONCTION",
                    "elu": nom_complet,
                    "commune": m.ville_ou_secteur,
                    "strate_priorite": strate,
                    "statut_salesforce_actuel": statut_actuel,
                    "statut_trouve_web": statut_trouve,
                    "source_url_trouvee": m.source_url,
                    "niveau_confiance": "HIGH",
                    "id_salesforce": found_a["id_salesforce"]
                })
        else:
            logger.debug(f"Élu {nom_complet} ({m.ville_ou_secteur}) ignoré car absent de Salesforce (Photo A).")
            
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
    
    if cache.get(url) == content_hash:
        logger.info(f"⏭️ Skip {ville} ({url}) : AUCUNE MODIFICATION MD5 DÉTECTÉE.")
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
    
    dispatcher_tasks = await load_urls_from_db(db_path)
    if not dispatcher_tasks:
        logger.warning("Aucune URL active à traiter. Fin du script.")
        return

    # Instanciation du provider et chargement de la Photo A et des CP
    logger.info("Chargement des données Salesforce (Photo A)...")
    provider = SalesforceProvider(root_dir)
    photo_a = await provider.get_photo_a()
    map_cp = await provider.get_villes_cp_map()

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
