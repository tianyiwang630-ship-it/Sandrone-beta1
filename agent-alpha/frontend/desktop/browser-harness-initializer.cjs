const { spawn } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')

const BROWSER_HARNESS_VERSION = '0.1.13'

function cleanPythonEnv(baseEnv) {
  const env = { ...baseEnv }
  for (const key of [
    'PYTHONHOME',
    'PYTHONPATH',
    'VIRTUAL_ENV',
    'CONDA_PREFIX',
    'CONDA_DEFAULT_ENV',
    'CONDA_PROMPT_MODIFIER',
  ]) delete env[key]
  env.PYTHONUTF8 = '1'
  env.PYTHONIOENCODING = 'utf-8'
  env.PYTHONNOUSERSITE = '1'
  env.UV_OFFLINE = '1'
  env.UV_PYTHON_DOWNLOADS = 'never'
  return env
}

function runCommand(file, args, { cwd, env, timeoutMs = 30000 } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(file, args, {
      cwd,
      env,
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
    })
    let stdout = ''
    let stderr = ''
    let settled = false
    const finish = (callback) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      callback()
    }
    const timer = setTimeout(() => {
      child.kill()
      finish(() => reject(new Error('Browser Harness 初始化超时。')))
    }, timeoutMs)
    child.stdout.on('data', (chunk) => { stdout = (stdout + chunk.toString()).slice(-4000) })
    child.stderr.on('data', (chunk) => { stderr = (stderr + chunk.toString()).slice(-4000) })
    child.once('error', (error) => finish(() => reject(error)))
    child.once('exit', (code) => finish(() => resolve({ code, stdout, stderr })))
  })
}

async function installedVersion(executable, run, env) {
  if (!fs.existsSync(executable)) return null
  try {
    const result = await run(executable, ['--version'], { env, timeoutMs: 10000 })
    return result.code === 0 ? result.stdout.trim() : null
  } catch {
    return null
  }
}

async function ensureBrowserHarness(layout, { run = runCommand, baseEnv = process.env } = {}) {
  if (!layout.isPackaged) return { initialized: false, skipped: true }

  for (const [label, requiredPath] of [
    ['uv', layout.uv],
    ['Browser Harness Python', layout.browserPython],
    ['Browser Harness 离线安装包', layout.browserHarnessWheel],
  ]) {
    if (!fs.existsSync(requiredPath)) throw new Error(`缺少${label}：${requiredPath}`)
  }

  const env = cleanPythonEnv(baseEnv)
  const currentVersion = await installedVersion(layout.browserHarnessExecutable, run, env)
  if (currentVersion === BROWSER_HARNESS_VERSION) {
    return { initialized: false, executable: layout.browserHarnessExecutable }
  }

  fs.mkdirSync(layout.browserHarnessPrefix, { recursive: true })
  fs.mkdirSync(path.dirname(layout.browserHarnessExecutable), { recursive: true })
  fs.mkdirSync(layout.uvCache, { recursive: true })

  const result = await run(layout.uv, [
    'pip',
    'install',
    '--offline',
    '--no-index',
    '--no-deps',
    '--reinstall',
    '--link-mode',
    'copy',
    '--cache-dir',
    layout.uvCache,
    '--prefix',
    layout.browserHarnessPrefix,
    '--python',
    layout.browserPython,
    layout.browserHarnessWheel,
  ], {
    cwd: layout.dataRoot,
    env,
    timeoutMs: 60000,
  })
  if (result.code !== 0) {
    throw new Error(`Browser Harness 初始化失败：${(result.stderr || result.stdout).trim() || `退出码 ${result.code}`}`)
  }

  const generated = path.join(layout.browserHarnessPrefix, 'Scripts', 'browser-harness.exe')
  if (!fs.existsSync(generated)) throw new Error('uv 已完成，但没有生成 browser-harness.exe。')
  fs.copyFileSync(generated, layout.browserHarnessExecutable)

  const installed = await installedVersion(layout.browserHarnessExecutable, run, env)
  if (installed !== BROWSER_HARNESS_VERSION) {
    throw new Error(`Browser Harness 初始化后的版本不正确：${installed || '无法读取版本'}。`)
  }
  return { initialized: true, executable: layout.browserHarnessExecutable }
}

module.exports = {
  BROWSER_HARNESS_VERSION,
  cleanPythonEnv,
  ensureBrowserHarness,
  runCommand,
}
