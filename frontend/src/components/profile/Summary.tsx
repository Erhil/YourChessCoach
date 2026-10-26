import type { Achievements, Activity } from '../../api/activity'
import type { NextMistake } from '../../api/mistakes'
import type { Progress } from '../../api/progress'
import { AchievementsTile, CalendarTile, DeckTile, LessonsTile, ThemesTile } from './MoreTiles'
import css from './Profile.module.css'
import { BlundersTile, GamesTile, RatingTile, WeekTile } from './Tiles'

/**
 * The dense summary: one screen on iPad and on a computer; 2, 3 or 4 columns by the width.
 * 6 tiles of one cell and 3 wide tiles (12 cells); this order fills every row in 2, 3 and 4 columns.
 */
export default function Summary({ d, activity, ach, next, now = new Date() }: {
  d: Progress
  activity: Activity | null | undefined
  ach: Achievements | null | undefined
  next: NextMistake | null | undefined
  now?: Date
}) {
  return (
    <div className={css.wrap}>
      <section aria-label="Сводка" className={css.grid}>
        <RatingTile p={d.puzzles} now={now} />
        <WeekTile a={activity} />
        <BlundersTile weeks={d.weeks} />
        <AchievementsTile ach={ach} />
        <CalendarTile dates={d.calendar ?? []} now={now} />
        <GamesTile g={d.games} />
        <ThemesTile themes={d.themes} />
        <DeckTile m={d.mistakes} next={next} />
        <LessonsTile l={d.lessons} />
      </section>
    </div>
  )
}
