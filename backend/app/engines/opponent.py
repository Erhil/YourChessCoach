import random
import threading
from pathlib import Path

import chess
import chess.engine

from app.engines.locate import find_binary, find_maia_weights
from app.engines.pool import EngineUnavailableError, stop_engine

LEVELS = {
    800: "Новичок",
    1100: "Начинающий",
    1300: "Любитель",
    1500: "Клубный",
    1700: "Сильный",
    1900: "Эксперт",
}
BEGINNER_LEVEL = 800
RANDOM_MOVE_PROBABILITY = 0.25
SKILL_BY_LEVEL = {800: 0, 1100: 3}  # levels below UCI_Elo minimum
STOCKFISH_MOVETIME_S = 0.1
START_TIMEOUT_S = 30
COMMAND_TIMEOUT_S = 10  # added to the move time to get the wait limit of one move
MAIA_TIME_BOUND_S = 3  # lc0 stops at 1 node, so this only bounds a stuck process


class _StartError(EngineUnavailableError):
    """The engine process did not start."""


class _Slot:
    """One engine process that serves one request at a time."""

    def __init__(self, command: list[str]):
        self.command = command
        self.lock = threading.Lock()
        self.engine: chess.engine.SimpleEngine | None = None

    def close(self) -> None:
        engine, self.engine = self.engine, None
        if engine is not None:
            stop_engine(engine)


class Opponent:
    def __init__(self, engines_dir: Path, use_maia: bool = True):
        self._engines_dir = engines_dir
        self._lc0 = find_binary(engines_dir, "lc0") if use_maia else None
        self._stockfish = find_binary(engines_dir, "stockfish")
        self._lc0_broken = False  # lc0 failed to start: use Stockfish from then on
        self._slots: dict[str, _Slot] = {}
        self._slots_lock = threading.Lock()

    def _weights(self, level: int) -> Path | None:
        if self._lc0 is None or self._lc0_broken:
            return None
        return find_maia_weights(self._engines_dir, 1100 if level == BEGINNER_LEVEL else level)

    def engine_name(self, level: int) -> str:
        return "maia" if self._weights(level) else "stockfish"

    def _slot(self, key: str, command: list[str]) -> _Slot:
        with self._slots_lock:
            return self._slots.setdefault(key, _Slot(command))

    def move(self, board: chess.Board, level: int) -> tuple[chess.Move, str]:
        if level not in LEVELS:
            raise ValueError(f"unknown level {level}")
        legal = list(board.legal_moves)
        if not legal:
            raise ValueError("game is over")
        if level == BEGINNER_LEVEL and random.random() < RANDOM_MOVE_PROBABILITY:
            return random.choice(legal), self.engine_name(level)
        weights = self._weights(level)
        if weights is not None:
            # no --backend: lc0 picks its CPU backend (blas on Windows, eigen on Linux)
            command = [str(self._lc0), f"--weights={weights}"]
            slot = self._slot(f"maia-{weights.name}", command)
            try:
                return self._play(slot, board, chess.engine.Limit(nodes=1), None), "maia"
            except _StartError:
                self._lc0_broken = True  # fall back to Stockfish below
        if self._stockfish is None:
            raise EngineUnavailableError("no opponent engine found (lc0 with Maia or Stockfish)")
        slot = self._slot("stockfish", [str(self._stockfish)])
        limit = chess.engine.Limit(time=STOCKFISH_MOVETIME_S)
        return self._play(slot, board, limit, level), "stockfish"

    def _play(
        self, slot: _Slot, board: chess.Board, limit: chess.engine.Limit, sf_level: int | None
    ) -> chess.Move:
        if limit.time is None:  # without a time part python-chess waits for ever
            limit = chess.engine.Limit(nodes=limit.nodes, time=MAIA_TIME_BOUND_S)
        with slot.lock:
            if slot.engine is None:
                try:
                    slot.engine = chess.engine.SimpleEngine.popen_uci(
                        slot.command, timeout=START_TIMEOUT_S
                    )
                except (OSError, TimeoutError, chess.engine.EngineError) as exc:
                    raise _StartError(f"opponent engine did not start: {exc}") from exc
                slot.engine.timeout = COMMAND_TIMEOUT_S
            try:
                if sf_level is not None:
                    slot.engine.configure(self._stockfish_options(slot.engine, sf_level))
                return slot.engine.play(board, limit).move
            except (OSError, TimeoutError, chess.engine.EngineError) as exc:
                slot.close()
                raise EngineUnavailableError(f"opponent engine failed: {exc}") from exc

    @staticmethod
    def _stockfish_options(engine: chess.engine.SimpleEngine, level: int) -> dict:
        if level in SKILL_BY_LEVEL:
            return {"UCI_LimitStrength": False, "Skill Level": SKILL_BY_LEVEL[level]}
        min_elo = engine.options["UCI_Elo"].min or level
        return {"UCI_LimitStrength": True, "UCI_Elo": max(level, min_elo)}

    def close(self) -> None:
        with self._slots_lock:
            slots = list(self._slots.values())
            self._slots.clear()
        for slot in slots:
            slot.close()
