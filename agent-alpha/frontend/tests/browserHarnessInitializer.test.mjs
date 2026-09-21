import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'
import { after, test } from 'node:test'
import { fileURLToPath } from 'node:url'

const require = createRequire(import.meta.url)
const { ensureBrowserHarness } = require('../desktop/browser-harness-initializer.cjs')

const frontendRoot = path.dirname(path.dirname(fileURLToPath(import.meta.url)))
const testRoot = path.join(path.dirname(frontendRoot), 'temp', `desktop-browser-init-${process.pid}`)

after(() => fs.rmSync(testRoot, { recursive: true, force: true }))

function makeLayout(name, isPackaged = true) {
  const root = path.join(testRoot, name)
  const appRoot = path.join(root, 'app')
  const dataRoot = path.join(root, 'data')
  const layout = {
    isPackaged,
    appRoot,
    dataRoot,
    browserPython: path.join(appRoot, 'runtime', 'browser-python', 'python.exe'),
    browserHarnessExecutable: path.join(dataRoot, 'bin', 'browser-harness.exe'),
    browserHarnessPrefix: path.join(dataRoot, 'runtime', 'browser-harness-launcher', '0.1.13'),
    browserHarnessWheel: path.join(appRoot, 'runtime', 'bootstrap', 'browser_harness-0.1.13-py3-none-any.whl'),
    uv: path.join(appRoot, 'runtime', 'bootstrap', 'uv.exe'),
    uvCache: path.join(dataRoot, 'cache', 'uv', 'browser-harness-bootstrap'),
  }
  for (const file of [layout.browserPython, layout.browserHarnessWheel, layout.uv]) {
    fs.mkdirSync(path.dirname(file), { recursive: true })
    fs.writeFileSync(file, 'fixture')
  }
  return layout
}

test('development mode never initializes or replaces its existing Browser Harness', async () => {
  const layout = makeLayout('development', false)
  let calls = 0

  const result = await ensureBrowserHarness(layout, { run: async () => { calls += 1 } })

  assert.deepEqual(result, { initialized: false, skipped: true })
  assert.equal(calls, 0)
})

test('missing offline material fails before invoking any installer', async () => {
  const layout = makeLayout('missing-wheel')
  fs.unlinkSync(layout.browserHarnessWheel)
  let calls = 0
  await assert.rejects(
    ensureBrowserHarness(layout, { run: async () => { calls += 1 } }),
    /离线安装包/,
  )
  assert.equal(calls, 0)
})

test('failed regeneration reports the failure without overwriting the old executable', async () => {
  const layout = makeLayout('failed-regeneration')
  fs.mkdirSync(path.dirname(layout.browserHarnessExecutable), { recursive: true })
  fs.writeFileSync(layout.browserHarnessExecutable, 'old-executable')
  const run = async (file) => file === layout.uv
    ? { code: 1, stdout: '', stderr: 'disk full' }
    : { code: 0, stdout: '0.0.1', stderr: '' }
  await assert.rejects(ensureBrowserHarness(layout, { run, baseEnv: {} }), /disk full/)
  assert.equal(fs.readFileSync(layout.browserHarnessExecutable, 'utf8'), 'old-executable')
})

test('packaged mode keeps a valid generated executable without running uv again', async () => {
  const layout = makeLayout('already-ready')
  fs.mkdirSync(path.dirname(layout.browserHarnessExecutable), { recursive: true })
  fs.writeFileSync(layout.browserHarnessExecutable, 'existing')
  const calls = []
  const run = async (file, args) => {
    calls.push({ file, args })
    return { code: 0, stdout: '0.1.13\n', stderr: '' }
  }

  const result = await ensureBrowserHarness(layout, { run, baseEnv: {} })

  assert.equal(result.initialized, false)
  assert.equal(calls.length, 1)
  assert.equal(calls[0].file, layout.browserHarnessExecutable)
})

test('packaged mode uses bundled uv offline when the executable is missing', async () => {
  const layout = makeLayout('first-start')
  const calls = []
  const run = async (file, args, options) => {
    calls.push({ file, args, options })
    if (file === layout.uv) {
      const generated = path.join(layout.browserHarnessPrefix, 'Scripts', 'browser-harness.exe')
      fs.mkdirSync(path.dirname(generated), { recursive: true })
      fs.writeFileSync(generated, 'generated')
      return { code: 0, stdout: '', stderr: '' }
    }
    return { code: 0, stdout: '0.1.13\n', stderr: '' }
  }

  const result = await ensureBrowserHarness(layout, { run, baseEnv: { PYTHONPATH: 'host-value' } })

  assert.equal(result.initialized, true)
  assert.equal(fs.readFileSync(layout.browserHarnessExecutable, 'utf8'), 'generated')
  const install = calls.find((call) => call.file === layout.uv)
  assert.ok(install)
  assert.ok(install.args.includes('--offline'))
  assert.ok(install.args.includes('--no-index'))
  assert.ok(install.args.includes('--no-deps'))
  assert.ok(install.args.includes(layout.browserHarnessWheel))
  assert.equal(install.options.env.PYTHONPATH, undefined)
  assert.equal(install.options.env.UV_OFFLINE, '1')
})
