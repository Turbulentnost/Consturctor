const ENCODED_WORD = /=\?([^?]+)\?([bqBQ])\?([\s\S]*?)\?=/g

function charsetName(raw: string): string {
  const name = raw.trim().toLowerCase()
  if (name === 'utf8') return 'utf-8'
  if (name === 'cp1251' || name === 'windows1251') return 'windows-1251'
  if (name === 'koi8r') return 'koi8-r'
  return name || 'utf-8'
}

function bytesFromBase64(text: string): Uint8Array {
  const binary = atob(text.replace(/\s/g, ''))
  const out = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i += 1) out[i] = binary.charCodeAt(i)
  return out
}

function bytesFromQuoted(text: string): Uint8Array {
  const bytes: number[] = []
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i]
    if (ch === '_') {
      bytes.push(0x20)
      continue
    }
    if (ch === '=' && i + 2 < text.length) {
      const hex = text.slice(i + 1, i + 3)
      if (/^[0-9A-Fa-f]{2}$/.test(hex)) {
        bytes.push(Number.parseInt(hex, 16))
        i += 2
        continue
      }
    }
    bytes.push(ch.charCodeAt(0) & 0xff)
  }
  return Uint8Array.from(bytes)
}

/** RFC 2047: =?utf-8?Q?...?= и =?utf-8?B?...?= → обычный текст. */
export function decodeMimeHeader(value: string): string {
  const raw = value ?? ''
  if (!raw.includes('=?')) return raw
  const collapsed = raw.replace(/\?=\s+=\?/g, '?==?')
  return collapsed.replace(ENCODED_WORD, (whole, charset, encoding, text) => {
    try {
      const bytes =
        String(encoding).toUpperCase() === 'B'
          ? bytesFromBase64(String(text))
          : bytesFromQuoted(String(text))
      return new TextDecoder(charsetName(String(charset)), { fatal: false }).decode(bytes)
    } catch {
      return whole
    }
  })
}
