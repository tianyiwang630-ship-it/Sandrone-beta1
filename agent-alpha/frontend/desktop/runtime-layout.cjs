const path = require('node:path')

function resolveRuntimeLayout({ isPackaged, resourcesPath, frontendRoot, env = process.env, execPath = process.execPath }) {
  if (!isPackaged) {
    const appRoot = path.resolve(frontendRoot, '..')
    return {
      isPackaged: false,
      appRoot,
      dataRoot: appRoot,
      python: path.join(appRoot, '.venv', 'Scripts', 'python.exe'),
      browserPython: path.join(appRoot, 'tools', 'uv', 'browser-harness', 'Scripts', 'python.exe'),
      browserHarnessExecutable: path.join(appRoot, 'bin', 'browser-harness.exe'),
      openWebsearchEntry: '',
      icon: path.join(frontendRoot, 'desktop', 'app.ico'),
      frontendIndex: path.join(frontendRoot, 'dist', 'index.html'),
    }
  }

  const appRoot = path.join(resourcesPath, 'agent-alpha')
  const localAppData = env.LOCALAPPDATA || path.dirname(env.APPDATA || resourcesPath)
  const dataRoot = path.join(localAppData, 'AgentAlpha')
  return {
    isPackaged: true,
    appRoot,
    dataRoot,
    python: path.join(appRoot, 'runtime', 'backend-python', 'python.exe'),
    browserPython: path.join(appRoot, 'runtime', 'browser-python', 'python.exe'),
    browserHarnessExecutable: path.join(dataRoot, 'bin', 'browser-harness.exe'),
    browserHarnessPrefix: path.join(dataRoot, 'runtime', 'browser-harness-launcher', '0.1.13'),
    browserHarnessWheel: path.join(appRoot, 'runtime', 'bootstrap', 'browser_harness-0.1.13-py3-none-any.whl'),
    uv: path.join(appRoot, 'runtime', 'bootstrap', 'uv.exe'),
    uvCache: path.join(dataRoot, 'cache', 'uv', 'browser-harness-bootstrap'),
    openWebsearchEntry: path.join(appRoot, 'runtime', 'mcp', 'open-websearch-entry.cjs'),
    icon: path.join(resourcesPath, 'app.ico'),
    frontendIndex: path.join(appRoot, 'frontend', 'dist', 'index.html'),
    nodeExecutable: execPath,
  }
}

function buildBackendEnv(layout, baseEnv = process.env) {
  if (!layout.isPackaged) return { ...baseEnv }
  return {
    ...baseEnv,
    AGENT_ALPHA_APP_ROOT: layout.appRoot,
    AGENT_ALPHA_ROOT: layout.dataRoot,
    AGENT_ALPHA_PYTHON: layout.python,
    AGENT_ALPHA_BROWSER_PYTHON: layout.browserPython,
    ...(layout.nodeExecutable ? { AGENT_ALPHA_NODE_EXECUTABLE: layout.nodeExecutable } : {}),
    ...(layout.openWebsearchEntry ? { AGENT_ALPHA_OPEN_WEBSEARCH_ENTRY: layout.openWebsearchEntry } : {}),
    PYTHONUTF8: '1',
    PYTHONIOENCODING: 'utf-8',
  }
}

module.exports = { buildBackendEnv, resolveRuntimeLayout }
