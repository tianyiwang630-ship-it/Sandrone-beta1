import json, os

logs_dir = r'D:\files\demo\0312-newagent\agent-alpha\session-log\logs'
files = sorted([f for f in os.listdir(logs_dir) if f.endswith('.json') and f != '.gitkeep'],
               key=lambda f: os.path.getsize(os.path.join(logs_dir, f)), reverse=True)

for f in files[:20]:
    fp = os.path.join(logs_dir, f)
    size = os.path.getsize(fp)
    with open(fp, 'r', encoding='utf-8') as fh:
        try:
            data = json.load(fh)
            if isinstance(data, list):
                entries = len(data)
                print(f'{f:70s} size={size:>8d} total_entries={entries}')
            elif isinstance(data, dict):
                keys = list(data.keys())
                msgs = len(data.get('messages', [])) if 'messages' in data else 0
                print(f'{f:70s} size={size:>8d} dict_keys={keys[:5]} messages={msgs}')
            else:
                print(f'{f:70s} size={size:>8d} type={type(data).__name__}')
        except Exception as e:
            print(f'{f:70s} size={size:>8d} parse_error={str(e)[:50]}')
