import json
import logging

def compute_diff(old_state, new_state, insee_filter=None):
    """
    Compare deux états de la base RNE et sort un tableau de changements.
    insee_filter: list de codes INSEE pour restreindre le diff (ex: ["13043", "31555", "69123"]). 
    Si None, compare toutes les communes.
    """
    diff_report = []
    
    insee_codes = set(old_state.keys()).union(new_state.keys())
    if insee_filter:
        insee_codes = insee_codes.intersection(insee_filter)
        
    for insee in insee_codes:
        old_c = old_state.get(insee, {"nom_commune": "", "elus": {}})
        new_c = new_state.get(insee, {"nom_commune": "", "elus": {}})
        
        nom_commune = new_c.get("nom_commune") or old_c.get("nom_commune")
        
        old_elus = old_c.get("elus", {})
        new_elus = new_c.get("elus", {})
        
        changements = []
        elu_keys = set(old_elus.keys()).union(new_elus.keys())
        
        for elu_key in elu_keys:
            if elu_key not in old_elus:
                changements.append({
                    "elu": f"{new_elus[elu_key]['prenom']} {new_elus[elu_key]['nom']}",
                    "commune": nom_commune,
                    "type_changement": "NOUVEL_ELU",
                    "anciens_postes": [],
                    "nouveaux_postes": new_elus[elu_key]["postes"]
                })
            elif elu_key not in new_elus:
                changements.append({
                    "elu": f"{old_elus[elu_key]['prenom']} {old_elus[elu_key]['nom']}",
                    "commune": nom_commune,
                    "type_changement": "ELU_SORTANT",
                    "anciens_postes": old_elus[elu_key]["postes"],
                    "nouveaux_postes": []
                })
            else:
                old_p = set(old_elus[elu_key]["postes"])
                new_p = set(new_elus[elu_key]["postes"])
                if old_p != new_p:
                    changements.append({
                        "elu": f"{new_elus[elu_key]['prenom']} {new_elus[elu_key]['nom']}",
                        "commune": nom_commune,
                        "type_changement": "MODIFICATION_POSTE",
                        "anciens_postes": sorted(list(old_p)),
                        "nouveaux_postes": sorted(list(new_p))
                    })
                    
        if changements:
            diff_report.append({
                "commune_code_insee": insee,
                "commune_nom": nom_commune,
                "changements": changements
            })
            
    return diff_report

def save_state(state, filepath="rne_state.json"):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def load_state(filepath="rne_state.json"):
    import os
    if not os.path.exists(filepath):
        return {}
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)
