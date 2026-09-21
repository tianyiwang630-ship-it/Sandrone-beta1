const path = require('node:path')
const { pathToFileURL } = require('node:url')

const entry = path.join(__dirname, 'node_modules', 'open-websearch', 'build', 'index.js')
import(pathToFileURL(entry).href).catch((error) => {
  process.stderr.write(`${error?.stack || error}\n`)
  process.exitCode = 1
})
