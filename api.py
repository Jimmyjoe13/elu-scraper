import os
from fastapi import FastAPI, Depends, HTTPException, Security, status, BackgroundTasks
from fastapi.security import APIKeyHeader
from datetime import datetime
import threading
import logging
import unicodedata

try:
    from sync_rne import main as sync_main
    from rne_differ import load_state
except ImportError:
    logging.warning("Le module sync_rne n'a pas pu être importé. Mode développement local possible.")
    def sync_main():
        pass
    def load_state():
        return {}


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

# Lancement serveur dev si exécuté directement
if __name__ == "__main__":
    import uvicorn
    # Affiche un rappel clair de la clé dans la console
    print(f"Démarrage de l'API. Clé d'accès exigée: {API_KEY}")
    uvicorn.run("api:app", host="127.0.0.1", port=8000, reload=True)
