# -*- coding: utf-8 -*-
import json, os, re

logs_dir = r'D:\files\demo\0312-newagent\agent-alpha\session-log\logs'
output_dir = r'D:\files\demo\0312-newagent\agent-alpha\workspace\0611'

# Extract specific AI error messages from key sessions
key_sessions = [
    # (filename, description)
    ('2026-05-27_16-42-57_session_b6980e.json', 'AI说不能运行命令'),
    ('2026-05-29_15-00-57_session_0d6e42.json', 'Agent Reach安装渠道问题'),
    ('2026-05-29_17-01-56_session_2874ac.json', '用户质疑AI不用agent-reach'),
    ('2026-06-10_14-45-50_session_8c1689.json', '最近大会话'),
    ('2026-06-10_17-41-17_session_6859c7.json', '最近最大会话'),
]

output_lines = []
W = output_lines.append

W('# AI具体错误摘录\n\n')

for fname, desc in key_sessions:
    fp = os.path.join(logs_dir, fname)
    if not os.path.exists(fp):
        continue
    
    with open(fp, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    hist = data.get('history', [])
    sid = data.get('session_id', '?')
    start = data.get('start_time', '?')[:19]
    
    W(f'## Session: {fname}\n')
    W(f'说明: {desc}\n')
    W(f'Session ID: {sid}, 时间: {start}\n\n')
    
    W('### AI Assistant 错误/问题消息摘录\n\n')
    
    for i, msg in enumerate(hist):
        role = msg.get('role', '')
        content = str(msg.get('content', ''))
        reasoning = msg.get('reasoning_content', '')
        tool_calls = msg.get('tool_calls', [])
        
        if role == 'assistant' and content:
            # Look for error patterns in the thinking/reasoning
            if reasoning and re.search(r'(sandbox|denied|blocked|error|fail|cannot|unable|sorry)', reasoning, re.IGNORECASE):
                clean = reasoning.replace('\n', ' ').replace('\r', '')[:300]
                W(f'- **Msg#{i} (thinking)**: {clean}\n\n')
            
            # Check content for admissions
            if re.search(r'(?i)(sorry|apologize|my mistake|i (was|am) wrong|cannot|could not)', content):
                clean = content.replace('\n', ' ').replace('\r', '')[:300]
                W(f'- **Msg#{i} (response)**: {clean}\n\n')
        
        if role == 'tool' and content:
            # Extract errors from tool results
            if '"success": false' in content or '"error"' in content:
                clean = content.replace('\n', ' ').replace('\r', '')[:200]
                W(f'- **Msg#{i} (tool error)**: {clean}\n\n')
    
    W('---\n\n')

outpath = os.path.join(output_dir, 'ai_error_excerpts.md')
with open(outpath, 'w', encoding='utf-8') as f:
    f.writelines(output_lines)

print(f'Written to: {outpath}')
