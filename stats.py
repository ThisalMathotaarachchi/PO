import sqlite3
c = sqlite3.connect('D:/po_stress_test/.test.db')
print('Tool calls executed:', c.execute('SELECT COUNT(*) FROM tool_calls').fetchone()[0])
print('\nTool breakdown:')
for row in c.execute('SELECT tool, COUNT(*) as cnt FROM tool_calls GROUP BY tool ORDER BY cnt DESC'):
    print(f'  {row[0]}: {row[1]}')
print('\nModel usage:')
for row in c.execute('SELECT model, prompt_tokens, completion_tokens FROM model_usage'):
    print(f'  {row[0]}: {row[1]} prompt tokens, {row[2]} completion tokens')
