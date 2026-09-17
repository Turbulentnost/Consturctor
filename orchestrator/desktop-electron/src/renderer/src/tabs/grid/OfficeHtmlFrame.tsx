import { useMemo } from 'react'

function htmlFromDataUrl(dataUrl: string): string {
  if (dataUrl.startsWith('data:text/html;charset=utf-8,')) {
    return decodeURIComponent(dataUrl.slice('data:text/html;charset=utf-8,'.length))
  }
  if (dataUrl.startsWith('data:text/html,')) {
    return decodeURIComponent(dataUrl.slice('data:text/html,'.length))
  }
  return ''
}

export function OfficeHtmlFrame({
  dataUrl,
  className
}: {
  dataUrl: string
  className?: string
}): React.JSX.Element {
  const html = useMemo(() => htmlFromDataUrl(dataUrl), [dataUrl])
  if (html) {
    return <iframe className={className} title="Файл" srcDoc={html} sandbox="" />
  }
  return <iframe className={className} title="Файл" src={dataUrl} sandbox="" />
}
