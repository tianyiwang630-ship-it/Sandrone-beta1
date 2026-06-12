import json, os

logs_dir = r'D:\files\demo\0312-newagent\agent-alpha\session-log\logs'

# Take the largest 5 files
files = sorted([f for f in os.listdir(logs_dir) if f.endswith('.json') and f != '.gitkeep'],
               key=lambda f: os.path.getsize(os.path.join(logs_dir, f)), reverse=True)[:5]

for fname in files:
    fp = os.path.join(logs_dir, fname)
    with open(fp, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    print(f'=== {fname} ===')
    sid = data.get('session_id', '?')
    st = data.get('start_time', '?')
    et = data.get('end_time', '?')
    dur = data.get('duration_seconds', '?')
    tt = data.get('total_turns', '?')
    print(f'Session ID: {sid}')
    print(f'Start: {st}')
    print(f'End: {et}')
    print(f'Duration: {dur}')
    print(f'Total turns: {tt}')
    
    # Examine the turns structure
    turns = data.get('turns', data.get('messages', []))
    if isinstance(turns, list):
        print(f'Turns count: {len(turns)}')
        for i, turn in enumerate(turns[:3]):
            print(f'  Turn {i}: keys={list(turn.keys())[:8]}')
        if len(turns) > 0:
            # Show last 2 turns too
            print(f'  ...')
            for i, turn in enumerate(turns[-2:]):
                idx = len(turns) - 2 + i
                print(f'  Turn {idx}: keys={list(turn.keys())[:8]}')
    
    # Also check for 'messages' key inside
    for key in ['entries', 'steps', 'messages']:
        if key in data and data[key] and isinstance(data[key], list):
            print(f'  [{key}] count={len(data[key])}')
    
    print()
