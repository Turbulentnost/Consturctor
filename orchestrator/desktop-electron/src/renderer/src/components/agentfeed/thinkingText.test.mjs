import assert from 'node:assert/strict'
import test from 'node:test'
import { streamDelta } from './thinkingText.ts'

function stream(chunks) {
  return chunks.reduce((text, chunk) => text + streamDelta(text, chunk), '')
}

test('short deltas already seen earlier in the text are kept', () => {
  const answer = 'За период 01.01.2026—16.10.2026. П.1 Карташова: не подтверждено, задача у исполнителя.'
  const chunks = answer.match(/.{1,3}/gsu)
  assert.equal(stream(chunks), answer)
})

test('cumulative snapshots are not duplicated', () => {
  assert.equal(stream(['Открытых ', 'Открытых поручений 15', 'Открытых поручений 15.']), 'Открытых поручений 15.')
})

test('a replayed long piece is dropped', () => {
  const head = 'Открытых поручений за период — 16. У АСТ00-00110 появились новые файлы.'
  assert.equal(stream([head, head.slice(10)]), head)
})

test('a replayed tail is trimmed to the new part', () => {
  const head = 'Вложения сверены: извещения СТО подписаны, обучения нет.'
  const tail = head.slice(-40)
  assert.equal(stream([head, `${tail} Сохраняю отчёт.`]), `${head} Сохраняю отчёт.`)
})
