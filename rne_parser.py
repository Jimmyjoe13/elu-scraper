import os
import csv
import json
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def process_file(filepath, default_poste, state):
    """
    Lit un fichier CSV du RNE et met à jour l'état.
    """
    if not os.path.exists(filepath):
        logging.warning(f"Fichier introuvable: {filepath}")
        return

    logging.info(f"Analyse de {filepath}...")
    with open(filepath, mode='r', encoding='utf-8') as f:
        # Les fichiers utilisent le point-virgule
        reader = csv.DictReader(f, delimiter=';')
        
        # Pour une compatibilité robuste, on nettoie les espaces autour des noms de colonnes
        header = {k.strip(): k for k in reader.fieldnames}
        
        # Mapping des colonnes (elles peuvent légèrement varier)
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
            
            # Gestion de la fonction / poste
            poste = row.get(col_fonction, "").strip() if col_fonction else ""
            if not poste:
                poste = default_poste

            if not insee or not nom:
                continue

            # Création de la clé unique
            elu_key = f"{nom}|{prenom}|{dob}"

            if insee not in state:
                state[insee] = {
                    "nom_commune": nom_commune,
                    "elus": {}
                }

            if elu_key not in state[insee]["elus"]:
                state[insee]["elus"][elu_key] = {
                    "nom": nom,
                    "prenom": prenom,
                    "postes": []
                }

            if poste not in state[insee]["elus"][elu_key]["postes"]:
                state[insee]["elus"][elu_key]["postes"].append(poste)

def parse_all_rne_datasets(data_dir="data_rne"):
    """
    Parse les fichiers RNE locaux et retourne un dictionnaire agrégé.
    """
    state = {}
    
    # 1. Conseillers Municipaux
    # On ajoute un default poste si par hasard la colonne fonction est vide
    process_file(
        os.path.join(data_dir, "elus-conseillers-municipaux-cm.csv"),
        default_poste="Conseiller municipal",
        state=state
    )

    # 2. Maires (souvent sans colonne "fonction", donc on force "Maire")
    process_file(
        os.path.join(data_dir, "elus-maires-mai.csv"),
        default_poste="Maire",
        state=state
    )

    # 3. Arrondissements
    process_file(
        os.path.join(data_dir, "elus-conseillers-darrondissements-ca.csv"),
        default_poste="Conseiller d'arrondissement",
        state=state
    )
    
    # 4. Communautaires (EPCI) - Optionnel si l'on veut un scope agglomération
    # process_file(
    #     os.path.join(data_dir, "elus-conseillers-communautaires-epci.csv"),
    #     default_poste="Conseiller communautaire",
    #     state=state
    # )

    logging.info(f"Parsing terminé. Communes trouvées : {len(state)}")
    return state

if __name__ == "__main__":
    state = parse_all_rne_datasets()
    # Test avec la commune de Gignac (Insee potentiellement 13043 pour Gignac-la-Nerthe)
    gignac_insee = "13043"
    if gignac_insee in state:
        print(f"Elus de {state[gignac_insee]['nom_commune']}:")
        for elu in state[gignac_insee]["elus"].values():
            print(f"- {elu['prenom']} {elu['nom']} : {', '.join(elu['postes'])}")
    else:
        print("Commune 13043 non trouvée.")
