import urllib.parse
from typing import List
from bs4 import BeautifulSoup

from ..base import BaseParser
from ..factory import ParserFactory

@ParserFactory.register("marseille_html_v1")
class MarseilleHtmlV1Parser(BaseParser):
    """
    Parser Routeur pour les élus de Marseille (Mairie Centrale + Secteurs).
    Délègue les sélecteurs selon le domaine.
    """
    
    def extract(self) -> List[dict]:
        if not self.html_content:
            return []
            
        domain = urllib.parse.urlparse(self.url).netloc
        soup = BeautifulSoup(self.html_content, 'html.parser')
        
        # Fallback dynamique heuristique s'il s'agit du fameux trou pour 9-10
        if "marseille9-10.fr" in domain:
            from .generic_html_v1 import GenericHtmlV1Parser
            generic_parser = GenericHtmlV1Parser(self.url, self.ville_ou_secteur)
            generic_parser.html_content = self.html_content
            return generic_parser.extract()
            
        strategies = {
            "mairie1-7.marseille.fr": {
                "container": ".view-liste-des-elues .views-row", 
                "name": ".views-field-title", 
                "func": ".views-field-field-fonction"
            },
            "www.mairie-marseille2-3.com": {
                "container": ".team-member, .elu", 
                "name": ".name", 
                "func": ".role"
            },
            "www.marseille4-5.fr": {
                "container": ".elementor-widget-image-box", 
                "name": ".elementor-image-box-title", 
                "func": ".elementor-image-box-description"
            },
            "mairie-marseille6-8.fr": {
                "container": ".sppb-person-block, .person", 
                "name": ".sppb-person-name, .name", 
                "func": ".sppb-person-designation, .function"
            },
            "marseille1112.fr": {
                "container": ".elus-item, .elementor-image-box-wrapper", 
                "name": ".elu-name, .elementor-image-box-title", 
                "func": ".elu-role, .elementor-image-box-description"
            },
            "mairie13-14.marseille.fr": {
                "container": ".elu-item, .views-row", 
                "name": ".elu-title, .views-field-title", 
                "func": ".elu-function, .views-field-field-fonction"
            },
            "mairie-marseille15-16.fr": {
                "container": ".team-item, .member", 
                "name": ".team-name, .name", 
                "func": ".team-job, .fonction"
            },
            "www.marseille.fr": {
                "container": ".cadre_maire_vdm, .cadre_elu_vdm", 
                "name": ".nom_elu_vdm", 
                "func": ".titre_elu_vdm"
            }
        }
        
        strategy = strategies.get(domain)
        # S'il n'y a pas de stratégie spécifique, on réplique le comportement par défaut de l'ancienne version
        if not strategy:
            strategy = strategies["www.marseille.fr"]

        results = []
        elus_elements = soup.select(strategy["container"])
        
        # Test de fallback générique avant d'abandonner si aucun élément n'est trouvé
        if not elus_elements and "marseille.fr" not in domain:
            from .generic_html_v1 import GenericHtmlV1Parser
            generic_parser = GenericHtmlV1Parser(self.url, self.ville_ou_secteur)
            generic_parser.html_content = self.html_content
            return generic_parser.extract()
            
        for elu in elus_elements:
            name_tag = elu.select_one(strategy["name"])
            if not name_tag:
                continue
                
            full_name = " ".join(name_tag.get_text(strip=True).split())
            if not full_name:
                continue
            
            parts = full_name.split(" ", 1)
            prenom = parts[0]
            nom = parts[1] if len(parts) > 1 else ""
                
            func_tag = elu.select_one(strategy["func"])
            fonction = " ".join(func_tag.get_text(strip=True).split()) if func_tag else "Conseiller"
            
            results.append({
                "nom": nom,
                "prenom": prenom,
                "fonction": fonction
            })
            
        return results
