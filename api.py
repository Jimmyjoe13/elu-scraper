import os
from fastapi import FastAPI, Depends, HTTPException, Security, status, BackgroundTasks
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
import threading
import logging
import unicodedata
from dotenv import load_dotenv

load_dotenv()

try:
    from sync_rne import main as sync_main
except ImportError:
    logging.warning("Le module sync_rne n'a pas pu être importé. Mode développement local possible.")
    def sync_main():
        pass

from database import init_db, get_db_connection, upsert_elus_batch
import json


app = FastAPI(
    title="API RNE Élus",
    description="API pour déclencher et surveiller l'extraction des données du Répertoire National des Élus.",
    version="1.0.0"
)

@app.on_event("startup")
def startup_event():
    init_db()

# --- SECURITE ---
# Clé secrète d'accès à l'API (à remplacer en production par une variable d'environnement)
API_KEY = os.getenv("RNE_API_KEY", "super-secret-key-carel-2026").strip()
API_KEY_NAME = "X-API-Key"

api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=True)

def get_api_key(api_key: str = Security(api_key_header)):
    if api_key == API_KEY:
        return api_key
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Clé d'API invalide ou manquante."
    )

# --- MODELES PYDANTIC ---

class SalesforceElu(BaseModel):
    id_salesforce: str
    code_insee: str
    nom: str
    prenom: str
    fonction_actuelle: Optional[str] = None

class BatchSyncRequest(BaseModel):
    codes_insee: List[str] = Field(..., description="Liste des codes INSEE à synchroniser")

class ScrapeRequest(BaseModel):
    url: str = Field(..., description="URL de la mairie à scraper")
    code_insee: str = Field(..., description="Code INSEE de la commune")
    nom_commune: str = Field(default="Inconnue", description="Nom de la commune")

class BatchCiblesRequest(BaseModel):
    insee_codes: List[str] = Field(..., description="Liste des codes INSEE à analyser")

# --- ETAT GLOBAL DE L'API ---
# Variable globale et verrou pour thread-safety
sync_status = {
    "is_running": False,
    "last_run": None,
    "last_status": "inconnu"
}
status_lock = threading.Lock()

def run_sync_task():
    """Tâche de fond exécutant la synchronisation du RNE."""
    with status_lock:
        if sync_status["is_running"]:
            return # Sécurité supplémentaire
        sync_status["is_running"] = True
        sync_status["last_status"] = "en cours"
        
    try:
        logging.info("Démarrage de la tâche de synchronisation en arrière-plan...")
        sync_main()
        
        with status_lock:
            sync_status["last_status"] = "succès"
            sync_status["last_run"] = datetime.now().isoformat()
            
    except Exception as e:
        logging.error(f"Erreur critique dans la tâche de fond RNE: {e}")
        with status_lock:
            sync_status["last_status"] = "erreur"
    finally:
        with status_lock:
            sync_status["is_running"] = False

# --- ENDPOINTS ---

@app.post("/api/v1/sync", status_code=status.HTTP_202_ACCEPTED, tags=["Synchronisation"])
def trigger_sync(background_tasks: BackgroundTasks, api_key: str = Depends(get_api_key)):
    """
    Déclenche le processus de synchronisation RNE.
    Exécute les tâches lourdes en arrière-plan pour ne pas bloquer l'appelant.
    Nécessite le header X-API-Key.
    """
    with status_lock:
        if sync_status["is_running"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Une synchronisation est déjà en cours."
            )
            
    background_tasks.add_task(run_sync_task)
    return {
        "message": "La tâche de synchronisation RNE a été démarrée en arrière-plan avec succès.",
        "status": "accepted"
    }

@app.get("/api/v1/status", tags=["Supervision"])
def get_status(api_key: str = Depends(get_api_key)):
    """
    Vérifie l'état actuel du processus de synchronisation RNE.
    Nécessite le header X-API-Key.
    """
    with status_lock:
        current_status = dict(sync_status)
        
    return {
        "status": "online",
        "sync_process": current_status,
        "timestamp": datetime.now().isoformat()
    }

def normalize_string(input_str: str) -> str:
    """Retire les accents et passe en minuscules pour faciliter la recherche."""
    return ''.join(c for c in unicodedata.normalize('NFD', input_str) if unicodedata.category(c) != 'Mn').lower().strip()

@app.get("/api/v1/commune/{identifiant}/elus", tags=["Consultation"])
def get_commune_elus(identifiant: str, api_key: str = Depends(get_api_key)):
    """
    Récupère la liste des élus d'une commune spécifique depuis SQLite.
    L'identifiant peut être un code INSEE ou le nom exact de la ville sans les accents.
    """
    conn = get_db_connection()
    c = conn.cursor()
    
    if identifiant.isdigit() and len(identifiant) >= 4:
        c.execute("SELECT code_insee, nom_commune, nom, prenom, postes FROM elus WHERE code_insee = ?", (identifiant,))
        rows = c.fetchall()
    else:
        # Recherche par nom exact corrigé
        search_term = normalize_string(identifiant)
        c.execute("SELECT code_insee, nom_commune, nom, prenom, postes FROM elus")
        all_rows = c.fetchall()
        
        filtered_rows = []
        for row in all_rows:
            if normalize_string(row['nom_commune']) == search_term:
                filtered_rows.append(row)
        rows = filtered_rows

    c.close()
    conn.close()

    if not rows:
        raise HTTPException(status_code=404, detail=f"Commune introuvable: {identifiant}")

    commune_nom = rows[0]['nom_commune']
    commune_insee = rows[0]['code_insee']
    elus_list = []
    for row in rows:
        elus_list.append({
            "nom": row['nom'],
            "prenom": row['prenom'],
            "postes": json.loads(row['postes'])
        })

    return {
        "commune_code_insee": commune_insee,
        "commune_nom": commune_nom,
        "total_elus": len(elus_list),
        "elus": elus_list
    }

@app.get("/api/v1/commune/{insee}/cibles", tags=["Filtrage Métier"])
def get_commune_cibles(insee: str, api_key: str = Depends(get_api_key)):
    """
    Filtre: Ne retourne OBLIGATOIREMENT que les élus dont le poste contient 'Maire' ou 'Adjoint'.
    """
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT code_insee, nom_commune, nom, prenom, postes FROM elus WHERE code_insee = ?", (insee,))
    rows = c.fetchall()
    c.close()
    conn.close()
    
    if not rows:
        raise HTTPException(status_code=404, detail=f"Code INSEE {insee} introuvable.")
        
    cibles = []
    
    for row in rows:
        postes = json.loads(row['postes'])
        is_cible = any("maire" in p.lower() or "adjoint" in p.lower() for p in postes)
        if is_cible:
            cibles.append({
                "nom": row['nom'],
                "prenom": row['prenom'],
                "postes": postes
            })
            
    return {
        "commune_code_insee": insee,
        "commune_nom": rows[0]['nom_commune'],
        "total_cibles": len(cibles),
        "cibles": cibles
    }

@app.post("/api/v1/communes/cibles/batch", tags=["Filtrage Métier"])
def get_communes_cibles_batch(request: BatchCiblesRequest, api_key: str = Depends(get_api_key)):
    """
    Extrait par lot les élus cibles (Maire/Adjoint) pour une liste de codes INSEE.
    """
    if not request.insee_codes:
        return []
        
    conn = get_db_connection()
    c = conn.cursor()
    
    all_rows = []
    # Requêtes SQL en chunk de 900 max par précaution
    for i in range(0, len(request.insee_codes), 900):
        chunk = request.insee_codes[i:i + 900]
        placeholders = ','.join(['?'] * len(chunk))
        c.execute(f"SELECT code_insee, nom_commune, nom, prenom, postes FROM elus WHERE code_insee IN ({placeholders})", chunk)
        all_rows.extend(c.fetchall())
        
    c.close()
    conn.close()
    
    result_flat = []
    for row in all_rows:
        postes = json.loads(row['postes'])
        cibles_postes = [p for p in postes if "maire" in p.lower() or "adjoint" in p.lower()]
        
        if cibles_postes:
            poste_str = " - ".join(cibles_postes)
            result_flat.append({
                "code_insee": row['code_insee'],
                "nom_commune": row['nom_commune'],
                "nom_elu": row['nom'],
                "prenom_elu": row['prenom'],
                "poste": poste_str,
                "action_requise": "UPDATE"
            })
            
    return result_flat

def run_batch_task(codes_insee: List[str]):
    """Tâche de fond pour forcer la mise à jour (via main RNE) si N8N envoie le code."""
    with status_lock:
        if sync_status["is_running"]:
            return
        sync_status["is_running"] = True
        sync_status["last_status"] = "en cours (batch)"
        
    try:
        logging.info(f"Démarrage de la synchro batch pour {len(codes_insee)} commune(s)...")
        # En production, cela appellerait une fonction qui scrape/sync uniquement ces INSEEs
        sync_main()
        
        with status_lock:
            sync_status["last_status"] = "succès (batch)"
            sync_status["last_run"] = datetime.now().isoformat()
    except Exception as e:
        logging.error(f"Erreur critique batch: {e}")
        with status_lock:
            sync_status["last_status"] = "erreur (batch)"
    finally:
        with status_lock:
            sync_status["is_running"] = False

@app.post("/api/v1/sync/batch", status_code=status.HTTP_202_ACCEPTED, tags=["Synchronisation"])
def trigger_batch_sync(request: BatchSyncRequest, background_tasks: BackgroundTasks, api_key: str = Depends(get_api_key)):
    """
    Déclenche une tâche de fond (BackgroundTasks) qui va forcer la mise à jour RNE (via ingestion locale par lot).
    """
    with status_lock:
        if sync_status["is_running"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Une synchronisation est déjà en cours."
            )
            
    background_tasks.add_task(run_batch_task, request.codes_insee)
    return {
        "message": f"Synchronisation batch démarrée pour {len(request.codes_insee)} codes INSEE.",
        "status": "accepted"
    }

@app.post("/api/v1/compare/salesforce", tags=["Comparaison"])
def compare_salesforce(elus_sf: List[SalesforceElu], api_key: str = Depends(get_api_key)):
    """
    Compare un lot d'élus Salesforce avec l'état DB locale (SQLite).
    Retourne exclusivement les objets nécessitant une mise à jour ou une création.
    """
    if not elus_sf: return {"upserts": []}

    sf_by_insee = {}
    insee_codes_to_fetch = set()
    for sf_elu in elus_sf:
        if sf_elu.code_insee not in sf_by_insee:
            sf_by_insee[sf_elu.code_insee] = []
        sf_by_insee[sf_elu.code_insee].append(sf_elu)
        insee_codes_to_fetch.add(sf_elu.code_insee)

    conn = get_db_connection()
    c = conn.cursor()
    
    all_rows = []
    insee_list = list(insee_codes_to_fetch)
    for i in range(0, len(insee_list), 900):
        chunk = insee_list[i:i + 900]
        placeholders = ','.join(['?'] * len(chunk))
        c.execute(f"SELECT code_insee, nom_commune, nom, prenom, postes FROM elus WHERE code_insee IN ({placeholders})", chunk)
        all_rows.extend(c.fetchall())
        
    c.close()
    conn.close()
    
    local_elus_by_insee = {}
    for row in all_rows:
        insee = row['code_insee']
        if insee not in local_elus_by_insee:
            local_elus_by_insee[insee] = []
        
        local_elus_by_insee[insee].append({
            "nom": row['nom'],
            "prenom": row['prenom'],
            "postes": json.loads(row['postes'])
        })

    upserts = []
    
    for insee, sf_list in sf_by_insee.items():
        commune_elus = local_elus_by_insee.get(insee, [])
        if not commune_elus:
            continue
            
        # 1. Vérifier UPDATE
        for sf_elu in sf_list:
            local_elu = None
            for elu_info in commune_elus:
                if elu_info["nom"].upper() == sf_elu.nom.upper() and \
                   normalize_string(elu_info["prenom"]) == normalize_string(sf_elu.prenom):
                    local_elu = elu_info
                    break
                    
            if local_elu:
                postes_locaux = " - ".join(local_elu["postes"])
                if not sf_elu.fonction_actuelle or normalize_string(sf_elu.fonction_actuelle) != normalize_string(postes_locaux):
                    upserts.append({
                        "id_salesforce": sf_elu.id_salesforce,
                        "code_insee": insee,
                        "nom": sf_elu.nom,
                        "prenom": sf_elu.prenom,
                        "nouvelle_fonction": postes_locaux,
                        "action": "UPDATE"
                    })
                    
        # 2. Vérifier CREATE (élus locaux absents de Salesforce)
        sf_keys = [f"{e.nom.upper()}|{normalize_string(e.prenom)}" for e in sf_list]
        for elu_info in commune_elus:
            nom_local = elu_info["nom"].upper()
            prenom_local = normalize_string(elu_info["prenom"])
            local_key = f"{nom_local}|{prenom_local}"
            
            if local_key not in sf_keys:
                upserts.append({
                    "id_salesforce": None,
                    "code_insee": insee,
                    "nom": elu_info["nom"],
                    "prenom": elu_info["prenom"],
                    "nouvelle_fonction": " - ".join(elu_info["postes"]),
                    "action": "CREATE"
                })

    return {"upserts": upserts}

@app.post("/api/v1/scrape/url", tags=["Scraping"])
def scrape_url_endpoint(request: ScrapeRequest, api_key: str = Depends(get_api_key)):
    """
    Importe et exécute le scraper universel (Mistral AI) à la volée sur l'URL cible,
    puis met à jour SQLite (l'état local) pour ce code INSEE avec Upsert.
    Intègre une auto-découverte (Spidering) et un cache local SQLite.
    """
    import scraper
    
    url_racine = request.url.strip()
    code_insee = request.code_insee
    scraped_data = []
    
    conn = get_db_connection()
    c = conn.cursor()
    
    try:
        # Étape 1 : Vérifier le cache SQLite
        c.execute("SELECT url_exacte FROM communes_urls WHERE code_insee = ?", (code_insee,))
        row = c.fetchone()
        
        if row and row["url_exacte"]:
            exact_url = row["url_exacte"]
            logging.info(f"URL exacte trouvée dans le cache SQLite pour {code_insee}: {exact_url}")
        else:
            # Étape 2 : Pas de cache, on lance le Spidering
            exact_url = scraper.find_elus_url(url_racine)
            
            if not exact_url:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Le Spider n'a trouvé aucune page d'élus sur le domaine racine {url_racine}. À vérifier manuellement."
                )
                
            # Étape 3 : Mise en cache pour les prochaines fois
            c.execute('''
                INSERT OR REPLACE INTO communes_urls (code_insee, url_racine, url_exacte)
                VALUES (?, ?, ?)
            ''', (code_insee, url_racine, exact_url))
            conn.commit()
            logging.info(f"Nouvelle URL exacte {exact_url} mise en cache pour INSEE {code_insee}.")
            
        # Étape 4 : Lancement du Scraper Universel
        scraped_data = scraper.scrape_universal_url(exact_url, code_insee)
            
        if not scraped_data:
            # Suppression du cache si on a 0 élus extraits pour éviter le verrou mort sur un Soft 404
            c.execute("DELETE FROM communes_urls WHERE code_insee = ?", (code_insee,))
            conn.commit()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Aucune donnée d'élu trouvée ou l'IA n'a pas pu l'extraire depuis l'URL spécifiée. Le cache a été nettoyé."
            )
            
        batch_elus = {}
        for elu in scraped_data:
            nom = elu.get("nom", "").upper()
            prenom = elu.get("prenom", "")
            poste = elu.get("poste", "")
            
            # Utiliser la mention Scraped pour éviter un écrasement accidentel avec DoB si on ré-ingère le RNE brut
            id_elu = f"{nom}|{prenom}|Scraped"
            
            if id_elu not in batch_elus:
                batch_elus[id_elu] = {
                    "code_insee": request.code_insee,
                    "nom_commune": request.nom_commune, 
                    "nom": nom,
                    "prenom": prenom,
                    "postes": []
                }
            if poste and poste not in batch_elus[id_elu]["postes"]:
                batch_elus[id_elu]["postes"].append(poste)
                
        # Insertion directe en base SQL avec protection merge :
        upsert_elus_batch(batch_elus)
            
        return {
            "message": "Scraping universel réussi (IA), état local SQLite mis à jour avec réactivité J+1.",
            "code_insee": request.code_insee,
            "url_racine": url_racine,
            "url_exacte_utilisee": exact_url,
            "elus_mis_a_jour_ou_crees": len(scraped_data)
        }
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Erreur scraping url: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur interne pendant le scraping: {e}"
        )
    finally:
        c.close()
        conn.close()

# Lancement serveur dev si exécuté directement
if __name__ == "__main__":
    import uvicorn
    # Affiche un rappel clair de la clé dans la console
    print(f"Démarrage de l'API. Clé d'accès exigée: {API_KEY}")
    uvicorn.run("api:app", host="127.0.0.1", port=8000, reload=True)
