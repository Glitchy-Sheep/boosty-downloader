import { QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from '@tanstack/react-router'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { createQueryClient } from '@/lib/queries'
import { createViewerRouter } from '@/router'
import './index.css'

const root = document.getElementById('root')
if (!root) throw new Error('The viewer root element is missing.')
const queryClient = createQueryClient()
const router = createViewerRouter(queryClient)

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
)
