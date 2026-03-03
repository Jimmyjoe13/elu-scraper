import os
import sqlite3

urls = [
    # Paris
    ("https://www.paris.fr/elu-e-s/maires-d-arrondissement/electeds", "paris_lutece_v1", "Paris"),
    ("https://www.paris.fr/elu-e-s/adjoint-e-s-a-la-maire/electeds", "paris_lutece_v1", "Paris"),
    ("https://www.paris.fr/elu-e-s/conseiller-ere-s-de-paris/electeds", "paris_lutece_v1", "Paris"),
    # Marseille
    ("https://mairie1-7.marseille.fr/liste-des-elues", "marseille_html_v1", "Marseille"),
    ("https://www.mairie-marseille2-3.com/pages/le-maire-et-les-elus", "marseille_html_v1", "Marseille"),
    ("https://www.marseille4-5.fr/__trashed/ma-mairie/le-conseil-darrondissements/les-elu-e-s-organigramme/", "marseille_html_v1", "Marseille"),
    ("https://mairie-marseille6-8.fr/index.php/lequipe-municipale", "marseille_html_v1", "Marseille"),
    ("https://marseille1112.fr/les-elus-au-conseil-d-arrondissements", "marseille_html_v1", "Marseille"),
    ("https://mairie13-14.marseille.fr/pages/les-elus", "marseille_html_v1", "Marseille"),
    ("https://mairie-marseille15-16.fr/minformer-sur-ma-mairie/le-maire-et-ses-adjoints/", "marseille_html_v1", "Marseille"),
    ("https://www.marseille9-10.fr/", "marseille_html_v1", "Marseille"),
]

def seed_db():
    root_dir = os.path.dirname(os.path.dirname(__file__))
    db_path = os.path.join(root_dir, 'elus_sources.db')
    
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    # Sécuriser la table si elle n'existait pas 
    c.execute('''CREATE TABLE IF NOT EXISTS source_urls
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT, parser_template TEXT, ville TEXT, is_active INTEGER)''')

    for url, tpl, ville in urls:
        c.execute("SELECT id FROM source_urls WHERE url = ?", (url,))
        if not c.fetchone():
            c.execute("INSERT INTO source_urls (url, parser_template, ville, scope, is_active) VALUES (?, ?, ?, 'secteur', 1)", (url, tpl, ville))
            print(f"Inserted PLM: {url}")
        else:
            c.execute("UPDATE source_urls SET is_active = 1, parser_template = ?, ville = ? WHERE url = ?", (tpl, ville, url))
            print(f"Updated PLM: {url}")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    seed_db()
