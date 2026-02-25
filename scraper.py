"""
Script de Scraping Universel avec Mistral AI
---------------------------------
Ce script extrait les informations des élus d'une mairie en scrapant le contenu texte brut
d'une URL puis en demandant à Mistral AI d'en formater la sortie au format JSON.
"""

import os
import requests
from bs4 import BeautifulSoup
import json
import logging
import csv
from urllib.parse import urljoin, urlparse
import urllib3
import re
from curl_cffi import requests as curequests
from dotenv import load_dotenv

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv()

# --- CONFIGURATION ---
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
# Le fallback webhook restera pour un envoi debug ou d'autres usages.
WEBHOOK_URL = "https://n8n.media-start.fr/webhook/a14f3c73-e1ce-4700-8113-7ab035a9ae16"

def clean_html_to_text(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 1. Détruire tout le "bruit" (menus, footers, scripts, popups)
    for element in soup(['script', 'style', 'header', 'footer', 'nav', 'aside', 'form', 'noscript', 'iframe']):
        element.decompose()
        
    # 2. Chercher la zone de contenu principal
    main_content = soup.find('main') or soup.find(id=re.compile('content|main', re.I)) or soup.find('article')
    
    if main_content:
        text = main_content.get_text(separator=' ', strip=True)
    else:
        # Fallback si pas de balise principale claire
        text = soup.get_text(separator=' ', strip=True)
        
    # 3. Nettoyer les espaces multiples
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def extract_elus_with_mistral(text_input):
    """Appel à l'API Mistral AI pour l'extraction de l'entité / NLP."""
    if not MISTRAL_API_KEY:
        logging.error("MISTRAL_API_KEY non configurée. Le scraping universel est désactivé.")
        raise Exception("Clé API Mistral manquante (MISTRAL_API_KEY).")
        
    mistral_url = "https://api.mistral.ai/v1/chat/completions"
    
    prompt = f"""
Tu es un système expert d'extraction de données rigoureux. Voici le texte brut d'une page web d'une mairie française. Ta mission est d'extraire la liste de l'équipe municipale (le Maire, les Adjoints, les Conseillers).

RÈGLES IMPÉRATIVES :
1. Tu dois retourner UNIQUEMENT un objet JSON. 
2. Le JSON doit contenir une clé "elus" qui est un tableau (list).
3. Chaque objet du tableau doit avoir EXACTEMENT ces clés: "prenom", "nom", "poste".
4. Les valeurs de "nom" doivent être ENTIÈREMENT EN MAJUSCULES.
5. Si aucun élu n'est trouvé, retourne {{"elus": []}}.
6. Ne génère pas de balises Markdown ` ```json `, renvoie seulement le JSON brut.
7. Ne fais aucune phrase d'introduction ni conclusion.

Texte web à traiter:
{text_input}
"""

    payload = {
        "model": "mistral-small-latest", # Modèle rapide et pas cher, idéal pour du parsing structuré
        "messages": [
             {"role": "user", "content": prompt}
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"}
    }
    
    headers = {
        "Authorization": f"Bearer {MISTRAL_API_KEY}",
        "Content-Type": "application/json"
    }

    try:
        logging.info("Envoi d'une requête au modèle Mistral-small (LLM Parsing)...")
        response = requests.post(mistral_url, json=payload, headers=headers, timeout=60)
        response.raise_for_status()
        
        content = response.json()['choices'][0]['message']['content'].strip()
        
        # Sécurité pour les modèles qui forcent quand même les backticks Markdown
        if content.startswith("```json"):
            content = content[7:]
        elif content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
            
        json_data = json.loads(content)
        return json_data.get("elus", [])
        
    except Exception as e:
        logging.error(f"Erreur avec Mistral API: {e}")
        return []

def parse_salesforce_csv(filepath):
    """Lit un fichier CSV et renvoie une liste de dictionnaires."""
    encodings = ['utf-8-sig', 'windows-1252', 'iso-8859-1', 'cp850', 'mac_roman']
    
    for enc in encodings:
        try:
            with open(filepath, mode='r', encoding=enc) as f:
                f.read(100) # Test de lecture
            with open(filepath, mode='r', encoding=enc) as f:
                reader = csv.DictReader(f, delimiter=';')
                return list(reader)
        except UnicodeDecodeError:
            continue
    raise Exception(f"Impossible de lire le fichier CSV {filepath} avec les encodages testés.")

def get_mairie_url(code_postal, ville):
    """
    Récupère l'URL de la mairie.
    Pour le POC: Dictionnaire en dur, sinon simulation API publique.
    """
    ville_upper = ville.upper().strip()
    
    # Dictionnaire POC
    poc_urls = {
        "PARIS": "https://www.paris.fr/",
        "LYON": "https://www.lyon.fr/",
        "MARSEILLE": "https://www.marseille.fr/",
        "NANTES": "https://metropole.nantes.fr/",
        "BORDEAUX": "https://www.bordeaux.fr/"
    }
    
    for p, url_p in poc_urls.items():
        if p in ville_upper:
            return url_p
    
    # Simulation d'un appel à l'API publique (Open Data) pour les autres villes
    # Exemple: api-lannuaire.service-public.fr ou équivalent
    # url_api = f"https://api-lannuaire.service-public.fr/api/explore/v2.1/catalog/datasets/api-lannuaire-administration/records?where=code_postal={code_postal}&where=pivot=mairie"
    # response = requests.get(url_api)
    # url_mairie = response.json()...
    
    logging.info(f"Simulation API publique pour obtenir l'URL de {ville} ({code_postal})")
    # Retour au format URL factice / standard probable
    return f"https://www.{ville_upper.lower().replace(' ', '')}.fr"

def hybrid_scrape(url, commune_nom):
    """
    Extraction hybride sans coût Mistral excessif.
    Mistral est utilisé UNIQUEMENT pour PLM.
    """
    plm_cities = ["PARIS", "LYON", "MARSEILLE"]
    is_plm = any(p in commune_nom.upper() for p in plm_cities)
    
    logging.info(f"Début extraction hybride pour {commune_nom} (PLM: {is_plm}) via: {url}")
    try:
        response = curequests.get(url, impersonate="chrome110", timeout=30, verify=False)
        response.raise_for_status()
        
        clean_text = clean_html_to_text(response.text)
        
        if is_plm:
            logging.info("Ville complexe (PLM). Activation de Mistral forcé.")
            return extract_elus_with_mistral(clean_text)
            
        # Extraction Regex sans fallback Mistral (anti coût astronomique)
        elus = []
        
        # Regex basique pour trouver ex: "Maire : Jean DUPONT"
        matches = re.findall(r'(?:Maire|Le Maire|La Maire)\s*:?\s*([A-Z][a-zA-Z\s\-]+[A-Z]+)', clean_text)
        for match in matches:
            elus.append({"prenom": "", "nom": match.strip(), "poste": "Maire"})
            
        soup = BeautifulSoup(response.text, 'html.parser')
        # Recherche basique de blocs d'élus
        for element in soup.find_all(['h2', 'h3', 'p', 'li']):
            texte = element.get_text(strip=True).replace('\\n', ' ')
            texte_lower = texte.lower()
            if 'adjoint' in texte_lower and len(texte) < 150:
                elus.append({"prenom": "", "nom": texte.upper(), "poste": "Adjoint"})
            elif 'conseill' in texte_lower and len(texte) < 150:
                elus.append({"prenom": "", "nom": texte.upper(), "poste": "Conseiller"})
                
        logging.info(f"{len(elus)} élus trouvés avec extraction Regex/BS4 (Coût 0).")
        return elus
        
    except Exception as e:
        logging.error(f"Échec de l'extraction sur {url}: {e}")
        return []

def find_elus_url(root_domain: str) -> str:
    """
    Auto-découverte experte avec trois niveaux de fallback.
    Minimise l'impact RAM et accélère la découverte.
    """
    if not root_domain.startswith("http"):
        root_domain = f"https://{root_domain}"
        
    logging.info(f"Spidering en cours sur le domaine racine : {root_domain}")
    
    # --- ÉTAPE 1 : Homepage Crawl (Le plus fiable) ---
    try:
        response = curequests.get(root_domain, impersonate="chrome110", timeout=30, verify=False)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        links = soup.find_all('a', href=True)
        
        keywords_href = ["/elu", "-elu", "elu-", "conseil-municipal", "equipe-municipale", "maire", "vos-elus", "trombinoscope"]
        
        for link in links:
            href = link.get('href', '').lower()
            text = link.get_text(strip=True).lower()
            
            href_match = any(kw in href for kw in keywords_href)
            text_match = re.search(r'\b(élu|élus|maire|conseil municipal|équipe municipale|vos élus)\b', text)
            
            if href_match or text_match:
                exact_url = urljoin(root_domain, link['href'])
                logging.info(f"URL exacte trouvée via Homepage crawl : {exact_url}")
                return exact_url
    except Exception as e:
        logging.warning(f"Homepage crawl échoué pour {root_domain}: {e}")

    # --- ÉTAPE 2 : Fast-Check avec Anti-Soft 404 ---
    common_paths = [
        "/les-institutions-de-la-ville-et-de-la-metropole/elus-municipaux/", 
        "/le-conseil-municipal", 
        "/equipe-municipale", 
        "/les-elus"
    ]
    
    keywords_soft404 = ["élu", "elu", "conseil", "maire"]
    
    for path in common_paths:
        test_url = urljoin(root_domain, path)
        try:
            # On utilise GET pour avoir le corps et faire l'anti-soft 404
            get_response = curequests.get(test_url, impersonate="chrome110", timeout=30, allow_redirects=True, verify=False)
            if get_response.status_code == 200:
                text_lower = get_response.text.lower()
                if any(kw in text_lower for kw in keywords_soft404):
                    logging.info(f"URL exacte trouvée via Fast-Check itératif (Validé Anti-Soft 404) : {test_url}")
                    return test_url
        except Exception:
            pass
            
    # --- ÉTAPE 3 : Recherche via Sitemap Streamé ---
    sitemap_paths = ["/sitemap.xml", "/sitemap_index.xml"]
    keywords_sitemap = ["elu", "conseil-municipal", "equipe"]
    
    for sitemap_path in sitemap_paths:
        sitemap_url = urljoin(root_domain, sitemap_path)
        try:
            import requests as standard_requests
            # fallback au module requests classique pour préserver stream=True (curl_cffi ne le gère pas)
            with standard_requests.get(sitemap_url, timeout=30, stream=True, verify=False) as response:
                if response.status_code == 200:
                    logging.info(f"Analyse streamée du Sitemap en cours : {sitemap_url}")
                    
                    for line_bytes in response.iter_lines():
                        if not line_bytes: continue
                        
                        line = line_bytes.decode('utf-8', errors='ignore').lower()
                        # Test natif et Regex en un seul passage ciblé
                        if '<loc>' in line and any(kw in line for kw in keywords_sitemap):
                            match = re.search(r'<loc>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</loc>', line, re.IGNORECASE)
                            if match:
                                exact_url = match.group(1).strip()
                                logging.info(f"URL exacte trouvée via Sitemap streamé : {exact_url}")
                                return exact_url
                                
        except Exception as e:
            logging.warning(f"Sitemap injoignable ({sitemap_url}) : {e}")
            continue
            
    logging.warning(f"Le Spidering n'a trouvé aucune URL pertinente pour {root_domain}.")
    return None

# --- Exécution standalone de Test ---
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    
    # Remplacer par le chemin de ton CSV
    csv_path = r"C:\Users\jimmy\OneDrive\Desktop\Professionnel\Projet Carel\elu-scraper\Fichier forgeron3 test mandat contrat.csv"
    
    try:
        data = parse_salesforce_csv(csv_path)
    except Exception as e:
        logging.error(f"Erreur à la lecture du CSV: {e}")
        sys.exit(1)
        
    logging.info(f"{len(data)} lignes lues depuis le CSV.")
    
    # Boucle sur l'ensemble du fichier
    for row in data:
        # Récupération dynamique des clés car l'encodage du CSV peut corrompre certains noms de colonnes ("Mandat: Mandat Name")
        ville = next((v for k, v in row.items() if k and 'ville' in k.lower()), "")
        if not ville:
            ville = next((v for k, v in row.items() if k and 'collectivit' in k.lower()), "")
            
        code_postal = next((v for k, v in row.items() if k and 'postal' in k.lower()), "")
        mandat_name = next((v for k, v in row.items() if k and 'mandat name' in k.lower()), "")
        nom_lu = next((v for k, v in row.items() if k and 'lu : nom' in k.lower()), "")
        if not nom_lu:
            nom_lu = next((v for k, v in row.items() if k and k.lower() == 'nom'), "")
            
        if not ville:
            continue
            
        print(f"\n--- Traitement de: {ville} (Mandat: {mandat_name}) ---")
        
        url = get_mairie_url(code_postal, ville)
        elus_extraits = []
        if url:
             # Utilise auto-découverte (spider) ou URL simple si le spider échoue
             url_elus = find_elus_url(url) or url
             elus_extraits = hybrid_scrape(url_elus, ville)
             
        # Formater un payload JSON pour N8N. Utilisation de mandat_name pour l'identifier côté webhook puisqu'il n'y a pas d'ID Salesforce direct.
        payload = {
            "mandat_name": mandat_name,
            "ville": ville,
            "code_postal": code_postal,
            "csv_elu_nom": nom_lu,
            "url_source": url,
            "elus_extraits": elus_extraits
        }
        
        logging.info(f"Payload prêt pour N8N: Ville {ville} - {len(elus_extraits)} élus (Mandat: {mandat_name})")
        
        # POST vers le Webhook N8N
        try:
            response = requests.post(WEBHOOK_URL, json=payload, timeout=10)
            logging.info(f"Webhook response: {response.status_code}")
        except Exception as e:
            logging.error(f"Erreur d'envoi Webhook pour {ville}: {e}")

