from bs4 import BeautifulSoup
from typing import List
from src.parsers.base import BaseParser
from src.parsers.factory import ParserFactory

@ParserFactory.register("paris_lutece_v1")
class ParisLuteceV1Parser(BaseParser):
    def extract(self) -> List[dict]:
        if not self.html_content:
            return []
            
        soup = BeautifulSoup(self.html_content, "html.parser")
        results = []
        
        # Exemple d'extraction basé sur un DOM Lutece "classique" (fictif/générique pour démonstration)
        elected_blocks = soup.find_all("div", class_="elu-card")
        
        for block in elected_blocks:
            nom_complet_elem = block.find("h2", class_="elu-name")
            if not nom_complet_elem:
                continue
                
            nom_complet = nom_complet_elem.text.strip()
            # Split prénom et nom
            parts = nom_complet.split(" ", 1)
            prenom = parts[0]
            nom = parts[1] if len(parts) > 1 else ""
            
            # Application de la règle métier stricte : 1 ligne de sortie = 1 mandat/fonction
            fonctions_list = block.find("ul", class_="elu-mandates")
            if fonctions_list:
                for li in fonctions_list.find_all("li"):
                    fonction = li.text.strip()
                    results.append({
                        "nom": nom,
                        "prenom": prenom,
                        "fonction": fonction
                    })
            else:
                # S'il n'y a qu'une seule fonction inscrite dans un span
                fonction_span = block.find("span", class_="elu-function")
                fonction = fonction_span.text.strip() if fonction_span else "Conseil de Paris"
                results.append({
                    "nom": nom,
                    "prenom": prenom,
                    "fonction": fonction
                })

        return results
