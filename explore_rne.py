import requests
import json

def get_links():
    url = "https://www.data.gouv.fr/api/1/datasets/5c34c4d1634f4173183a64f1/"
    response = requests.get(url)
    data = response.json()
    links = []
    for res in data.get('resources', []):
        if res['title'].endswith('.csv') or res['title'].endswith('.txt'):
            links.append({"title": res['title'], "url": res['url']})
            
    with open('rne_links.json', 'w', encoding='utf-8') as f:
        json.dump(links, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    get_links()
