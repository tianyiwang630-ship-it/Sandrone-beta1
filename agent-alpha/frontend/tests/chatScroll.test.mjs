import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import test from 'node:test'
import ts from 'typescript'

import {
  clampScrollTop,
  isCurrentSessionRequest,
  readSessionScrollTop,
  removeSessionScrollTop,
  scrollContainerToElement,
  withoutSession,
  writeSessionScrollTop,
} from '../src/chatScroll.ts'

const memoryStorage = () => {
  const values = new Map()
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  }
}

// Execute the production loader with a deferred API, without a browser or real sessions.
const appSource = ts.createSourceFile('App.tsx', readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
let detailLoaderSource
const findDetailLoader = (node) => {
  if (ts.isVariableDeclaration(node) && node.name.getText(appSource) === 'loadSessionDetail') {
    detailLoaderSource = node.initializer.getText(appSource)
  }
  ts.forEachChild(node, findDetailLoader)
}
findDetailLoader(appSource)
assert.ok(detailLoaderSource, 'production session loader must be present')
const detailLoaderCode = ts.transpileModule(`const loadSessionDetail = ${detailLoaderSource}; exports.load = loadSessionDetail;`, {
  compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS },
}).outputText

const deferredDetailRefresh = () => {
  let resolveRequest
  const request = new Promise((resolve) => { resolveRequest = resolve })
  const stream = { scrollTop: 120 }
  const selected = { current: 'a' }
  const pending = { current: null }
  const positions = { current: { a: 600 } }
  let displayedDetail
  const context = {
    exports: {}, selectedSessionId: 'a', selectedSessionIdRef: selected,
    api: { getSession: () => request },
    latestDetailRequestBySessionRef: { current: {} },
    scrollPositionsRef: positions, pendingScrollRestoreRef: pending,
    finalizingRunsRef: { current: new Set() }, deletedSessionIdsRef: { current: new Set() },
    captureSessionScroll: (sessionId) => {
      positions.current[sessionId] = stream.scrollTop
      return stream.scrollTop
    },
    localStorageOrNull: () => null, readSessionScrollTop, isCurrentSessionRequest,
    setSessionDetail: (detail) => { displayedDetail = detail },
  }
  runInNewContext(detailLoaderCode, context)
  return { load: context.exports.load, resolveRequest, stream, selected, pending, get displayedDetail() { return displayedDetail } }
}

test('a refresh preserves navigation or manual scrolling performed while its API request is pending', async () => {
  for (const latestTop of [860, 0]) {
    const refresh = deferredDetailRefresh()
    const loading = refresh.load('a', { preserveScroll: true })
    assert.equal(refresh.pending.current, null)
    refresh.stream.scrollTop = latestTop
    refresh.resolveRequest({ id: 'a', messages: [] })
    await loading
    assert.equal(refresh.pending.current.scrollTop, latestTop)
  }
})

test('switching sessions still restores its saved position instead of the previous visible session position', async () => {
  const refresh = deferredDetailRefresh()
  const loading = refresh.load('a', { restoreStoredScroll: true, preserveScroll: true })
  refresh.stream.scrollTop = 80
  refresh.resolveRequest({ id: 'a', messages: [] })
  await loading
  assert.equal(refresh.pending.current.scrollTop, 600)
})

test('a refresh for a session that was left cannot restore scrolling or replace the visible detail', async () => {
  const refresh = deferredDetailRefresh()
  const loading = refresh.load('a', { preserveScroll: true })
  refresh.selected.current = 'b'
  refresh.stream.scrollTop = 400
  refresh.resolveRequest({ id: 'a', messages: [] })
  assert.equal(await loading, null)
  assert.equal(refresh.pending.current, null)
  assert.equal(refresh.displayedDetail, undefined)
})

test('each session keeps an independent position, including an explicit top position', () => {
  const storage = memoryStorage()
  writeSessionScrollTop(storage, 'long', 1280.5)
  writeSessionScrollTop(storage, 'short', 0)

  assert.equal(readSessionScrollTop(storage, 'long'), 1280.5)
  assert.equal(readSessionScrollTop(storage, 'short'), 0)
})

test('restored positions are clamped only when the rendered session is shorter', () => {
  assert.equal(clampScrollTop(800, 2000, 600), 800)
  assert.equal(clampScrollTop(800, 500, 600), 0)
  assert.equal(clampScrollTop(800, 1000, 600), 400)
})

test('turn navigation scrolls the message stream itself and accounts for its border', () => {
  let scrollRequest
  const container = {
    scrollTop: 240,
    clientTop: 2,
    getBoundingClientRect: () => ({ top: 80 }),
    scrollTo: (request) => { scrollRequest = request },
  }
  const target = { getBoundingClientRect: () => ({ top: 530 }) }

  scrollContainerToElement(container, target)

  assert.deepEqual(scrollRequest, { top: 688, behavior: 'auto' })
})

test('turn navigation clamps a target above the start of the message stream', () => {
  let scrollRequest
  const container = {
    scrollTop: 0,
    clientTop: 1,
    getBoundingClientRect: () => ({ top: 100 }),
    scrollTo: (request) => { scrollRequest = request },
  }

  scrollContainerToElement(container, { getBoundingClientRect: () => ({ top: 90 }) })

  assert.deepEqual(scrollRequest, { top: 0, behavior: 'auto' })
})

test('corrupt, negative, infinite and unavailable storage safely fall back to top', () => {
  const corruptStorage = {
    getItem: () => '{not-json',
    setItem: () => { throw new Error('blocked') },
    removeItem: () => { throw new Error('blocked') },
  }
  assert.equal(readSessionScrollTop(corruptStorage, 'broken'), 0)
  assert.equal(readSessionScrollTop(null, 'missing'), 0)

  const storage = memoryStorage()
  writeSessionScrollTop(storage, 'negative', -1)
  writeSessionScrollTop(storage, 'infinite', Number.POSITIVE_INFINITY)
  assert.equal(readSessionScrollTop(storage, 'negative'), 0)
  assert.equal(readSessionScrollTop(storage, 'infinite'), 0)
  assert.doesNotThrow(() => writeSessionScrollTop(corruptStorage, 'blocked', 10))
  assert.doesNotThrow(() => removeSessionScrollTop(corruptStorage, 'blocked'))
})

test('deleting a session clears both persisted and in-memory state without touching neighbours', () => {
  const storage = memoryStorage()
  writeSessionScrollTop(storage, 'a', 10)
  writeSessionScrollTop(storage, 'b', 20)
  removeSessionScrollTop(storage, 'a')

  const positions = withoutSession({ a: 10, b: 20 }, 'a')
  assert.equal(readSessionScrollTop(storage, 'a'), 0)
  assert.equal(readSessionScrollTop(storage, 'b'), 20)
  assert.deepEqual(positions, { b: 20 })
})

test('a stale detail response cannot replace a newer request or another session', () => {
  assert.equal(isCurrentSessionRequest('a', 'a', 3, 3), true)
  assert.equal(isCurrentSessionRequest('a', 'a', 3, 2), false)
  assert.equal(isCurrentSessionRequest('b', 'a', 3, 3), false)
})

test('appended content never changes the saved top even when it was the old bottom', () => {
  const savedTop = 400
  assert.equal(clampScrollTop(savedTop, 1000, 600), 400)
  assert.equal(clampScrollTop(savedTop, 1800, 600), 400)
})

test('atomic handoff removes the live run from the render state without disturbing other sessions', () => {
  const running = withoutSession({ a: { requestId: 'done' }, b: { requestId: 'active' } }, 'a')
  assert.deepEqual(running, { b: { requestId: 'active' } })
})
