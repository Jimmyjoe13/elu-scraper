"""
Injection manuelle des 3 endpoints Sciez dans elus_sources.db.

Les élus de Sciez sont répartis sur 3 sous-pages distinctes :
  - /maire/       → Le Maire
  - /adjoints/    → Les Adjoints
  - /elus/        → Les Conseillers municipaux

L'ancienne entrée unique (ville-sciez.fr/) est désactivée au profit
de ces 3 URLs granulaires pour garantir un taux de couverture de 100%.
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "elus_sources.db")

SCIEZ_URLS = [
    {
        "ville": "SCIEZ",
        "scope": "Ville",
        "url": "https://ville-sciez.fr/mairie/conseil-municipal/maire/",
        "parser_template": "generic_html_v1",
        "is_active": 1,
    },
    {
        "ville": "SCIEZ",
        "scope": "Ville",
        "url": "https://ville-sciez.fr/mairie/conseil-municipal/adjoints/",
        "parser_template": "generic_html_v1",
        "is_active": 1,
    },
    {
        "ville": "SCIEZ",
        "scope": "Ville",
        "url": "https://ville-sciez.fr/mairie/conseil-municipal/elus/",
        "parser_template": "generic_html_v1",
        "is_active": 1,
    },
]

def main():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. Désactivation de l'ancienne URL racine (on ne la supprime pas pour traçabilité)
    cursor.execute(
        "UPDATE source_urls SET is_active = 0 WHERE ville = ? AND url LIKE ?",
        ("SCIEZ", "%ville-sciez.fr/%"),
    )
    disabled = cursor.rowcount
    print(f"  🔒 {disabled} ancienne(s) URL(s) Sciez désactivée(s).")

    # 2. Injection des 3 nouveaux endpoints
    inserted = 0
    for entry in SCIEZ_URLS:
        # Vérification d'existence pour idempotence (on peut relancer le script sans doublon)
        existing = cursor.execute(
            "SELECT id FROM source_urls WHERE url = ?", (entry["url"],)
        ).fetchone()

        if existing:
            # Réactivation si déjà présente mais inactive
            cursor.execute(
                "UPDATE source_urls SET is_active = 1 WHERE url = ?", (entry["url"],)
            )
            print(f"  ♻️  Réactivée : {entry['url']}")
        else:
            cursor.execute(
                "INSERT INTO source_urls (ville, scope, url, parser_template, is_active) VALUES (?, ?, ?, ?, ?)",
                (entry["ville"], entry["scope"], entry["url"], entry["parser_template"], entry["is_active"]),
            )
            inserted += 1
            print(f"  ✅ Insérée   : {entry['url']}")

    conn.commit()

    # 3. Validation finale
    rows = cursor.execute(
        "SELECT id, ville, url, is_active FROM source_urls WHERE ville = ?", ("SCIEZ",)
    ).fetchall()

    print(f"\n  📋 État final de Sciez dans source_urls :")
    for row in rows:
        status = "🟢 ACTIVE" if row[3] else "🔴 INACTIVE"
        print(f"     [{status}] id={row[0]} | {row[2]}")

    conn.close()
    print(f"\n  🏁 Injection terminée : {inserted} nouvelle(s), {disabled} désactivée(s).")


if __name__ == "__main__":
    print("=" * 60)
    print("  SEED SCIEZ — Injection des 3 endpoints")
    print("=" * 60)
    main()
