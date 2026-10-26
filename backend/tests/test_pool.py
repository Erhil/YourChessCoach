import threading
from pathlib import Path

import chess
import chess.engine
import pytest

from app.engines import pool as pool_mod
from app.engines.pool import EnginePool, EngineUnavailableError


class FakeEngine:
    def __init__(self, analyse=None, configure_error=None):
        self._analyse = analyse
        self._configure_error = configure_error
        self.closed = False

    def configure(self, options):
        if self._configure_error:
            raise self._configure_error

    def analyse(self, board, limit, multipv=1):
        return self._analyse()

    def quit(self):
        pass

    def close(self):
        self.closed = True


def make_pool(monkeypatch, engine):
    monkeypatch.setattr(pool_mod, "find_binary", lambda d, n: Path("stockfish"))
    monkeypatch.setattr(chess.engine.SimpleEngine, "popen_uci", lambda path: engine)
    return EnginePool(Path("."), size=1, threads=1, hash_mb=16)


def test_configure_failure_stops_new_engine(monkeypatch):
    engine = FakeEngine(configure_error=chess.engine.EngineError("bad option"))
    pool = make_pool(monkeypatch, engine)
    with pytest.raises(chess.engine.EngineError):
        pool.analyse(chess.Board(), depth=1)
    assert engine.closed
    assert pool._slots == 0


def test_waiter_is_released_when_holder_fails(monkeypatch):
    in_analyse = threading.Event()
    fail = threading.Event()

    def analyse():
        in_analyse.set()
        fail.wait(5)
        raise chess.engine.EngineTerminatedError("dead")

    pool = make_pool(monkeypatch, FakeEngine(analyse=analyse))
    errors = {}

    def run(name):
        try:
            pool.analyse(chess.Board(), depth=1)
        except (EngineUnavailableError, chess.engine.EngineError) as ex:
            errors[name] = ex

    holder = threading.Thread(target=run, args=("holder",), daemon=True)
    holder.start()
    assert in_analyse.wait(5)
    waiter = threading.Thread(target=run, args=("waiter",), daemon=True)
    waiter.start()
    waiter.join(0.3)
    assert waiter.is_alive()  # pool is full: the waiter blocks
    # Restart of the dead engine fails, so the holder gives up its slot.
    monkeypatch.setattr(pool_mod, "find_binary", lambda d, n: None)
    fail.set()
    holder.join(5)
    waiter.join(5)
    assert not waiter.is_alive(), "waiter hangs after the holder failed"
    assert isinstance(errors["holder"], EngineUnavailableError)
    assert isinstance(errors["waiter"], EngineUnavailableError)


def test_acquire_times_out_with_busy_error(monkeypatch):
    pool = make_pool(monkeypatch, FakeEngine(analyse=list))
    pool._acquire_timeout_s = 0.2
    pool._slots = pool._size  # every engine is taken, none is free
    with pytest.raises(pool_mod.EngineBusyError) as err:
        pool.analyse(chess.Board(), depth=1)
    assert "занят" in str(err.value)
    assert isinstance(err.value, EngineUnavailableError)  # routes answer 503
