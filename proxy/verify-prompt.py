import sqlite3, os, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
db = os.path.expandvars(r'%APPDATA%\com.srikanthnani.pluely\pluely.db')
con = sqlite3.connect(db)
for r in con.execute("SELECT id, name, length(prompt) AS chars FROM system_prompts"):
    print(r)
con.close()
