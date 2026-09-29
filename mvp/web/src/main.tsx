import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App'

// After a redeploy, a page loaded from the previous build may ask for a lazy chunk that no longer exists.
// Reload once to pick up the new build instead of leaving a white screen.
window.addEventListener('vite:preloadError', (e) => {
  try {
    if (sessionStorage.getItem('rr-reloaded') === '1') return
    sessionStorage.setItem('rr-reloaded', '1')
  } catch { /* storage blocked: still reload once per load */ }
  e.preventDefault()
  location.reload()
})
window.addEventListener('load', () => setTimeout(() => { try { sessionStorage.removeItem('rr-reloaded') } catch { /* ignore */ } }, 10000))

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
