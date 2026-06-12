# -*- coding: utf-8 -*-
import json, os

logs_dir = r'D:\files\demo\0312-newagent\agent-alpha\session-log\logs'
out_path = r'D:\files\demo\0312-newagent\agent-alpha\workspace\0611\yesterday_tasks.txt'

files = [
    '2026-06-10_14-45-50_session_8c1689.json',
    '2026-06-10_15-39-53_session_d0cbc4.json',
    '2026-06-10_17-41-17_session_6859c7.json',
]

all_lines = []

for fname in files:
    fp = os.path.join(logs_dir, fname)
    with open(fp, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    hist = data.get('history', [])
    sid = data.get('session_id')
    start = data.get('start_time', '?')[:19]
    turns = data.get('total_turns')
    
    all_lines.append(f'=== {fname} ===')
    all_lines.append(f'Session: {sid} | Start: {start} | Turns: {turns} | History msgs: {len(hist)}')
    all_lines.append('')
    
    # Extract user messages
    user_msgs = []
    for msg in hist:
        if msg.get('role') == 'user':
            content = str(msg.get('content', ''))
            lines = content.strip().split('\n')
            meaningful = [l.strip() for l in lines if l.strip() and len(l.strip()) > 3]
            first = meaningful[0] if meaningful else content[:200]
            user_msgs.append(first[:300])
    
    all_lines.append('用户问题：')
    for i, um in enumerate(user_msgs):
        all_lines.append(f'  [{i}] {um}')
    
    all_lines.append('')
    all_lines.append('---')
    all_lines.append('')

with open(out_path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(all_lines))

print('Written to:', out_path)
