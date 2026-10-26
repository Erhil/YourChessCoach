import contextlib
import queue
import threading
import time
from pathlib import Path

import chess
import chess.engine

from app.engines.locate import find_binary


class EngineUnavailableError(RuntimeError):
    pass


class EngineBusyError(EngineUnavailableError):
    """No engine became free in time. Routes answer 503 with this text."""


BUSY = "Сервер занят, попробуйте ещё раз"


def stop_engine(engine: chess.engine.SimpleEngine) -> None:
    """Stop an engine politely, then close the transport (kills the process if still alive)."""
    try:
        engine.quit()  # command timeout is 10 s by default
    except (chess.engine.EngineError, TimeoutError, OSError):
        pass  # engine already dead or stuck: close() below kills it
    finally:
        with contextlib.suppress(Exception):
            engine.close()


class EnginePool:
    """Lazy pool of Stockfish processes. A caller takes one engine and returns it."""

    def __init__(
        self,
        engines_dir: Path,
        size: int,
        threads: int,
        hash_mb: int,
        acquire_timeout_s: float = 30.0,
    ):
        self._engines_dir = engines_dir
        self._acquire_timeout_s = acquire_timeout_s
        self._size = size
        self._options = {"Threads": threads, "Hash": hash_mb}
        # None is a wake-up marker: a slot became free, so a waiter must retry.
        self._free: queue.Queue[chess.engine.SimpleEngine | None] = queue.Queue()
        self._started: set[chess.engine.SimpleEngine] = set()
        self._slots = 0  # engines started or being started
        self._lock = threading.Lock()

    def _start(self) -> chess.engine.SimpleEngine:
        path = find_binary(self._engines_dir, "stockfish")
        if path is None:
            raise EngineUnavailableError("Stockfish not found")
        engine = chess.engine.SimpleEngine.popen_uci(str(path))
        try:
            engine.configure(self._options)
        except BaseException:
            stop_engine(engine)  # not tracked yet: stop it here or it leaks
            raise
        with self._lock:
            self._started.add(engine)
        return engine

    def _release_slot(self) -> None:
        with self._lock:
            self._slots -= 1
        self._free.put(None)  # wake one waiter so it can start a new engine

    def _acquire(self) -> chess.engine.SimpleEngine:
        deadline = time.monotonic() + self._acquire_timeout_s
        while True:
            try:
                engine = self._free.get_nowait()
            except queue.Empty:
                engine = None
                with self._lock:
                    can_start = self._slots < self._size
                    if can_start:
                        self._slots += 1
                if can_start:
                    try:
                        return self._start()
                    except BaseException:
                        self._release_slot()
                        raise
                try:
                    engine = self._free.get(timeout=max(0.0, deadline - time.monotonic()))
                except queue.Empty:
                    raise EngineBusyError(BUSY) from None
            if engine is not None:
                return engine

    def analyse(
        self,
        board: chess.Board,
        depth: int | None = None,
        movetime_ms: int | None = None,
        multipv: int = 1,
    ) -> tuple[int, list[dict]]:
        """Return (depth, lines). Scores are from White's point of view."""
        if board.is_game_over():
            return 0, []
        limit = chess.engine.Limit(
            depth=depth, time=movetime_ms / 1000 if movetime_ms is not None else None
        )
        engine = self._acquire()
        try:
            try:
                infos = engine.analyse(board, limit, multipv=multipv)
            except chess.engine.EngineTerminatedError:
                stop_engine(engine)
                with self._lock:
                    self._started.discard(engine)
                engine = self._start()
                infos = engine.analyse(board, limit, multipv=multipv)
        except BaseException:
            # Engine state is unknown: drop it and free its slot.
            stop_engine(engine)
            with self._lock:
                self._started.discard(engine)
            self._release_slot()
            raise
        self._free.put(engine)

        lines = []
        for rank, info in enumerate(infos, start=1):
            score = info["score"].white()
            walker = board.copy()
            pv_san = []
            for move in info.get("pv", []):
                pv_san.append(walker.san(move))
                walker.push(move)
            lines.append(
                {
                    "rank": rank,
                    "score": {"cp": score.score(), "mate": score.mate()},
                    "pv_san": pv_san,
                    "pv_uci": [m.uci() for m in info.get("pv", [])],
                }
            )
        return infos[0].get("depth", 0), lines

    def close(self) -> None:
        with self._lock:
            engines = list(self._started)
            self._started.clear()
            self._slots = 0
        while not self._free.empty():
            try:
                self._free.get_nowait()
            except queue.Empty:
                break
        for engine in engines:
            stop_engine(engine)
