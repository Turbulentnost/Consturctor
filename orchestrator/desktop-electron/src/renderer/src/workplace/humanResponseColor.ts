/** Smooth color for human response wait time (minutes).
 * 1 → green, 30 → yellow, 60 → red; linear per minute between anchors.
 */

type Rgb = readonly [number, number, number]

const GREEN: Rgb = [8, 116, 95] // #08745f
const YELLOW: Rgb = [230, 168, 23] // #e6a817
const RED: Rgb = [198, 40, 40] // #c62828

function lerp(a: number, b: number, t: number): number {
  return Math.round(a + (b - a) * t)
}

function lerpRgb(from: Rgb, to: Rgb, t: number): Rgb {
  const x = Math.min(1, Math.max(0, t))
  return [lerp(from[0], to[0], x), lerp(from[1], to[1], x), lerp(from[2], to[2], x)]
}

function toCss(rgb: Rgb): string {
  return `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`
}

/** CSS color for elapsed human response minutes. */
export function humanResponseDelayColor(minutes: number): string {
  const m = Number.isFinite(minutes) ? Math.max(0, minutes) : 0
  if (m <= 1) return toCss(GREEN)
  if (m >= 60) return toCss(RED)
  if (m <= 30) {
    // 1 → 30: green → yellow (per minute)
    return toCss(lerpRgb(GREEN, YELLOW, (m - 1) / 29))
  }
  // 30 → 60: yellow → red (per minute)
  return toCss(lerpRgb(YELLOW, RED, (m - 30) / 30))
}

/** Discrete band for className fallbacks (cards with green/orange/red themes). */
export function humanResponseDelayBand(minutes: number): 'green' | 'orange' | 'red' {
  const m = Number.isFinite(minutes) ? Math.max(0, minutes) : 0
  if (m <= 20) return 'green'
  if (m < 45) return 'orange'
  return 'red'
}
