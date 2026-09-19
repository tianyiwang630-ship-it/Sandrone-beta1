const path = require('node:path')
const net = require('node:net')

function sameProjectRoot(actual, expected) {
  if (typeof actual !== 'string') return false
  return path.win32.normalize(actual).toLowerCase() === path.win32.normalize(expected).toLowerCase()
}

function portOccupied(url) {
  const address = new URL(url)
  return new Promise((resolve) => {
    const socket = net.connect(Number(address.port), address.hostname)
    let settled = false
    const finish = (occupied) => {
      if (settled) return
      settled = true
      socket.destroy()
      resolve(occupied)
    }
    socket.setTimeout(500)
    socket.once('connect', () => finish(true))
    socket.once('error', () => finish(false))
    socket.once('timeout', () => finish(false))
  })
}

async function inspectBackend(url, projectRoot, fetchHealth = fetch, checkPort = portOccupied) {
  let response
  try {
    response = await fetchHealth(`${url}/api/health`, { signal: AbortSignal.timeout(1000) })
  } catch {
    return (await checkPort(url)) ? 'foreign' : 'missing'
  }
  if (!response.ok) return 'foreign'
  try {
    const health = await response.json()
    return health.ok === true && sameProjectRoot(health.project_root, projectRoot) ? 'same' : 'foreign'
  } catch {
    return 'foreign'
  }
}

function stopOwnedBackend(child) {
  if (child && child.exitCode === null && !child.killed) child.kill()
}

async function shutdownBrowser(url, fetchShutdown = fetch, timeoutMs = 30000) {
  try {
    const response = await fetchShutdown(`${url}/api/runtime/browser`, {
      method: 'DELETE',
      signal: AbortSignal.timeout(timeoutMs),
    })
    if (!response.ok) return false
    const result = await response.json()
    return result.success === true
  } catch {
    return false
  }
}

async function shutdownDesktop(url, child, fetchShutdown = fetch, timeoutMs = 1000) {
  if (!child) return false
  let stopped = false
  let timer
  try {
    stopped = await Promise.race([
      (async () => {
        const response = await fetchShutdown(`${url}/api/runtime/executions`, {
          method: 'DELETE', signal: AbortSignal.timeout(timeoutMs),
        })
        return response.ok && (await response.json()).success === true
      })(),
      new Promise((resolve) => { timer = setTimeout(() => resolve(false), timeoutMs) }),
    ])
  } catch {
    // The host's Job handle also covers an unresponsive backend and browsers.
  } finally {
    clearTimeout(timer)
    stopOwnedBackend(child)
  }
  return stopped
}

module.exports = { inspectBackend, shutdownBrowser, shutdownDesktop, stopOwnedBackend }
