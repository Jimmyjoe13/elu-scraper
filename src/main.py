import asyncio
import aiohttp
import logging
import os
import aiosqlite
import csv
import unicodedata
import re
import uuid
import json
import argparse
from typing import List, Dict
from datetime import datetime

from src.parsers.factory import ParserFactory
from src.utils.cache import DiffCacheManager
from src.models.mandate import ElectedOfficialMandate
from src.utils.url_finder import find_city_website

# Initialisation des parsers pour enregistrement dans la Factory
import src.parsers.plugins.paris_lutece_v1
import src.parsers.plugins.lyon_drupal_v1
import src.parsers.plugins.marseille_html_v1
import src.parsers.plugins.generic_html_v1
import src.parsers.plugins.auto_agent_v1

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

WEBHOOK_URL = "https://n8n.apps.forgeron3.fr/webhook/5638bdee-37b4-4824-a144-973f8a3bad01"

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
    s = str(s).replace("-", " ")
    s = unicodedata.normalize('NFKD', str(s)).encode('ASCII', 'ignore').decode('utf-8')
    return s.strip().lower()

def normalize_ville(s: str) -> str:
    """Normalise un nom de ville en retirant les suffixes postaux français.
    
    Exemples:
        'LYON CEDEX 1'      -> 'lyon'
        'MARSEILLE CEDEX 20' -> 'marseille'
        'PARIS RP'          -> 'paris'
        'Paris'             -> 'paris'
    """
    if not s:
        return ""
    v = normalize_string(s)
    # Suppression des suffixes postaux français courants
    v = re.sub(r'\s+(cedex\s*\d*|rp|sp|cx\s*\d*|ptt)$', '', v).strip()
    return v

def normalize_fonction(s: str) -> str:
    """Normalise une fonction élective en sa racine sémantique canonique.
    
    Réduit les variantes de formulation à 4 rôles canoniques pour éliminer
    les faux positifs tout en détectant les vraies mutations de poste.
    
    Règles métier :
        - 'Adjoint au Maire de Marseille en charge de...' → 'adjoint'
        - 'Adjointe à la Maire'                          → 'adjoint'
        - '1er Adjoint'                                  → 'adjoint'
        - 'Conseiller de Paris'                          → 'conseiller'
        - 'Conseiller municipal'                         → 'conseiller'
        - 'Conseiller d'arrondissement'                  → 'conseiller'
        - 'Conseillère municipale déléguée'              → 'conseiller'
        - 'Maire d'arrondissement'                       → 'maire_arrondissement'
        - 'Maire de secteur'                             → 'maire_arrondissement'
        - 'Maire' / 'la Maire' / 'le Maire'             → 'maire'
    """
    if not s:
        return ""
    f = normalize_string(s)
    
    # Nettoyage du bruit : ordinaux en début de chaîne ("1er", "2ème", "3e", etc.)
    f = re.sub(r'^\d+(?:er|ere|eme|e|ieme)\s+', '', f).strip()
    # Nettoyage des articles de début ("le ", "la ", "l'")
    f = re.sub(r'^(?:le|la|l)\s+', '', f).strip()
    
    # ORDRE CRITIQUE : Adjoint AVANT Maire (car "Adjoint au Maire" contient les deux)
    if re.search(r'\badjoint', f):
        return "adjoint"
    
    # Maire d'arrondissement / de secteur (AVANT maire simple)
    if re.search(r'\bmaire\b.*(?:arrondissement|secteur)', f):
        return "maire_arrondissement"
    
    # Maire (simple)
    # "maire" doit être en position de TITRE, pas dans une sous-clause ("auprès du maire", "délégation du maire")
    # On exclut les patterns où "maire" est précédé de prépositions (du, au, de la, à la, par le)
    if re.search(r'\bmaire\b', f) and not re.search(r'\b(?:du|au|de la|à la|par le|par la|auprès du|auprès de la|adjoint au|adjointe au|adjointe à la|adjoint à la)\s+maire\b', f):
        return "maire"
    
    # Conseiller(ère) — toutes variantes (municipal, de Paris, d'arrondissement, délégué)
    if re.search(r'\bconseill', f):
        return "conseiller"
    
    # Aucune racine connue : retourner la chaîne normalisée telle quelle
    # (pour les rôles atypiques comme "Président", "Secrétaire", etc.)
    return f

def format_fonction_web(raw_fonction: str) -> str:
    """
    Convertit une fonction brute (extraite du web) en libellé canonique propre.
    Passe par normalize_fonction() pour obtenir la racine sémantique,
    puis retourne un libellé formaté pour affichage dans les alertes N8N.
    
    Si la racine est inconnue, retourne la version normalize_string() tronquée
    à 60 caractères max pour éviter les textes de descriptions entières.
    """
    canonical = normalize_fonction(raw_fonction)
    if canonical in _FONCTION_LABELS:
        return _FONCTION_LABELS[canonical]
    # Fallback : tronquer le brut nettoyé à 60 caractères
    cleaned = normalize_string(raw_fonction)
    return cleaned[:60].strip() if cleaned else raw_fonction[:60].strip()

# Matrice de suprématie des mandats : poids hiérarchique par rôle canonique
_FONCTION_LABELS = {
    "maire": "Maire",
    "adjoint": "Adjoint au Maire",
    "maire_arrondissement": "Maire d'arrondissement",
    "conseiller": "Conseiller Municipal",
}

_FONCTION_WEIGHTS = {
    "maire": 4,
    "adjoint": 3,
    "maire_arrondissement": 2,
    "conseiller": 1,
}

def get_fonction_weight(canonical: str) -> int:
    """Retourne le poids hiérarchique d'une fonction canonique.
    
    Maire (4) > Adjoint (3) > Maire d'arrondissement (2) > Conseiller (1).
    Les rôles inconnus retournent 0 (toujours alerter par sécurité).
    """
    return _FONCTION_WEIGHTS.get(canonical, 0)

def _normalize_type_mandat(raw: str) -> str:
    """Normalise le type de mandat Salesforce en valeur canonique.
    
    >>> _normalize_type_mandat("MANDAT CONTRAT")
    'CONTRAT'
    >>> _normalize_type_mandat("MANDAT PROSPECT")
    'PROSPECT'
    """
    r = raw.strip().upper()
    if "CONTRAT" in r:
        return "CONTRAT"
    if "PROSPECT" in r:
        return "PROSPECT"
    return "INCONNU"

def _normalize_etat_contrat(raw: str) -> str:
    """Normalise l'état du contrat Salesforce en valeur canonique.
    
    >>> _normalize_etat_contrat("En cours")
    'en_cours'
    >>> _normalize_etat_contrat("Résilié")
    'resilie'
    """
    r = normalize_string(raw)  # utilise la fonction normalize_string() déjà existante
    if "resil" in r:
        return "resilie"
    if "liquid" in r:
        return "liquide"
    if "cours" in r or "actif" in r or "en cours" in r:
        return "en_cours"
    return "inconnu"

class SalesforceProvider:
    def __init__(self, root_dir: str):
        self.root_dir = root_dir
        self.csv_files = [
            "report1773758799231.csv"
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

    def _find_key(self, keys: List[str], exact_matches: List[str]) -> str:
        # On cherche d'abord une correspondance EXACTE stricte
        for k in keys:
            if k in exact_matches:
                return k
        # Fallback partiel si vraiment non trouvé
        for k in keys:
            for match in exact_matches:
                if match in k:
                    return k
        return ""

    async def get_photo_a(self, date_photo_a: str) -> dict:
        """Charge l'état actuel (Photo A) depuis les CSV Salesforce."""
        # TODO (PROD): Remplacer la lecture CSV par un call API SOQL vers Salesforce
        # SCHEMA DE REQUÊTE ATTENDU:
        # SELECT Id, Name, Fonction__c, Parti__c, EPCI__c, Elu__r.Name, Mairie__r.Name
        # FROM Mandat__c
        # WHERE IsActive = TRUE
        photo_a = {}

        for filename in self.csv_files:
            csv_path = os.path.join(self.root_dir, filename)
            if not os.path.exists(csv_path):
                logger.warning(f"Fichier Salesforce {csv_path} introuvable.")
                continue

            with open(csv_path, encoding='utf-8-sig', errors='replace') as f:
                reader_obj = csv.reader(f, delimiter=';')
                try:
                    headers = next(reader_obj)
                except StopIteration:
                    continue

                cleaned_headers = [self._clean_header(h) for h in headers]
                logger.debug(f"Headers nettoyés détectés : {cleaned_headers}")

                # Ciblage robuste par index direct
                # Ville (9), Elu:Nom (11), Fonction (12), Mandat (19), Type (20), Etat (21)
                col_ville = cleaned_headers[9] if len(cleaned_headers) > 9 else None
                col_nom = cleaned_headers[11] if len(cleaned_headers) > 11 else None
                col_fonction = cleaned_headers[12] if len(cleaned_headers) > 12 else None
                col_mandat = cleaned_headers[19] if len(cleaned_headers) > 19 else None
                col_type_mandat = cleaned_headers[20] if len(cleaned_headers) > 20 else None
                col_etat_contrat = cleaned_headers[21] if len(cleaned_headers) > 21 else None

                # Fallback pour les colonnes optionnelles
                col_parti = "partipolitique" if "partipolitique" in cleaned_headers else None
                col_epci = "epci" if "epci" in cleaned_headers else None

                logger.debug(f"Mapping colonnes → ville:{col_ville}, nom:{col_nom}, fonction:{col_fonction}, mandat:{col_mandat}")

                if not col_ville or not col_nom:
                    logger.error(f"Colonnes critiques introuvables dans {csv_path}. Headers: {cleaned_headers}")
                    continue

                reader = csv.DictReader(f, fieldnames=cleaned_headers, delimiter=';')
                for row in reader:
                    ville = row.get(col_ville, "")
                    elu_nom = row.get(col_nom, "")
                    fonction = row.get(col_fonction, "")
                    mandat_id = row.get(col_mandat, "")

                    if not ville or not elu_nom:
                        continue

                    v_norm = normalize_ville(ville)
                    fonction_canon = normalize_fonction(fonction)
                    if not fonction_canon:
                        logger.debug(f"Fonction vide ignorée pour {elu_nom} ({ville})")
                        continue
                    key = f"{v_norm}---{fonction_canon}"

                    if key in photo_a:
                        logger.warning(f"Doublon fonction ignoré : {key} (déjà présent)")
                        continue

                    photo_a[key] = {
                        "nom": elu_nom.strip(),
                        "raw_nom": elu_nom.strip(),
                        "date_photo_a": date_photo_a,
                        "id_salesforce": mandat_id.strip(),
                        "type_mandat": _normalize_type_mandat(row.get(col_type_mandat, "")),
                        "etat_contrat": _normalize_etat_contrat(row.get(col_etat_contrat, "")),
                        "raw_ville": ville.strip()
                    }

        return photo_a

    async def get_villes_cp_map(self) -> dict:
        """Récupère le mapping Ville -> Code Postal depuis l'ensemble des CSV."""
        vmap = {}
        for filename in self.csv_files:
            csv_path = os.path.join(self.root_dir, filename)
            if not os.path.exists(csv_path):
                continue
                
            with open(csv_path, encoding='utf-8-sig', errors='replace') as f:
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


def generate_validation_alerts(photo_a: dict, mandates: List[ElectedOfficialMandate], date_photo_a: str) -> tuple:
    """Génère les alertes métier en comparant Photo A (CSV Salesforce) et Photo B (Scraping Web)."""
    # ÉTAPE A — Construire photo_b depuis les mandates scrapés
    photo_b = {}
    for m in mandates:
        ville_norm = normalize_ville(m.ville_ou_secteur)
        fonction_canon = normalize_fonction(m.fonction)
        if not fonction_canon:
            continue
        key = f"{ville_norm}---{fonction_canon}"
        date_det = m.date_extraction.strftime("%d%m%y")
        photo_b[key] = {
            "nom": normalize_string(f"{m.prenom} {m.nom}"),
            "raw_nom": f"{m.prenom} {m.nom}",
            "date_detection": date_det,
            "source_url": m.source_url
        }

    # ÉTAPE B — Comparer photo_a vs photo_b
    alerts = []
    non_couverte_list = []
    for key, data_a in photo_a.items():
        parts = key.split("---", 1)
        if len(parts) != 2:
            continue
        ville_raw, fonction_canon = parts
        if key in photo_b:
            data_b = photo_b[key]
            nom_a = normalize_string(data_a.get("nom", ""))
            nom_b = normalize_string(data_b.get("nom", ""))
            if nom_a != nom_b:
                alerts.append({
                    "alerte_type": "CHANGEMENT",
                    "ancien_nom": data_a.get("raw_nom", ""),
                    "nouveau_nom": data_b.get("raw_nom", ""),
                    "fonction": fonction_canon,
                    "commune": data_a.get("raw_ville", ""),
                    "source_url": data_b.get("source_url", ""),
                    "id_salesforce": data_a.get("id_salesforce", ""),
                    "type_mandat": data_a.get("type_mandat", "INCONNU"),
                    "etat_contrat": data_a.get("etat_contrat", "inconnu"),
                    "date_photo_a": date_photo_a,
                    "date_detection": data_b.get("date_detection", ""),
                    "strate_priorite": get_strate_priorite(data_a.get("raw_ville", "")),
                    "niveau_confiance": "HIGH"
                })
            else:
                try:
                    d_a = datetime.strptime(date_photo_a, "%d%m%y")
                    d_b = datetime.strptime(data_b.get("date_detection", ""), "%d%m%y")
                    if d_b > d_a:
                        alerts.append({
                            "alerte_type": "CONFIRMATION",
                            "nom": data_a.get("raw_nom", ""),
                            "fonction": fonction_canon,
                            "commune": data_a.get("raw_ville", ""),
                            "date_site": data_b.get("date_detection", ""),
                            "date_photo_a": date_photo_a,
                            "id_salesforce": data_a.get("id_salesforce", ""),
                            "source_url": data_b.get("source_url", ""),
                            "strate_priorite": get_strate_priorite(data_a.get("raw_ville", ""))
                        })
                except ValueError:
                    pass
        else:
            non_couverte_list.append({
                "fonction": fonction_canon,
                "commune": data_a.get("raw_ville", ""),
                "nom_attendu": data_a.get("raw_nom", ""),
                "id_salesforce": data_a.get("id_salesforce", "")
            })

    return alerts, non_couverte_list

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
        logger.info(f"ℹ️ Contenu identique pour {ville} ({url}), parsing quand même (mode POC).")
        # TODO (PROD): Décommenter le return ci-dessous pour activer le vrai skip en production
        # return ville, []
        
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

async def _execute_main(run_id: str, date_photo_a: str):
    root_dir = os.path.dirname(os.path.dirname(__file__))
    db_path = os.path.join(root_dir, 'elus_sources.db')
    
    dispatcher_tasks = await load_urls_from_db(db_path)
    if not dispatcher_tasks:
        logger.warning("Aucune URL active à traiter. Fin du script.")
        return

    # Instanciation du provider et chargement de la Photo A et des CP
    logger.info("Chargement des données Salesforce (Photo A)...")
    provider = SalesforceProvider(root_dir)
    photo_a = await provider.get_photo_a(date_photo_a=date_photo_a)
    logger.debug(f"Nombre de clés chargées dans la Photo A : {len(photo_a)}")
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
        alerts, non_couverte_list = generate_validation_alerts(photo_a, new_mandates, date_photo_a)

        for alert in alerts:
            alert["run_id"] = run_id

        sites_scraped_succes = len(set(m.source_url for m in new_mandates))
        nb_changement = sum(1 for a in alerts if a["alerte_type"] == "CHANGEMENT")
        nb_confirmation = sum(1 for a in alerts if a["alerte_type"] == "CONFIRMATION")

        logger.info("=========================================")
        logger.info("   RAPPORT D'EXÉCUTION SYNTHÉTIQUE       ")
        logger.info("=========================================")
        logger.info(f"Élus chargés (Photo A) : {len(photo_a)}")
        logger.info(f"Sites scrapés avec succès : {sites_scraped_succes}")
        logger.info(f"Alertes CHANGEMENT : {nb_changement}")
        logger.info(f"Alertes CONFIRMATION : {nb_confirmation}")
        logger.info(f"Entrées NON_COUVERTE : {len(non_couverte_list)}")
        logger.info("=========================================")

        # Bulk Upload des alertes vers l'interface de validation
        if alerts:
            logger.info(f"Opération terminée. {len(alerts)} alertes de validation transmises vers N8N.")
            await send_to_n8n(session, alerts)
            await DiffCacheManager.save(cache)
        else:
            logger.info("Fin du script. Aucun changement détecté entre Salesforce et le Web.")

        coverage_path = os.path.join(root_dir, "coverage_report.json")
        existing_coverage = []
        if os.path.exists(coverage_path):
            with open(coverage_path, "r", encoding="utf-8") as f_cov:
                existing_coverage = json.load(f_cov)
        existing_coverage.append({
            "run_id": run_id,
            "date": datetime.utcnow().isoformat() + "Z",
            "non_couvertes": non_couverte_list
        })
        with open(coverage_path, "w", encoding="utf-8") as f_cov:
            json.dump(existing_coverage, f_cov, ensure_ascii=False, indent=2)
        logger.info(f"{len(non_couverte_list)} entrées NON_COUVERTE sauvegardées dans coverage_report.json")

_job_running = False

async def main(date_photo_a: str):
    global _job_running
    if _job_running:
        logger.warning("Job déjà en cours, exécution ignorée.")
        return
    _job_running = True
    try:
        run_id = str(uuid.uuid4())
        logger.info(f"Démarrage d'un nouveau job (run_id: {run_id})")
        await _execute_main(run_id, date_photo_a)
    finally:
        _job_running = False

if __name__ == "__main__":
    import argparse
    parser_args = argparse.ArgumentParser(description="Scraper élus municipaux")
    parser_args.add_argument(
        "--date_photo_a",
        type=str,
        required=True,
        help="Date extraction CSV Salesforce format DDMMYY (ex: 180326)"
    )
    args = parser_args.parse_args()
    asyncio.run(main(args.date_photo_a))
