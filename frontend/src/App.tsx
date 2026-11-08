import { useCallback, useEffect, useState } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { logout, me } from './api/auth.ts'
import { setUnauthorizedHandler } from './api/http.ts'
import { setSessionLogin } from './auth/session.ts'
import Layout from './components/Layout.tsx'
import Today from './pages/Today.tsx'
import Play from './pages/Play.tsx'
import Puzzles from './pages/Puzzles.tsx'
import Lessons from './pages/Lessons.tsx'
import Lesson from './pages/Lesson.tsx'
import Review from './pages/Review.tsx'
import Mistakes from './pages/Mistakes.tsx'
import Profile from './pages/Profile.tsx'
import Login from './pages/Login.tsx'
import Admin from './pages/Admin.tsx'
import ModelBench from './pages/ModelBench.tsx'

export default function App() {
  // undefined: not known yet; null: no session.
  const [user, setUser] = useState<string | null | undefined>(undefined)
  const location = useLocation()
  // The device storage key reads the login, so it is set before the pages render.
  const apply = useCallback((login: string | null) => {
    setSessionLogin(login ?? '')
    setUser(login)
  }, [])

  useEffect(() => {
    setUnauthorizedHandler(() => apply(null))
    me().then((r) => apply(r.login), () => apply(null))
    return () => setUnauthorizedHandler(null)
  }, [apply])

  const leave = async () => {
    await logout().catch(() => undefined)
    apply(null)
  }

  const adminArea = location.pathname.startsWith('/admin')
  if (user === undefined && !adminArea && location.pathname !== '/login') return null
  return (
    <Routes>
      <Route path="admin" element={<Admin />} />
      <Route path="admin/bench" element={<ModelBench />} />
      <Route path="login" element={<Login user={user ?? null} onLogin={apply} />} />
      {user ? (
        <Route element={<Layout login={user} onLogout={leave} />}>
          <Route index element={<Today login={user} />} />
          <Route path="play" element={<Play />} />
          <Route path="puzzles" element={<Puzzles />} />
          <Route path="lessons" element={<Lessons />} />
          <Route path="lessons/:slug" element={<Lesson />} />
          <Route path="review" element={<Review />} />
          <Route path="mistakes" element={<Mistakes />} />
          <Route path="profile" element={<Profile />} />
          <Route path="progress" element={<Navigate to="/profile" replace />} />
          <Route path="settings" element={<Navigate to="/profile#settings" replace />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      ) : (
        <Route path="*" element={<Navigate to="/login" replace state={{ from: location }} />} />
      )}
    </Routes>
  )
}
