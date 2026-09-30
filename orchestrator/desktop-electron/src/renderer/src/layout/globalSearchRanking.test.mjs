import assert from 'node:assert/strict'
import test from 'node:test'
import { normalizeGlobalSearch, rankGlobalSearch } from './globalSearchRanking.ts'

function entry(overrides) {
  return {
    id: 'base',
    source: 'test',
    pageKey: 'tasks',
    kind: 'entity',
    targetId: 'base',
    title: 'Базовая задача',
    ...overrides
  }
}

test('normalizes case, whitespace and ё', () => {
  assert.equal(normalizeGlobalSearch('  Ёлка  '), 'елка')
})

test('ranks exact and prefix title matches before metadata matches', () => {
  const rows = [
    entry({ id: 'metadata', targetId: 'metadata', title: 'Другое', keywords: ['задача'] }),
    entry({ id: 'prefix', targetId: 'prefix', title: 'Задача на день' }),
    entry({ id: 'exact', targetId: 'exact', title: 'Задача' })
  ]
  assert.deepEqual(
    rankGlobalSearch(rows, 'задача').map((row) => row.id),
    ['exact', 'prefix', 'metadata']
  )
})

test('deduplicates the same navigation target and honors limit', () => {
  const rows = [
    entry({ id: 'first', targetId: 'same', title: 'Задача первая' }),
    entry({ id: 'duplicate', targetId: 'same', title: 'Задача вторая' }),
    entry({ id: 'other', targetId: 'other', title: 'Задача третья' })
  ]
  const deduplicated = rankGlobalSearch(rows, 'задача')
  assert.deepEqual(deduplicated.map((row) => row.targetId), ['same', 'other'])
  assert.equal(rankGlobalSearch(rows, 'задача', 1).length, 1)
})
