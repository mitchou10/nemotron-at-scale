import { QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { lazy, Suspense, useState } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { Layout } from '@/components/layout'
import { Login } from '@/components/login'
import { useTheme } from '@/hooks/use-theme'
import { ApiError, setToken } from '@/lib/api'

// One chunk per page: the charts (recharts) are only downloaded with the overview.
const OverviewPage = lazy(() => import('@/pages/overview').then((m) => ({ default: m.OverviewPage })))
const WorkersPage = lazy(() => import('@/pages/workers').then((m) => ({ default: m.WorkersPage })))
const SttPage = lazy(() => import('@/pages/stt').then((m) => ({ default: m.SttPage })))
const TtsPage = lazy(() => import('@/pages/tts').then((m) => ({ default: m.TtsPage })))

export default function App() {
  const [locked, setLocked] = useState(false)
  const [rejected, setRejected] = useState(false)
  useTheme()

  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { retry: 1, staleTime: 5_000 } },
        queryCache: new QueryCache({
          onError: (error) => {
            // The backend wants a token (none, or a wrong one): ask for it.
            if (error instanceof ApiError && error.status === 401) {
              setRejected(true)
              setLocked(true)
            }
          },
        }),
      }),
  )

  if (locked) {
    return (
      <Login
        error={rejected}
        onSubmit={(token) => {
          setToken(token)
          setRejected(false)
          setLocked(false)
          void client.invalidateQueries()
        }}
      />
    )
  }

  const logout = () => {
    setToken(null)
    client.clear()
    setRejected(false)
    setLocked(true)
  }

  return (
    <QueryClientProvider client={client}>
      <BrowserRouter>
        <Suspense fallback={null}>
        <Routes>
          <Route element={<Layout onLogout={logout} />}>
            <Route index element={<OverviewPage />} />
            <Route path="workers" element={<WorkersPage />} />
            <Route path="stt" element={<SttPage />} />
            <Route path="tts" element={<TtsPage />} />
            <Route path="*" element={<OverviewPage />} />
          </Route>
        </Routes>
        </Suspense>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
