import os
import csv
import logging
from database import upsert_elus_batch, init_db

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def process_file_stream(filepath, default_poste):
    """
    Lit un fichier CSV du RNE en streaming et insère par lots dans SQLite.
    """
    if not os.path.exists(filepath):
        logging.warning(f"Fichier introuvable: {filepath}")
        return

    logging.info(f"Analyse en streaming de {filepath}...")
    batch_size = 2000
    current_batch = {}

    with open(filepath, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter=';')
        
        # Pour une compatibilité robuste, on nettoie les espaces autour des noms de colonnes
        header = {k.strip(): k for k in reader.fieldnames}
        
        col_insee = header.get("Code de la commune") or header.get("Code de la commune ou de l'arrondissement")
        col_nom_commune = header.get("Libellé de la commune") or header.get("Libellé de la commune ou de l'arrondissement")
        col_nom = header.get("Nom de l'élu")
        col_prenom = header.get("Prénom de l'élu")
        col_dob = header.get("Date de naissance")
        col_fonction = header.get("Libellé de la fonction")

        if not all([col_insee, col_nom, col_prenom]):
            logging.error(f"Colonnes essentielles manquantes dans {filepath}. Header: {reader.fieldnames}")
            return

        for row in reader:
            insee = row.get(col_insee, "").strip()
            nom_commune = row.get(col_nom_commune, "").strip()
            nom = row.get(col_nom, "").strip().upper()
            prenom = row.get(col_prenom, "").strip()
            dob = row.get(col_dob, "").strip()
            
            poste = row.get(col_fonction, "").strip() if col_fonction else ""
            if not poste:
                poste = default_poste

            if not insee or not nom:
                continue

            # Création de la clé primaire robuste
            elu_key = f"{nom}|{prenom}|{dob}"
            
            if elu_key not in current_batch:
                current_batch[elu_key] = {
                    "code_insee": insee,
                    "nom_commune": nom_commune,
                    "nom": nom,
                    "prenom": prenom,
                    "postes": []
                }
                
            if poste and poste not in current_batch[elu_key]["postes"]:
                current_batch[elu_key]["postes"].append(poste)
                
            if len(current_batch) >= batch_size:
                upsert_elus_batch(current_batch)
                current_batch.clear()

        # Insérer les reliquats
        if current_batch:
            upsert_elus_batch(current_batch)
            current_batch.clear()
            
    logging.info(f"Terminé pour {filepath}.")

def parse_all_rne_datasets(data_dir="data_rne"):
    """
    Parse les fichiers RNE locaux et les pousse vers SQLite, sans saturation RAM.
    """
    init_db()
    
    # 1. Conseillers Municipaux
    process_file_stream(
        os.path.join(data_dir, "elus-conseillers-municipaux-cm.csv"),
        default_poste="Conseiller municipal"
    )

    # 2. Maires (souvent sans colonne "fonction", on force "Maire")
    process_file_stream(
        os.path.join(data_dir, "elus-maires-mai.csv"),
        default_poste="Maire"
    )

    # 3. Arrondissements
    process_file_stream(
        os.path.join(data_dir, "elus-conseillers-darrondissements-ca.csv"),
        default_poste="Conseiller d'arrondissement"
    )

    logging.info("Toutes les insertions SQL RNE sont terminées.")

if __name__ == "__main__":
    parse_all_rne_datasets()
