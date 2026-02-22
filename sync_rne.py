import os
import logging
from database import init_db
from rne_parser import parse_all_rne_datasets

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def main():
    logging.info("Démarrage de la synchronisation RNE SQLite...")
    
    init_db()
    
    # Décommentez pour télécharger dynamiquement
    # from rne_downloader import download_all_rne_datasets
    # download_all_rne_datasets()
    
    logging.info("Parsing streaming et ingestion batch SQLite en cours (économie de RAM activée)...")
    parse_all_rne_datasets()
    
    logging.info("Synchronisation terminée, base de données locale à jour.")

if __name__ == "__main__":
    main()
