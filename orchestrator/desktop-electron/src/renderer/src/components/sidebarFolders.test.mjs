import assert from 'node:assert/strict'
import test from 'node:test'
import {
  addSidebarFolder,
  deleteSidebarFolder,
  folderNodeId,
  loadSidebarLayout,
  moveSidebarTab,
  normalizeSidebarLayout,
  saveSidebarLayout,
  sidebarLayoutStorageKey,
  tabNodeId
} from './sidebarFolders.ts'

const KEYS = ['today', 'tasks', 'projects', 'settings']

test('normalizes corrupt layout and appends newly available tabs', () => {
  const layout = normalizeSidebarLayout(
    {
      root: [tabNodeId('today'), tabNodeId('missing'), folderNodeId('work')],
      folders: [
        { id: 'work', name: 'Работа', expanded: false, tabKeys: ['tasks', 'tasks', 'missing'] },
        { id: 'work', name: 'Дубликат', tabKeys: ['projects'] },
        { id: '', name: 'Без id', tabKeys: [] }
      ]
    },
    KEYS
  )

  assert.deepEqual(layout.root, [tabNodeId('today'), folderNodeId('work'), tabNodeId('projects'), tabNodeId('settings')])
  assert.deepEqual(layout.folders, [
    { id: 'work', name: 'Работа', expanded: false, tabKeys: ['tasks'] }
  ])
})

test('moves a tab into a folder and back to the root', () => {
  const initial = addSidebarFolder(normalizeSidebarLayout(null, KEYS), 'Работа', 'work')
  const filed = moveSidebarTab(initial, 'tasks', 'work')

  assert.equal(filed.root.includes(tabNodeId('tasks')), false)
  assert.deepEqual(filed.folders[0].tabKeys, ['tasks'])

  const restored = moveSidebarTab(filed, 'tasks', null)
  assert.deepEqual(restored.folders[0].tabKeys, [])
  assert.equal(restored.root.at(-1), tabNodeId('tasks'))
})

test('deleting a folder restores its tabs at the folder position', () => {
  const initial = {
    version: 1,
    root: [tabNodeId('today'), folderNodeId('work'), tabNodeId('settings')],
    folders: [{ id: 'work', name: 'Работа', expanded: true, tabKeys: ['tasks', 'projects'] }]
  }

  const restored = deleteSidebarFolder(initial, 'work')
  assert.deepEqual(restored.root, [
    tabNodeId('today'),
    tabNodeId('tasks'),
    tabNodeId('projects'),
    tabNodeId('settings')
  ])
  assert.deepEqual(restored.folders, [])
})

test('separates storage by user and navigation scope', () => {
  assert.notEqual(sidebarLayoutStorageKey('user-1', 'user'), sidebarLayoutStorageKey('user-2', 'user'))
  assert.notEqual(
    sidebarLayoutStorageKey('user-1', 'user'),
    sidebarLayoutStorageKey('user-1', 'admin:default')
  )
  assert.notEqual(
    sidebarLayoutStorageKey('user-1', 'admin:default'),
    sidebarLayoutStorageKey('user-1', 'admin:finance')
  )
})

test('restores the saved folder layout from localStorage', () => {
  const values = new Map()
  const previousWindow = globalThis.window
  globalThis.window = {
    localStorage: {
      getItem: (key) => values.get(key) ?? null,
      setItem: (key, value) => values.set(key, value)
    }
  }
  try {
    const initial = addSidebarFolder(normalizeSidebarLayout(null, KEYS), 'Работа', 'work')
    const filed = moveSidebarTab(initial, 'projects', 'work')
    saveSidebarLayout('user-1', 'user', filed)

    assert.deepEqual(loadSidebarLayout('user-1', 'user', KEYS), filed)
    assert.deepEqual(loadSidebarLayout('user-2', 'user', KEYS).folders, [])
  } finally {
    if (previousWindow === undefined) delete globalThis.window
    else globalThis.window = previousWindow
  }
})
