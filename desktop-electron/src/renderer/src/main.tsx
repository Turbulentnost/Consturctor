import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import './styles.css'

function preventWindowFileOpen(event: DragEvent): void {
  event.preventDefault()
}

window.addEventListener('dragover', preventWindowFileOpen)
window.addEventListener('drop', preventWindowFileOpen)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>
)
