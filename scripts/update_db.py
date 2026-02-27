import sqlite3
import os

def migrate_db():
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'elus_sources.db')
    print(f"Migration de la base de données : {db_path}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Création de la table pour le Delta Engine (Action 2)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS mandats_history (
        id_technique TEXT PRIMARY KEY,
        ville TEXT,
        payload_json TEXT,
        status TEXT,
        last_seen_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    conn.commit()
    conn.close()
    print("Table mandats_history créée avec succès.")

if __name__ == "__main__":
    migrate_db()
