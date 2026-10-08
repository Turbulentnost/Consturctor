import assert from 'node:assert/strict'
import test from 'node:test'
import {
  DEFAULT_QUICK_ACCESS,
  loadQuickAccess,
  loadSidebarCollapsed,
  normalizeQuickAccess,
  quickAccessStorageKey,
  saveQuickAccess,
  saveSidebarCollapsed,
  toggleQuickAccess
} from './sidebarQuickAccess.ts'

const KEYS = ['today', 'tasks', 'mail', 'docflow', 'kpi', 'extensions', 'settings']

function withStorage(run) {
  const data = new Map()
  globalThis.window = {
    localStorage: {
      getItem: (key) => (data.has(key) ? data.get(key) : null),
      setItem: (key, value) => data.set(key, String(value))
    }
  }
  try {
    run(data)
  } finally {
    delete globalThis.window
  }
}

test('defaults to today, docflow, extensions and settings', () => {
  assert.deepEqual(DEFAULT_QUICK_ACCESS, ['today', 'docflow', 'extensions', 'settings'])
  assert.deepEqual(normalizeQuickAccess(undefined, KEYS), ['today', 'docflow', 'extensions', 'settings'])
})

test('keeps menu order and drops unknown keys', () => {
  assert.deepEqual(normalizeQuickAccess(['settings', 'kpi', 'ghost', 'today', 'kpi'], KEYS), ['today', 'kpi', 'settings'])
})

test('toggle adds and removes without losing currently unavailable tabs', () => {
  const stored = ['today', 'ext:report']
  const added = toggleQuickAccess(stored, 'kpi')
  assert.deepEqual(added, ['today', 'ext:report', 'kpi'])
  assert.deepEqual(toggleQuickAccess(added, 'today'), ['ext:report', 'kpi'])
  assert.deepEqual(normalizeQuickAccess(added, KEYS), ['today', 'kpi'])
})

test('choice and collapsed state persist per user', () => {
  withStorage((data) => {
    assert.deepEqual(loadQuickAccess('u1'), DEFAULT_QUICK_ACCESS)
    saveQuickAccess('u1', ['mail'])
    assert.equal(data.get(quickAccessStorageKey('u1')), '["mail"]')
    assert.deepEqual(loadQuickAccess('u1'), ['mail'])
    assert.deepEqual(loadQuickAccess('u2'), DEFAULT_QUICK_ACCESS)

    assert.equal(loadSidebarCollapsed('u1', true), true)
    saveSidebarCollapsed('u1', false)
    assert.equal(loadSidebarCollapsed('u1', true), false)

    data.set(quickAccessStorageKey('u3'), '{broken')
    assert.deepEqual(loadQuickAccess('u3'), DEFAULT_QUICK_ACCESS)
  })
})
