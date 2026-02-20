import os
import requests
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

RNE_API_URL = "https://www.data.gouv.fr/api/1/datasets/5c34c4d1634f4173183a64f1/"

TARGET_FILES = [
    "elus-maires-mai.csv",
    "elus-conseillers-municipaux-cm.csv",
    "elus-conseillers-darrondissements-ca.csv",
    "elus-conseillers-communautaires-epci.csv"
]

def get_latest_download_links():
    """Retrieve the latest URLs for the RNE CSV files from data.gouv.fr API."""
    logging.info("Fetching latest links from RNE API...")
    try:
        response = requests.get(RNE_API_URL, timeout=10)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        logging.error(f"Failed to fetch RNE index: {e}")
        return {}

    links = {}
    for res in data.get('resources', []):
        for target in TARGET_FILES:
            if target in res['title']:
                links[target] = res['url']
    return links

def download_file(url, dest_path):
    """Download a large file streaming via HTTP."""
    logging.info(f"Downloading {url} to {dest_path}...")
    try:
        with requests.get(url, stream=True, timeout=20) as r:
            r.raise_for_status()
            with open(dest_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        logging.info(f"Successfully downloaded {dest_path}")
        return True
    except Exception as e:
        logging.error(f"Error downloading {url}: {e}")
        return False

def download_all_rne_datasets(download_dir="data_rne"):
    """Download all required RNE datasets to the specified directory."""
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)
        
    links = get_latest_download_links()
    success = True
    for target, url in links.items():
        dest = os.path.join(download_dir, target)
        if not download_file(url, dest):
            success = False
            
    return success

if __name__ == "__main__":
    download_all_rne_datasets()
