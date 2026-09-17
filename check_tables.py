import sqlite3
c = sqlite3.connect('D:/po_stress_test/.test.db')
print("Tables:", [t[0] for t in c.execute("SELECT name FROM sqlite_master WHERE type='table'")])
print("\nTool calls count:", c.execute("SELECT COUNT(*) FROM tool_calls").fetchone()[0])
print("Events count:", c.execute("SELECT COUNT(*) FROM events").fetchone()[0])
print("\nRecent events:")
for row in c.execute("SELECT type, data FROM events ORDER BY id DESC LIMIT 20"):
    print(f"  {row[0]}: {row[1][:100] if len(row[1]) < 100 else row[1][:100] + '...'}")
c.close()
