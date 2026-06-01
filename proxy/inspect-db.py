import sqlite3, os, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
db = os.path.expandvars(r'%APPDATA%\com.srikanthnani.pluely\pluely.db')
con = sqlite3.connect(db)
cur = con.cursor()
tables = [n for (n,) in cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
print('TABLES:', tables)
for t in tables:
    print(f"\n=== {t} ===")
    cols = [r for r in cur.execute(f"PRAGMA table_info('{t}')")]
    for c in cols: print(' col:', c)
    cnt = cur.execute(f"SELECT COUNT(*) FROM '{t}'").fetchone()[0]
    print(' rows:', cnt)
    if cnt and cnt < 50:
        print(' --- sample ---')
        for row in cur.execute(f"SELECT * FROM '{t}' LIMIT 5"):
            print(' ', row)
con.close()
