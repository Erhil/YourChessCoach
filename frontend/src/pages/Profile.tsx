import { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { getAchievements, getActivity, type Achievements, type Activity } from '../api/activity'
import { getNextMistake, type NextMistake } from '../api/mistakes'
import { getProgress, type Progress } from '../api/progress'
import { sessionLogin } from '../auth/session'
import EarnedAchievements from '../components/EarnedAchievements'
import NextAchievements from '../components/NextAchievements'
import Summary from '../components/profile/Summary'
import { ProgressView } from '../components/ProgressView'
import SettingsSection from '../components/SettingsSection'
import WeeksSummary from '../components/WeeksSummary'

/** «Профиль»: the summary, the details and the settings (`#settings`). */
export default function Profile() {
  const [d, setD] = useState<Progress | null>(null)
  const [error, setError] = useState(false)
  // undefined: loading; null: the request failed (the rest of the page still shows).
  const [activity, setActivity] = useState<Activity | null>()
  const [ach, setAch] = useState<Achievements | null>()
  const [next, setNext] = useState<NextMistake | null>()
  const [loaded, setLoaded] = useState(false)
  const { hash } = useLocation()
  useEffect(() => {
    const no = () => null
    Promise.allSettled([
      getProgress().then(setD, () => setError(true)),
      getActivity().then(setActivity, () => setActivity(no)),
      getAchievements().then(setAch, () => setAch(no)),
      getNextMistake().then(setNext, () => setNext(no)),
    ]).then(() => setLoaded(true))
  }, [])
  // All the blocks above the settings change their height while they load: scroll once, after all the requests.
  useEffect(() => {
    if (loaded && hash === '#settings') document.getElementById('settings')?.scrollIntoView()
  }, [hash, loaded])

  return (
    <>
      <h1>Профиль</h1>
      <p className="muted">{sessionLogin()}</p>
      {error && <p>Не удалось загрузить прогресс.</p>}
      {!d && !error && <p className="muted">Загружаю прогресс…</p>}
      {d && (
        <>
          <Summary d={d} activity={activity} ach={ach} next={next} />
          <h2>Подробности</h2>
          {d.weeks && <WeeksSummary weeks={d.weeks} />}
          {ach && (
            <>
              <EarnedAchievements items={ach.earned} />
              <NextAchievements items={ach.next} />
            </>
          )}
          <ProgressView d={d} chartTitle="График рейтинга" />
        </>
      )}
      <SettingsSection />
    </>
  )
}
