import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { test } from 'node:test'

const require = createRequire(import.meta.url)
const { inspectBackend, shutdownBrowser, shutdownDesktop, stopOwnedBackend } = require('../desktop/backend.cjs')
const root = 'D:\\files\\demo\\agent-alpha'

test('reuses only a healthy backend from the same project', async () => {
  const same = await inspectBackend('http://127.0.0.1:8787', root, async () => ({
    ok: true,
    json: async () => ({ ok: true, project_root: 'd:\\FILES\\demo\\agent-alpha' }),
  }))
  assert.equal(same, 'same')

  const other = await inspectBackend('http://127.0.0.1:8787', root, async () => ({
    ok: true,
    json: async () => ({ ok: true, project_root: 'D:\\files\\demo\\other' }),
  }))
  assert.equal(other, 'foreign')
})

test('does not treat a reachable non-alpha server as a free port', async () => {
  assert.equal(await inspectBackend('', root, async () => ({ ok: false })), 'foreign')
  assert.equal(await inspectBackend('', root, async () => ({ ok: true, json: async () => ({ ok: false }) })), 'foreign')
  assert.equal(await inspectBackend('', root, async () => ({ ok: true, json: async () => { throw new Error('bad JSON') } })), 'foreign')
  assert.equal(await inspectBackend('', root, async () => { throw new Error('connection refused') }, async () => false), 'missing')
  assert.equal(await inspectBackend('', root, async () => { throw new Error('health timed out') }, async () => true), 'foreign')
})

test('stops only a live backend owned by the Electron process', () => {
  let killed = 0
  const child = { exitCode: null, killed: false, kill() { killed += 1; this.killed = true } }
  stopOwnedBackend(null)
  stopOwnedBackend(child)
  stopOwnedBackend(child)
  assert.equal(killed, 1)
  stopOwnedBackend({ exitCode: 0, killed: false, kill() { throw new Error('already exited') } })
})

test('requests browser cleanup through the backend runtime API', async () => {
  const calls = []
  const stopped = await shutdownBrowser('http://127.0.0.1:8787', async (url, options) => {
    calls.push({ url, options })
    return { ok: true, json: async () => ({ success: true }) }
  })

  assert.equal(stopped, true)
  assert.equal(calls[0].url, 'http://127.0.0.1:8787/api/runtime/browser')
  assert.equal(calls[0].options.method, 'DELETE')
  assert.ok(calls[0].options.signal)
})

test('still stops only the owned backend when browser cleanup fails', async () => {
  let killed = 0
  const child = { exitCode: null, killed: false, kill() { killed += 1; this.killed = true } }

  const stopped = await shutdownDesktop('', child, async () => { throw new Error('offline') })

  assert.equal(stopped, false)
  assert.equal(killed, 1)
})

test('does not control an external backend or its browser', async () => {
  let requests = 0

  const stopped = await shutdownDesktop('', null, async () => {
    requests += 1
    return { ok: true, json: async () => ({ success: true }) }
  })

  assert.equal(stopped, false)
  assert.equal(requests, 0)
})

test('desktop exit is bounded even when the backend ignores cancellation', async () => {
  let killed = false
  const child = { exitCode: null, killed: false, kill() { killed = true } }
  const start = Date.now()
  assert.equal(await shutdownDesktop('', child, () => new Promise(() => {}), 20), false)
  assert.equal(killed, true)
  assert.ok(Date.now() - start < 1000)
})

test('treats an unsuccessful cleanup result as a failed shutdown', async () => {
  const stopped = await shutdownBrowser('', async () => ({
    ok: true,
    json: async () => ({ success: false, stage: 'shutdown' }),
  }))

  assert.equal(stopped, false)
})
