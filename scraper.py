"""
Script de Scraping Universel avec Mistral AI
---------------------------------
Ce script extrait les informations des élus d'une mairie en scrapant le contenu texte brut
d'une URL puis en demandant à Mistral AI d'en formater la sortie au format JSON.
"""

import os
import requests
from bs4 import BeautifulSoup
import re
import json
import logging
from urllib.parse import urljoin, urlparse
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION ---
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
# Le fallback webhook restera pour un envoi debug ou d'autres usages.
WEBHOOK_URL = "https://n8n.media-start.fr/webhook/a14f3c73-e1ce-4700-8113-7ab035a9ae16"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1"
}

def clean_html_to_text(html_content):
    """Extrait efficacement le texte brut pertinent d'une page."""
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Suppression des balises inutiles pouvant saturer le LLM
    for tag in soup(['script', 'style', 'header', 'footer', 'nav', 'aside', 'svg', 'iframe']):
        tag.decompose()
        
    text = soup.get_text(separator=' ', strip=True)
    # Remplacer les espaces multiples par un seul
    text = re.sub(r'\s+', ' ', text)
    
    # On limite raisonnablement la taille du texte à ~30k caractères (budget tokens Mistral)
    return text[:30000]

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

def scrape_universal_url(url, code_insee):
    """
    Fonction principale: Va chercher n'importe quelle URL de mairie, et extracte via IA.
    Retourne la liste d'attributs des élus (Dict).
    """
    logging.info(f"Début du scraping universel pour l'URL: {url} (INSEE: {code_insee})")
    try:
        response = requests.get(url, headers=HEADERS, timeout=20)
        response.raise_for_status()
        
        # 1. Obtenir un texte propre
        clean_text = clean_html_to_text(response.text)
        if len(clean_text) < 100:
            logging.warning("Le texte de la page semble vide ou rendu côté client (JavaScript). L'extraction risque de rater.")
            
        # 2. Convertir en JSON via Mistral AI
        elus_extraits = extract_elus_with_mistral(clean_text)
        logging.info(f"{len(elus_extraits)} élus extraits depuis la page.")
        
        return elus_extraits
        
    except Exception as e:
        logging.error(f"Échec de l'extraction sur {url}: {e}")
        raise e

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
        response = requests.get(root_domain, headers=HEADERS, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        links = soup.find_all('a', href=True)
        
        keywords_homepage = ["elu", "conseil-municipal", "equipe-municipale", "maire", "vos-elus"]
        
        for link in links:
            href = link.get('href', '').lower()
            text = link.get_text(strip=True).lower()
            
            # Si un mot-clé correspond dans le href ou dans le texte du lien
            if any(kw in href for kw in keywords_homepage) or any(kw in text.replace('é', 'e') for kw in keywords_homepage):
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
            get_response = requests.get(test_url, headers=HEADERS, timeout=10, allow_redirects=True)
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
            # stream=True est indispensable pour lire un gros Sitemap sans le stocker en RAM
            with requests.get(sitemap_url, headers=HEADERS, timeout=10, stream=True) as response:
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
    test_root_domain = "https://www.montpellier.fr" # Ville de Montpellier
    test_insee = "34172"
    
    print(f"--- Test de Spidering sur {test_root_domain} ---")
    exact_url = find_elus_url(test_root_domain)
    
    if exact_url:
        print(f"URL exacte trouvée : {exact_url}")
        print("--- Test de l'Extraction Mistral IA ---")
        try:
            resultats = scrape_universal_url(exact_url, test_insee)
            print(json.dumps(resultats, indent=2, ensure_ascii=False))
        except Exception as e:
            print(f"Test d'extraction échoué : {e}")
    else:
        print("Le Spider n'a pas trouvé la page. Test d'extraction annulé.")
