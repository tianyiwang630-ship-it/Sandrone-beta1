# -*- coding: utf-8 -*-
import json, os, re

logs_dir = r'D:\files\demo\0312-newagent\agent-alpha\session-log\logs'
output_dir = r'D:\files\demo\0312-newagent\agent-alpha\workspace\0611'

# Key sessions to examine in detail (largest + interesting ones)
key_files = [
    '2026-05-27_11-23-10_session_a413be.json',  # First Agent Reach install attempt
    '2026-05-27_16-42-57_session_b6980e.json',  # User said "帮我执行安装"
    '2026-05-28_23-17-21_session_78066a.json',  # Long session with cookies & removal
    '2026-05-29_01-03-17_session_931f94.json',  # Using agent reach to check Twitter
    '2026-05-29_15-00-57_session_0d6e42.json',  # Very long history (155 msgs)
    '2026-05-29_17-01-56_session_2874ac.json',  # More agent reach
    '2026-06-06_19-55-25_session_d22ff2.json',  # 98 msgs, 2 turns
    '2026-06-09_20-40-00_session_27a882.json',  # Recent large session
    '2026-06-09_21-16-35_session_2b1b08.json',  # Recent large session
    '2026-06-09_23-23-22_session_acff1a.json',  # Recent large session
    '2026-06-10_14-45-50_session_8c1689.json',  # Largest recent (153 msgs, 11 turns)
    '2026-06-10_17-41-17_session_6859c7.json',  # 163 msgs, 7 turns
    '2026-06-11_15-50-08_session_a4cfbd.json',  # Today's session
]

def extract_user_msgs(hist):
    """Extract clean user messages."""
    msgs = []
    for msg in hist:
        if msg.get('role') == 'user':
            content = str(msg.get('content', ''))
            # Get first meaningful lines
            lines = content.strip().split('\n')
            meaningful = [l.strip() for l in lines if l.strip() and len(l.strip()) > 3]
            first = meaningful[0] if meaningful else content[:80]
            msgs.append(first[:120])
    return msgs

def extract_ai_admissions(hist):
    """Find places where AI admits it can't do something or made a mistake."""
    results = []
    for i, msg in enumerate(hist):
        if msg.get('role') == 'assistant':
            content = str(msg.get('content', ''))
            # Look for signs of giving up or admitting failure
            patterns = [
                (r'(?i)(i can not|cannot|could not|unable to|failed attempt)', 'inability'),
                (r'(?i)(let me (try|attempt|see if))', 'retry attempt'),
                (r'(?i)(i apologize|i\'?m sorry|sorry for)', 'apology'),
                (r'(?i)(i was wrong|my mistake|incorrect|mistakenly)', 'admit mistake'),
                (r'(?i)(i think i need|you need to (manually|do it yourself))', 'give up / handoff'),
                (r'(?i)(workaround|alternative approach|instead, try)', 'workaround'),
                (r'(?i)(sandbox denied|permission denied|not allowed)', 'sandbox issue (AI comment)'),
            ]
            for pattern, label in patterns:
                if re.search(pattern, content):
                    snippet = content[:300].replace('\n', ' ').replace('\r', '')
                    results.append((i, label, snippet))
                    break
    return results

def examine_session(fname):
    fp = os.path.join(logs_dir, fname)
    with open(fp, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    hist = data.get('history', [])
    sid = data.get('session_id', '?')
    start = data.get('start_time', '?')[:19]
    turns = data.get('total_turns', '?')
    
    user_msgs = extract_user_msgs(hist)
    ai_admissions = extract_ai_admissions(hist)
    
    # Find sandbox denials by looking at tool call results
    sandbox_count = 0
    cmd_fail_count = 0
    for msg in hist:
        content = str(msg.get('content', ''))
        if '"error"' in content and 'Sandbox denied' in content:
            sandbox_count += 1
        elif '"success": false' in content and 'stderr' in content:
            cmd_fail_count += 1
    
    return {
        'filename': fname,
        'session_id': sid,
        'start_time': start,
        'total_turns': turns,
        'history_len': len(hist),
        'user_msgs': user_msgs,
        'ai_admissions': ai_admissions,
        'sandbox_count': sandbox_count,
        'cmd_fail_count': cmd_fail_count,
    }

# Run analysis
results = []
for fname in key_files:
    fp = os.path.join(logs_dir, fname)
    if os.path.exists(fp):
        r = examine_session(fname)
        results.append(r)
        print(f'Analyzed: {fname}')

# Generate deep dive report
lines = []
W = lines.append

W('# AI 错误深度分析报告\n\n')
W('## 关键会话深入分析\n\n')

for r in results:
    W(f'### Session: {r["filename"]}\n\n')
    W(f'- Session ID: `{r["session_id"]}`\n')
    W(f'- 时间: {r["start_time"]}\n')
    W(f'- 用户轮次: {r["total_turns"]}\n')
    W(f'- 历史消息数: {r["history_len"]}\n')
    W(f'- Sandbox拒绝: {r["sandbox_count"]}次\n')
    W(f'- 命令失败: {r["cmd_fail_count"]}次\n\n')
    
    W('#### 用户问题脉络:\n\n')
    for i, um in enumerate(r['user_msgs']):
        W(f'1. {um}\n')
    
    W('\n')
    
    if r['ai_admissions']:
        W('#### AI承认问题/出错的记录:\n\n')
        for msg_idx, label, snippet in r['ai_admissions']:
            # Clean the snippet for display
            clean = snippet.replace('|', '-')
            if len(clean) > 250:
                clean = clean[:250] + '...'
            W(f'- **Msg#{msg_idx}** [{label}]: {clean}\n\n')
    else:
        W('#### AI问题记录: 未检测到AI主动承认错误\n\n')
    
    W('---\n\n')

# Summary of key error patterns across all sessions
W('## 综合错误模式分析\n\n')

W('### 模式1: Sandbox权限问题 (最常见)\n\n')
W('AI在早期会话（5月27-29日）尝试安装Agent Reach时，大量命令被Sandbox拒绝。'
   '典型错误信息: `"error": "Sandbox denied", "reason": "This bash command is not in an allowed or safely parseable form"`\n\n')
W('AI的应对方式：反复尝试不同的命令格式，但始终未能突破Sandbox限制。'
   'AI花了大量轮次在"试错"上，而不是阅读系统提示中的Sandbox规则来调整命令格式。\n\n')

W('### 模式2: 路径处理错误\n\n')
W('AI在Windows系统上使用了Unix风格的路径（如 `~/.agent-reach-venv`），'
   '导致命令失败。同时也出现了使用Windows路径时反斜杠未正确转义的问题。\n\n')

W('### 模式3: 工具选择不当\n\n')
W('在5月27日的会话中，AI没有使用系统已提供的 `install-alpha-skill` 技能来安装Agent Reach，'
   '而是自己手动尝试各种命令。这说明AI没有充分利用已有工具。\n\n')

W('### 模式4: 重复相同策略\n\n')
W('在会话 `a413be` 中，AI尝试了约12次不同的bash命令，全部被Sandbox拒绝。'
   '但AI仍然继续尝试类似的命令，没有从根本上改变方法。\n\n')

W('### 模式5: 跨日长会话的延续问题\n\n')
W('Session `5cf6e6` 有3个日志文件，跨越5月29日到6月1日。'
   '其中最长的一个持续超过250,000秒（约2.8天）。这可能是Agent Reach安装成功后持续使用的会话。\n\n')

W('### 模式6: 配置信息泄露风险\n\n')
W('在会话 `78066a` 中，用户直接粘贴了Twitter的auth_token等敏感信息到对话中，'
   '这些信息被记录在日志文件中。这是一个潜在的安全问题。\n\n')

# Tool evolution
W('## 工具数量演变\n\n')
W('| 时间段 | 工具数 |\n')
W('|--------|-------|\n')
W('| 5月27日 10:54 - 14:37 | 18 |\n')
W('| 5月27日 15:58 - 5月29日 17:48 | 15 |\n')
W('| 5月31日 及之后 | 28 |\n\n')
W('工具数量在5月31日之后从15增加到28个，说明系统在5月底进行了升级。\n\n')

# Final stats
W('## 数据统计\n\n')
total_sandbox = sum(r['sandbox_count'] for r in results)
total_cmd_fail = sum(r['cmd_fail_count'] for r in results)
W(f'- 分析的会话数: {len(results)}\n')
W(f'- 总Sandbox拒绝: {total_sandbox}\n')
W(f'- 总命令执行失败: {total_cmd_fail}\n')

outpath = os.path.join(output_dir, 'ai_errors_deep_dive.md')
with open(outpath, 'w', encoding='utf-8') as f:
    f.writelines(lines)

print(f'\nDeep dive report written to: {outpath}')
