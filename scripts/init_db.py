import sqlite3
import os

# Le chemin pointe vers ../elus_sources.db depuis scripts/init_db.py
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'elus_sources.db')

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Create table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS source_urls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ville TEXT NOT NULL,
            scope TEXT NOT NULL,
            url TEXT UNIQUE NOT NULL,
            parser_template TEXT NOT NULL,
            is_active BOOLEAN DEFAULT 1
        )
    ''')
    
    # Data to insert
    data = [
        ('Paris', 'Ville', 'https://www.paris.fr/la-maire-et-les-elu-e-s', 'paris_lutece_v1'),
        ('Paris', 'Arrondissement', 'https://mairie08.paris.fr/municipalite', 'paris_lutece_v1'),
        ('Lyon', 'Ville', 'https://www.lyon.fr/actions-et-projets/le-maire-et-les-elus/les-conseilleres-et-conseillers-municipaux', 'lyon_drupal_v1'),
        ('Lyon', 'Arrondissement', 'https://mairie2.lyon.fr/conseil_arrondissement', 'lyon_drupal_v1'),
        ('Marseille', 'Ville', 'https://www.marseille.fr/mairie/conseil-municipal/elus', 'marseille_html_v1')
    ]

    cursor.executemany('''
        INSERT OR IGNORE INTO source_urls (ville, scope, url, parser_template)
        VALUES (?, ?, ?, ?)
    ''', data)

    # Update any existing marseille_pdf_v1 to marseille_html_v1 just in case
    cursor.execute('''
        UPDATE source_urls
        SET parser_template = 'marseille_html_v1'
        WHERE parser_template = 'marseille_pdf_v1'
    ''')

    conn.commit()
    conn.close()
    print(f"Database initialized at {DB_PATH} with {len(data)} potential new entries.")

if __name__ == '__main__':
    init_db()
