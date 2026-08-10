import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

// Dev mode serves hundreds of individual unbundled ES modules that change on every edit;
// cache-first over that would fight Vite's own HMR instead of helping anyone. Only register
// against a real production build, where the shell is the small bundle it's meant to be.
if ("serviceWorker" in navigator && import.meta.env.PROD) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/service-worker.js");
  });
}
