# -*- coding: utf-8 -*-
import json, os, re, sys
from datetime import datetime

logs_dir = r'D:\files\demo\0312-newagent\agent-alpha\session-log\logs'

output_file = r'D:\files\demo\0312-newagent\agent-alpha\workspace\0611\log_analysis_report.md'

def safe_text(t, maxlen=500):
    """Keep ASCII, newlines, common punctuation; replace problematic chars."""
    if not t:
        return ''
    # Replace \ufffd (replacement character) 
    t = t.replace('\ufffd', '?')
    # Replace other chars that might cause encoding issues
    result = []
    for ch in t[:maxlen]:
        try:
            ch.encode('gbk')
            result.append(ch)
        except:
            result.append('?')
    return ''.join(result)

files = sorted([f for f in os.listdir(logs_dir) if f.endswith('.json') and f != '.gitkeep'],
               key=lambda f: os.path.getsize(os.path.join(logs_dir, f)), reverse=True)

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

all_sessions.sort(key=lambda s: s['start_time'])

lines = []
W = lines.append

W('# agent-alpha 运行日志分析报告\n')
W(f'生成时间: {datetime.now().isoformat()}\n')
W(f'日志文件总数: {len(all_sessions)}\n\n')

# ---- Summary ----
W('## 1. 总体概览\n\n')
W('| 序号 | 时间 | Session ID | 轮次 | 历史条数 | 工具数 | 时长(秒) | 文件名 |\n')
W('|------|------|-----------|------|---------|-------|---------|--------|\n')
for i, s in enumerate(all_sessions):
    dt = s['start_time'][:19] if s['start_time'] else '?'
    fn = s['filename']
    W(f'| {i+1} | {dt} | {s["session_id"]} | {s["total_turns"]} | {s["history_len"]} | {s["tools_count"]} | {round(s["duration"],1)} | {fn} |\n')

W('\n')

# ---- Sessions grouped by date ----
W('## 2. 按日期分组的会话脉络\n\n')

# Group files by date
date_groups = {}
for s in all_sessions:
    dt = s['start_time'][:10] if s['start_time'] else 'unknown'
    if dt not in date_groups:
        date_groups[dt] = []
    date_groups[dt].append(s)

for dt in sorted(date_groups.keys()):
    sessions = date_groups[dt]
    W(f'### {dt} ({len(sessions)} 个会话)\n\n')
    for s in sessions:
        fn = s['filename']
        W(f'**{fn}** | Session: {s["session_id"]} | {s["total_turns"]} turns | {s["history_len"]} msgs | {round(s["duration"],1)}s\n\n')
        
        # Extract conversation topics from user messages
        hist = s['history']
        user_msgs = []
        for msg in hist:
            if msg.get('role') == 'user':
                content = str(msg.get('content', ''))
                # Get first meaningful line
                first_line = content.strip().split('\n')[0][:100]
                user_msgs.append(first_line)
        
        if user_msgs:
            W('  - 用户问题:\n')
            for j, um in enumerate(user_msgs):
                W(f'    {j+1}. {safe_text(um, 120)}\n')
        
        # Check for AI errors
        errors = []
        for msg_idx, msg in enumerate(hist):
            role = msg.get('role', '')
            content = str(msg.get('content', ''))
            
            if role == 'assistant':
                # AI apologizing or admitting mistake
                if re.search(r'(?i)(sorry|apologize|my mistake|i was wrong|let me correct)', content):
                    errors.append((msg_idx, 'AI道歉/承认错误', safe_text(content[:200], 200)))
            
            if role == 'tool' and content:
                if '"error"' in content and 'Sandbox denied' in content:
                    errors.append((msg_idx, 'Sandbox拒绝执行', safe_text(content[:150], 150)))
                elif '"success": false' in content and 'stderr' in content:
                    errors.append((msg_idx, '命令执行失败', safe_text(content[:200], 200)))
                elif re.search(r'(?i)(traceback|exception)', content):
                    errors.append((msg_idx, 'Python异常', safe_text(content[:200], 200)))
        
        if errors:
            W('  - ⚠️ 出现问题:\n')
            for msg_idx, etype, snippet in errors:
                snip_clean = snippet.replace('\n', ' ').replace('\r', '')
                W(f'    - Msg#{msg_idx} [{etype}]: {snip_clean}\n')
        else:
            W('  - ✅ 未发现明显错误\n')
        
        W('\n')

# ---- AI Error Summary ----
W('## 3. AI 错误汇总分析\n\n')

all_errors = []
for s in all_sessions:
    hist = s['history']
    for msg_idx, msg in enumerate(hist):
        role = msg.get('role', '')
        content = str(msg.get('content', ''))
        
        if role == 'tool' and content:
            if '"error"' in content and 'Sandbox denied' in content:
                all_errors.append({
                    'session': s['filename'],
                    'session_id': s['session_id'],
                    'time': s['start_time'],
                    'msg_idx': msg_idx,
                    'type': 'Sandbox拒绝',
                    'detail': safe_text(content[:200], 200)
                })
            elif '"success": false' in content and 'stderr' in content:
                stderr_match = re.search(r'"stderr":\s*"([^"]+)"', content)
                detail = stderr_match.group(1) if stderr_match else safe_text(content[:200], 200)
                all_errors.append({
                    'session': s['filename'],
                    'session_id': s['session_id'],
                    'time': s['start_time'],
                    'msg_idx': msg_idx,
                    'type': '命令执行失败',
                    'detail': safe_text(detail, 200)
                })
        
        if role == 'assistant' and content:
            if re.search(r'(?i)(sorry|apologize|my mistake|i was wrong|let me correct)', content):
                all_errors.append({
                    'session': s['filename'],
                    'session_id': s['session_id'],
                    'time': s['start_time'],
                    'msg_idx': msg_idx,
                    'type': 'AI承认错误',
                    'detail': safe_text(content[:200], 200)
                })

# Count error types
error_types = {}
for e in all_errors:
    et = e['type']
    if et not in error_types:
        error_types[et] = 0
    error_types[et] += 1

W('### 3.1 错误类型统计\n\n')
W('| 错误类型 | 出现次数 |\n')
W('|---------|--------|\n')
for et, count in sorted(error_types.items(), key=lambda x: -x[1]):
    W(f'| {et} | {count} |\n')

W(f'\n**总计: {len(all_errors)} 个问题点**\n\n')

# Show all errors chronologically
W('### 3.2 错误明细 (按时间)\n\n')
W('| 时间 | Session | 消息# | 类型 | 详情 |\n')
W('|------|---------|------|------|------|\n')
for e in all_errors:
    t = e['time'][:19] if e['time'] else '?'
    detail = e['detail'].replace('\n', ' ').replace('\r', '')[:100]
    W(f'| {t} | {e["session_id"]} | {e["msg_idx"]} | {e["type"]} | {detail} |\n')

W('\n')

# ---- Key observations ----
W('## 4. 关键发现与分析\n\n')

# Count Sandbox denials
sandbox_count = sum(1 for e in all_errors if e['type'] == 'Sandbox拒绝')
cmd_fail_count = sum(1 for e in all_errors if e['type'] == '命令执行失败')
ai_apology_count = sum(1 for e in all_errors if e['type'] == 'AI承认错误')

W(f'### 4.1 主要问题模式\n\n')
W(f'1. **Sandbox权限拒绝** ({sandbox_count}次) - 最多的问题类型。AI尝试执行被沙箱阻止的命令，主要集中在安装Agent Reach skill时。\n')
W(f'2. **命令执行失败** ({cmd_fail_count}次) - 命令本身可以运行但返回了非零退出码。\n')
W(f'3. **AI承认错误** ({ai_apology_count}次) - AI主动道歉或承认自己出错了。\n\n')

W('### 4.2 AI出错的具体场景\n\n')
W('**场景一：安装Agent Reach Skill时的反复失败**\n\n')
W('从5月27日到5月29日，AI多次尝试安装Agent Reach skill。典型流程：\n')
W('1. 用户请求安装Agent Reach\n')
W('2. AI尝试各种bash命令安装，但多次被Sandbox拒绝（路径问题、命令格式问题）\n')
W('3. AI反复尝试不同命令格式但持续失败\n')
W('4. 部分情况下AI最终放弃并告诉用户手动安装\n')
W('5. 最终（5月29日后）Agent Reach似乎安装成功了（home/.agents/skills/agent-reach存在）\n\n')

W('**场景二：Session ID 5cf6e6 的跨日异常会话**\n\n')
W('session_5cf6e6 有三个日志文件，时间从5月29日横跨到6月1日，持续超过250,000秒（约2.8天），可能是长会话的继续。\n\n')

W('**场景三：6月6日及之后的工具数量变化**\n\n')
W('5月27日至5月29日的会话只有15-18个工具可用；6月1日及之后增加到28个工具。这表明系统在6月初进行了升级或配置变更。\n\n')

W('### 4.3 AI的主要错误类型\n\n')
W('1. **路径格式错误** - AI在Windows环境下使用了Unix风格的路径，或在路径中包含空格时未正确转义\n')
W('2. **命令格式不符合沙箱规则** - Sandbox对某些命令格式（如包含管道、重定向、复杂分号链）比较严格\n')
W('3. **重复尝试相同策略** - 一种方法失败后，AI多次尝试类似但略有不同的命令，而不是从根本上改变方法\n')
W('4. **未能正确利用install-alpha-skill skill** - 系统已有install-alpha-skill（智能安装skill的工具），但AI在早期尝试中没有使用它\n\n')

W('---\n')
W(f'*报告结束 - 共分析 {len(all_sessions)} 个会话日志文件*\n')

# Write output
with open(output_file, 'w', encoding='utf-8') as f:
    f.writelines(lines)

print(f'Report written to: {output_file}')
print(f'Total sessions: {len(all_sessions)}')
print(f'Total errors found: {len(all_errors)}')
print(f'  - Sandbox denials: {sandbox_count}')
print(f'  - Command failures: {cmd_fail_count}')
print(f'  - AI apologies: {ai_apology_count}')
