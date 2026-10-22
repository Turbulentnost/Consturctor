import assert from 'node:assert/strict'
import test from 'node:test'
import { bentoColumns, bentoPages } from './newsBento.ts'

function news(pattern) {
  return [...pattern].map((kind, index) => ({ id: `n${index}`, photo: kind === 'p' }))
}

function filled(page, cols) {
  const grid = Array.from({ length: page.rows }, () => Array(cols).fill(0))
  for (const cell of page.cells) {
    for (let r = cell.row; r < cell.row + cell.rowSpan; r += 1) {
      for (let c = cell.col; c < cell.col + cell.colSpan; c += 1) grid[r - 1][c - 1] += 1
    }
  }
  return grid.flat()
}

test('одна новость занимает всю строку', () => {
  const [page] = bentoPages(news('t'), 5)
  assert.equal(page.rows, 1)
  assert.deepEqual(page.cells[0], { id: 'n0', col: 1, row: 1, colSpan: 5, rowSpan: 1, size: 'tile' })
})

test('фото в одну строку шире текстовых карточек', () => {
  const [page] = bentoPages(news('ptt'), 5)
  assert.equal(page.rows, 1)
  assert.equal(page.cells[0].size, 'wide')
  assert.ok(page.cells[0].colSpan > page.cells[1].colSpan)
})

test('не больше двух строк и без пустых клеток при любом наборе', () => {
  for (const pattern of ['t', 'pp', 'tttt', 'pttpt', 'tttttttttt', 'pppppppp', 'tptptptptp', 'ppt']) {
    for (const cols of [1, 2, 3, 4, 5, 6]) {
      const pages = bentoPages(news(pattern), cols)
      const shown = pages.flatMap((page) => page.cells.map((cell) => cell.id))
      assert.deepEqual(shown, news(pattern).map((item) => item.id), `${pattern} × ${cols}`)
      for (const page of pages) {
        assert.ok(page.rows <= 2)
        assert.ok(filled(page, cols).every((count) => count === 1), `${pattern} × ${cols}`)
      }
    }
  }
})

test('десять текстовых новостей на широком экране — одна страница 5×2', () => {
  const pages = bentoPages(news('tttttttttt'), 5)
  assert.equal(pages.length, 1)
  assert.ok(pages[0].cells.every((cell) => cell.size === 'tile' && cell.colSpan === 1))
})

test('фото на две строки становится главной карточкой', () => {
  const [page] = bentoPages(news('pttt'), 4)
  assert.equal(page.cells[0].size, 'hero')
  assert.equal(page.cells[0].rowSpan, 2)
})

test('колонки зависят от ширины', () => {
  assert.equal(bentoColumns(1600), 6)
  assert.equal(bentoColumns(1000), 4)
  assert.equal(bentoColumns(380), 1)
})
