# -*- coding: utf-8 -*-
import json, os, re, sys

logs_dir = r'D:\files\demo\0312-newagent\agent-alpha\session-log\logs'
out_dir = r'D:\files\demo\0312-newagent\agent-alpha\workspace\0611'

def safe(s, maxlen=1000):
    """Replace characters that can't be encoded in standard output."""
    result = []
    for ch in str(s)[:maxlen]:
        try:
            ch.encode('utf-8')
            result.append(ch)
        except:
            result.append('?')
    return ''.join(result)

output = []

def log(msg):
    output.append(msg)

# === Session b6980e: AI says can't run commands ===
fname = '2026-05-27_16-42-57_session_b6980e.json'
fp = os.path.join(logs_dir, fname)
with open(fp, 'r', encoding='utf-8') as f:
    data = json.load(f)
hist = data.get('history', [])

log(f'\n{"="*80}')
log(f'Session: {fname} - AI说自己不能运行命令')
log(f'Total msgs: {len(hist)}')
log(f'{"="*80}')

# Look at Msg#26 where AI says it can't run commands
for i, msg in enumerate(hist):
    role = msg.get('role', '')
    content = str(msg.get('content', ''))
    
    if 'can\'t run' in content.lower() or 'cannot run' in content.lower() or 'manually' in content.lower():
        log(f'\n--- Msg#{i} [{role}] ---')
        log(f'Content:\n{content[:1000]}')
        # Also show previous tool call context
        log(f'\n--- Context (previous 3 messages) ---')
        for j in range(max(0,i-3), i):
            prev = hist[j]
            pr = prev.get('role','')
            pc = str(prev.get('content',''))
            log(f'Msg#{j} [{pr}]: {safe(pc[:200])}')
        break

# Check tool call at Msg#25
log(f'\n--- Checking tool calls around error ---')
for i in range(20, len(hist)):
    msg = hist[i]
    if msg.get('role') == 'assistant':
        tc = msg.get('tool_calls', [])
        if tc:
            for t in tc:
                fn = t.get('function', {}).get('name', '?')
                args = str(t.get('function', {}).get('arguments', ''))
                log(f'Msg#{i} tool_call: {fn}({safe(args[:300])})')

# === Session 2874ac: User questions why AI not using agent-reach ===
fname2 = '2026-05-29_17-01-56_session_2874ac.json'
fp2 = os.path.join(logs_dir, fname2)
with open(fp2, 'r', encoding='utf-8') as f:
    data2 = json.load(f)
hist2 = data2.get('history', [])

log(f'\n{"="*80}')
log(f'Session: {fname2} - 用户质疑AI为什么不用agent-reach')
log(f'{"="*80}')

# Find the user message about agent-reach
for i, msg in enumerate(hist2):
    if msg.get('role') == 'user':
        content = str(msg.get('content', ''))
        if 'agent-reach' in content.lower() and ('为什么' in content or '不用' in content):
            log(f'\nUser Msg#{i}: {safe(content[:500])}')
            for j in range(i, min(i+5, len(hist2))):
                if hist2[j].get('role') == 'assistant':
                    log(f'\nAI Response Msg#{j}: {safe(str(hist2[j].get("content",""))[:800])}')
                    break
            break

# === Session 0d6e42: Agent Reach installation channel issues ===
fname3 = '2026-05-29_15-00-57_session_0d6e42.json'
fp3 = os.path.join(logs_dir, fname3)
with open(fp3, 'r', encoding='utf-8') as f:
    data3 = json.load(f)
hist3 = data3.get('history', [])

log(f'\n{"="*80}')
log(f'Session: {fname3} - Agent Reach安装渠道错误')
log(f'{"="*80}')

# Find assistant responses with errors or retry attempts
for i, msg in enumerate(hist3):
    if msg.get('role') == 'assistant':
        content = str(msg.get('content', ''))
        reasoning = msg.get('reasoning_content', '')
        
        # Show thinking that mentions errors
        if reasoning and re.search(r'(error|fail|not working|try|retry|sandbox)', reasoning, re.IGNORECASE):
            log(f'\nMsg#{i} thinking: {safe(reasoning[:400])}')
        
        # Show content that mentions errors  
        if content and re.search(r'(sorry|error|fail|cannot|unable)', content, re.IGNORECASE):
            log(f'\nMsg#{i} content: {safe(content[:400])}')
        
        tc = msg.get('tool_calls', [])
        if tc:
            for t in tc:
                fn = t.get('function', {}).get('name', '?')
                args = str(t.get('function', {}).get('arguments', ''))
                if re.search(r'(error|fail|try)', args, re.IGNORECASE):
                    log(f'Msg#{i} tool: {fn}({safe(args[:200])})')

# === Recent sessions ===
log(f'\n{"="*80}')
log(f'Recent session summaries')
log(f'{"="*80}')

recent = [
    '2026-06-09_20-40-00_session_27a882.json',
    '2026-06-09_21-16-35_session_2b1b08.json', 
    '2026-06-09_23-23-22_session_acff1a.json',
    '2026-06-10_14-45-50_session_8c1689.json',
    '2026-06-10_17-41-17_session_6859c7.json',
    '2026-06-11_15-50-08_session_a4cfbd.json',
]

for fname in recent:
    fp = os.path.join(logs_dir, fname)
    if not os.path.exists(fp):
        continue
    with open(fp, 'r', encoding='utf-8') as f:
        data = json.load(f)
    hist = data.get('history', [])
    
    # Count errors
    sandbox = 0
    cmd_fail = 0
    for msg in hist:
        content = str(msg.get('content', ''))
        if '"error"' in content and 'Sandbox' in content:
            sandbox += 1
        elif '"success": false' in content:
            cmd_fail += 1
    
    log(f'\n{fname}: {len(hist)} msgs, {sandbox} sandbox denials, {cmd_fail} cmd failures')

# Write to file
outpath = os.path.join(out_dir, 'ai_errors_raw.txt')
with open(outpath, 'w', encoding='utf-8') as f:
    f.write('\n'.join(output))
# Write a simple message to console
import sys
sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', closefd=False)
sys.stdout.write(f'\nWritten to: {outpath}\n')
