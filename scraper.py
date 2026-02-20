"""
Script de Scraping Multi-Mairies
---------------------------------
Ce script extrait les informations (Prénom, Nom, Poste) des élus de plusieurs 
mairies et les envoie vers un webhook n8n.

Mairies supportées : 
- Gignac-la-Nerthe
- Toulouse
- Lyon
"""

import os
import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime

# --- CONFIGURATION ---
WEBHOOK_URL = "https://n8n.media-start.fr/webhook/a14f3c73-e1ce-4700-8113-7ab035a9ae16"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

def clean_text(text):
    """Nettoie les espaces, sauts de ligne et caractères spéciaux."""
    if not text: return ""
    # Remplace les sauts de ligne et tabulations par des espaces
    text = text.replace('\r', ' ').replace('\n', ' ').replace('\t', ' ')
    # Supprime les espaces multiples
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def parse_name_simple(full_name):
    """Sépare le prénom du nom. Hypothèse : dernier mot = Nom."""
    full_name = clean_text(full_name)
    if not full_name: return "", ""
    parts = full_name.split()
    if len(parts) == 1: return "", parts[0]
    # Si le nom est en majuscules, on peut l'isoler plus précisément
    upper_parts = [p for p in parts if p.isupper() and len(p) > 1]
    if upper_parts:
        prenom = " ".join([p for p in parts if p not in upper_parts])
        nom = " ".join(upper_parts)
        return prenom, nom
    return " ".join(parts[:-1]), parts[-1]

def parse_name_by_case(full_name):
    """Sépare le prénom du nom en utilisant la casse (MAJUSCULES pour le nom)."""
    full_name = clean_text(full_name)
    clean_name = full_name.replace("Monsieur le Maire,", "").replace("M.", "").replace("Mme", "").strip()
    clean_name = clean_name.split(',')[0].strip()
    parts = clean_name.split()
    if not parts: return "", ""
    nom_parts = [p for p in parts if p.isupper()]
    prenom_parts = [p for p in parts if not p.isupper()]
    if not nom_parts:
        return " ".join(parts[:-1]), parts[-1]
    return " ".join(prenom_parts), " ".join(nom_parts)

def scrape_gignac():
    """Scraping spécifique pour Gignac-la-Nerthe."""
    url = "https://www.gignaclanerthe.fr/notre-mairie/le-maire-et-les-elus/"
    data = []
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        date_today = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

        # Maire
        maire_tag = soup.find('p', string=re.compile(r"Monsieur le Maire", re.I))
        if maire_tag:
            p, n = parse_name_by_case(maire_tag.get_text())
            data.append({"prenom": p, "nom": n, "poste": "Maire", "date_scraping": date_today, "source": url})

        # Adjoints/Conseillers
        for block in soup.find_all('div', class_='wpb_text_column'):
            ps = block.find_all('p')
            if ps and ps[0].get_text().startswith(('M. ', 'Mme ', 'Franck ')):
                if "Monsieur le Maire" in ps[0].get_text(): continue
                p, n = parse_name_by_case(ps[0].get_text())
                poste = clean_text(ps[1].get_text()) if len(ps) > 1 else "Conseiller"
                data.append({"prenom": p, "nom": n, "poste": poste, "date_scraping": date_today, "source": url})
    except Exception as e:
        print(f"Erreur Gignac: {e}")
    return data

def scrape_toulouse():
    """Scraping spécifique pour Toulouse."""
    url = "https://metropole.toulouse.fr/elus-au-conseil-municipal"
    data = []
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        date_today = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

        articles = soup.find_all('article', class_='elect__list')
        for art in articles:
            name_link = art.find('a', class_='elect__url')
            if not name_link: continue
            
            p, n = parse_name_simple(name_link.get_text())
            
            func_tag = art.find('p', class_='elect__function')
            deleg_tag = art.find('p', class_='elect__delegation')
            
            poste = ""
            if func_tag: poste += func_tag.get_text()
            if deleg_tag: 
                deleg_text = deleg_tag.get_text()
                poste = f"{poste} - {deleg_text}" if poste else deleg_text
            
            poste = clean_text(poste)
            if not poste: poste = "Conseiller municipal"

            data.append({
                "prenom": p, "nom": n, "poste": poste, 
                "date_scraping": date_today, "source": url
            })
    except Exception as e:
        print(f"Erreur Toulouse: {e}")
    return data

def scrape_lyon():
    """Scraping global Lyon (central + arrondissements) via URLs live."""
    # On utilise un dictionnaire pour regrouper par subdivision
    data = {
        "Mairie centrale": []
    }
    date_today = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    added_names = set()
    
    # 1. Mairie Centrale (Adjoints et Conseillers)
    central_urls = [
        "https://www.lyon.fr/actions-et-projets/le-maire-et-les-elus/les-adjoints-et-les-conseillers-delegues",
        "https://www.lyon.fr/actions-et-projets/le-maire-et-les-elus/les-conseilleres-et-conseillers-municipaux"
    ]
    
    for url in central_urls:
        print(f"Scraping Lyon Centrale ({url.split('/')[-1]})...")
        try:
            response = requests.get(url, headers=HEADERS, timeout=15)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            for li in soup.find_all('li'):
                a_tag = li.find('a', href=True)
                if not a_tag or "/elu/" not in a_tag['href']: continue
                
                strong = a_tag.find('strong')
                full_name = clean_text(strong.get_text() if strong else a_tag.get_text())
                
                if len(full_name) < 4 or any(x in full_name for x in ["Le Maire", "trombinoscope", "Mairies"]): continue
                if full_name in added_names: continue
                added_names.add(full_name)

                p, n = parse_name_simple(full_name)
                
                li_text = li.get_text(separator='|', strip=True)
                parts = [clean_text(pt) for pt in li_text.split('|') if pt.strip()]
                
                poste = "Conseiller municipal"
                if len(parts) > 1:
                    valid_parts = []
                    name_found = False
                    for part in parts:
                        if full_name in part and not name_found:
                            name_found = True
                            continue
                        if any(x in part for x in ["Lettre de mission", " Mo", " Ko"]): break
                        valid_parts.append(part)
                    if valid_parts:
                        poste = " ".join(valid_parts)
                
                data["Mairie centrale"].append({
                    "prenom": p, "nom": n, "poste": clean_text(poste), 
                    "date_scraping": date_today, "source": url
                })
        except Exception as e:
            print(f"Erreur Lyon Centrale ({url}): {e}")

    # 2. Arrondissements (live URLs)
    for i in range(1, 10):
        key = f"{i}er arrondissement" if i == 1 else f"{i}e arrondissement"
        data[key] = []
        url = f"https://www.lyon.fr/actions-et-projets/les-conseils-d-arrondissement/ca/{i}"
        print(f"Scraping Lyon Arrdt {i}...")
        try:
            response = requests.get(url, headers=HEADERS, timeout=15)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Maire (H1)
            h1s = soup.find_all('h1')
            for h1 in h1s:
                full_text = clean_text(h1.get_text())
                if "Conseil du" in full_text or len(full_text) < 4: continue
                if full_text in added_names: continue
                added_names.add(full_text)
                p, n = parse_name_simple(full_text)
                data[key].append({
                    "prenom": p, "nom": n, 
                    "poste": f"Maire du {i}er arrondissement" if i==1 else f"Maire du {i}e arrondissement", 
                    "date_scraping": date_today, "source": url
                })
            
            # Adjoints et Conseillers
            for a in soup.find_all('a', href=True):
                if "/elu/" not in a['href']: continue
                
                raw_text = a.get_text(separator='|', strip=True)
                parts = [clean_text(pt) for pt in raw_text.split('|') if pt.strip()]
                if not parts: continue
                
                full_name = parts[0]
                if len(full_name) < 4 or any(x in full_name for x in ["Le Maire", "trombinoscope", "Mairies"]): continue
                if full_name in added_names: continue
                added_names.add(full_name)
                
                p, n = parse_name_simple(full_name)
                
                poste_parts = []
                for pt in parts[1:]:
                    if any(x in pt for x in ["mandat", "Délégation", "Conseiller", "Adjoint", "ème", "er(e)"]):
                        poste_parts.append(pt)
                    elif pt[0].isupper() and len(pt) > 5:
                        poste_parts.append(pt)
                
                poste = " - ".join(poste_parts) if poste_parts else f"Conseiller d'arrondissement ({i})"
                data[key].append({"prenom": p, "nom": n, "poste": clean_text(poste), "date_scraping": date_today, "source": url})
        except Exception as e:
            print(f"Erreur Lyon Arrdt {i}: {e}")
            
    return data





def send_to_webhook(data):
    """Envoie les données au webhook."""
    if not data: return
    try:
        # Calcul du total en gérant les structures plates et imbriquées
        total_count = 0
        for city_data in data.values():
            if isinstance(city_data, dict):
                total_count += sum(len(sub) for sub in city_data.values())
            else:
                total_count += len(city_data)
                
        print(f"Envoi de {total_count} élus au webhook (regroupés par ville)...")
        response = requests.post(WEBHOOK_URL, json=data, timeout=20)
        response.raise_for_status()
        print(f"Succès ! Code : {response.status_code}")
    except Exception as e:
        print(f"Erreur Webhook: {e}")


if __name__ == "__main__":
    # --- Flux Principal ---
    results_by_city = {}
    
    # 1. Scraping Gignac
    print("Scraping Gignac-la-Nerthe...")
    results_by_city["Gignac"] = scrape_gignac()
    
    # 2. Scraping Toulouse
    print("Scraping Toulouse...")
    results_by_city["Toulouse"] = scrape_toulouse()
    
    # 3. Scraping Lyon
    print("Scraping Lyon...")
    results_by_city["Lyon"] = scrape_lyon()
    
    # 4. Affichage des résultats par ville
    for city, elus in results_by_city.items():
        if isinstance(elus, dict):
            city_total = sum(len(sub) for sub in elus.values())
            print(f" - {city} : {city_total} élus trouvés ({len(elus)} subdivisions).")
        else:
            print(f" - {city} : {len(elus)} élus trouvés.")

    # 5. Calcul du total global
    total_total = 0
    for elus in results_by_city.values():
        if isinstance(elus, dict):
            total_total += sum(len(sub) for sub in elus.values())
        else:
            total_total += len(elus)
            
    print(f"Total récupéré : {total_total} élus.")
    
    # 6. Envoi au Webhook
    if total_total > 0:
        send_to_webhook(results_by_city)
    else:
        print("Fin du script : aucune donnée collectée.")


