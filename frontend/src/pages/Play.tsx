import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { EvalBar } from '../components/EvalBar'
import { Board } from '../components/Board'
import { CoachPanel } from '../components/CoachPanel'
import { HelpSelect } from '../components/HelpSelect'
import { IconsToggle } from '../components/IconsToggle'
import { MoveList } from '../components/MoveList'
import { OpeningName } from '../components/OpeningName'
import { adviceArrows, type Arrow } from '../chess/arrows'
import { readHelp, readIcons } from '../chess/coachSettings'
import { boardBadge } from '../chess/quality'
import { useQuality } from '../chess/useQuality'
import { statusText } from '../chess/game'
import { useHelp } from '../chess/useHelp'
import type { Advice } from '../chess/useCoach'
import { useGame } from '../chess/useGame'
import { PlaySetup } from './PlaySetup'
import css from './Play.module.css'

const EVAL_KEY = 'play.evalBar'

function readEval(): boolean {
  try {
    return localStorage.getItem(EVAL_KEY) === '1'
  } catch {
    return false
  }
}

type Ask = 'new' | 'resign'
const QUESTION: Record<Ask, string> = {
  new: 'Начать новую партию? Текущая партия сохранится как незаконченная.',
  resign: 'Сдаться? Партия будет записана как поражение.',
}

export default function Play() {
  const game = useGame()
  const navigate = useNavigate()
  const [showEval, setShowEval] = useState(readEval)
  const [ask, setAsk] = useState<Ask | null>(null)
  const [level, setLevel] = useState(readHelp)
  const [icons, setIcons] = useState(readIcons)
  const [shown, setShown] = useState<Advice | null>(null)
  const [asked, setAsked] = useState<{ a: Advice; arrows: Arrow[] } | null>(null)
  const help = useHelp(game.fen, level, game.canMove && level >= 2, game.markHint)
  const { advice } = game
  const color = game.g?.color ?? 'white'
  const quality = useQuality(game.g?.id, color, game.uci, game.verdicts, icons)
  // The arrows of a note fit only the position right after its move (a note can stay after the reply).
  const mine = advice && advice.after === game.fen ? advice : null
  const arrows =
    mine && asked?.a === mine
      ? asked.arrows
      : mine && shown === mine
        ? adviceArrows(mine.before, mine.uci, mine.facts)
        : help.arrows

  const toggleEval = (on: boolean) => {
    setShowEval(on)
    try {
      localStorage.setItem(EVAL_KEY, on ? '1' : '0')
    } catch {
      /* the choice is not kept */
    }
  }
  const confirm = () => {
    if (ask === 'new') game.leave()
    else game.resign()
    setAsk(null)
  }

  return (
    <>
      <h1>Игра</h1>
      <div className={game.g ? css.layout : `${css.layout} ${css.noGame}`}>
        <div className={game.g ? undefined : css.idle}>
          <Board
            position={game.fen}
            orientation={color}
            canMove={game.canMove}
            onMove={game.move}
            lastMove={game.lastMove}
            arrows={arrows}
            badge={boardBadge(quality, game.uci, color)}
          />
        </div>
        <div className={css.side}>
          {!game.g && <PlaySetup onStart={game.start} />}
          {game.g && (
            <div className={css.buttons}>
              <button type="button" onClick={game.undo} disabled={!game.canUndo}>
                Ход назад
              </button>
              {level >= 2 && game.active && (
                <button type="button" onClick={help.press} disabled={!game.canMove}>
                  Подсказка
                </button>
              )}
            </div>
          )}
          {help.lines.length > 0 && (
            <div role="status">
              {help.lines.map((l) => (
                <p key={l}>{l}</p>
              ))}
            </div>
          )}
          {game.checking && <p role="status">Тренер проверяет ход…</p>}
          {game.warn && (
            <div className={css.dialog} role="alertdialog" aria-label="Предупреждение">
              <p>Осторожно: похоже, этот ход — зевок. Проверьте, что соперник может сделать в ответ.</p>
              <div className={css.buttons}>
                <button type="button" onClick={game.warnThink}>
                  Подумать ещё
                </button>
                <button type="button" onClick={game.warnGo}>
                  Всё равно сходить
                </button>
              </div>
            </div>
          )}
          {advice && (
            <>
              <CoachPanel
                text={advice.text}
                source={advice.source}
                lesson={advice.lesson}
                onShow={() => {
                  setAsked(null)
                  setShown(advice)
                }}
                fen={advice.before}
                move={advice.uci}
                classification={advice.facts.classification}
                onArrows={(arrows) => setAsked({ a: advice, arrows })}
              />
              {advice.hold && (
                <div className={css.buttons}>
                  <button type="button" onClick={game.undo}>
                    Взять ход назад
                  </button>
                  <button type="button" onClick={game.proceed}>
                    Играть дальше
                  </button>
                </div>
              )}
            </>
          )}
          {game.thinking && !advice?.hold && <p role="status">Соперник думает…</p>}
          {game.oppFailed && <p role="alert">Соперник не ответил. Нажмите «Ход назад» или начните новую партию.</p>}
          {game.status.over && (
            <>
              <p className={css.over} role="status">{statusText(game.status)}</p>
              <div className={css.buttons}>
                <button type="button" onClick={game.leave}>
                  Новая партия
                </button>
                {game.savedGameId !== null && (
                  <button type="button" onClick={() => navigate(`/review?game=${game.savedGameId}`)}>
                    Разобрать партию
                  </button>
                )}
              </div>
            </>
          )}
          {game.saveError && <p className="muted">Партию не удалось сохранить.</p>}
          {showEval && <EvalBar fen={game.fen} />}
          <MoveList moves={game.sans} badges={quality} />
          <OpeningName moves={game.uci} />
          {(!!game.g?.takebacks || !!game.g?.hints) && (
            <p className="muted">
              Тренировочная партия: были возвраты хода или подсказки. В счёт побед она не идёт.
              {!!game.g.hints && ` Подсказок: ${game.g.hints}.`}
            </p>
          )}
          <div className={css.secondary}>
            {ask && (
              <div className={css.dialog} role="alertdialog" aria-label="Подтверждение">
                <p>{QUESTION[ask]}</p>
                <div className={css.buttons}>
                  <button type="button" onClick={confirm}>
                    Да
                  </button>
                  <button type="button" onClick={() => setAsk(null)}>
                    Отмена
                  </button>
                </div>
              </div>
            )}
            {game.active && !ask && (
              <div className={css.buttons}>
                <button type="button" onClick={() => setAsk('resign')}>
                  Сдаться
                </button>
                <button type="button" onClick={() => setAsk('new')}>
                  Новая партия
                </button>
              </div>
            )}
            <HelpSelect onChange={setLevel} />
            <IconsToggle onChange={setIcons} />
            <label className="choice">
              <input type="checkbox" checked={showEval} onChange={(e) => toggleEval(e.target.checked)} />
              Шкала оценки
            </label>
          </div>
        </div>
      </div>
    </>
  )
}
