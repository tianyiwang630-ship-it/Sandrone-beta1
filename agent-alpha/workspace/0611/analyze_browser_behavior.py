# -*- coding: utf-8 -*-
import json, os

logs_dir = r'D:\files\demo\0312-newagent\agent-alpha\session-log\logs'

sessions = {
    '8c1689': '2026-06-10_14-45-50_session_8c1689.json',
    '6859c7': '2026-06-10_17-41-17_session_6859c7.json',
}

for sid, fname in sessions.items():
    fp = os.path.join(logs_dir, fname)
    with open(fp, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    hist = data.get('history', [])
    
    print(f'{"="*80}')
    print(f'Session {sid} - {fname}')
    print(f'Total history messages: {len(hist)}')
    print(f'{"="*80}')
    
    # Walk through all messages and extract browser-related activity
    browser_tools = ['browser_navigate', 'browser_snapshot', 'browser_click', 'browser_type', 
                     'browser_scroll', 'browser_press', 'browser_close', 'browser_connect_cdp',
                     'browser_disconnect_cdp', 'browser_cdp_status',
                     'profile_list', 'profile_create', 'profile_login_headed']
    
    turn_num = 0
    browser_actions = []
    all_tool_calls = []
    
    for i, msg in enumerate(hist):
        role = msg.get('role', '')
        content = str(msg.get('content', ''))
        reasoning = msg.get('reasoning_content', '')
        tool_calls = msg.get('tool_calls', [])
        
        if role == 'user':
            # Check if this is a new user turn
            lines = content.strip().split('\n')
            meaningful = [l.strip() for l in lines if l.strip() and len(l.strip()) > 3]
            first = meaningful[0] if meaningful else content[:200]
            turn_num += 1
        
        # Track all browser tool calls
        if tool_calls:
            for tc in tool_calls:
                func_name = tc.get('function', {}).get('name', '')
                func_args = str(tc.get('function', {}).get('arguments', ''))
                
                all_tool_calls.append({
                    'msg_idx': i,
                    'turn': turn_num,
                    'func': func_name,
                    'args_preview': func_args[:300]
                })
                
                if func_name in browser_tools:
                    browser_actions.append({
                        'msg_idx': i,
                        'turn': turn_num,
                        'func': func_name,
                        'args_preview': func_args[:300]
                    })
    
    # Print summary of all tool usage
    print(f'\n用户轮次: {turn_num}')
    print(f'总工具调用数: {len(all_tool_calls)}')
    print(f'浏览器工具调用数: {len(browser_actions)}')
    
    # Print browser action sequence
    if browser_actions:
        print(f'\n--- 浏览器工具调用序列 ---')
        for ba in browser_actions:
            args = ba['args_preview']
            print(f'  [Turn#{ba["turn"]} Msg#{ba["msg_idx"]}] {ba["func"]}')
            print(f'    参数: {args}')
            print()
    
    # Print ALL tool calls in order to see the full picture
    print(f'\n--- 所有工具调用序列 ---')
    prev_func_group = None
    for tc in all_tool_calls:
        func = tc['func']
        # Group consecutive same-function calls
        if func != prev_func_group:
            print(f'\n  [Turn#{tc["turn"]} Msg#{tc["msg_idx"]}] {func}')
            print(f'    参数: {tc["args_preview"]}')
            prev_func_group = func
        else:
            print(f'  [Turn#{tc["turn"]} Msg#{tc["msg_idx"]}] {func}')
    
    print(f'\n\n')
