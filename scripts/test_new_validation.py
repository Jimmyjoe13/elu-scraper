import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from unittest.mock import MagicMock
from datetime import datetime
from src.main import generate_validation_alerts

DATE_A = "170326"

# --- Photo A simulée (nouveau schéma : ville---fonction_canonique) ---
photo_a = {
    "paris---maire": {
        "nom": "Anne Hidalgo",
        "raw_nom": "Anne Hidalgo",
        "date_photo_a": DATE_A,
        "id_salesforce": "SF001",
        "type_mandat": "CONTRAT",
        "etat_contrat": "en_cours",
        "raw_ville": "Paris"
    },
    "lyon---adjoint": {
        "nom": "Jean Dupont",
        "raw_nom": "Jean Dupont",
        "date_photo_a": DATE_A,
        "id_salesforce": "SF002",
        "type_mandat": "PROSPECT",
        "etat_contrat": "inconnu",
        "raw_ville": "Lyon"
    },
    "bordeaux---maire": {
        "nom": "Pierre Martin",
        "raw_nom": "Pierre Martin",
        "date_photo_a": DATE_A,
        "id_salesforce": "SF003",
        "type_mandat": "CONTRAT",
        "etat_contrat": "en_cours",
        "raw_ville": "Bordeaux"
    },
}

# --- Mandates simulés (Photo B = résultats scraping) ---
def make_mandate(prenom, nom, ville, fonction, source_url, date_extraction_str="180326"):
    m = MagicMock()
    m.prenom = prenom
    m.nom = nom
    m.ville_ou_secteur = ville
    m.fonction = fonction
    m.source_url = source_url
    m.date_extraction = datetime.strptime(date_extraction_str, "%d%m%y")
    return m

mandates = [
    # Paris — même nom, date récente → attendu CONFIRMATION
    make_mandate("Anne", "Hidalgo", "Paris", "Maire", "https://paris.fr", "180326"),
    # Lyon — nom différent → attendu CHANGEMENT
    make_mandate("Gregory", "Doucet", "Lyon", "Adjoint au Maire", "https://lyon.fr", "180326"),
    # Bordeaux absent → attendu NON_COUVERTE
]

# --- Exécution ---
alerts, non_couvertes = generate_validation_alerts(photo_a, mandates, DATE_A)

print("=== RÉSULTATS ===")
print(f"Total alertes : {len(alerts)}")
for a in alerts:
    print(f"  [{a['alerte_type']}] commune={a.get('commune')} | "
          f"ancien={a.get('ancien_nom', a.get('nom', ''))} | "
          f"nouveau={a.get('nouveau_nom', '-')} | "
          f"fonction={a.get('fonction')}")

print(f"Non couvertes : {len(non_couvertes)}")
for nc in non_couvertes:
    print(f"  [NON_COUVERTE] commune={nc['commune']} | fonction={nc['fonction']}")

# --- Assertions ---
changements = [a for a in alerts if a["alerte_type"] == "CHANGEMENT"]
confirmations = [a for a in alerts if a["alerte_type"] == "CONFIRMATION"]

assert len(changements) == 1, f"FAIL: attendu 1 CHANGEMENT, obtenu {len(changements)}"
assert changements[0]["commune"] == "Lyon", f"FAIL: CHANGEMENT attendu pour Lyon"
assert changements[0]["ancien_nom"] == "Jean Dupont", f"FAIL: ancien_nom incorrect"

assert len(confirmations) == 1, f"FAIL: attendu 1 CONFIRMATION, obtenu {len(confirmations)}"
assert confirmations[0]["commune"] == "Paris", f"FAIL: CONFIRMATION attendue pour Paris"

assert len(non_couvertes) == 1, f"FAIL: attendu 1 NON_COUVERTE, obtenu {len(non_couvertes)}"
assert non_couvertes[0]["commune"] == "Bordeaux", f"FAIL: NON_COUVERTE attendue pour Bordeaux"

print("")
print("=== TOUS LES TESTS PASSENT ✅ ===")