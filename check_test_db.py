import sqlite3
import tempfile
from pathlib import Path

db_path = Path(tempfile.gettempdir()) / "po_test_dbs" / "po_stress_test.db"
if db_path.exists():
    c = sqlite3.connect(str(db_path))
    print('Tasks:', c.execute('SELECT status, summary FROM tasks ORDER BY created_at DESC LIMIT 1').fetchone())
    print('Tool calls:', c.execute('SELECT COUNT(*) FROM tool_calls').fetchone()[0])
    print('\nLast 5 tool calls:')
    for row in c.execute('SELECT tool, status FROM tool_calls ORDER BY id DESC LIMIT 5'):
        print(f'  {row[0]}: {row[1]}')
else:
    print(f"Database not found at {db_path}")
