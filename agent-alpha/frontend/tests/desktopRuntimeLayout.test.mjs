import assert from 'node:assert/strict'
import path from 'node:path'
import { createRequire } from 'node:module'
import { test } from 'node:test'

const require = createRequire(import.meta.url)
const { buildBackendEnv, resolveRuntimeLayout } = require('../desktop/runtime-layout.cjs')

test('development desktop keeps the existing project layout', () => {
  const frontendRoot = 'D:\\source\\agent-alpha\\frontend'
  const layout = resolveRuntimeLayout({ isPackaged: false, resourcesPath: '', frontendRoot, env: {} })
  const baseEnv = { PATH: 'host-path', CUSTOM: 'kept' }

  assert.equal(layout.isPackaged, false)
  assert.equal(layout.appRoot, path.win32.normalize('D:\\source\\agent-alpha'))
  assert.equal(layout.dataRoot, layout.appRoot)
  assert.equal(layout.python, path.win32.join(layout.appRoot, '.venv', 'Scripts', 'python.exe'))
  assert.deepEqual(buildBackendEnv(layout, baseEnv), baseEnv)
})

test('packaged desktop separates installed resources from local user data', () => {
  const layout = resolveRuntimeLayout({
    isPackaged: true,
    resourcesPath: 'C:\\Program Files\\Agent Alpha\\resources',
    frontendRoot: '',
    env: { LOCALAPPDATA: 'C:\\Users\\person\\AppData\\Local' },
    execPath: 'C:\\Program Files\\Agent Alpha\\Agent Alpha.exe',
  })
  const env = buildBackendEnv(layout, { PATH: 'host-path' })

  assert.equal(layout.dataRoot, path.win32.normalize('C:\\Users\\person\\AppData\\Local\\AgentAlpha'))
  assert.equal(layout.isPackaged, true)
  assert.equal(env.AGENT_ALPHA_APP_ROOT, layout.appRoot)
  assert.equal(env.AGENT_ALPHA_ROOT, layout.dataRoot)
  assert.equal(env.AGENT_ALPHA_PYTHON, layout.python)
  assert.equal(env.AGENT_ALPHA_BROWSER_PYTHON, layout.browserPython)
  assert.equal(env.AGENT_ALPHA_NODE_EXECUTABLE, 'C:\\Program Files\\Agent Alpha\\Agent Alpha.exe')
  assert.equal(layout.browserHarnessExecutable, path.win32.join(layout.dataRoot, 'bin', 'browser-harness.exe'))
  assert.equal(layout.uv, path.win32.join(layout.appRoot, 'runtime', 'bootstrap', 'uv.exe'))
})
