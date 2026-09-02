const fs = require('node:fs')
const path = require('node:path')

const electronRoot = path.resolve(__dirname, '..')
const repoRoot = path.resolve(electronRoot, '..', '..')
const runtimeRoot = path.join(electronRoot, '.installer-runtime')

function removeIfExists(target) {
  fs.rmSync(target, { recursive: true, force: true })
}

function copyTree(from, to, filter) {
  if (!fs.existsSync(from)) {
    throw new Error(`Missing installer resource: ${from}`)
  }
  removeIfExists(to)
  fs.cpSync(from, to, {
    recursive: true,
    filter: (src) => {
      const rel = path.relative(from, src).replace(/\\/g, '/')
      return filter ? filter(rel, src) : true
    }
  })
}

function skipCommon(rel) {
  if (!rel) return true
  const parts = rel.split('/')
  const top = parts[0]
  if (parts.includes('__pycache__')) return false
  if (parts.includes('tests')) return false
  if (parts.includes('.pytest_cache')) return false
  if (parts.includes('.mypy_cache')) return false
  if (parts.includes('.ruff_cache')) return false
  if (['build', 'dist', 'release', 'installer', '.venv', 'venv'].includes(top)) return false
  if (rel.endsWith('.pyc')) return false
  if (rel.endsWith('.pyo')) return false
  if (rel.endsWith('.spec')) return false
  return true
}

function skipTools(rel) {
  if (!skipCommon(rel)) return false
  return !rel.split('/').includes('node_modules')
}

exports.default = async function afterSign(context) {
  const resources = path.join(context.appOutDir, 'resources')
  fs.mkdirSync(resources, { recursive: true })

  copyTree(path.join(electronRoot, 'pybridge'), path.join(resources, 'pybridge'), skipCommon)
  copyTree(path.join(repoRoot, 'desktop'), path.join(resources, 'desktop'), skipCommon)
  copyTree(path.join(repoRoot, 'tools'), path.join(resources, 'tools'), skipTools)
  copyTree(path.join(runtimeRoot, 'python'), path.join(resources, 'python'))
  copyTree(path.join(runtimeRoot, 'node'), path.join(resources, 'node'))

  const playwrightSource = path.join(runtimeRoot, 'ms-playwright')
  if (fs.existsSync(playwrightSource)) {
    copyTree(playwrightSource, path.join(resources, 'desktop', 'ms-playwright'))
  }

  console.log('installer runtime resources copied after signing')
}
