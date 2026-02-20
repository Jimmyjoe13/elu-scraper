import os
import time
import logging
import requests
from rne_downloader import download_all_rne_datasets
from rne_parser import parse_all_rne_datasets
from rne_differ import compute_diff, load_state, save_state

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

WEBHOOK_URL = "https://n8n.media-start.fr/webhook/a14f3c73-e1ce-4700-8113-7ab035a9ae16"

def send_to_webhook(diff_report):
    """
    Envoie les données (le diff) au webhook n8n par lots (chunks) 
    pour éviter les timeouts ou les rejets en cas de payload massif.
    """
    if not diff_report:
        logging.info("Aucune donnée à envoyer.")
        return True
        
    CHUNK_SIZE = 50  # Envoi par paquets de 50 communes
    total_chunks = (len(diff_report) + CHUNK_SIZE - 1) // CHUNK_SIZE
    
    logging.info(f"Envoi de {len(diff_report)} communes modifiées au webhook ({total_chunks} lots)...")
    
    success_all = True
    
    for i in range(0, len(diff_report), CHUNK_SIZE):
        chunk = diff_report[i:i + CHUNK_SIZE]
        chunk_index = (i // CHUNK_SIZE) + 1
        
        try:
            logging.info(f"Envoi du lot {chunk_index}/{total_chunks} ({len(chunk)} communes)...")
            response = requests.post(WEBHOOK_URL, json={"rne_updates": chunk}, timeout=30)
            response.raise_for_status()
            
            # Petite pause pour ne pas surcharger n8n
            time.sleep(2)
        except Exception as e:
            logging.error(f"Erreur lors de l'envoi au webhook pour le lot {chunk_index}: {e}")
            success_all = False
            # On continue d'envoyer les autres lots même si l'un échoue
            
    if success_all:
        logging.info("Succès complet des envois Webhook !")
    else:
        logging.warning("Certains envois Webhook ont échoué.")
        
    return success_all

def main():
    logging.info("Démarrage de la synchronisation RNE...")
    
    # 1. Télécharger (commentez la ligne si vous lancez plusieurs fois pour gagner du temps)
    # L'appel complet du Datalake peut prendre quelques minutes
    # download_all_rne_datasets()
    
    # 2. Lire le nouvel état
    logging.info("Parsing des fichiers locaux RNE (Ceci prendra du temps pour toute la France)...")
    new_state = parse_all_rne_datasets()
    
    # 3. Charger l'état précédent
    old_state = load_state()
    is_first_run = len(old_state) == 0
    
    # 4. Calculer le diff (Plus de filtre, on vérifie les ~35000 communes)
    logging.info("Calcul des différences...")
    diff_report = compute_diff(old_state, new_state, insee_filter=None)
    
    if not diff_report:
        logging.info("Aucun changement détecté.")
        return
        
    logging.info(f"Changements détectés sur {len(diff_report)} commune(s).")
    
    # 5. Envoi Webhook avec sécurité "First Run"
    if is_first_run:
        logging.info("PREMIÈRE EXÉCUTION DÉTECTÉE.")
        logging.info(f"Pour éviter de saturer le webhook avec {len(diff_report)} créations d'un coup, l'envoi est ignoré.")
        logging.info("Seul l'état de référence actuel sera sauvegardé.")
        success = True
    else:
        success = send_to_webhook(diff_report)
    
    # 6. Mettre à jour et sauvegarder si l'envoi réussit
    if success:
        logging.info("Sauvegarde du nouvel état RNE global...")
        save_state(new_state)
        logging.info("Sauvegarde terminée.")
    else:
        logging.warning("L'état n'a pas été sauvegardé à cause d'erreurs d'envoi. La prochaine exécution retentera l'envoi complet.")

if __name__ == "__main__":
    main()
