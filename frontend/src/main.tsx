import { createRoot } from 'react-dom/client'
import App from './App.tsx'
import MobileApp from './mobile/MobileApp.tsx'
import './App.css'

const isMobile = window.matchMedia('(max-width: 768px)').matches

createRoot(document.getElementById('root')!).render(isMobile ? <MobileApp /> : <App />)
