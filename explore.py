import requests
from bs4 import BeautifulSoup
import warnings
import json
warnings.filterwarnings('ignore')

urls = {
    'paris': ('https://www.paris.fr/la-maire-et-les-elu-e-s', 'Hidalgo'),
    'lyon': ('https://www.lyon.fr/actions-et-projets/le-maire-et-les-elus/les-conseilleres-et-conseillers-municipaux', 'Doucet'),
    'marseille': ('https://www.marseille.fr/mairie/conseil-municipal/elus', 'Payan')
}

for city, (url, search_name) in urls.items():
    try:
        r = requests.get(url, verify=False, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # Save HTML for reference
        with open(f'{city}.html', 'w', encoding='utf-8') as f:
            f.write(soup.prettify())
            
        print(f"\n--- {city} ---")
        
        # Find element containing the mayor's name
        target = soup.find(string=lambda t: t and search_name in t)
        if target:
            parent = target.parent
            # Find a container element
            for _ in range(5):
                print(f"Tag: {parent.name}, classes: {parent.get('class')}")
                # print snippet of text
                print("Text:", parent.get_text(separator=' ', strip=True)[:100])
                print("---")
                parent = parent.parent
                if not parent or parent.name == 'body':
                    break
        else:
            print(f"Could not find {search_name}")
            
    except Exception as e:
        print('Error:', e)
