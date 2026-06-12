# -*- coding: utf-8 -*-
import json, os

logs_dir = r'D:\files\demo\0312-newagent\agent-alpha\session-log\logs'
out_dir = r'D:\files\demo\0312-newagent\agent-alpha\workspace\0611'

sessions = {
    '8c1689': '2026-06-10_14-45-50_session_8c1689.json',
    '6859c7': '2026-06-10_17-41-17_session_6859c7.json',
}

browser_tools = ['browser_navigate', 'browser_snapshot', 'browser_click', 'browser_type', 
                 'browser_scroll', 'browser_press', 'browser_close', 'browser_connect_cdp',
                 'browser_disconnect_cdp', 'browser_cdp_status',
                 'profile_list', 'profile_create', 'profile_login_headed']

# Also consider search/web tools that interact with web content
web_tools = ['mcp__open-websearch__search', 'mcp__open-websearch__fetchWebContent', 
             'mcp__open-websearch__fetchGithubReadme', 'fetch']

for sid, fname in sessions.items():
    fp = os.path.join(logs_dir, fname)
    with open(fp, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    hist = data.get('history', [])
    
    output = []
    output.append(f'{"="*80}')
    output.append(f'Session {sid} - {fname}')
    output.append(f'Total history messages: {len(hist)}')
    output.append(f'{"="*80}')
    
    all_calls = []
    turn_num = 0
    user_msgs_raw = []
    
    for i, msg in enumerate(hist):
        role = msg.get('role', '')
        content = str(msg.get('content', ''))
        reasoning = msg.get('reasoning_content', '')
        tool_calls = msg.get('tool_calls', [])
        
        if role == 'user':
            turn_num += 1
            lines = content.strip().split('\n')
            meaningful = [l.strip() for l in lines if l.strip() and len(l.strip()) > 3]
            first = meaningful[0] if meaningful else content[:200]
            user_msgs_raw.append(f'  [Turn#{turn_num}] User: {first[:200]}')
        
        if tool_calls:
            for tc in tool_calls:
                func_name = tc.get('function', {}).get('name', '')
                func_args = str(tc.get('function', {}).get('arguments', ''))
                all_calls.append({
                    'msg_idx': i, 'turn': turn_num,
                    'func': func_name, 'args': func_args[:300],
                    'is_browser': func_name in browser_tools,
                    'is_web': func_name in web_tools
                })
    
    # Print user messages
    output.append('\n=== 用户问题流程 ===')
    for um in user_msgs_raw:
        output.append(um)
    
    # Categorize tool usage
    browser_calls = [c for c in all_calls if c['is_browser']]
    web_calls = [c for c in all_calls if c['is_web']]
    other_calls = [c for c in all_calls if not c['is_browser'] and not c['is_web']]
    
    output.append(f'\n=== 统计数据 ===')
    output.append(f'用户轮次: {turn_num}')
    output.append(f'总工具调用: {len(all_calls)}')
    output.append(f'浏览器工具: {len(browser_calls)}')
    output.append(f'搜索/网页工具: {len(web_calls)}')
    output.append(f'其他工具(读写等): {len(other_calls)}')
    
    # Detailed call sequence - show all in order
    output.append(f'\n=== 完整工具调用序列 ===')
    
    for c in all_calls:
        label = '[BROWSER]' if c['is_browser'] else '[WEB]' if c['is_web'] else '[OTHER]'
        output.append(f'{label} Turn#{c["turn"]} Msg#{c["msg_idx"]}: {c["func"]}')
        output.append(f'  参数: {c["args"]}')
    
    # Analyze AI thinking patterns related to browser
    output.append(f'\n=== AI关于浏览器的思考/推理摘录 ===')
    for i, msg in enumerate(hist):
        reasoning = msg.get('reasoning_content', '')
        if reasoning and ('browser' in reasoning.lower() or 'cdp' in reasoning.lower() or 
                          '无头' in reasoning or 'headless' in reasoning.lower() or
                          'snapshot' in reasoning.lower() or 'navigate' in reasoning.lower()):
            output.append(f'--- Msg#{i} ---')
            output.append(reasoning[:500])
            output.append('')
    
    outpath = os.path.join(out_dir, f'browser_behavior_session_{sid}.txt')
    with open(outpath, 'w', encoding='utf-8') as f:
        f.write('\n'.join(output))
    print(f'Written: {outpath}')
