import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { AppShell } from '@/components/app-shell'
import './index.css'

const root = document.getElementById('root')
if (!root) throw new Error('The viewer root element is missing.')

createRoot(root).render(
  <StrictMode>
    <AppShell />
  </StrictMode>,
)
