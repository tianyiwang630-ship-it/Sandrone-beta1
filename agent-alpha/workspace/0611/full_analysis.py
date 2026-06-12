import json, os, re
from datetime import datetime

logs_dir = r'D:\files\demo\0312-newagent\agent-alpha\session-log\logs'

files = sorted([f for f in os.listdir(logs_dir) if f.endswith('.json') and f != '.gitkeep'],
               key=lambda f: os.path.getsize(os.path.join(logs_dir, f)), reverse=True)

# Collect ALL file info first
all_sessions = []
for fname in files:
    fp = os.path.join(logs_dir, fname)
    with open(fp, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
        except:
            continue
    
    hist = data.get('history', [])
    all_sessions.append({
        'filename': fname,
        'session_id': data.get('session_id'),
        'start_time': data.get('start_time', ''),
        'end_time': data.get('end_time', ''),
        'duration': data.get('duration_seconds', 0),
        'total_turns': data.get('total_turns', 0),
        'history_len': len(hist),
        'tools_count': data.get('available_tools', 0),
        'role': data.get('role', ''),
        'history': hist
    })

# Sort by start time
all_sessions.sort(key=lambda s: s['start_time'])

# ===== Summary Table =====
print('=' * 120)
print('SESSION LOG SUMMARY (sorted by time)')
print('=' * 120)
print(f'{"Date":<14s} {"Session ID":<12s} {"Turns":<6s} {"H-Len":<6s} {"Tools":<6s} {"Duration(s)":<11s} {"Filename":<50s}')
print('-' * 120)
for s in all_sessions:
    dt = s['start_time'][:19] if s['start_time'] else '?'
    print(f'{dt:<14s} {s["session_id"]:<12s} {str(s["total_turns"]):<6s} {str(s["history_len"]):<6s} {str(s["tools_count"]):<6s} {str(round(s["duration"],1)):<11s} {s["filename"]:<50s}')
print('=' * 120)
print(f'Total sessions: {len(all_sessions)}')
print()

# ===== Detailed Analysis for Each Session =====
# Focus on finding errors in AI responses
error_patterns = [
    (r'(?i)(error|exception|traceback|fail(ed|ure)?|mistake|wrong|incorrect)', 'error/exception reference'),
    (r'(?i)(sorry|apologize|apology|my mistake|i was wrong)', 'AI apology/admission of error'),
    (r'(?i)(timeout|timed out|rate limit|too many requests)', 'rate/timeout issue'),
    (r'(?i)(permission denied|access denied|unauthorized|forbidden)', 'permission error'),
    (r'(?i)(syntaxerror|typeerror|valueerror|keyerror|importerror|modulenotfounderror|filenotfounderror)', 'Python exception'),
    (r'(?i)(command not found|not a valid command|not recognized)', 'command error'),
    (r'(?i)(invalid|failed to|unable to|can\'?t|cannot)', 'failure indicator'),
]

print('=' * 120)
print('DETAILED SESSION ANALYSIS')
print('=' * 120)
print()

for s in all_sessions:
    print(f'--- Session: {s["filename"]} ---')
    print(f'   Session ID: {s["session_id"]}')
    print(f'   Start: {s["start_time"]}')
    print(f'   End: {s["end_time"]}')
    print(f'   Duration: {round(s["duration"],1)}s')
    print(f'   Total turns (user requests): {s["total_turns"]}')
    print(f'   History msgs: {s["history_len"]}')
    print(f'   Tools available: {s["tools_count"]}')
    
    # Extract the conversation flow
    hist = s['history']
    user_msgs = []
    assistant_msgs = []
    tool_calls_count = 0
    errors_found = []
    
    for i, msg in enumerate(hist):
        role = msg.get('role', '')
        content = msg.get('content', '')
        content_str = str(content) if content else ''
        
        if role == 'user':
            user_msgs.append({'idx': i, 'content': content_str[:200]})
        elif role == 'assistant':
            tool_calls = msg.get('tool_calls', [])
            reasoning = msg.get('reasoning_content', '')
            if tool_calls:
                tool_calls_count += len(tool_calls)
                for tc in tool_calls:
                    func_name = tc.get('function', {}).get('name', '?') if isinstance(tc, dict) else '?'
                    tool_calls_count_str = '?'
            
            assistant_msgs.append({'idx': i, 'content': content_str[:200], 'has_tool_calls': bool(tool_calls)})
            
            # Check for AI errors in assistant responses
            if content_str:
                for pattern, desc in error_patterns:
                    if re.search(pattern, content_str):
                        # Find the relevant snippet
                        matches = re.findall(pattern, content_str)
                        snippet = content_str[:300]
                        errors_found.append({
                            'msg_idx': i,
                            'type': desc,
                            'patterns_found': list(set(matches)),
                            'snippet': snippet
                        })
                        break
        
        elif role == 'tool':
            # Check tool result for errors
            if content_str and len(content_str) < 500:
                for pattern, desc in error_patterns:
                    if re.search(pattern, content_str):
                        errors_found.append({
                            'msg_idx': i,
                            'type': f'TOOL_RESULT: {desc}',
                            'patterns_found': [],
                            'snippet': content_str[:300]
                        })
                        break
    
    print(f'   User msgs: {len(user_msgs)}, Assistant msgs: {len(assistant_msgs)}, Tool calls: {tool_calls_count}')
    
    # Print first few user messages to understand context
    print(f'   --- Conversation Flow (first 50 chars each) ---')
    for i, um in enumerate(user_msgs[:5]):
        short = um['content'].replace('\n', ' ')[:60]
        print(f'   [{i}] USER: {short}')
    
    print(f'   --- Last conversation ---')
    last_n = min(3, len(user_msgs))
    for i, um in enumerate(user_msgs[-last_n:]):
        idx = len(user_msgs) - last_n + i
        short = um['content'].replace('\n', ' ')[:60]
        print(f'   [{idx}] USER: {short}')
    
    if errors_found:
        print(f'   *** ERRORS FOUND: {len(errors_found)} ***')
        for e in errors_found:
            print(f'       Msg#{e["msg_idx"]} [{e["type"]}]: {e["snippet"][:120]}')
    else:
        print(f'   No obvious errors detected.')
    
    print()
