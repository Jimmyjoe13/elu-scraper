import re
from typing import List
from bs4 import BeautifulSoup

from ..base import BaseParser
from ..factory import ParserFactory

@ParserFactory.register("generic_html_v1")
class GenericHtmlV1Parser(BaseParser):
    """
    Parser générique performant basé sur des heuristiques regex sans connaitre
    la structure HTML exacte du site cible (pour la scalabilité).
    """

    def extract(self) -> List[dict]:
        if not self.html_content:
            return []

        soup = BeautifulSoup(self.html_content, 'html.parser')
        results = []
        
        # 1. Nettoyage du bruit HTML
        for el in soup(["script", "style", "nav", "footer", "iframe", "noscript", "svg"]):
            el.extract()
            
        # 2. Heuristiques par Expressions Régulières
        # Recherche de fonctions typiques
        func_keywords = r'(Maire(?:\s+délégué(?:e)?)?|Adjoint(?:e)?(?:\s+au\s+maire)?|Conseiller(?:ère)?(?:\s+municipal(?:e)?)?)'
        func_pattern = re.compile(func_keywords, re.IGNORECASE)
        
        # Recherche d'un Prénom Nom (Optionnel: Civilité) - Basé sur la convention Française: Prénom NOM
        upper_chars = "A-ZÉÈÊËÀÂÎÏÔÙÛÜÇ"
        lower_chars = "a-zéèêëàâîïôùûüç"
        
        # Ex: Jean-Marc DUPONT, ou Marie JOUBERT-LAURENT
        name_pattern = re.compile(
            rf'(?:(?:M\.|Mme|M|Monsieur|Madame)\s+)?([{upper_chars}][{lower_chars}-]+(?:\s+[{upper_chars}][{lower_chars}-]+)*)\s+([{upper_chars}-]{{2,}}(?:\s+[{upper_chars}-]{{2,}})*)'
        )

        seen = set()

        # 3. Parcours du DOM pour trouver les couples (Nom/Prénom + Fonction)
        # On itère sur tous les blocs de texte raisonnables (< 300 caractères)
        tags_to_check = soup.body.descendants if soup.body else soup.descendants
        
        for tag in tags_to_check:
            if not tag.name or tag.name in ["html", "body", "head"]:
                continue
                
            text = tag.get_text(separator=' ', strip=True)
            if not text or len(text) > 300: 
                continue
                
            func_match = func_pattern.search(text)
            if func_match:
                func = func_match.group(1).strip()
                
                # Cherche le nom dans la MÊME balise
                name_match = name_pattern.search(text)
                
                # S'il n'y est pas, heuristique 2: regarde le parent direct (s'il n'est pas trop grand)
                if not name_match and tag.parent:
                    parent_text = tag.parent.get_text(separator=' ', strip=True)
                    if len(parent_text) < 400:
                        name_match = name_pattern.search(parent_text)
                        
                # S'il n'y est toujours pas, heuristique 3: regarde la balise soeur (ex: <tr><td>Nom</td><td>Fonction</td></tr>)
                if not name_match:
                    next_sib = tag.find_next_sibling()
                    if next_sib:
                        sib_text = next_sib.get_text(separator=' ', strip=True)
                        name_match = name_pattern.search(sib_text)
                        
                if name_match:
                    prenom = name_match.group(1).strip()
                    nom = name_match.group(2).strip()
                    
                    # Filtres anti faux-positifs
                    if nom.upper() not in ["MAIRE", "ADJOINT", "CONSEILLER", "MUNICIPAL", "VILLE"]:
                        unique_key = f"{prenom.lower()}-{nom.lower()}-{func.lower()}"
                        if unique_key not in seen:
                            seen.add(unique_key)
                            results.append({
                                "nom": nom.strip(),
                                "prenom": prenom.strip(),
                                "fonction": func.strip()
                            })
                            
        return results
