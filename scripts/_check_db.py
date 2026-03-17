import sqlite3, os
db = os.path.join(os.path.dirname(__file__), "..", "elus_sources.db")
conn = sqlite3.connect(db)
c = conn.cursor()

villes = ["TOULOUSE", "NICE", "NANTES", "MONTPELLIER", "STRASBOURG", "BORDEAUX",
          "LILLE", "REIMS", "SAINT-ETIENNE", "LE HAVRE", "TOULON", "GRENOBLE",
          "DIJON", "ANGERS", "BREST", "TOURS", "AMIENS", "LIMOGES", "PERPIGNAN", "METZ"]

# Check unique constraint on source_urls
c.execute("SELECT sql FROM sqlite_master WHERE name='source_urls'")
print("=== Schema source_urls ===")
print(c.fetchone()[0])
print()

# Check indexes
c.execute("SELECT sql FROM sqlite_master WHERE tbl_name='source_urls' AND type='index'")
print("=== Indexes ===")
for r in c.fetchall():
    print(f"  {r[0]}")
print()

# Check existing entries for these cities
for ville in villes:
    c.execute("SELECT ville, url, parser_template, is_active FROM source_urls WHERE ville=?", (ville,))
    rows = c.fetchall()
    if rows:
        for r in rows:
            print(f"  FOUND: {r}")
    else:
        # Check by URL fragment 
        c.execute("SELECT ville, url, parser_template, is_active FROM source_urls WHERE url LIKE ?", (f"%{ville.lower().split()[0]}%",))
        rows2 = c.fetchall()
        if rows2:
            for r in rows2:
                print(f"  URL-MATCH: {r}")
        else:
            print(f"  MISSING: {ville}")

conn.close()
