# Session 2 (6859c7) 浏览器工具选择分析

## 关键发现：AI有明确的"效率分层"策略

AI在思考过程中多次明确提到了效率考量，形成了三级工具链：

---

## 第一层：发现 → browser_navigate（仅导航）

**为什么只用 navigate，不用 scroll/click/snapshot？**

因为 AI 把 Google 搜索结果页当"搜索API"用。从思考内容可以清楚看到，AI **直接读取了 Google 搜索结果的摘要信息**（页面内容通过浏览器返回给了AI），看完摘要后：

- 如果标的有潜力 → 记下代码，加入候选列表
- 如果标的没潜力 → 跳过，继续搜下一个

**不需要 scroll/click/snapshot 的原因：**
- 一个标的的判断只需要几秒钟（看摘要的营收/净利/PE数据）
- 如果用完整流程（scroll → click → snapshot → read），每个标的需要5-6次工具调用，搜50个就要250-300次调用
- AI 明确说：*"Rather than searching each one individually... let me batch search"*、*"Instead of doing each search individually in the browser (which is slow)"*

> **本质：这是一个"广度优先"的筛选任务，不是"深度阅读"任务**

---

## 第二层：验证 → yfinance Python 脚本

AI 搜到候选标的列表后，**一次性写一个 Python 脚本**，用 yfinance 批量拉取50+只标的的财务数据。

AI 的思考：*"Let me write a comprehensive yfinance script that covers 50+ A股 stocks at once"*

这比用浏览器逐页查财务数据快 **2个数量级**（一次脚本运行 vs 每只股票打开东方财富/雪球页面手动翻数据）。

---

## 第三层：深挖 → fetch

当用户要求"每一个标的的逻辑要更详细"时，AI 尝试了两种方式：

1. 先用 `browser_navigate` 导航到新闻页面（Yahoo Finance, Investing.com）→ **页面没加载好** ❌
2. 主动切换策略：*"Let me try fetching the content via the fetch tool instead, which might work better"* → **用 fetch**

之后形成固定模式：
```
browser_navigate → 搜Google找到文章链接 → fetch(URL) → 获取全文
```

`fetch` 比 `navigate+scroll+snapshot` 高效的原因：
- 1 次工具调用 vs 5-6 次工具调用
- 直接返回干净的文本内容 vs 需要AI"阅读"截图
- 这个场景不需要看页面渲染/JS动态效果

---

## 横向对比：Session 1 为什么相反？

Session 1（AI搜索研究）中，AI 用了大量 scroll/click/snapshot，原因是：

| 维度 | Session 1（研究） | Session 2（投资） |
|------|:---:|:---:|
| 任务类型 | **深度阅读**（读知乎回答、X帖子） | **广度筛选**（50+标的中找出候选） |
| 页面类型 | 知乎/X/人人都是产品经理 → 需要看帖子内容 | Google搜索结果 → 摘要已足够 |
| 数据需求 | 需要阅读完整文章和评论 | 只需营收/净利/PE几个数字 |
| 验证方式 | 浏览器内阅读+摘录 | yfinance脚本批量拉取 |
| 深挖方式 | 浏览器 scroll+click 翻页 | fetch 直接抓取新闻全文 |

**Session 2 的 AI 比 Session 1 的 AI 更高效**，因为 Session 2 的 AI 找到了"这个场景最匹配的工具链"，而 Session 1 的 AI 被 CDP session 管理问题拖累、且混用了搜索工具。
