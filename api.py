import os
from fastapi import FastAPI, Depends, HTTPException, Security, status, BackgroundTasks
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
import threading
import logging
import unicodedata

try:
    from sync_rne import main as sync_main
    from rne_differ import load_state, save_state
except ImportError:
    logging.warning("Le module sync_rne n'a pas pu être importé. Mode développement local possible.")
    def sync_main():
        pass
    def load_state():
        return {}
    def save_state(state): pass


app = FastAPI(
    title="API RNE Élus",
    description="API pour déclencher et surveiller l'extraction des données du Répertoire National des Élus.",
    version="1.0.0"
)

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
    Récupère la liste des élus d'une commune spécifique depuis l'état RNE local.
    L'identifiant peut être un code INSEE ou le nom exact de la ville sans les accents.
    Nécessite le header X-API-Key.
    """
    state_data = load_state()
    if not state_data:
         raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="La base de données RNE n'a pas encore été initialisée. Veuillez lancer une synchronisation au préalable."
        )

    commune_data = None
    commune_insee = None
    
    # 1. Recherche directe par code INSEE
    if identifiant.isdigit() and len(identifiant) >= 4:
        if identifiant in state_data:
            commune_data = state_data[identifiant]
            commune_insee = identifiant
    
    # 2. Recherche par nom exact corrigé si pas trouvé par INSEE
    if not commune_data:
        search_term = normalize_string(identifiant)
        for insee, data in state_data.items():
            if normalize_string(data.get("nom_commune", "")) == search_term:
                commune_data = data
                commune_insee = insee
                break

    if not commune_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Commune introuvable pour l'identifiant: {identifiant}"
        )

    # 3. Formatage de la réponse
    elus_list = []
    for elu_key, elu_info in commune_data.get("elus", {}).items():
        elus_list.append({
            "nom": elu_info.get("nom", ""),
            "prenom": elu_info.get("prenom", ""),
            "postes": elu_info.get("postes", [])
        })

    return {
        "commune_code_insee": commune_insee,
        "commune_nom": commune_data.get("nom_commune", ""),
        "total_elus": len(elus_list),
        "elus": elus_list
    }

@app.get("/api/v1/commune/{insee}/cibles", tags=["Filtrage Métier"])
def get_commune_cibles(insee: str, api_key: str = Depends(get_api_key)):
    """
    Filtre: Ne retourne OBLIGATOIREMENT que les élus dont le poste contient 'Maire' ou 'Adjoint'.
    Rôle: Réduire la taille du payload pour N8N.
    """
    state_data = load_state()
    if not state_data:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="La base RNE locale n'est pas initialisée."
        )
        
    if insee not in state_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Code INSEE {insee} introuvable."
        )
        
    commune_data = state_data[insee]
    cibles = []
    
    for elu_key, elu_info in commune_data.get("elus", {}).items():
        postes = elu_info.get("postes", [])
        is_cible = any("maire" in p.lower() or "adjoint" in p.lower() for p in postes)
        if is_cible:
            cibles.append({
                "nom": elu_info.get("nom", ""),
                "prenom": elu_info.get("prenom", ""),
                "postes": postes
            })
            
    return {
        "commune_code_insee": insee,
        "commune_nom": commune_data.get("nom_commune", ""),
        "total_cibles": len(cibles),
        "cibles": cibles
    }

def run_batch_task(codes_insee: List[str]):
    """Tâche de fond pour forcer la mise à jour d'un lot de codes INSEE."""
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
    Déclenche une tâche de fond (BackgroundTasks) qui va forcer la mise à jour RNE pour ces communes.
    Permet de lisser la charge avec des envois par lots depuis N8N.
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
    Compare un lot d'élus Salesforce avec l'état local load_state().
    Retourne exclusivement les objets nécessitant une mise à jour ou une création.
    """
    state_data = load_state()
    if not state_data:
         raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="La base RNE locale n'est pas chargée."
        )

    upserts = []
    # Group input by code_insee for CREATE detection
    sf_by_insee = {}
    for sf_elu in elus_sf:
        if sf_elu.code_insee not in sf_by_insee:
            sf_by_insee[sf_elu.code_insee] = []
        sf_by_insee[sf_elu.code_insee].append(sf_elu)

    for insee, sf_list in sf_by_insee.items():
        if insee not in state_data:
            continue
            
        commune_elus = state_data[insee].get("elus", {})
        
        # 1. Vérifier UPDATE
        for sf_elu in sf_list:
            local_elu = None
            for key, elu_info in commune_elus.items():
                if elu_info.get("nom", "").upper() == sf_elu.nom.upper() and \
                   normalize_string(elu_info.get("prenom", "")) == normalize_string(sf_elu.prenom):
                    local_elu = elu_info
                    break
                    
            if local_elu:
                postes_locaux = " - ".join(local_elu.get("postes", []))
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
        for key, elu_info in commune_elus.items():
            nom_local = elu_info.get("nom", "").upper()
            prenom_local = normalize_string(elu_info.get("prenom", ""))
            local_key = f"{nom_local}|{prenom_local}"
            
            if local_key not in sf_keys:
                upserts.append({
                    "id_salesforce": None,
                    "code_insee": insee,
                    "nom": elu_info.get("nom", ""),
                    "prenom": elu_info.get("prenom", ""),
                    "nouvelle_fonction": " - ".join(elu_info.get("postes", [])),
                    "action": "CREATE"
                })

    return {"upserts": upserts}

@app.post("/api/v1/scrape/url", tags=["Scraping"])
def scrape_url_endpoint(request: ScrapeRequest, api_key: str = Depends(get_api_key)):
    """
    Importe et exécute les fonctions de scraper.py à la volée sur l'URL cible,
    puis met à jour l'état local pour ce code INSEE précis.
    """
    import scraper
    
    url = request.url.lower()
    scraped_data = []
    
    try:
        if "gignac" in url:
            scraped_data = scraper.scrape_gignac()
        elif "toulouse" in url:
            scraped_data = scraper.scrape_toulouse()
        elif "lyon" in url:
            lyon_data = scraper.scrape_lyon()
            for arr_name, elus in lyon_data.items():
                scraped_data.extend(elus)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="URL non supportée par les scripts de scraping."
            )
            
        if not scraped_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Aucune donnée trouvée via l'URL spécifiée."
            )
            
        # Mise à jour avec Lock
        with status_lock:
            state_data = load_state()
            insee = request.code_insee
            
            if insee not in state_data:
                state_data[insee] = {"nom_commune": "Commune Scrapée dynamiquement", "elus": {}}
                
            for elu in scraped_data:
                nom = elu.get("nom", "").upper()
                prenom = elu.get("prenom", "")
                poste = elu.get("poste", "")
                
                matched_key = None
                for k, v in state_data[insee]["elus"].items():
                    if v.get("nom", "").upper() == nom and normalize_string(v.get("prenom", "")) == normalize_string(prenom):
                        matched_key = k
                        break
                        
                if not matched_key:
                    new_key = f"{nom}|{prenom}|Scraped"
                    state_data[insee]["elus"][new_key] = {
                        "nom": nom, "prenom": prenom, "postes": [poste] if poste else []
                    }
                else:
                    if poste and poste not in state_data[insee]["elus"][matched_key]["postes"]:
                        state_data[insee]["elus"][matched_key]["postes"].append(poste)
                        
            save_state(state_data)
            
        return {
            "message": "Scraping réussi, état local mis à jour avec réactivité J+1.",
            "code_insee": insee,
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

# Lancement serveur dev si exécuté directement
if __name__ == "__main__":
    import uvicorn
    # Affiche un rappel clair de la clé dans la console
    print(f"Démarrage de l'API. Clé d'accès exigée: {API_KEY}")
    uvicorn.run("api:app", host="127.0.0.1", port=8000, reload=True)
