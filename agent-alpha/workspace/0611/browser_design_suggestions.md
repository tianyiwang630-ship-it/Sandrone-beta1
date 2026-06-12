# 浏览器工具设计与 AI 浏览器行为改进建议

基于 Session 1（AI搜索研究）和 Session 2（投资研究）的真实失败数据推导。

---

## 一、当前工具的 7 个核心缺陷

### 缺陷 1：没有"新标签页"概念 — AI 不会并行探索

**观察数据**：Session 1 中 AI 7 次 navigate 到知乎，每次都是**替换当前页面**。搜到一篇好文章 → navigate 到文章 → 看完后想回搜索结果 → 但没有 back 按钮 → 只能重新 navigate 搜索页。

**人类怎么做**：看到感兴趣的链接 → **右键/中键在新标签页打开** → 继续浏览搜索结果 → 看完所有感兴趣的再逐个切标签页阅读

**当前工具**：只有 `browser_navigate(url)` — 直接替换当前页面，没有 "open in new tab" 的概念

### 缺陷 2：Snapshot 不是"阅读"而是"拍照" — 信息密度低

**观察数据**：Session 1 中 AI 对知乎搜索结果页做了 snapshot，从截图内容中 AI 读到了文章标题。但当 AI 想读全文时，它**无法通过 snapshot 获取正文内容**。

**人类怎么做**：目光扫过标题 → 点击链接 → **眼睛阅读正文**（逐行滚动）

**当前 snapshot** 的问题：
- 返回的是 DOM 结构的简化文本，不是视觉渲染内容
- 对于 SPA 页面（知乎、Twitter），snapshot 经常遗漏动态加载的内容
- 信息密度比直接 `fetch(url)` 低得多
- 但 snapshot 又比 fetch 多了交互能力（click/type）

### 缺陷 3：点击是"黑箱射击" — 不知道点的是什么

**观察数据**：Session 1 中 AI 在知乎搜索页点击了 `ref=e41`、`ref=e254`、`ref=e255`。从 AI 的思考看，它"以为" e41 是"AI 搜索"标签、e254 是"阅读全文"按钮——但实际效果不符合预期。

**人类怎么做**：看到按钮上的文字 → 知道点了什么 → 预期结果 → 验证结果

**当前 click** 的问题：
- ref 编号没有语义，AI 只能凭元素在 DOM 中的位置推断是什么
- 对于 SPA 页面，click 后 JS 可能不触发导航，但 AI 无法区分"点击未生效"和"内容在同页展开了"
- AI 连续点击了 4 次不同元素都没有触发页面跳转，它花了大量心智去诊断

### 缺陷 4：没有"等待加载"机制 — AI 不等页面渲染完

**观察数据**：Session 1 的 timeline：
1. `browser_navigate`（知乎搜索页）
2. 立即 `browser_scroll`（没有等搜索结果渲染）
3. 立即 `browser_snapshot`

AI 思考中说："The snapshot doesn't show the search result items, probably because they haven't loaded yet"

**人类怎么做**：输入搜索词 → 等页面加载 → 等结果出现 → 再看内容

### 缺陷 5：CDP Session 管理没有"复用"意识

**观察数据**：Session 1 创建了 **10 个不同的 CDP session ID**。每次用户说"再来一次"，AI 就 `disconnect` 旧的、`connect` 新的。最后一次性 `disconnect` 了 4 个残留 session。

**人类怎么做**：打开一个浏览器窗口 → 一直用 → 用完关闭

**问题根因**：工具没有提供"检查当前 session 是否仍然有效"的语义化方法，AI 只能 disconnect 再 reconnect 来"重置"。

### 缺陷 6：没有"后退"和"前进" — AI 只能重新导航

**观察数据**：Session 1 中 AI 从知乎搜索结果 navigate 到 X，想回知乎看更多内容时，只能重新 `navigate` 到知乎搜索 URL。它没有 `browser_go_back()` 可用。

**人类怎么做**：看完一个页面 → 点浏览器"后退"按钮 → 回到搜索结果 → 点下一个链接

### 缺陷 7：没有"阅读进度"追踪 — AI 会重复做已做过的事

**观察数据**：Session 1 Turn#9 的搜索词 (`AI搜索产品测评+对比+Perplexity+秘塔+天工`) 和 Turn#3 的搜索词几乎一样。AI 不知道自己已经搜过了。

**人类怎么做**：看到熟悉的搜索结果 → "这个我看过了" → 划走

---

## 二、改进建议

### 建议 1：新增标签页管理工具

```python
# 新增工具
browser_new_tab(url)          # 在新标签页打开链接，不切换当前页
browser_switch_tab(index|id)  # 切换到指定标签页
browser_list_tabs()            # 列出所有标签页及其 URL/标题
browser_close_tab(index)       # 关闭指定标签页
browser_go_back()              # 后退
browser_go_forward()           # 前进
```

**设计理由**：Session 1 的场景中，如果 AI 能在搜索结果页对每篇感兴趣的文章执行 `browser_new_tab(url)` 打开3-5个标签页，然后逐个 `switch_tab` 阅读、`close_tab` 关闭，这种行为链更接近人类研究者。而且不需要反复 connect/disconnect。

### 建议 2：browser_navigate 增加 wait_until 参数

```python
browser_navigate(
    url: str,
    wait_until: Optional[str] = "load",  # "load" | "domcontentloaded" | "networkidle" | "visible:selector"
    wait_selector: Optional[str] = None, # 等待特定元素出现
    timeout: int = 30000,
    session_id: Optional[str] = None
)
```

**设计理由**：Session 1 中 AI 导航到知乎后 snapshot 看不到结果，就是因为没等页面渲染。如果能设 `wait_until="networkidle"` 或 `wait_selector=".SearchResultItem"`，AI 就不需要做无效的 scroll+snapshot。

### 建议 3：增加 `browser_extract_text()` — 从当前页提取正文

```python
browser_extract_text(
    selector: Optional[str] = None,  # CSS selector，默认提取正文
    session_id: Optional[str] = None
) -> str  # 返回干净的文本内容
```

**设计理由**：当前 AI 获取页面内容的途径只有两种：
- `snapshot` → 返回 DOM 结构文本，信息密度低，且包含导航/侧栏等噪音
- `fetch(url)` → 返回干净文本，但不支持交互（如点击"展开全文"、翻页等）

`extract_text` 介于两者之间：在当前浏览器页面执行 `document.body.innerText` 或 article 提取，既保留了页面的交互状态（已点击展开、已登录），又返回干净的文本内容。

这样 AI 做 `click → extract_text` 就能"阅读"一篇文章，而不是 `click → snapshot` 去"看截图"。

### 建议 4：增加点击确认/重试机制

```python
browser_click(
    ref: str,
    wait_for_navigation: bool = False,  # 是否等待页面跳转
    timeout: int = 10000,
    alternative_strategy: bool = False, # 点击失败时是否尝试 JS 事件
    session_id: Optional[str] = None
)
```

**设计理由**：Session 1 中 AI 在知乎搜索页点了 4 次都失败了，但工具返回了"成功"（没有报错）。如果 `wait_for_navigation=True` 能在点击后检测 URL 是否变化、页面内容是否更新，AI 就能第一时间知道点击是否生效，而不是盲目地再截一次图去验证。

### 建议 5：CDP session 智能复用

```python
# 内部逻辑变更——不是新增工具
browser_connect_cdp(cdp_url) 的行为改为：
  1. 检查是否已有连接到该 URL 的活跃 session
  2. 如果有 → 返回已有 session_id（不创建新连接）
  3. 如果没有 → 建立新连接
```

**设计理由**：Session 1 中 AI 反复 connect/disconnect 同一端口，产生了 10 个 session。如果工具能自动复用，AI 的行为会自然变得"像人"——连上一次浏览器，一直用同一个窗口。

### 建议 6：增加"滚动阅读"模式

```python
browser_scroll_read(
    direction: str = "down",
    lines: int = 30,           # 相当于"看多少行"
    return_text: bool = True,  # 返回滚动后可见区域的新文本
    session_id: Optional[str] = None
) -> str  # 新出现在视口中的文本
```

**设计理由**：当前 `scroll + snapshot` 组合的问题是：snapshot 每次返回整个页面，AI 无法知道"哪些内容是新的"。`scroll_read` 像人类一样逐屏阅读，只返回新出现的文本。这比每次都做全页 snapshot 更高效，也更接近人的阅读节奏。

### 建议 7：Prompt 层的"浏览器行为指南"

在系统提示词中加入以下指引：

```
## 浏览器使用指南

当你需要通过浏览器探索网页时，请遵循人类研究者的行为模式：

1. **搜索阶段**：在搜索页找到感兴趣的链接，用 `browser_new_tab` 打开多个候选页面（不要点一个看一个）
2. **阅读阶段**：切换到新标签页 → `browser_extract_text` 获取正文 → 如果内容有折叠，`browser_click` 展开后再提取 → 读完用 `browser_close_tab` 关闭
3. **回溯阶段**：回到搜索标签页继续浏览，或 `browser_go_back` 返回上级页面
4. **记录阶段**：阅读过程中发现关键信息，用 `write` 保存到工作区文件
5. **CDP 连接**：连接到用户浏览器后，**不要反复断开重连**。同一个 CDP 端口复用同一个 session
6. **等待加载**：导航到页面后，先检查页面是否完全加载再操作。复杂页面请设定 wait_selector
7. **避免重复**：记录你已经搜索过的关键词和访问过的 URL，不要重复相同操作
```

---

## 三、一个更高层级的思路：Browser Research Skill

如果把上述改进封装成一个 Skill，给 AI 的接口可以更接近人的思维方式：

```python
# 高层技能接口（AI 直接调用，底层组合多个工具）

def research_topic(
    topic: str,
    sources: list[str],  # ["zhihu", "x.com", "woshipm"]
    depth: int = 3,      # 1=只搜标题, 2=读摘要, 3=读全文
    max_articles: int = 10
) -> ResearchNotes:
    """
    像一个人类研究员一样探索一个主题。
    
    阶段1: 对每个 source 执行搜索，收集结果列表
    阶段2: 扫描标题和摘要，筛选最相关的文章
    阶段3: 用新标签页打开筛选后的文章，提取正文
    阶段4: 汇总关键发现，去重，生成结构化笔记
    
    全程自动管理：
    - 标签页生命周期（打开→切换→关闭）
    - 等待页面加载
    - 处理 SPA 点击展开
    - 记录已访问 URL 避免重复
    """

def read_article(url: str) -> ArticleContent:
    """
    像人一样"阅读"一篇文章。
    
    1. 在新标签页打开 URL
    2. 等待正文加载
    3. 如果检测到"展开全文"按钮，点击它
    4. 提取正文文本（去除导航/广告/侧栏）
    5. 滚动检查是否有更多内容
    6. 返回结构化内容（标题+作者+时间+正文）
    7. 关闭标签页
    """
```

---

## 四、优先级建议

| 优先级 | 改进项 | 预期效果 | 复杂度 |
|--------|--------|---------|--------|
| P0 | `browser_navigate` 增加 `wait_until` | 消除"页面没加载好"的问题，减少无效 scroll+snapshot | 低（参数改造） |
| P0 | CDP session 自动复用 | Session 1 的 10 个 session → 1 个 session，消除 50% 的 connect/disconnect 开销 | 低（连接池逻辑） |
| P1 | 新增 `browser_new_tab` / `switch_tab` | 让 AI 能并行探索，像人一样"先搜一批、再看一批" | 中 |
| P1 | 新增 `browser_extract_text` | 替代 `snapshot` 的"阅读"功能，信息密度更高 | 中 |
| P1 | 新增 `browser_go_back` | 让 AI 能回到搜索结果，而不是重新 navigate | 低 |
| P2 | `browser_click` 增加 `wait_for_navigation` | 解决 SPA 点击不生效的"盲点"问题 | 中 |
| P2 | Prompt 层浏览器行为指南 | 从源头引导 AI 形成好的浏览习惯 | 低（纯文本） |
| P3 | 高层级 Browser Research Skill | 彻底解决"工具太底层、AI 用不好"的问题 | 高 |
