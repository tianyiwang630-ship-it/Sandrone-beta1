import json, os

logs_dir = r'D:\files\demo\0312-newagent\agent-alpha\session-log\logs'

files = sorted([f for f in os.listdir(logs_dir) if f.endswith('.json') and f != '.gitkeep'],
               key=lambda f: os.path.getsize(os.path.join(logs_dir, f)), reverse=True)[:5]

for fname in files:
    fp = os.path.join(logs_dir, fname)
    with open(fp, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    print(f'=== {fname} ===')
    print(f'Top-level keys: {list(data.keys())}')
    
    for k, v in data.items():
        if k in ('session_id', 'start_time', 'end_time', 'duration_seconds', 'total_turns'):
            continue
        vt = type(v).__name__
        if isinstance(v, list):
            print(f'  {k}: list[{len(v)}]')
            if len(v) > 0:
                print(f'    item0 keys: {list(v[0].keys())[:10]}')
        elif isinstance(v, dict):
            print(f'  {k}: dict with keys {list(v.keys())[:10]}')
        else:
            print(f'  {k}: {vt} = {str(v)[:80]}')
    print()
