import asyncio
import csv
import sqlite3
import aiohttp
import os
import re
import unicodedata
import sys

# Ajout du path pour importer les modules internes
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.utils.url_finder import find_city_website

def normalize_ville(s):
    if not s: return ''
    s = str(s).replace('-', ' ')
    s = unicodedata.normalize('NFKD', str(s)).encode('ASCII', 'ignore').decode('utf-8')
    s = s.strip().lower()
    s = re.sub(r'\s+(cedex\s*\d*|rp|sp|cx\s*\d*|ptt)$', '', s).strip()
    return s

async def seed_from_csv():
    csv_files = ['Fichier forgeron3 test mandat prospect.csv', 'Fichier forgeron3 test mandat contrat.csv']
    cities = set()
    
    # 1. Extraction des villes uniques
    print("Étape 1: Extraction des communes depuis les CSV...")
    for file in csv_files:
        if not os.path.exists(file): 
            continue
        with open(file, encoding='cp850', errors='replace') as f:
            reader = csv.reader(f, delimiter=';')
            headers = next(reader)
            for row in reader:
                if len(row) > 8:
                    cp = row[7].strip()
                    ville_raw = row[8].strip()
                    norm_v = normalize_ville(ville_raw)
                    # Exclusion des PLM déjà traitées
                    if norm_v and norm_v not in ['paris', 'lyon', 'marseille']:
                        cities.add((ville_raw, cp, norm_v))

    print(f"[{len(cities)}] communes uniques identifiées à traiter.")
    
    # 2. Connexion DB et recherche URL
    db_path = 'elus_sources.db'
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    added_count = 0
    
    async with aiohttp.ClientSession() as session:
        for ville_raw, cp, norm_v in cities:
            # Vérifier si la ville est déjà dans la base
            cursor.execute('SELECT 1 FROM source_urls WHERE ville = ?', (norm_v.upper(),))
            if cursor.fetchone():
                continue
            
            print(f"Recherche de l'URL pour {ville_raw} ({cp})...")
            url = await find_city_website(session, ville_raw, cp)
            
            if url:
                print(f"   ✅ URL trouvée : {url}")
                cursor.execute('''
                    INSERT INTO source_urls (url, parser_template, ville, scope, is_active)
                    VALUES (?, ?, ?, 'Ville', 1)
                ''', (url, 'generic_html_v1', norm_v.upper()))
                conn.commit()
                added_count += 1
            else:
                print(f"   ❌ URL introuvable pour {ville_raw}")
                
    conn.close()
    print(f"\nTerminé. {added_count} nouvelles mairies injectées dans la base de données.")

if __name__ == '__main__':
    asyncio.run(seed_from_csv())
