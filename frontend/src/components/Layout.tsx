import { useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import AchievementNote from './AchievementNote'
import styles from './Layout.module.css'

const links = [
  { to: '/', label: 'Сегодня' },
  { to: '/play', label: 'Игра' },
  { to: '/puzzles', label: 'Задачи' },
  { to: '/lessons', label: 'Уроки' },
  { to: '/review', label: 'Разбор партии' },
  { to: '/mistakes', label: 'Колода ошибок' },
  { to: '/profile', label: 'Профиль' },
]

export default function Layout({ login, onLogout }: { login: string; onLogout: () => void }) {
  const [open, setOpen] = useState(false)
  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <button
          type="button"
          className={styles.menuButton}
          aria-label="Меню"
          aria-expanded={open}
          onClick={() => setOpen(!open)}
        >
          ☰
        </button>
        <span className={styles.title}>Шахматный тренер</span>
      </header>
      <nav className={`${styles.nav} ${open ? styles.navOpen : ''}`} aria-label="Разделы">
        {links.map((l) => (
          <NavLink
            key={l.to}
            to={l.to}
            end={l.to === '/'}
            className={({ isActive }) => `${styles.link} ${isActive ? styles.active : ''}`}
            onClick={() => setOpen(false)}
          >
            {l.label}
          </NavLink>
        ))}
        <div className={styles.account}>
          <span className={styles.login}>{login}</span>
          <button type="button" onClick={onLogout}>Выйти</button>
        </div>
      </nav>
      <main className={styles.main}>
        <Outlet />
      </main>
      <AchievementNote />
    </div>
  )
}
