import sqlite3
import json

conn = sqlite3.connect('D:/po_stress_test/.test.db')
cursor = conn.cursor()

print("\n=== TASK INFO ===")
cursor.execute('SELECT status, summary, error FROM tasks ORDER BY created_at DESC LIMIT 1')
task = cursor.fetchone()
if task:
    print(f"Status: {task[0]}")
    print(f"Summary: {task[1]}")
    print(f"Error: {task[2]}")

print("\n=== TOOL CALLS (last 15) ===")
cursor.execute('SELECT tool, status, arguments, result FROM tool_calls ORDER BY id DESC LIMIT 15')
for row in cursor.fetchall():
    tool, status, args, result = row
    print(f"\n{tool}: {status}")
    if args:
        try:
            args_dict = json.loads(args)
            if 'path' in args_dict:
                print(f"  Path: {args_dict['path']}")
            if 'command' in args_dict:
                print(f"  Command: {args_dict['command']}")
        except:
            pass
    if result and len(result) < 500:
        print(f"  Result: {result[:200]}")

print("\n=== STEPS ===")
cursor.execute('SELECT iteration, state, tool, message FROM steps ORDER BY iteration')
for row in cursor.fetchall():
    print(f"Iter {row[0]}: {row[1]} - {row[2]} - {row[3]}")

conn.close()
