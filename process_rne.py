import pandas as pd
import random
import os

def get_formule(fonction, civilite):
    fonction_lower = str(fonction).lower()
    if "maire" in fonction_lower and "adjoint" not in fonction_lower and "arrondissement" not in fonction_lower:
        return "la Maire" if civilite == "Mme" else "le Maire"
    elif "adjoint" in fonction_lower:
        return "la Maire" if civilite == "Mme" else "le Maire"
    else:
        return "la Conseillère" if civilite == "Mme" else "le Conseiller"

def validate_output(df_source, df_contrat, df_prospect):
    print("\n--- Rapport de validation ---")
    
    cols_expected = [
        "Nom", "Nom abrégé de la collectivité", "Type de collectivité",
        "Adresse 1", "Adresse 2", "BP/CS", "Code", "Code Postal", "Ville",
        "Élu : Civilité", "Élu : Nom", "Fonction élective", "Formule de politesse",
        "Élu : Adresse 1", "Élu : Adresse 2", "Élu : Code Postal", "Élu : Ville",
        "Nom du chargé commercial", "Mandat : Mandat Name", "Mandat : Type d'enregistrement"
    ]
    
    cols_contrat_ok = list(df_contrat.columns) == cols_expected
    cols_prospect_ok = list(df_prospect.columns) == cols_expected
    if cols_contrat_ok and cols_prospect_ok:
        print("✅ Schéma 20 colonnes : OK sur les 2 fichiers")
    else:
        print("❌ Erreur : Schéma 20 colonnes non respecté")

    total_out = len(df_contrat) + len(df_prospect)
    if total_out == len(df_source):
        print("✅ Conservation volumétrie : OK (contrat + prospect = total source)")
    else:
        print(f"❌ Erreur volumétrie : {total_out} != {len(df_source)}")

    type_contrat = set(df_contrat["Mandat : Type d'enregistrement"].unique())
    type_prospect = set(df_prospect["Mandat : Type d'enregistrement"].unique())
    
    if (type_contrat == {"MANDAT CONTRAT"} or len(type_contrat)==0) and \
       (type_prospect == {"MANDAT PROSPECT"} or len(type_prospect)==0):
        print("✅ Type d'enregistrement : 100% valide")
    else:
        print(f"❌ Erreur Type d'enregistrement : Contrat={type_contrat}, Prospect={type_prospect}")

    all_civ = set(df_contrat["Élu : Civilité"].unique()).union(set(df_prospect["Élu : Civilité"].unique()))
    all_civ = {x for x in all_civ if str(x).strip() != ""}
    if all_civ.issubset({"M.", "Mme"}):
        print("✅ Civilité : 100% valide")
    else:
        print(f"❌ Erreur Civilité : contenant d'autres valeurs : {all_civ}")

    print("--- Taux de remplissage colonnes clés ---")
    def calc_fill(df):
        res = {}
        for col in ["Élu : Nom", "Fonction élective", "Mandat : Mandat Name", "Élu : Civilité"]:
            fill_rate = 100.0 if len(df) == 0 else (df[col] != "").sum() / len(df) * 100
            res[col] = fill_rate
        return res
    
    f_contrat = calc_fill(df_contrat)
    f_prospect = calc_fill(df_prospect)
    
    print(f"[Contrat] Élu : Nom → {f_contrat['Élu : Nom']:.1f}% | Fonction élective → {f_contrat['Fonction élective']:.1f}% | Mandat Name → {f_contrat['Mandat : Mandat Name']:.1f}% | Civilité → {f_contrat['Élu : Civilité']:.1f}%")
    print(f"[Prospect] Élu : Nom → {f_prospect['Élu : Nom']:.1f}% | Fonction élective → {f_prospect['Fonction élective']:.1f}% | Mandat Name → {f_prospect['Mandat : Mandat Name']:.1f}% | Civilité → {f_prospect['Élu : Civilité']:.1f}%")
    
    top5 = pd.concat([df_contrat, df_prospect])["Fonction élective"].value_counts().head(5)
    print("Top 5 fonctions détectées :")
    for func, count in top5.items():
        if func:
            print(f"  - {func}: {count}")

def main():
    file_path = "elus-conseillers-municipaux-cm.csv"
    
    print("Détection de l'encodage et du séparateur...")
    try:
        df_source = pd.read_csv(file_path, sep=None, engine='python', encoding='utf-8', dtype=str)
        encoding = 'utf-8'
    except UnicodeDecodeError:
        df_source = pd.read_csv(file_path, sep=None, engine='python', encoding='latin-1', dtype=str)
        encoding = 'latin-1'

    print(f"✅ Encodage détecté : {encoding}")
    print(f"✅ Chargement : {len(df_source)} lignes")

    df_source = df_source.fillna("")

    df = pd.DataFrame()
    
    def get_type_collectivite(row):
        commune = str(row.get("Libellé de la commune", "")).upper()
        if commune == "PARIS":
            return "Paris"
        if commune in ["LYON", "MARSEILLE"]:
            return "Marseille Lyon"
            
        code = str(row.get("Code de la commune", ""))
        statut = str(row.get("Libellé de la collectivité à statut particulier", "")).strip()
        if (code.startswith("75") or code.startswith("69") or code.startswith("13")) and statut != "":
            return "PLM Mairie Arrondissement"
        return "Commune"

    df["Nom"] = df_source["Libellé de la commune"].apply(lambda x: "MAIRIE DE " + str(x).upper())
    df["Nom abrégé de la collectivité"] = df["Nom"]
    df["Type de collectivité"] = df_source.apply(get_type_collectivite, axis=1)
    df["Adresse 1"] = "HÔTEL DE VILLE"
    df["Adresse 2"] = ""
    df["BP/CS"] = ""
    df["Code"] = ""
    df["Code Postal"] = df_source["Code de la commune"].apply(lambda x: str(x).zfill(5) if str(x) != "" else "")
    df["Ville"] = df_source["Libellé de la commune"].apply(lambda x: str(x).upper())
    df["Élu : Civilité"] = df_source["Code sexe"].apply(lambda x: "M." if str(x).strip().upper() == "M" else "Mme" if str(x).strip().upper() == "F" else "")
    df["Élu : Nom"] = df_source.apply(lambda row: (str(row.get("Nom de l'élu", "")) + " " + str(row.get("Prénom de l'élu", ""))).upper().strip(), axis=1)
    df["Fonction élective"] = df_source["Libellé de la fonction"]
    df["Formule de politesse"] = df.apply(lambda row: get_formule(row["Fonction élective"], row["Élu : Civilité"]), axis=1)
    df["Élu : Adresse 1"] = ""
    df["Élu : Adresse 2"] = ""
    df["Élu : Code Postal"] = ""
    df["Élu : Ville"] = ""
    df["Nom du chargé commercial"] = ""
    
    df["Mandat : Mandat Name"] = [f"MANDAT-RNE-{str(i).zfill(7)}" for i in range(1, len(df) + 1)]

    random.seed(42)
    is_contrat = [random.random() < 0.20 for _ in range(len(df))]
    
    df["is_contrat"] = is_contrat
    df["Mandat : Type d'enregistrement"] = df["is_contrat"].apply(lambda x: "MANDAT CONTRAT" if x else "MANDAT PROSPECT")

    cols_order = [
        "Nom", "Nom abrégé de la collectivité", "Type de collectivité",
        "Adresse 1", "Adresse 2", "BP/CS", "Code", "Code Postal", "Ville",
        "Élu : Civilité", "Élu : Nom", "Fonction élective", "Formule de politesse",
        "Élu : Adresse 1", "Élu : Adresse 2", "Élu : Code Postal", "Élu : Ville",
        "Nom du chargé commercial", "Mandat : Mandat Name", "Mandat : Type d'enregistrement"
    ]

    df_contrat = df[df["is_contrat"] == True][cols_order]
    df_prospect = df[df["is_contrat"] == False][cols_order]

    os.makedirs("output", exist_ok=True)
    
    print(f"✅ MANDAT CONTRAT : {len(df_contrat)} lignes → output/forgeron3_rne_mandat_contrat.csv")
    print(f"✅ MANDAT PROSPECT : {len(df_prospect)} lignes → output/forgeron3_rne_mandat_prospect.csv")

    df_contrat.to_csv("output/forgeron3_rne_mandat_contrat.csv", sep=";", encoding="utf-8-sig", index=False)
    df_prospect.to_csv("output/forgeron3_rne_mandat_prospect.csv", sep=";", encoding="utf-8-sig", index=False)

    validate_output(df_source, df_contrat, df_prospect)

if __name__ == "__main__":
    main()
