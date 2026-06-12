# 自进化 AI Agent 的记忆模块实现方式调研

> 调研日期：2026-05-29
> 数据来源：Mem0 Blog、NousResearch 官方文档、Meta ICLR 2026 论文、ByteDance DeerFlow、Anthropic Claude Code 源码分析

---

## 目录

- [一、背景与核心问题](#一背景与核心问题)
- [二、Hermes Agent（NousResearch）—— 插拔式外部记忆](#二hermes-agentnousresearch--插拔式外部记忆)
- [三、Claude Code（Anthropic）—— 基于文件的扁平记忆](#三claude-codeanthropic--基于文件的扁平记忆)
- [四、HyperAgents（Meta）—— 自涌现的记忆系统](#四hyperagentsmeta--自涌现的记忆系统)
- [五、DeerFlow（ByteDance）—— 异步置信度驱动的 JSON 记忆](#五deerflowbytedance--异步置信度驱动的-json-记忆)
- [六、横向对比](#六横向对比)
- [七、核心趋势与总结](#七核心趋势与总结)

---

## 一、背景与核心问题

自进化 AI Agent 面临一个根本性挑战：**如何让 agent 在多次对话/任务中积累经验、记住用户偏好、并不断自我改进？**

传统方案（把所有历史塞进 context window）在 token 成本和信息质量上都不可持续。因此，专门的**记忆模块**成为自进化 agent 的核心基础设施。

本次调研覆盖 **4 个代表性实践**，涵盖工程化方案和涌现式方案两条路径。

---

## 二、Hermes Agent（NousResearch）—— 插拔式外部记忆

> 来源：Mem0 Blog《How to Add Memory to Your Hermes Agent》(2026.4.6) + NousResearch 官方文档

### 2.1 概述

**Hermes Agent** 是 NousResearch 出品的**自进化 AI agent CLI**，支持长周期任务（几分钟到数小时）。它原生使用本地文件系统记忆（`MEMORY.md` + `USER.md`），并新增了**可插拔的外部记忆提供商插槽**，支持 6 种记忆提供商（Mem0 是其中之一）。

### 2.2 记忆触发架构

Hermes 在每轮对话的 **3 个关键时间点**操作记忆：

```
┌──────────────────────────────────────────────────┐
│               每轮对话周期                          │
├──────────┬───────────────────┬───────────────────┤
│ 响应之前  │    响应之后       │   对话间隙         │
├──────────┼───────────────────┼───────────────────┤
│ 注入缓存  │ 后台提取事实      │ 预取相关记忆       │
│ 零延迟    │ 无需人工指定      │ 为下轮做好准备     │
└──────────┴───────────────────┴───────────────────┘
```

### 2.3 记忆注入格式

在每轮会话开始时，记忆块以冻结文本注入 system prompt：

```
══════════════════════════════════════════════
MEMORY (your personal notes) [67% — 1,474/2,200 chars]
══════════════════════════════════════════════
User's project is a Rust web service at ~/code/myapi using Axum + SQLx
This machine runs Ubuntu 22.04, has Docker and Podman installed
User prefers concise responses, dislikes verbose explanations
```

格式包含：
- 存储来源头（MEMORY 或 USER PROFILE）
- 使用率百分比和字符数（让 agent 知道剩余容量）
- 用 `§` 分隔的条目（支持多行）

### 2.4 双目标记忆系统

| 存储目标 | 存储内容 | 类比 |
|---------|---------|------|
| **memory** | 环境事实、项目约定、工具特性、已完成工作、验证过的技术 | agent 的"工作笔记" |
| **user** | 用户名称、角色、时区、沟通偏好、技术能力 | agent 的"用户画像" |

### 2.5 三个记忆工具（LLM 自动调用）

当 Mem0 激活时，agent 获得三个自动调用工具：

| 工具 | 功能 |
|------|------|
| `mem0_profile` | 获取所有存储的用户记忆 |
| `mem0_search` | 语义搜索（可选 reranking + top_k 过滤） |
| `mem0_conclude` | 直接存储一条事实（跳过服务端提取） |

### 2.6 可靠性机制

- **Circuit breaker**：连续 5 次失败 → 暂停 2 分钟 → 自动重试，agent 持续工作
- **非阻塞**：所有 API 调用在后台线程运行，不影响对话速度

### 2.7 设计哲学

> "大多数记忆系统在查询时搜索，增加了每次交互的延迟。Hermes 反转了这一点：搜索在对话间隙完成，结果在你输入之前已经缓存。Mem0 在服务端处理提取，Hermes 不需要决定什么值得记住。"

---

## 三、Claude Code（Anthropic）—— 基于文件的扁平记忆

> 来源：Mem0 Blog《How Memory Works in Claude Code》(2026.4.5)，基于 Claude Code 泄露源码的反向工程

### 3.1 概述

Claude Code 是 Anthropic 的编码 agent。其记忆系统是该领域**最简化的方案**——纯 Markdown 文件存储在磁盘上。整个架构仅 **7 个文件**。

### 3.2 文件结构

```
~/.claude/projects/<your-repo-name>/memory/
    ├── MEMORY.md          # 索引文件（入口，200行上限）
    ├── user/              # 用户记忆
    ├── feedback/          # 反馈记忆
    ├── project/           # 项目记忆
    └── reference/         # 引用记忆
```

每个项目有独立的文件夹，每次对话都可以写入，文件跨会话持久化。

### 3.3 四种记忆类型

| 类型 | 内容 | 可见性 |
|------|------|--------|
| **User** | 你的角色、专长、偏好、沟通方式 | 私有 |
| **Feedback** | 你给出的纠正、验证过的方法、停止做的事 | 私有 |
| **Project** | 项目截止日期、架构决策、无法从代码推导的上下文 | 团队共享 |
| **Reference** | 外部系统指针：bug tracker、Slack 频道 | 团队共享 |

> 源码明确约束：**如果可以从代码库通过 grep/git 推导的信息，不应保存为记忆**。

### 3.4 硬编码限制（源码级）

```
MEMORY.md 有两道硬限制：
├── 200 行    → 超出后静默截断，追加警告（仅文件可见）
└── 25KB      → 针对单行超长的字节上限

每轮最多加载 5 个文件 → 通过 Sonnet 副调用来选择
```

**静默遗忘问题**：超出限制后，最旧的记忆无声消失。agent 不知道自己忘了什么，用户也不知道。

### 3.5 每轮记忆检索流程

```
1. 扫描所有记忆文件 → 提取文件名 + 一行描述
2. 将清单发送给 Claude Sonnet（独立 API 调用）
3. Sonnet 挑选最相关的 5 个文件
4. 对 >1 天的记忆附加"陈旧警告"
```

> ⚠️ **关键发现**：这里没有 embeddings、没有向量搜索、没有语义相似度。完全靠 Sonnet LLM 读文件名列表做判断。

### 3.6 记忆新鲜度机制

```python
memoryFreshnessText()  # 源码函数
# → 生成："This memory is X days old. Memories are point-in-time observations..."
# → 对超过 1 天的记忆自动附加此警告
```

### 3.7 后台提取器

```python
EXTRACT_MEMORIES  # Feature flag
# 对话结束后运行后台进程
# 审查对话内容并自动提取记忆
# 受 feature flag 控制，非全覆盖
```

### 3.8 局限性

> "200 行索引、5 个文件/轮、无 embeddings。你用了三个月后，第 201 条记忆无声消失。Claude 写了一个测试命中已知有问题的端点，因为关于那个端点的记忆被截断了。这不是幻觉，不是故障，它只是忘了。"

---

## 四、HyperAgents（Meta）—— 自涌现的记忆系统

> 来源：Meta ICLR 2026 论文 + Mem0 Blog《How Memory Works in HyperAgents》(2026.4.3)

### 4.1 最惊人的发现

> **记忆不是人类设计的——是系统自己演化出来的。**

HyperAgents 是一个**自指涉（self-referential）agent**，能够修改自己的代码，包括修改"修改代码"的元过程。

### 4.2 记忆涌现过程

```
Generation 0:  只有 task_agent.py + meta_agent.py，没有记忆
       ↓
Generation 1:  meta_agent 发现每次迭代都从零开始，增益无法累积
       ↓
Generation 3:  agent 自己发明了 3 个记忆组件
               ├── PerformanceTracker（性能追踪器）
               ├── Persistent Synthesized Memory（综合记忆）
               └── Causal Hypothesis Log（因果日志）
```

### 4.3 涌现出的三个记忆组件

#### ① PerformanceTracker（性能追踪器）

agent 自己编写的代码（论文第 11 页）：

```python
class PerformanceTracker:
    """Tracks performance metrics across agent generations."""
    def __init__(self):
        self.tracking_file = "./outputs/performance_history.json"

    def record_generation(self, generation_id, domain, score, metadata=None):
        """记录每代的表现"""

    def get_improvement_trend(self, domain=None, window=5):
        """计算最近 N 代的改进趋势（正数 = 在进步）"""
```

#### ② Persistent Synthesized Memory（综合记忆）

存储的不是原始分数，而是**综合洞察、因果诊断、前瞻计划**：

```json
{
  "best_performers_analysis": {
    "value": "Paper Review:\n- Gen55: 63% acc, 88% reject recall (too harsh)\n- Gen64: 61% acc, 58% accept/reject recall (BEST BALANCE)\nKey Insight: Need to combine gen55's critical reasoning with gen64's balance.",
    "timestamp": "2026-01-07T00:43:27.560275"
  },
  "iteration_66_improvement": {
    "value": "CORRECTED after gen65 over-correction. New approach: (1) Clear REJECT criteria, (2) Decision Protocol with explicit thresholds (~40%/~60%), (3) Borderline defaults to REJECT.",
    "timestamp": "2026-01-07T06:35:55.982000"
  }
}
```

#### ③ Causal Hypothesis Log（因果假设日志）

记录"什么改动导致了什么结果"，形成因果推理链条。

### 4.4 每代循环架构

```python
def run_generation(repo, task, generation_num):
    # 1. 执行任务
    result = repo.task_agent.run(task)
    score = evaluate(result, task)

    # 2. 反思（meta_agent 分析结果）
    meta_reflection = repo.meta_agent.reflect(result, score)

    # 3. 加载历史记忆（Generation 1 时尚不存在）
    history = repo.memory.load_history()

    # 4. 重写自身（不仅是 task_agent，meta_agent 也可以被改写）
    next_repo = repo.meta_agent.rewrite(repo, meta_reflection)

    # 5. 保存记忆
    next_repo.memory.save(meta_reflection)

    return next_repo, score
```

### 4.5 基准成绩

| 领域 | 基线 → 最终成绩 |
|------|:--------------:|
| 论文评审（Paper Review） | 0.0 → **0.71** |
| 机器人（Robotics） | 0.06 → **0.37** |
| 跨领域迁移 | **+0.63** vs 0.0 基线 |

### 4.6 关键启示

> "HyperAgents 证明了：不需要人类告诉 agent 什么是'记忆'。只要给 agent 修改自身代码的能力，经过几代演化，它自己就会发明持久化记忆——因为不这样做，改进就无法累积。"

---

## 五、DeerFlow（ByteDance）—— 异步置信度驱动的 JSON 记忆

> 来源：Mem0 Blog《How Memory Works in DeerFlow》(2026.4.1)，GitHub #1 趋势项目（49.2K Stars）

### 5.1 概述

**DeerFlow**（Deep Exploration and Efficient Research Flow）是 ByteDance 的开源超 agent 框架，基于 LangGraph 编排。它的记忆系统采用**纯 JSON 文件 + 置信度评分 + 异步提取**的方式。

### 5.2 存储结构

```
backend/.deer-flow/memory.json
```

纯本地 JSON 文件，跨会话持久化，无任何外部依赖。

### 5.3 记忆写入流

```
用户发送消息 → Agent 响应
         ↓
MemoryMiddleware（中间件链 #8）
         ↓
过滤：只保留用户输入 + 最终 AI 输出
         ↓
加入异步队列（30 秒防抖定时器）
    ┌──────────────────────────────────┐
    │ 同一 thread_id 有未处理更新？     │
    │ → 新条目替换旧条目，不追加        │
    └──────────────────────────────────┘
         ↓
LLM Extractor 执行 → 产生 diff：
    { newFacts: [], factsToRemove: [], shouldUpdate: {} }
         ↓
更新 memory.json（write-then-rename，原子写入）
```

### 5.4 记忆数据结构

每条事实包含：
| 字段 | 说明 |
|------|------|
| **content** | 事实文本 |
| **confidence** | 置信度分（0~1），**低于 0.7 不存储** |
| **source** | 来源对话的 thread UUID |
| **timestamp** | 时间戳 |
| **category** | User Context / Current Focus / History |

### 5.5 容量与检索

**存储上限**：
- 最多 **100 条事实**
- 超额时驱逐**置信度最低**的

**注入预算**：
- 每轮对话从记忆池中注入 **2,000 token**
- 按置信度从高到低排序，逐步添加直到预算用尽
- 使用 `tiktoken` 精确计数

### 5.6 关键设计特点

| 特性 | 实现方式 |
|------|---------|
| **异步提取** | 30 秒防抖才触发提取，不阻塞用户响应 |
| **去重** | 文本级别（去除空白后精确匹配），非语义去重 |
| **线程替换** | 同 thread_id 未处理的更新，新替旧不追加 |
| **原子写入** | write-then-rename，防止崩溃导致文件损坏 |
| **可选轻量模型** | 提取 LLM 可指定更便宜的模型 |

### 5.7 实际体验发现

经过 3 小时对话测试后的限制：

- ✅ **简单检索**正常工作
- ❌ **删除记忆**不生效：即使 LLM Extractor 产生 `factsToRemove` diff，实际存储未删除
- ❌ **语言偏好误解**：设置英文偏好后仍推荐中文内容
- ❌ **无语义去重**：相同语义的不同表述会重复存储
- ❌ **无语义搜索**：靠置信度排序注入，而非与当前查询的相关性

### 5.8 设计哲学

> "大多数 agent 框架把记忆当作检索问题：embedding 所有内容，存到向量数据库，查询时召回最相似的块。这有效，但代价高昂——添加 embedding 模型、向量存储、检索步骤到每次请求。DeerFlow 采用不同方式：不存储对话，存储理解。"

---

## 六、横向对比

### 6.1 核心维度对比

| 维度 | **Hermes Agent** | **Claude Code** | **HyperAgents (Meta)** | **DeerFlow (ByteDance)** |
|------|:---:|:---:|:---:|:---:|
| **存储介质** | 插拔（支持6种提供商） | Markdown 文件 | 自生成 Python 类 + JSON | JSON 文件 |
| **检索方式** | 语义搜索（embedding） | Sonnet 读文件名 | 直接注入 | 置信度排序 + token 预算 |
| **去重机制** | 云端自动去重 | 无 | N/A（自生成） | 文本级别去重 |
| **异步写入** | ✅ 后台线程 | ✅ 后台提取 | ✅ 代际间 | ✅ 30秒防抖队列 |
| **硬性上限** | 无硬限制 | 200行 / 5文件 | 代际累积 | 100条 / 2000 token |
| **遗忘策略** | 语义相关性筛选 | 静默截断 | 代际自然衰减 | 低置信度驱逐 |
| **自进化** | 工具自动调用 | ❌ 静态 | ✅ 涌现式自生成 | ❌ 静态 |
| **基础设施** | Mem0 API | 纯文件系统 | 自管理 | 纯文件系统 |
| **开源** | ✅ | ❌ 闭源 | ✅ | ✅ |

### 6.2 记忆操作对比

| 操作 | Hermes | Claude Code | HyperAgents | DeerFlow |
|------|:------:|:-----------:|:-----------:|:--------:|
| 添加 | `add` | 写入 markdown | `memory.save()` | LLM 提取 |
| 搜索 | `mem0_search` | Sonnet 选文件 | 直接加载 | 置信度排序 |
| 更新 | `replace` | 覆写文件 | `rewrite()` | diff 更新 |
| 删除 | `remove` | 手动删除 | 代际清理 | 低置信度驱逐 |
| 读取 | 自动注入 prompt | 自动注入 prompt | 自动加载 | 自动注入 `<memory>` 标签 |

### 6.3 遗忘机制对比

```
Claude Code:  "你可能不知道你忘了"
  200行限制 → 静默截断 → agent 不知道自己忘了

DeerFlow:     "不确定的就不要"
  置信度 <0.7 不存 → 超 100 条驱逐最低分的

Hermes:       "找最相关的"
  语义搜索 → 只注入最相关的内容

HyperAgents:  "下一代自然会覆盖上一代"
  代际迭代 → 隐式重塑
```

---

## 七、核心趋势与总结

### 7.1 四条共同趋势

#### ① 写入异步化
所有系统都把记忆写入放在**后台**。用户交互的延迟不应该因为记忆存储而增加。

```
Hermes     → 后台线程
Claude Code → 对话结束后的后台提取器
DeerFlow   → 30 秒防抖异步队列
HyperAgents → 代际之间的批处理
```

#### ② 提取代理化
不存储原始对话，而是用专门的 LLM 提取关键信息。

```
原始数据 → LLM Extractor → 结构化记忆
  (对话)                   (事实/洞察/偏好)
```

#### ③ 置信度/质量门槛
不是所有信息都值得记住。所有系统都有某种形式的**信号过滤**。

| 系统 | 过滤机制 |
|------|---------|
| DeerFlow | 置信度 < 0.7 不存储 |
| Hermes/Mem0 | 服务端自动提取+相关性排序 |
| HyperAgents | 代际自然淘汰 |
| Claude Code | 仅存储不可从代码推导的信息 |

#### ④ 注入式读取
所有系统都把记忆注入到 **system prompt 前缀**中，而非让 agent 主动查询。

```
Hermes     → 冻结块注入 system prompt
Claude Code → 在 context 顶部加载
DeerFlow   → <memory> 标签注入
HyperAgents → 直接加载到代码环境
```

### 7.2 进化的两条路径

| 路径 | 代表 | 核心思想 |
|:----|:-----|:---------|
| **🛠 工程优化** | Hermes、Claude Code、DeerFlow | 由人类设计记忆架构，用更好的检索、存储、提取算法不断优化 |
| **🧬 涌现进化** | HyperAgents | agent 自己发现需要记忆，自己生成记忆系统 |

> HyperAgents 的 path 更激进但也更有启发性：**只要给 agent 修改自身代码的能力，经过几代演化，它自己就会发明持久化记忆——因为不这样做，改进就无法累积。**

### 7.3 Mem0 的定位

Mem0 在多个 agent 中充当**通用记忆层**，本质上是：
1. **向量存储**替代扁平文件 → 解决容量上限
2. **语义检索**替代文件名/置信度匹配 → 解决相关性
3. **无上限扩展**替代硬编码行数限制 → 解决静默遗忘
4. **Token 优化的上下文压缩** → 降低 token 成本

### 7.4 实践建议

```
选择记忆方案的参考因素：

├── 规模 < 100条 且 不需要语义检索
│   └── 🟢 DeerFlow 式 JSON 或 Claude Code 式 Markdown 足够
│
├── 需要跨会话语义检索 且 可接受外部依赖
│   └── 🟢 Mem0 / 向量数据库
│
├── 需要 agent 自进化能力
│   └── 🟢 HyperAgents 式自指涉架构
│
└── 需要开箱即用的生产级方案
    └── 🟢 Hermes Agent + Mem0 插件（1 条命令配置）
```

---

> **参考来源**
> - Mem0 Blog: https://mem0.ai/blog
> - Hermes Agent: https://hermes-agent.nousresearch.com
> - HyperAgents Paper: ICLR 2026
> - DeerFlow: https://github.com/ByteDance/DeerFlow
> - Claude Code Memory: 基于泄露源码分析
