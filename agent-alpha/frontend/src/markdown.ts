function escapeHtml(value: string) {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function escapeAttribute(value: string) {
  return escapeHtml(value).replace(/`/g, '&#96;')
}

function isSafeHref(value: string) {
  return /^(https?:|mailto:)/i.test(value)
}

function renderInlineMarkdown(value: string) {
  const codeTokens: string[] = []
  let html = value.replace(/`([^`\n]+)`/g, (_match: string, code: string) => {
    const token = `@@CODETOKEN${codeTokens.length}@@`
    codeTokens.push(`<code>${escapeHtml(code)}</code>`)
    return token
  })

  html = escapeHtml(html)
  html = html.replace(/&lt;br\s*\/?&gt;/gi, '<br />')
  html = html.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_match: string, label: string, href: string) => {
    if (!isSafeHref(href)) return label
    return `<a href="${escapeAttribute(href)}" target="_blank" rel="noreferrer">${label}</a>`
  })
  html = html.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/__([^_\n]+)__/g, '<strong>$1</strong>')
  html = html.replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, '<em>$1</em>')
  html = html.replace(/(?<!_)_([^_\n]+)_(?!_)/g, '<em>$1</em>')
  html = html.replace(/~~([^~\n]+)~~/g, '<del>$1</del>')

  return codeTokens.reduce(
    (result, tokenHtml, index) => result.replace(`@@CODETOKEN${index}@@`, tokenHtml),
    html,
  )
}

function splitTableRow(line: string) {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim())
}

function isTableSeparator(line: string, expectedCells?: number) {
  const cells = splitTableRow(line)
  return (
    cells.length >= 2 &&
    (expectedCells == null || cells.length === expectedCells) &&
    cells.every((cell) => /^:?-{3,}:?$/.test(cell))
  )
}

function isTableStart(lines: string[], index: number) {
  const header = splitTableRow(lines[index] || '')
  return (
    header.length >= 2 &&
    /^\|?.+\|.+$/.test((lines[index] || '').trim()) &&
    index + 1 < lines.length &&
    isTableSeparator(lines[index + 1] || '', header.length)
  )
}

function renderMarkdownTable(lines: string[], start: number) {
  const header = splitTableRow(lines[start] || '')
  const body: string[][] = []
  let index = start + 2

  while (index < lines.length) {
    const line = lines[index] || ''
    if (!line.trim() || !line.includes('|')) break
    const row = splitTableRow(line)
    if (row.length !== header.length) break
    body.push(row)
    index += 1
  }

  const thead = `<thead><tr>${header.map((cell) => `<th>${renderInlineMarkdown(cell)}</th>`).join('')}</tr></thead>`
  const tbody = body.length
    ? `<tbody>${body
        .map((row) => `<tr>${row.map((cell) => `<td>${renderInlineMarkdown(cell)}</td>`).join('')}</tr>`)
        .join('')}</tbody>`
    : ''

  return {
    html: `<table>${thead}${tbody}</table>`,
    nextIndex: index,
  }
}

function renderQuote(lines: string[]) {
  const quote = lines
    .join('\n')
    .split(/\n\s*\n/)
    .map((part) => {
      const renderedLines = part
        .trim()
        .split('\n')
        .map((line) => renderInlineMarkdown(line))
        .join('<br />')
      return `<p>${renderedLines}</p>`
    })
    .join('')
  return `<blockquote>${quote}</blockquote>`
}

function shouldBreakParagraph(lines: string[], index: number) {
  const current = lines[index] || ''
  const trimmed = current.trim()
  return (
    /^```/.test(trimmed) ||
    /^(#{1,6})\s+/.test(current) ||
    /^\s{0,3}([-*_])(\s*\1){2,}\s*$/.test(current) ||
    /^\s*>\s?/.test(current) ||
    /^\s*[-*+]\s+/.test(current) ||
    /^\s*\d+\.\s+/.test(current) ||
    isTableStart(lines, index)
  )
}

export function renderMarkdown(value: string) {
  const lines = value.replace(/\r\n/g, '\n').split('\n')
  const blocks: string[] = []
  let index = 0

  while (index < lines.length) {
    const line = lines[index] || ''
    const trimmed = line.trim()

    if (!trimmed) {
      index += 1
      continue
    }

    const codeFence = trimmed.match(/^```([\w-]+)?\s*$/)
    if (codeFence) {
      const codeLines: string[] = []
      index += 1
      while (index < lines.length && !(lines[index] || '').trim().startsWith('```')) {
        codeLines.push(lines[index] || '')
        index += 1
      }
      if (index < lines.length) index += 1
      const language = codeFence[1] ? ` class="language-${escapeAttribute(codeFence[1])}"` : ''
      blocks.push(`<pre><code${language}>${escapeHtml(codeLines.join('\n'))}</code></pre>`)
      continue
    }

    if (isTableStart(lines, index)) {
      const table = renderMarkdownTable(lines, index)
      blocks.push(table.html)
      index = table.nextIndex
      continue
    }

    const heading = line.match(/^(#{1,6})\s+(.+)$/)
    if (heading) {
      const level = heading[1].length
      blocks.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`)
      index += 1
      continue
    }

    if (/^\s{0,3}([-*_])(\s*\1){2,}\s*$/.test(line)) {
      blocks.push('<hr />')
      index += 1
      continue
    }

    if (/^\s*>\s?/.test(line)) {
      const quoteLines: string[] = []
      while (index < lines.length && /^\s*>\s?/.test(lines[index] || '')) {
        quoteLines.push((lines[index] || '').replace(/^\s*>\s?/, ''))
        index += 1
      }
      blocks.push(renderQuote(quoteLines))
      continue
    }

    if (/^\s*[-*+]\s+/.test(line)) {
      const items: string[] = []
      while (index < lines.length && /^\s*[-*+]\s+/.test(lines[index] || '')) {
        items.push(`<li>${renderInlineMarkdown((lines[index] || '').replace(/^\s*[-*+]\s+/, ''))}</li>`)
        index += 1
      }
      blocks.push(`<ul>${items.join('')}</ul>`)
      continue
    }

    if (/^\s*\d+\.\s+/.test(line)) {
      const items: string[] = []
      while (index < lines.length && /^\s*\d+\.\s+/.test(lines[index] || '')) {
        items.push(`<li>${renderInlineMarkdown((lines[index] || '').replace(/^\s*\d+\.\s+/, ''))}</li>`)
        index += 1
      }
      blocks.push(`<ol>${items.join('')}</ol>`)
      continue
    }

    const paragraphLines: string[] = []
    while (index < lines.length) {
      const current = lines[index] || ''
      if (!current.trim()) break
      if (shouldBreakParagraph(lines, index)) break
      paragraphLines.push(current.trim())
      index += 1
    }
    blocks.push(`<p>${renderInlineMarkdown(paragraphLines.join(' '))}</p>`)
  }

  return blocks.join('')
}
