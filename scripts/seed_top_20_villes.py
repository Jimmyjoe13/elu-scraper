"""
Seed script : insère les 20 grandes villes françaises dans source_urls.

Usage :
    python -m scripts.seed_top_20_villes

Idempotent grâce à INSERT OR IGNORE (unicité sur la colonne `url`).
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "elus_sources.db")

VILLES = [
    ("TOULOUSE",      "https://metropole.toulouse.fr/elus-au-conseil-municipal"),
    ("NICE",          "https://www.nice.fr/conseil-municipal/les-elus/"),
    ("NANTES",        "https://metropole.nantes.fr/ma-ville-ma-metropole/nantes-et-ses-11-quartiers/elus-municipaux"),
    ("MONTPELLIER",   "https://www.montpellier.fr/institutions/ville-de-montpellier/les-elus-de-la-ville-de-montpellier"),
    ("STRASBOURG",    "https://www.strasbourg.eu/annuaire-elus-ville"),
    ("BORDEAUX",      "https://www.bordeaux.fr/elus"),
    ("LILLE",         "https://www.lille.fr/Votre-Mairie/Le-conseil-municipal/Les-conseillers-municipaux"),
    ("REIMS",         "https://www.reims.fr/la-ville-de-reims/vie-institutionnelle/les-elus"),
    ("SAINT-ETIENNE", "https://www.saint-etienne.fr/annuaire-des-elu-e-s"),
    ("LE HAVRE",      "http://lehavre.fr/ma-ville/le-conseil-municipal/les-elus"),
    ("TOULON",        "https://toulon.fr/le-conseil-municipal-de-la-ville-de-toulon"),
    ("GRENOBLE",      "https://www.grenoble.fr/147-les-elue-s.htm"),
    ("DIJON",         "https://www.dijon.fr/la-vie-municipale/les-elus/trombinoscope-des-elus-du-conseil-municipal/"),
    ("ANGERS",        "https://www.angers.fr/l-action-municipale/vos-elus/trombinoscope/index.html"),
    ("BREST",         "https://brest.fr/brest-ville-et-metropole/la-ville-de-brest/les-elus-de-la-ville-de-brest"),
    ("TOURS",         "https://www.tours.fr/elus/"),
    ("AMIENS",        "https://www.amiens.fr/Institutions/Vos-elus/Conseillers-municipaux"),
    ("LIMOGES",       "https://www.limoges.fr/citoyenne/trombinoscope-des-elus-du-conseil-municipal"),
    ("PERPIGNAN",     "https://perpignan.fr/municipalite/conseil-municipal"),
    ("METZ",          "https://metz.fr/projets/conseil_municipal/membres_conseil_militant.php"),
]

PARSER_TEMPLATE = "auto_agent_v1"


def seed():
    db_path = os.path.normpath(DB_PATH)
    print(f"Connexion à la base : {db_path}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    inserted = 0
    for ville, url in VILLES:
        cursor.execute(
            """
            INSERT OR IGNORE INTO source_urls (ville, scope, url, parser_template, is_active)
            VALUES (?, 'commune', ?, ?, 1)
            """,
            (ville, url, PARSER_TEMPLATE),
        )
        if cursor.rowcount > 0:
            inserted += 1
            print(f"  ✅ {ville}")
        else:
            print(f"  ⏭️  {ville} (déjà présente)")

    conn.commit()
    conn.close()
    print(f"\nTerminé : {inserted}/{len(VILLES)} villes insérées.")


if __name__ == "__main__":
    seed()
