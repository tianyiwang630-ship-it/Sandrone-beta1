# -*- coding: utf-8 -*-
import json, os, re

fp = r'D:\files\demo\0312-newagent\agent-alpha\session-log\logs\2026-06-10_17-41-17_session_6859c7.json'
out_dir = r'D:\files\demo\0312-newagent\agent-alpha\workspace\0611'

with open(fp, 'r', encoding='utf-8') as f:
    data = json.load(f)

hist = data.get('history', [])

output = []
W = output.append

W('=' * 80)
W('Session 6859c7 — AI工具选择决策深度分析')
W('=' * 80)

# Extract ALL assistant thoughts and tool calls with detailed context
turn_num = 0
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
        W(f'\n{"─"*60}')
        W(f'Turn#{turn_num} 用户: {first[:200]}')
        W(f'{"─"*60}')
        continue
    
    if role == 'assistant':
        # Show reasoning - this is where AI explains WHY it chooses tools
        if reasoning:
            W(f'\n[AI思考 Msg#{i}]:')
            # Split reasoning into meaningful segments
            for line in reasoning.split('\n'):
                line = line.strip()
                if line:
                    W(f'  {line}')
        
        # Show tool calls
        if tool_calls:
            for tc in tool_calls:
                fn = tc.get('function', {}).get('name', '')
                args = str(tc.get('function', {}).get('arguments', ''))
                W(f'  → 工具调用: {fn}')
                # Only show first 200 chars of args
                if len(args) > 200:
                    W(f'    参数(截断): {args[:200]}...')
                else:
                    W(f'    参数: {args}')
        
        # Show assistant content (response to user)
        if content and tool_calls:
            W(f'  [同时回复用户]: {content[:150]}...' if len(content) > 150 else f'  [回复]: {content}')
        
        W('')

# Now specifically analyze the browser vs fetch decision points
W('\n\n')
W('=' * 80)
W('浏览器 vs fetch 工具选择分析')
W('=' * 80)

# Find all places where AI chose fetch vs browser for specific URLs
W('\n场景1：获取SMCI财报详情时——AI的混合策略')
W('─' * 50)

# Look at Turn#4 specifically
in_turn4 = False
for i, msg in enumerate(hist):
    reasoning = msg.get('reasoning_content', '')
    if reasoning and 'Turn#4' in str(i):
        pass
    
    role = msg.get('role', '')
    content = str(msg.get('content', ''))
    tool_calls = msg.get('tool_calls', [])
    
    if role == 'user':
        cnt = str(content)
        if '更详细一些' in cnt or '重新再去搜' in cnt:
            in_turn4 = True
            W(f'\n用户触发：{cnt[:100]}')
            continue
        elif in_turn4 and len(tool_calls) > 0:
            break
    
    if in_turn4 and role == 'assistant':
        if tool_calls:
            for tc in tool_calls:
                fn = tc.get('function', {}).get('name', '')
                args = str(tc.get('function', {}).get('arguments', ''))
                if 'url' in args.lower():
                    import re
                    urls = re.findall(r'https?://[^\s",]+', args)
                    for u in urls:
                        W(f'\n[{fn}] 目标URL: {u}')
                else:
                    W(f'\n[{fn}] 非URL参数: {args[:150]}')

# Also look at Turn#0 and Turn#1 - initial search approach
W('\n\n场景2：最初Turn#0-1的批量搜索策略')
W('─' * 50)
W('AI在Turn#0一次性发出 2 个browser_navigate（搜A股标的）')
W('然后在Turn#1又连续发出 2 个browser_navigate + 1 个write脚本 + 1 个bash跑脚本')
W('说明AI的策略是：浏览器搜发现 → 脚本批量验证，而不是浏览器逐页细读')

# Analyze the trade-offs
W('\n\n')
W('=' * 80)
W('工具效率对比分析')
W('=' * 80)

W('''
Session 2中AI面临的工具选择：

┌─────────────────────────────────────────────────────────┐
│  浏览器 navigate + scroll + click + snapshot 完整流程    │
│  成本: ~6-8次工具调用/页（navigate + wait + snapshot）    │
│  收益: 能看到渲染后的页面，处理JS动态内容                  │
│  缺点: 慢，尤其是大量页面的场景                           │
├─────────────────────────────────────────────────────────┤
│  fetch 直接抓取网页内容                                  │
│  成本: 1次工具调用/页                                    │
│  收益: 快速获取结构化文本                                 │
│  缺点: 无法处理JS渲染，可能错过动态内容                    │
├─────────────────────────────────────────────────────────┤
│  browser_navigate 仅导航到搜索页                         │
│  成本: 1次工具调用 —— 但只作为"搜索入口"                   │
│  收益: 利用CDP用户已登录浏览器的Cookie/搜索权限            │
│  缺点: 只导航不抓内容的话，需要配合其他工具获取数据          │
└─────────────────────────────────────────────────────────┘
''')

outpath = os.path.join(out_dir, 'session2_tool_analysis.txt')
with open(outpath, 'w', encoding='utf-8') as f:
    f.write('\n'.join(output))
print(f'Written to: {outpath}')
