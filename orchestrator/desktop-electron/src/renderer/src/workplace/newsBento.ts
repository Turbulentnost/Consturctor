/** Bento-сетка новостей «Сегодня»: не больше двух строк, пустых клеток нет. */

export type BentoInput = { id: string; photo: boolean }

/** hero — фото на две строки, wide — фото в одну строку, tall — текст на две строки, tile — текст. */
export type BentoSize = 'hero' | 'wide' | 'tall' | 'tile'

export type BentoCell = {
  id: string
  col: number
  row: number
  colSpan: number
  rowSpan: number
  size: BentoSize
}

export type BentoPage = { rows: 1 | 2; cells: BentoCell[] }

type Block = { width: number; ids: BentoInput[] }

/** До трёх новостей — одна строка во всю ширину, иначе две строки. */
const ONE_ROW_MAX = 3

export function bentoColumns(width: number): number {
  if (width >= 1500) return 6
  if (width >= 1180) return 5
  if (width >= 920) return 4
  if (width >= 660) return 3
  if (width >= 420) return 2
  return 1
}

function widen(blocks: Block[], cols: number): void {
  let extra = cols - blocks.reduce((sum, block) => sum + block.width, 0)
  if (extra <= 0 || !blocks.length) return
  // Место отдаём сначала фото, потом одиночным текстам, потом парам.
  const rank = (block: Block): number => (block.ids[0].photo ? 0 : block.ids.length === 1 ? 1 : 2)
  const order = blocks.map((_, index) => index).sort((a, b) => rank(blocks[a]) - rank(blocks[b]) || a - b)
  for (let step = 0; extra > 0; step += 1) {
    blocks[order[step % order.length]].width += 1
    extra -= 1
  }
}

function place(blocks: Block[], rows: 1 | 2): BentoCell[] {
  const cells: BentoCell[] = []
  let col = 1
  for (const block of blocks) {
    if (block.ids.length === 2) {
      block.ids.forEach((item, index) =>
        cells.push({ id: item.id, col, row: index + 1, colSpan: block.width, rowSpan: 1, size: 'tile' })
      )
    } else {
      const item = block.ids[0]
      const size: BentoSize = item.photo ? (rows === 2 ? 'hero' : 'wide') : rows === 2 ? 'tall' : 'tile'
      cells.push({ id: item.id, col, row: 1, colSpan: block.width, rowSpan: rows, size })
    }
    col += block.width
  }
  return cells
}

export function bentoPages(items: BentoInput[], cols: number): BentoPage[] {
  const width = Math.max(1, cols)
  const photoWidth = Math.min(2, width)
  const baseWidth = (item: BentoInput): number => (item.photo ? photoWidth : 1)
  if (!items.length) return []

  const total = items.reduce((sum, item) => sum + baseWidth(item), 0)
  if (items.length <= ONE_ROW_MAX && total <= width) {
    const blocks = items.map((item) => ({ width: baseWidth(item), ids: [item] }))
    widen(blocks, width)
    return [{ rows: 1, cells: place(blocks, 1) }]
  }

  const pages: BentoPage[] = []
  let index = 0
  while (index < items.length) {
    const blocks: Block[] = []
    let used = 0
    while (index < items.length) {
      const item = items[index]
      const next = items[index + 1]
      const blockWidth = baseWidth(item)
      if (used + blockWidth > width) break
      if (!item.photo && next && !next.photo) {
        blocks.push({ width: 1, ids: [item, next] })
        index += 2
      } else {
        blocks.push({ width: blockWidth, ids: [item] })
        index += 1
      }
      used += blockWidth
    }
    widen(blocks, width)
    pages.push({ rows: 2, cells: place(blocks, 2) })
  }
  return pages
}
