import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getActivity, setWeekGoal, type Activity } from '../api/activity.ts'
import { getLessons, getPuzzleThemes, type LessonSummary, type PuzzleTheme } from '../api/client.ts'
import { getPlan, planLesson, type Plan } from '../api/mcp.ts'
import { getPuzzleOpenings, type PuzzleOpening } from '../api/openings.ts'
import { getProgress, type Progress } from '../api/progress.ts'
import DailyTasks from '../components/DailyTasks.tsx'
import NextAchievements from '../components/NextAchievements.tsx'
import PlanBlock, { nameOf } from '../components/PlanBlock.tsx'
import Training from '../components/Training.tsx'
import WeekBlock from '../components/WeekBlock.tsx'
import tcss from '../components/Today.module.css'
import { nextLesson } from '../lessons/nextLesson.ts'
import { candidates, dailyTasks, focusTheme, loadSwap, storeSwap, type Swap, type Task } from '../today/dailyTasks.ts'

const ZERO = { puzzles: 0, cards: 0, lesson_positions: 0, games: 0 }

export default function Today({ login }: { login: string }) {
  const [activity, setActivity] = useState<Activity | null | undefined>(undefined)
  // undefined = loading, null = failed: the tasks then go without the weak theme and the due cards
  const [progress, setProgress] = useState<Progress | null | undefined>(undefined)
  const [lessons, setLessons] = useState<LessonSummary[] | null>(null)
  const [plan, setPlan] = useState<Plan | null>(null)
  const [themes, setThemes] = useState<PuzzleTheme[]>([])
  const [openings, setOpenings] = useState<PuzzleOpening[]>([])
  const [swap, setSwap] = useState<Swap | null>(null)
  const loadActivity = useCallback(
    () =>
      getActivity().then(
        (a) => {
          setActivity(a)
          setSwap(loadSwap(a.date))
        },
        () => setActivity(null),
      ),
    [],
  )
  useEffect(() => {
    getPlan().then(setPlan, () => {})
    getPuzzleThemes().then(setThemes, () => {})
    getPuzzleOpenings().then(setOpenings, () => {})
    getProgress().then(setProgress, () => setProgress(null))
    getLessons().then(setLessons, () => setLessons([]))
    void loadActivity()
  }, [loadActivity])

  const [goalError, setGoalError] = useState(false)
  const changeGoal = (goal: number) => {
    setGoalError(false)
    setWeekGoal(goal).then(loadActivity, () => setGoalError(true))
  }

  let daily: ReturnType<typeof dailyTasks> | null = null
  if (progress !== undefined && lessons && activity !== undefined) {
    const w = progress?.weak_theme
    const focus = focusTheme(plan?.focus_themes ?? [], themes.map((t) => t.key), activity?.date ?? '')
    const training = progress?.training
    const transfer = training?.transfer
    const selected = transfer?.theme ?? focus ?? training?.game_theme ?? w?.key
    const target = training?.target ?? 5
    const puzzles = {
      target,
      to: selected ? `/puzzles?theme=${encodeURIComponent(selected)}${transfer ? `&exclude=${encodeURIComponent(transfer.exclude)}` : ''}` : '/puzzles',
      text: transfer ? `Новая позиция по знакомой теме — ${target} задач` : selected
        ? `Задачи по теме «${nameOf(themes, selected)}» — ${target} задач`
        : `Смешанные задачи — ${target} задач`,
    }
    const lesson = (plan && planLesson(plan, lessons)) || nextLesson(lessons)
    const list = candidates({ today: activity?.today ?? ZERO, due: progress?.mistakes.due ?? 0, puzzles, lesson })
    daily = dailyTasks(list, swap, activity?.date ?? '')
  }
  const doSwap = (t: Task) => {
    if (!activity) return
    const s = { date: activity.date, kind: t.kind }
    storeSwap(s)
    setSwap(s)
  }
  const comeback = !!activity?.comeback && Object.values(activity.today).every((n) => n === 0)
  // The only «Одна задача» link: in the comeback card when it shows.
  const one = <Link to="/puzzles?one=1" className={tcss.primary}>Одна задача</Link>

  return (
    <>
      <h1>Сегодня</h1>
      <Training key={login} login={login} />
      <p className="muted">Хватит и 5 минут: начните с одной задачи.</p>
      {comeback ? (
        <section aria-label="С возвращением" className={tcss.card}>
          <p>С возвращением!</p>
          {one}
        </section>
      ) : (
        <p>{one}</p>
      )}
      {progress?.training?.provisional && <p className="muted">План предварительный: для выбора слабой темы нужно хотя бы 10 попыток по теме.</p>}
      {progress?.training?.transfer && <p className="muted">Попробуйте другую позицию по теме после перерыва. Это практика, а не подтверждение переноса навыка.</p>}
      {daily && <DailyTasks tasks={daily.tasks} spare={daily.spare} swapped={daily.swapped || !activity} onSwap={doSwap} date={activity?.date ?? ''} />}
      {activity && <WeekBlock week={activity.week} date={activity.date} onGoal={changeGoal} />}
      {goalError && <p role="alert">Не удалось сохранить цель недели. Попробуйте ещё раз.</p>}
      <PlanBlock plan={plan} themes={themes} openings={openings} lessons={lessons} />
      {activity && <NextAchievements items={activity.achievements?.next ?? []} />}
    </>
  )
}
