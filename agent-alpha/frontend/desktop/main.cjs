const { app, BrowserWindow, dialog } = require('electron')
const { spawn } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')
const { inspectBackend, shutdownDesktop, stopOwnedBackend } = require('./backend.cjs')

const frontendRoot = path.resolve(__dirname, '..')
const projectRoot = path.resolve(frontendRoot, '..')
const python = path.join(projectRoot, '.venv', 'Scripts', 'python.exe')
const index = path.join(frontendRoot, 'dist', 'index.html')
const icon = path.join(__dirname, 'app.ico')
const url = 'http://127.0.0.1:8787'
let ownedBackend = null
let mainWindow = null
let quitting = false

if (!app.requestSingleInstanceLock()) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (!mainWindow) return
    if (mainWindow.isMinimized()) mainWindow.restore()
    mainWindow.focus()
  })

  app.on('before-quit', (event) => {
    if (quitting) return
    event.preventDefault()
    quitting = true
    shutdownDesktop(url, ownedBackend).finally(() => app.quit())
  })
  app.whenReady().then(start).catch(showStartupError)
}

function showStartupError(error) {
  stopOwnedBackend(ownedBackend)
  dialog.showErrorBox('agent-alpha 启动失败', String(error.message || error))
  app.quit()
}

async function start() {
  if (!fs.existsSync(index)) throw new Error('缺少前端构建文件，请运行 npm run desktop:prepare。')
  if (!fs.existsSync(python)) throw new Error('缺少项目 Python 环境，请先运行 setup-agent-alpha.ps1。')

  const current = await inspectBackend(url, projectRoot)
  if (current === 'foreign') throw new Error('8787 端口已被其他服务占用，请先释放该端口。')
  if (current === 'missing') await startBackend()

  app.setAppUserModelId('agent-alpha.desktop')
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 800,
    minHeight: 600,
    autoHideMenuBar: true,
    icon,
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true },
  })
  mainWindow.webContents.on('will-navigate', (event, nextUrl) => {
    if (nextUrl !== url && !nextUrl.startsWith(`${url}/`)) event.preventDefault()
  })
  mainWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  mainWindow.on('closed', () => { mainWindow = null })
  await mainWindow.loadURL(url)
}

async function startBackend() {
  let startupOutput = ''
  let exited = false
  ownedBackend = spawn(python, ['-m', 'agent.server.app'], {
    cwd: projectRoot,
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  ownedBackend.on('error', (error) => { startupOutput = error.message; exited = true })
  ownedBackend.on('exit', () => { exited = true })
  for (const stream of [ownedBackend.stdout, ownedBackend.stderr]) {
    stream.on('data', (chunk) => { startupOutput = (startupOutput + chunk.toString()).slice(-2000) })
  }

  const deadline = Date.now() + 15000
  while (Date.now() < deadline) {
    const state = await inspectBackend(url, projectRoot)
    if (state === 'same') return
    if (state === 'foreign') throw new Error('8787 端口被其他服务占用。')
    if (exited) break
    await new Promise((resolve) => setTimeout(resolve, 300))
  }
  throw new Error(`后端未能启动。${startupOutput.trim() || '请检查项目 Python 环境。'}`)
}
