# -*- coding: utf-8 -*-
import json, os, re
from urllib.parse import unquote

fp = r'D:\files\demo\0312-newagent\agent-alpha\session-log\logs\2026-06-10_14-45-50_session_8c1689.json'
out_dir = r'D:\files\demo\0312-newagent\agent-alpha\workspace\0611'

with open(fp, 'r', encoding='utf-8') as f:
    data = json.load(f)

hist = data.get('history', [])

output = []
W = output.append

W('=' * 80)
W('Session 8c1689 — 知乎浏览器使用轨迹全链路')
W('=' * 80)
W(f'总消息数: {len(hist)}')
W('')

# Extract only browser-related actions, focusing on zhihu
browser_tools = ['browser_navigate', 'browser_snapshot', 'browser_click', 'browser_type',
                 'browser_scroll', 'browser_press', 'browser_close', 'browser_connect_cdp',
                 'browser_disconnect_cdp', 'browser_cdp_status',
                 'profile_list', 'profile_create', 'profile_login_headed']

# Also track session state
cdp_sessions = {}  # session_id -> status (active/disconnected)

turn_num = 0
browser_actions = []
user_msgs = []
ai_reasoning_about_browser = []

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
        user_msgs.append((turn_num, i, first[:200]))
    
    if tool_calls:
        for tc in tool_calls:
            fn = tc.get('function', {}).get('name', '')
            args = str(tc.get('function', {}).get('arguments', ''))
            
            if fn in browser_tools:
                # Track CDP session state
                if fn == 'browser_connect_cdp':
                    # Extract session_id from args if present
                    pass
                elif fn == 'browser_disconnect_cdp':
                    pass
                
                browser_actions.append({
                    'turn': turn_num,
                    'msg_idx': i,
                    'func': fn,
                    'args': args[:400],
                    'has_zhihu': 'zhihu' in args.lower() or 'zhihu' in args.lower(),
                    'has_x': 'x.com' in args.lower() or 'twitter' in args.lower(),
                    'has_woshipm': 'woshipm' in args.lower(),
                })
    
    if reasoning and ('browser' in reasoning.lower() or 'cdp' in reasoning.lower() or 
                      'zhihu' in reasoning.lower() or 'snapshot' in reasoning.lower()):
        ai_reasoning_about_browser.append((i, reasoning[:500]))

# Print user messages
W('=== 用户轮次 ===')
for t, idx, msg in user_msgs:
    W(f'  Turn#{t}: {msg}')
W('')

# Print full browser action sequence with context
W('=== 完整浏览器操作轨迹 ===')
W('')
W('【CDP Session 生命周期追踪】')
W('')

prev_session = None
session_actions = []
current_session_actions = []

for ba in browser_actions:
    fn = ba['func']
    args = ba['args']
    
    # Track connect/disconnect
    if fn == 'browser_connect_cdp':
        if current_session_actions:
            session_actions.append(current_session_actions)
        current_session_actions = [ba]
        W(f'\n🔗 [Turn#{ba["turn"]} Msg#{ba["msg_idx"]}] CDP CONNECT')
        W(f'    参数: {args}')
    elif fn == 'browser_disconnect_cdp':
        current_session_actions.append(ba)
        session_actions.append(current_session_actions)
        W(f'🔌 [Turn#{ba["turn"]} Msg#{ba["msg_idx"]}] CDP DISCONNECT')
        W(f'    参数: {args}')
        current_session_actions = []
    elif fn == 'browser_cdp_status':
        W(f'📊 [Turn#{ba["turn"]} Msg#{ba["msg_idx"]}] CDP STATUS CHECK')
    elif fn == 'profile_login_headed':
        W(f'🖥️ [Turn#{ba["turn"]} Msg#{ba["msg_idx"]}] HEADED BROWSER (有头浏览器)')
        W(f'    参数: {args}')
        current_session_actions = [ba]
    elif fn == 'browser_close':
        W(f'❌ [Turn#{ba["turn"]} Msg#{ba["msg_idx"]}] CLOSE BROWSER')
        W(f'    参数: {args}')
        if current_session_actions:
            session_actions.append(current_session_actions)
        current_session_actions = []
    else:
        current_session_actions.append(ba)
        # Determine the site
        site = ''
        if ba['has_zhihu']: site = ' [知乎]'
        elif ba['has_x']: site = ' [X/Twitter]'
        elif ba['has_woshipm']: site = ' [人人都是产品经理]'
        
        # Decode URL
        url_match = re.search(r'"url":\s*"([^"]+)"', args)
        ref_match = re.search(r'"ref":\s*"([^"]+)"', args)
        
        detail = ''
        if url_match:
            decoded = unquote(url_match.group(1))
            detail = decoded[:120]
        elif ref_match:
            detail = f'ref={ref_match.group(1)}'
        elif 'full' in args and 'true' in args:
            detail = 'full snapshot'
        elif 'direction' in args:
            dir_match = re.search(r'"direction":\s*"([^"]+)"', args)
            px_match = re.search(r'"pixels":\s*(\d+)', args)
            detail = f'{dir_match.group(1) if dir_match else "?"} {px_match.group(1) if px_match else ""}px'
        
        W(f'  [{ba["turn"]}/{ba["msg_idx"]}] {fn}{site}')
        if detail:
            W(f'    {detail}')

# Print the remaining session actions
if current_session_actions:
    session_actions.append(current_session_actions)

W('')
W('=' * 80)
W('知乎相关操作 — 单独提取')
W('=' * 80)
W('')

zhihu_actions = [ba for ba in browser_actions if ba['has_zhihu']]
for ba in zhihu_actions:
    fn = ba['func']
    url_match = re.search(r'"url":\s*"([^"]+)"', ba['args'])
    ref_match = re.search(r'"ref":\s*"([^"]+)"', ba['args'])
    detail = ''
    if url_match:
        decoded = unquote(url_match.group(1))
        detail = decoded
    elif ref_match:
        detail = f'click ref={ref_match.group(1)}'
    elif 'direction' in ba['args']:
        dir_match = re.search(r'"direction":\s*"([^"]+)"', ba['args'])
        detail = f'scroll {dir_match.group(1)}'
    else:
        detail = ba['args'][:100]
    
    W(f'  [Turn#{ba["turn"]} Msg#{ba["msg_idx"]}] {fn}')
    W(f'    {detail}')
    W('')

W('=' * 80)
W('AI 关于浏览器的思考过程摘录（知乎相关）')
W('=' * 80)
W('')

for idx, reasoning in ai_reasoning_about_browser:
    if 'zhihu' in reasoning.lower() or '知乎' in reasoning:
        W(f'--- Msg#{idx} ---')
        for line in reasoning.split('\n'):
            line = line.strip()
            if line:
                W(f'  {line}')
        W('')

outpath = os.path.join(out_dir, 'session1_zhihu_trajectory.txt')
with open(outpath, 'w', encoding='utf-8') as f:
    f.write('\n'.join(output))
print(f'Written to: {outpath}')
