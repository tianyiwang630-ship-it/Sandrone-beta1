import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const styles = readFileSync(new URL('../src/styles.css', import.meta.url), 'utf8')

test('long conversation titles stay on one line inside the fixed top bar', () => {
  assert.match(styles, /\.topbar\s*{[^}]*display:\s*grid;[^}]*grid-template-columns:\s*minmax\(0, 1fr\) auto;/s)
  assert.match(styles, /\.topbar > :first-child\s*{[^}]*min-width:\s*0;[^}]*overflow:\s*hidden;/s)
  assert.match(styles, /\.topbar h1\s*{[^}]*overflow:\s*hidden;[^}]*text-overflow:\s*ellipsis;[^}]*white-space:\s*nowrap;/s)
})

test('expanded tool details keep vertical rows at their content height', () => {
  assert.match(styles, /\.tool-call-details\s*{[^}]*display:\s*flex;[^}]*flex-direction:\s*column;/s)
  assert.match(styles, /\.tool-call-section,\s*\.tool-output-orphan\s*{[^}]*display:\s*flex;[^}]*flex-direction:\s*column;/s)
})

test('user messages use Codex neutral colors and the system chat font', () => {
  assert.match(styles, /\.message\.user\s*{[^}]*background:\s*#f0f0f0;[^}]*border-color:\s*#e2e2e2;/s)
  assert.match(styles, /\.user-message-content\s*{[^}]*font-family:\s*inherit;[^}]*font-size:\s*var\(--chat-font-size\);/s)
})
