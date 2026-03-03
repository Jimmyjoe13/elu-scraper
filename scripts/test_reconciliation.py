"""
Script de test de réconciliation isolé (sans appel réseau).

Objective : valider que la chaîne Photo A (CSV) vs Photo B (mandats synthétiques)
détecte correctement les mutations pour TOUTES les villes, pas seulement Paris.

Usage : python scripts/test_reconciliation.py
"""

import asyncio
import sys
import os

# Ajout du répertoire racine au PYTHONPATH
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.main import SalesforceProvider, generate_validation_alerts, normalize_ville
from src.models.mandate import ElectedOfficialMandate

# ────────────────────────────────────────────────────────
# Couleurs terminal
# ────────────────────────────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BOLD = "\033[1m"
RESET = "\033[0m"


async def run_tests():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # ── 1. Chargement de la Photo A réelle ──
    print(f"\n{BOLD}{'='*60}")
    print("  TEST DE RÉCONCILIATION — PHOTO A vs PHOTO B SYNTHÉTIQUE")
    print(f"{'='*60}{RESET}\n")
    
    provider = SalesforceProvider(root_dir)
    photo_a = await provider.get_photo_a()
    
    print(f"  Photo A chargée : {len(photo_a)} clés")
    
    # ── 2. Diagnostic : vérifier que les villes cibles existent dans Photo A ──
    villes_cibles = ["paris", "lyon", "marseille"]
    print(f"\n{BOLD}  Diagnostic des clés Photo A par ville :{RESET}")
    for ville in villes_cibles:
        keys_ville = [k for k in photo_a if k.startswith(f"{ville}---")]
        print(f"    {ville:15s} → {len(keys_ville)} clés")
        if keys_ville:
            # Afficher les 3 premières clés comme échantillon
            for k in keys_ville[:3]:
                elus = photo_a[k]
                print(f"      ex: {k} → fonction={elus[0]['fonction']!r}")
    
    # ── 3. Test normalize_ville ──
    print(f"\n{BOLD}  Test normalize_ville :{RESET}")
    test_cases = [
        ("LYON CEDEX 1", "lyon"),
        ("MARSEILLE CEDEX 20", "marseille"),
        ("PARIS RP", "paris"),
        ("Paris", "paris"),
    ]
    for raw, expected in test_cases:
        result = normalize_ville(raw)
        status = f"{GREEN}OK{RESET}" if result == expected else f"{RED}FAIL{RESET}"
        print(f"    {status}: normalize_ville({raw!r}) = {result!r}")
    
    # ── 4. Création de mandats synthétiques (Photo B) ──
    # On simule des élus EXISTANTS dans le CSV mais avec une FONCTION MODIFIÉE
    
    # D'abord, trouvons des élus réels dans Photo A pour chaque ville
    mandats_synthetiques = []
    test_expectations = []  # (ville, nom_complet, should_alert)
    
    for ville in villes_cibles:
        keys_ville = [k for k in photo_a if k.startswith(f"{ville}---")]
        if not keys_ville:
            print(f"\n  {YELLOW}⚠ Aucun élu trouvé pour {ville} dans Photo A — skip{RESET}")
            continue
        
        # Prendre le premier élu de cette ville
        first_key = keys_ville[0]
        elu_data = photo_a[first_key][0]
        
        # Extraire nom/prénom depuis la clé (ville---prenom nom ou ville---nom prenom)
        nom_part = first_key.split("---")[1]
        parts = nom_part.split(" ", 1)
        prenom = parts[0].title()
        nom = parts[1].upper() if len(parts) > 1 else ""
        
        fonction_originale = elu_data["fonction"]
        fonction_modifiee = "Ministre de Test"
        
        print(f"\n  {BOLD}Élu synthétique pour {ville.upper()} :{RESET}")
        print(f"    Nom: {prenom} {nom}")
        print(f"    Fonction CSV (originale) : {fonction_originale!r}")
        print(f"    Fonction Web (simulée)   : {fonction_modifiee!r}")
        
        mandate = ElectedOfficialMandate(
            nom=nom,
            prenom=prenom,
            ville_ou_secteur=ville.title(),  # Simule ce que le parser Web retournerait
            fonction=fonction_modifiee,
            source_url=f"https://test.{ville}.fr/elus"
        )
        mandats_synthetiques.append(mandate)
        test_expectations.append((ville, f"{prenom} {nom}", True))
    
    # ── 5. Exécution de la réconciliation ──
    print(f"\n{BOLD}  Exécution de generate_validation_alerts...{RESET}")
    alerts = generate_validation_alerts(photo_a, mandats_synthetiques)
    
    print(f"\n  Résultat : {len(alerts)} alerte(s) générée(s)")
    
    # ── 6. Vérification ──
    print(f"\n{BOLD}  Vérification des alertes :{RESET}")
    all_passed = True
    
    for ville, nom_complet, should_alert in test_expectations:
        found = any(
            normalize_ville(a["commune"]) == ville 
            for a in alerts
        )
        
        if found == should_alert:
            print(f"    {GREEN}✅ PASS{RESET}: {ville.upper():15s} — Alerte détectée pour mutation délibérée")
        else:
            print(f"    {RED}❌ FAIL{RESET}: {ville.upper():15s} — Alerte {'non trouvée' if should_alert else 'inattendue'}")
            all_passed = False
    
    # Détail des alertes
    if alerts:
        print(f"\n{BOLD}  Détail des alertes :{RESET}")
        for a in alerts:
            print(f"    📋 {a['commune']:15s} | {a['elu']:25s} | SF: {a['statut_salesforce_actuel']!r:30s} → Web: {a['statut_trouve_web']!r}")
    
    # ── 7. Verdict final ──
    print(f"\n{BOLD}{'='*60}")
    if all_passed and len(alerts) == len(test_expectations):
        print(f"  {GREEN}✅ TOUS LES TESTS PASSÉS — Le moteur détecte les mutations{RESET}")
        print(f"  {GREEN}   pour TOUTES les villes (Paris, Lyon, Marseille).{RESET}")
    else:
        print(f"  {RED}❌ CERTAINS TESTS ONT ÉCHOUÉ{RESET}")
        print(f"  {RED}   Attendu: {len(test_expectations)} alertes, Obtenu: {len(alerts)}{RESET}")
    print(f"{'='*60}\n")
    
    return all_passed


if __name__ == "__main__":
    success = asyncio.run(run_tests())
    sys.exit(0 if success else 1)
