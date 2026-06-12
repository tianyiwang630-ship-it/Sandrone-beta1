# 浏览器工具改进：具体 API 设计与行为推演

> **数据来源日志文件：**
> - Session 1（知乎/CDP研究任务）：`2026-06-10_14-45-50_session_8c1689.json`，Session ID `8c1689`，153 条历史消息，11 轮用户交互，62 次浏览器工具调用
> - Session 2（投资研究任务）：`2026-06-10_17-41-17_session_6859c7.json`，Session ID `6859c7`，163 条历史消息，7 轮用户交互，16 次浏览器工具调用
> - 关联上下文 Session（复现安装问题与用户质疑）：`2026-05-27_16-42-57_session_b6980e.json`，Session ID `b6980e`

基于以上会话的真实失败链，逐条推演改进方案的详细设计。

---

## 背景：Session 1（`8c1689`）中 AI 的一条典型失败链

```
用户说 "用cdp，去知乎搜AI搜索产品评测"
  → AI: browser_connect_cdp("9222")
  → AI: browser_navigate("zhihu.com/search?q=AI搜索+产品经理+2025")
  → AI: browser_scroll("down", 800)     ← 没等页面加载，白滚了
  → AI: browser_snapshot()               ← 看不到结果
  → AI: browser_click("e41")             ← 以为e41是"AI搜索"标签
  → AI: browser_snapshot()               ← 看起来没变化
  → AI: browser_navigate("zhihu.com/第二次搜索")  ← 换搜索词重试
  → AI: browser_scroll("down", 800)
  → AI: browser_snapshot()               ← 终于看到文章标题了！
  → AI: browser_click("e254")            ← 点"阅读全文"
  → AI: browser_snapshot()               ← 页面没跳转 ❌
  → AI: browser_click("e255")            ← 再点文章标题
  → AI: browser_snapshot()               ← 还是没跳转 ❌
  → AI: 放弃浏览器 → 换 fetch(url) 抓全文
```

总共用了 **12 次工具调用**，实际有效产出只有 1 次 snapshot 看到的标题列表。

---

## 改进一：browser_navigate — 增加等待机制

### 当前行为

```python
# 当前
browser_navigate(url: str, session_id?: str) -> snapshot
```
返回很快但不保证页面已渲染。AI 必须手动 scroll+snapshot 去验证页面是否加载完成。

### 改进设计

```python
browser_navigate(
    url: str,
    wait_until: str = "load",          # "load" | "domcontentloaded" | "networkidle" | "visible:selector"
    wait_selector: str | None = None,  # 如 "div.search-result-item", "article"
    timeout_ms: int = 15000,
    return_content: bool = True,       # 是否同时返回可见文本
    session_id: str | None = None
) -> PageState

class PageState:
    url: str
    title: str
    status: str                        # "loaded" | "timeout" | "error"
    visible_text: str | None           # 当前视口内的可见文本
    snap_refs: list[ElementRef]        # 可供后续 click/type 的元素引用
    suggestions: list[str] | None      # 发现页面异常时的建议
```

### wait_until 模式详解

| 模式 | 行为 | 适用场景 |
|------|------|---------|
| `"load"` | 等待 `window.load` 事件 | 普通静态页面 |
| `"domcontentloaded"` | 等待 DOM 解析完成，不等图片/CSS | 快速获取内容 |
| `"networkidle"` | 等待网络请求停止（500ms 内无请求） | **SPA 页面（知乎、X）** |
| `"visible:selector"` | 等待特定 CSS 选择器出现在 DOM 中 | 知道页面结构时 |
| `"interactable:selector"` | 等待元素可见并可交互 | 点开文章前确认按钮可用 |

### 在 Session 1（`8c1689`）中的效果推演

**原来**（12 次调用，产出低）：
```
navigate → scroll(无效) → snapshot(空白) → click(猜) → snapshot(验证) → ...
```

**改进后**（2 次调用，直接可读）：
```
navigate("zhihu.com/search?q=...", wait_until="networkidle", return_content=True)
  → 返回: {
      status: "loaded",
      visible_text: "全网最全AI搜索PK...60赞同\nAI搜索工具横评...\n...",
      snap_refs: [e41(标题链接), e42(阅读全文), ...]
    }
```

AI 直接在返回值里看到了搜索结果的文章标题和摘要，不需要 scroll+snapshot 去"看一眼"。而且返回的 `snap_refs` 带语义——因为工具可以标注元素类型（link/button/text），AI 知道 `e41` 是一个文章标题链接，而不是盲猜。

---

## 改进二：browser_extract_text — 从"拍照"到"阅读"

### 当前困境

AI 有两条路获取页面文本，各有致命缺陷：

| 方式 | 优点 | 缺点 |
|------|------|------|
| `snapshot` | 保留交互能力（click/type） | 文本碎片化，包含导航/广告，不是纯正文 |
| `fetch(url)` | 文本干净 | 没有交互状态（未登录、未展开全文）、不支持 SPA |

### 改进设计

```python
browser_extract_text(
    mode: str = "auto",              # "auto" | "visible" | "article" | "full"
    selector: str | None = None,     # 自定义选择器
    clean: bool = True,              # 是否去除导航/广告/侧栏
    max_length: int = 100000,
    session_id: str | None = None
) -> PageText

class PageText:
    url: str
    title: str
    content: str                     # 提取的正文
    word_count: int
    has_more: bool                   # 是否有折叠/分页内容
    fold_buttons: list[ElementRef]   # "展开全文"按钮引用
    suggestions: list[str]           # "检测到有8个展开全文按钮，是否点击？"
```

### mode 详解

| mode | 行为 | 适用场景 |
|------|------|---------|
| `"auto"` | 自动检测正文区域（article → main → 最长文本块） | 打开一篇文章后直接读 |
| `"visible"` | 只返回当前视口内的可见文本 | 确认当前页是什么 |
| `"article"` | 使用 Readability/Reader Mode 提取 | 新闻、博客 |
| `"full"` | 返回 `document.body.innerText` | 需要全部文本 |

### 在 Session 1（`8c1689`）中怎么用

**原来 AI 点开知乎文章失败的原因**：
知乎搜索结果页的"阅读全文"按钮是通过 JS 在同页展开内容，不是导航到新 URL。`browser_click` 点击后页面 URL 没变，AI 以为没生效，反复点。

**改进后的流程**：
```
Step 1: navigate("zhihu.com/search?q=...", wait_until="networkidle")
Step 2: extract_text(mode="visible")
  → 返回文章列表标题+摘要  ✅  直接看到有8篇相关文章
  
Step 3: click(ref=e41)  # 点标题链接
Step 4: extract_text(mode="article", clean=True)
  → 返回"全网最全AI搜索PK..."的正文 ✅ 直接读完整文章
  → fold_buttons: [展开全文按钮]  ← 提示AI还有折叠内容
```

关键变化：`extract_text` 返回了 `fold_buttons` 字段，AI 知道还有折叠内容需要展开，而不是盲目认为文章就这么多。

---

## 改进三：browser_click — 从"盲点"到"有反馈地点击"

### 当前行为

```python
# 当前
browser_click(ref: str, session_id?: str) -> snapshot
```
无论点击是否触发了页面变化，都返回一个 snapshot。AI 必须自己对比前后两个 snapshot 来判断点击是否生效。

### 改进设计

```python
browser_click(
    ref: str,
    wait_for: str | None = None,       # "navigation" | "content_change" | "element:selector"
    timeout_ms: int = 10000,
    retry: int = 0,                    # 失败重试次数
    strategy: str = "auto",            # "auto" | "dom" | "js" | "keyboard(Enter)"
    session_id: str | None = None
) -> ClickResult

class ClickResult:
    success: bool
    effect: str                        # "navigation" | "content_update" | "modal" | "no_change"
    page_url: str                      # 点击后的 URL（可能变了）
    page_title: str
    new_content: str | None            # 页面新增的文本内容（如果是同页展开）
    visible_refs: list[ElementRef]     # 点击后新增/变化的元素
    error: str | None                  # 点击失败的详细原因
```

### strategy 参数

| strategy | 行为 | 适用场景 |
|----------|------|---------|
| `"dom"` | 标准 DOM click 事件 | 普通链接、按钮 |
| `"js"` | `element.dispatchEvent(new MouseEvent('click'))` | SPA 页面（知乎、X） |
| `"keyboard(Enter)"` | 聚焦后按回车 | 某些表单/按钮 |
| `"auto"` | 先用 DOM click，失败自动降级为 JS click | 默认 |

### 在 Session 1（`8c1689`）中的效果

**原来**：AI 在知乎上点了 4 次，每次返回的效果都一样（snapshot），AI 无法判断是"没点中"还是"点中了但内容在同页展开"。

**改进后**：
```
click(ref=e41, wait_for="content_change", strategy="auto")
  → 返回: {
      success: true,
      effect: "no_change",             ← 工具检测到页面内容没有变化
      error: "Element clicked but no navigation or content update detected.
              Possible causes: 
              1. Element is below the fold and not visible (try scroll first)
              2. Element is a SPA expand button that needs JS dispatch
              3. Element ref is stale (page changed after last snapshot)"
    }
```

AI 拿到这个错误信息，就知道：
- 不是"点中了但没反应" → 而是"点击根本没生效"
- 工具给出了原因建议 → AI 可以针对性调整策略

换用 `strategy="js"` 或先 `scroll` 让元素可见再点，成功率会大幅提升。

---

## 改进四：标签页管理 — 从"单页串行"到"多页并行"

### 当前困境（Session `8c1689` 实测）

AI 所有的 navigate 都是**替换当前页面**。Session `8c1689` 中：
- 搜索结果页 → navigate 到文章页面 → 看完想回到搜索结果 → **没有 back，只能重新 navigate 搜索 URL**
- 想同时看知乎 + X + 人人都是产品经理 → **只能串行，一个一个 navigate**
- 看了一篇文章发现不相关 → 已经替换了当前页，只能 browser_navigate 回去
- Turn#9 用几乎相同的搜索词重新搜索 → 因为 Turn#3 的搜索结果页已经被替换了

### 改进设计

```python
# 新增工具

browser_new_tab(
    url: str,
    activate: bool = False,            # 是否立即切换到新标签页
    wait_until: str = "domcontentloaded",
    session_id: str | None = None
) -> TabInfo

browser_switch_tab(
    tab_id: str | int,                 # 标签页 ID 或索引（0-based）
    session_id: str | None = None
) -> TabSnapshot                      # 返回当前标签页状态

browser_close_tab(
    tab_id: str | int | None = None,   # None = 关闭当前标签页
    session_id: str | None = None
) -> TabInfo                          # 返回切换到的新当前标签页

browser_list_tabs(
    session_id: str | None = None
) -> list[TabInfo]

class TabInfo:
    id: str
    index: int                         # 在窗口中的位置
    url: str
    title: str
    status: str                        # "loading" | "loaded" | "error"
    last_active: datetime
    
class TabSnapshot:
    tab: TabInfo
    visible_text: str | None
    refs: list[ElementRef]
```

### 在 Session 1（`8c1689`）中的效果推演

**改进前的行为**（串行，12 次调用）：
```
navigate(知乎搜索结果) → snapshot → navigate(文章A) → snapshot → 
navigate(知乎搜索结果) → snapshot → navigate(文章B) → snapshot → ...
```
每次切换都要重新 navigate，搜索结果页的状态丢失了。

**改进后的行为**（并行，9 次调用，覆盖更多内容）：
```
# 阶段1：搜索 → 打开多个候选
navigate(知乎搜索结果, wait_until="networkidle")     → 看到8篇相关文章
new_tab(zhuanlan.zhihu.com/p/A, activate=false)      → 后台打开文章A
new_tab(zhuanlan.zhihu.com/p/B, activate=false)      → 后台打开文章B  
new_tab(zhuanlan.zhihu.com/p/C, activate=false)      → 后台打开文章C

# 阶段2：逐个阅读（不丢失搜索结果页）
switch_tab(tab=文章A) → extract_text(mode="article") → 读完整篇文章
close_tab()
switch_tab(tab=文章B) → extract_text(mode="article") → 读完整篇文章
close_tab()
switch_tab(tab=文章C) → extract_text(mode="article") → 读完整篇文章
close_tab()

# 阶段3：回到搜索结果页，继续找更多
# 搜索结果页还在！不需要重新搜索！AI可以继续浏览更多文章
```

关键变化：
1. **搜索结果页一直开着**，读完一篇文章可以无缝继续浏览
2. **不会重复搜索** —— 当前没有 `back`，读完文章只能重新 navigate
3. **并行加载** —— 3 篇文章在后台同时加载，读的时候不需要等

---

## 改进五：browser_scroll — 从"盲滚"到"逐屏阅读"

### 当前行为

```python
# 当前
browser_scroll(direction: str, pixels: int, session_id?: str)
```
只是滚动，不返回任何新内容。AI 必须手动再调用一次 `snapshot` 才能看到滚动后的内容，而且无法区分"新出现的文本"和"之前已经看过的文本"。

### 改进设计

```python
browser_scroll(
    direction: str = "down",           # "down" | "up" | "page_down" | "page_up" | "to_bottom" | "to_top"
    amount: str | int = "auto",        # "auto"=一屏, "page"=整页, 或像素值
    return_new_text: bool = True,      # 只返回新进入视口的文本
    session_id: str | None = None
) -> ScrollResult

class ScrollResult:
    new_text: str                      # 新出现在视口中的文本（如果 return_new_text=True）
    total_text: str                    # 整页文本（如果 return_new_text=False）
    scroll_percent: float              # 当前滚动位置（0.0~100.0）
    at_bottom: bool                    # 是否已到底
    at_top: bool                       # 是否已到顶
    new_refs: list[ElementRef]         # 新进入视口的可交互元素
```

### 关键设计点：`new_text` 的意义

当前 `scroll + snapshot` 组合的问题是：每次 snapshot 返回整个页面的文本，AI 需要自行对比"哪些内容之前已经看过了"。

`return_new_text=True` 时，工具会**滚动后提取新进入视口的文本**，类似于：
```
第一次 scroll:  "全网最全AI搜索PK...\nAI搜索工具横评..."
第二次 scroll:  "我花了一周深度实测Perplexity...\nAI搜索引擎横向测评..."
第三次 scroll:  "2026年AI搜索谁最强？..."
```

这样 AI 就像人一样"逐屏阅读"，每次拿到新内容，不需要做去重。

---

## 改进六：工具的回传信息 — 从"裸数据"到"有建议的反馈"

### 当前问题

当前所有浏览器工具返回的信息都很底层：
- `browser_click` → snapshot（AI 自行判断有没有点中）
- `browser_navigate` → 返回页面已加载（但不等渲染）
- `browser_connect_cdp("9222")` → session_id（不检查 9222 是否可达）

**AI 需要用大量思考来诊断这些裸数据**。Session 1（`8c1689`）中 AI 大量的 thinking 内容都是在诊断"为什么页面没加载？为什么点击没反应？"。

### 改进理念：工具应该"主动建议"，而不是"被动返回数据"

每个工具在返回时，应该包含：
1. **发生了什么**（事实层）
2. **有什么异常**（诊断层）
3. **建议下一步做什么**（策略层）

```python
# 所有浏览器工具返回的通用包装
class BrowserResponse:
    ok: bool
    data: Any                          # 工具特有的数据
    warnings: list[str]                # "页面可能未完全加载"
    suggestions: list[str]             # "是否尝试 wait_until='networkidle'?"
    alternative_tools: list[str]       # "如果继续失败，可考虑用 fetch(url) 获取此页面"
```

### 示例：改进后的 connect_cdp

```python
browser_connect_cdp(cdp_url: str) -> BrowserResponse
  → {
      ok: true,
      data: { session_id: "abc", tabs: 3, current_url: "zhihu.com" },
      warnings: [],
      suggestions: [
        "当前窗口有3个标签页，可以用 browser_list_tabs 查看",
        "当前页面是 zhihu.com，用户可能已登录知乎"
      ]
    }
```

```python
browser_connect_cdp(cdp_url: str) -> BrowserResponse  # 如果端口不可达
  → {
      ok: false,
      data: null,
      warnings: ["连接 9222 超时"],
      suggestions: [
        "确认 Chrome 是否以 --remote-debugging-port=9222 启动",
        "尝试 browser_connect_cdp(cdp_url='http://127.0.0.1:9222')",
        "如果无法连接CDP，可使用 profile_login_headed 开有头浏览器",
        "或使用无头浏览器 browser_navigate(url, use_headless=true)"
      ],
      alternative_tools: ["profile_login_headed", "browser_navigate"]
    }
```

### 在 Session 1（`8c1689`）中的效果

**原来**：AI 在 connect_cdp 成功后，不知道当前窗口已经打开了什么页面，不知道用户已经登录了什么网站。它只能盲目地 navigate，浪费了用户已登录的状态。

**改进后**：connect_cdp 返回 `current_url` 和 `suggestions`，AI 发现"当前页面是知乎，用户已登录"，直接在当前页搜索，而不是 navigate 到一个全新的知乎搜索 URL。

---

## 七、把这些改造成一个 "Browser Skill" 的接口设计

如果把上述改进封装成一个 Skill，接口应该是"以任务为中心"而不是"以工具为中心"：

```python
# ========== 以工具为中心（当前，AI 用不好） ==========
browser_connect_cdp → browser_navigate → browser_scroll → 
browser_snapshot → browser_click → browser_snapshot → ...

# ========== 以任务为中心（改进后，AI 一次调用） ==========

read_page(url: str, expand_folds: bool = True) -> PageContent
  """
  像人一样"读"一个页面。
  
  内部自动执行：
  1. 新标签页打开 URL（不替换当前页）
  2. 等 networkidle（确保 SPA 渲染完）
  3. 如果检测到"展开全文"按钮 → 逐个点击展开
  4. 提取正文（Readability 算法，去广告/导航）
  5. 滚动检查是否到底
  6. 关闭标签页
  7. 返回 struct：{title, author, publish_time, content, word_count}
  """

search_and_collect(query: str, sources: list[str], max_results: int = 10) -> SearchResult[]
  """
  像人一样搜索并收集结果。
  
  内部自动执行：
  1. 对每个 source 在搜索页执行搜索
  2. 等待搜索结果加载
  3. 收集文章标题/摘要/链接/元数据
  4. 去重（跨 source 的相同文章只保留一份）
  5. 返回 struct 列表：{source, title, url, summary, metadata}
  """

research_topic(
    topic: str,
    sources: list[str],
    depth: int = 2,           # 1=标题, 2=摘要, 3=全文
    max_articles: int = 10
) -> ResearchNote
  """
  像一个人类研究员一样探索主题。
  
  阶段1: search_and_collect → 收集各来源的结果
  阶段2: 按相关度排序，筛选 top_N
  阶段3: read_page 逐个阅读全文
  阶段4: 汇总 → 生成结构化研究笔记
  
  全程自动管理标签页生命周期
  """
```

Skill 层把 6-12 次底层的浏览器工具调用，封装成 AI 一次能理解的"任务单位"。AI 不再需要思考"先 connect_cdp 还是先 navigate？这个 ref 是什么？为什么点击没反应？"，而是直接说"我要研究这个主题"。

---

## 总结：改进路径

```
当前状态：
  工具是"浏览器 API" → AI 需要自己组合 → 容易出错且低效

第一步（低风险，高收益）：
  给现有工具增加 wait_until, extract_text, 点击反馈建议
  → AI 还是用同样的工具名，但行为更可靠

第二步（中风险，中收益）：
  增加标签页管理、back、scroll_read
  → AI 开始能"并行浏览"，像人了

第三步（高风险，高收益）：
  封装 Browser Research Skill
  → AI 不再操作浏览器，而是"发布研究任务"
  → 但灵活性降低，不适合需要精细控制浏览器行为的场景
```
