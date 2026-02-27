from typing import List
from bs4 import BeautifulSoup

from ..base import BaseParser
from ..factory import ParserFactory

@ParserFactory.register("marseille_html_v1")
class MarseilleHtmlV1Parser(BaseParser):
    """
    Parser pour le site HTML des élus de la ville de Marseille.
    """
    
    def extract(self) -> List[dict]:
        if not self.html_content:
            return []
            
        soup = BeautifulSoup(self.html_content, 'html.parser')
        elus_elements = soup.select('.cadre_maire_vdm, .cadre_elu_vdm')
        
        results = []
        for elu in elus_elements:
            name_tag = elu.select_one('.nom_elu_vdm')
            if not name_tag:
                continue
                
            full_name = " ".join(name_tag.get_text(strip=True).split())
            if not full_name:
                continue
            
            parts = full_name.split(" ", 1)
            prenom = parts[0]
            nom = parts[1] if len(parts) > 1 else ""
                
            func_tag = elu.select_one('.titre_elu_vdm')
            fonction = " ".join(func_tag.get_text(strip=True).split()) if func_tag else "Conseiller municipal"
            
            results.append({
                "nom": nom,
                "prenom": prenom,
                "fonction": fonction
            })
                
        return results
