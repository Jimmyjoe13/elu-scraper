import sqlite3
import json
import logging
from typing import Dict

DB_PATH = "rne_data.db"

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Activer le mode WAL et réduire le fsync pour la performance / concurrence
    conn.execute('PRAGMA journal_mode=WAL;')
    conn.execute('PRAGMA synchronous=NORMAL;')
    return conn

def init_db():
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS elus (
                id_elu TEXT PRIMARY KEY,
                code_insee TEXT NOT NULL,
                nom_commune TEXT NOT NULL,
                nom TEXT NOT NULL,
                prenom TEXT NOT NULL,
                postes TEXT NOT NULL
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_code_insee ON elus(code_insee)')
        conn.commit()
        logging.info("Base de données SQLite initialisée avec succès.")
    except Exception as e:
        logging.error(f"Erreur lors de l'initialisation de la DB SQLite: {e}")
    finally:
        conn.close()

def upsert_elus_batch(batch_elus: Dict[str, Dict]):
    """
    Upsert multiple elus.
    batch_elus is a dictionary: { "id_elu": { "code_insee": ..., "nom_commune": ..., "nom": ..., "prenom": ..., "postes": [...] } }
    """
    if not batch_elus: return
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        ids = list(batch_elus.keys())
        
        # We query existing rows to safely merge 'postes' lists
        placeholders = ','.join(['?'] * len(ids))
        cursor.execute(f"SELECT id_elu, postes FROM elus WHERE id_elu IN ({placeholders})", ids)
        existing_rows = cursor.fetchall()
        
        for row in existing_rows:
            id_elu = row['id_elu']
            existing_postes = json.loads(row['postes'])
            for p in existing_postes:
                if p not in batch_elus[id_elu]['postes']:
                    batch_elus[id_elu]['postes'].append(p)
                    
        formatted_data = []
        for id_elu, elu in batch_elus.items():
            formatted_data.append((
                id_elu,
                elu['code_insee'],
                elu['nom_commune'],
                elu['nom'],
                elu['prenom'],
                json.dumps(elu['postes'], ensure_ascii=False)
            ))
            
        cursor.executemany('''
            INSERT OR REPLACE INTO elus (id_elu, code_insee, nom_commune, nom, prenom, postes)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', formatted_data)
        conn.commit()
    finally:
        conn.close()
