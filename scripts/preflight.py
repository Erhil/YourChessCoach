"""Проверка окружения перед установкой. Работает на Windows и Linux.

Запуск:  python scripts/preflight.py
Ничего не устанавливает, только проверяет и подсказывает, что сделать.
Код возврата 1, если есть критичные проблемы (FAIL).
"""

from __future__ import annotations

import contextlib
import json
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
import urllib.request
from pathlib import Path

IS_WIN = os.name == "nt"

with contextlib.suppress(
    AttributeError, OSError, ValueError
):  # на Windows вывод в пайп по умолчанию идёт в cp1251
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

fails = 0
warns = 0


def ok(msg: str) -> None:
    print(f"  OK    {msg}")


def bad(msg: str, fix: str) -> None:
    global fails
    fails += 1
    print(f"  FAIL  {msg}\n        -> {fix}")


def soft(msg: str, fix: str) -> None:
    global warns
    warns += 1
    print(f"  WARN  {msg}\n        -> {fix}")


def run(cmd: list[str], timeout: int = 15) -> str | None:
    exe = shutil.which(cmd[0])
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, *cmd[1:]],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return (out.stdout or out.stderr).strip()


def version_tuple(text: str) -> tuple[int, ...]:
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text or "")
    return tuple(int(x) for x in m.groups() if x is not None) if m else ()


def hint(win: str, linux: str) -> str:
    return win if IS_WIN else linux


# ---------------------------------------------------------------- система
def cpu_name() -> str:
    if IS_WIN:
        out = run(
            ["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor).Name"]
        )
        if out:
            return out.splitlines()[0].strip()
    else:
        try:
            for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
        except OSError:
            pass
    return platform.processor() or "неизвестно"


def ram_gb() -> float | None:
    if IS_WIN:
        import ctypes

        class MEMSTAT(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        st = MEMSTAT()
        st.dwLength = ctypes.sizeof(MEMSTAT)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return st.ullTotalPhys / 1024**3
        return None
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal"):
                return int(line.split()[1]) / 1024**2
    except OSError:
        pass
    return None


print("== Система")
ok(f"ОС: {platform.system()} {platform.release()} ({platform.machine()})")
ok(f"CPU: {cpu_name()}, логических ядер: {os.cpu_count()}")
ram = ram_gb()
if ram is None:
    soft("не удалось определить объём ОЗУ", "проверьте вручную")
elif ram < 12:
    soft(f"ОЗУ {ram:.1f} ГБ", "впритык: LLM лучше держать целиком в видеопамяти")
else:
    ok(f"ОЗУ {ram:.1f} ГБ")
free_gb = shutil.disk_usage(Path(__file__).resolve().parent.parent).free / 1024**3
if free_gb >= 20:
    ok(f"свободно на диске {free_gb:.0f} ГБ")
else:
    soft(f"свободно на диске {free_gb:.0f} ГБ", "нужно ~20 ГБ (модели, база задач, node_modules)")

# ---------------------------------------------------------------- инструменты
print("== Инструменты разработки")
pv = sys.version_info
if pv >= (3, 11):
    ok(f"python {pv.major}.{pv.minor}.{pv.micro} ({sys.executable})")
else:
    bad(
        f"python {pv.major}.{pv.minor} (нужен 3.11+)",
        hint("winget install Python.Python.3.12", "поставьте python3.11+ или uv"),
    )

# The migrations use ALTER TABLE ... DROP COLUMN (SQLite 3.35+).
if version_tuple(sqlite3.sqlite_version) >= (3, 35):
    ok(f"sqlite {sqlite3.sqlite_version}")
else:
    bad(
        f"sqlite {sqlite3.sqlite_version} (нужен 3.35+)",
        hint(
            "поставьте свежий Python с python.org",
            "обновите libsqlite3 или поставьте Python через uv",
        ),
    )

uv = run(["uv", "--version"])
ok(f"uv {uv.split()[1]}") if uv else soft(
    "uv не найден (необязательно, ускоряет установку)",
    hint(
        'powershell -c "irm https://astral.sh/uv/install.ps1 | iex"',
        "curl -LsSf https://astral.sh/uv/install.sh | sh",
    ),
)

node = run(["node", "--version"])
if node and version_tuple(node) >= (20,):
    ok(f"node {node}")
elif node:
    bad(
        f"node {node} (нужен 20+)",
        hint("winget install OpenJS.NodeJS.LTS", "поставьте Node 20+ через nvm"),
    )
else:
    bad("node не найден", hint("winget install OpenJS.NodeJS.LTS", "поставьте Node 20+ через nvm"))

git = run(["git", "--version"])
ok(git) if git else bad("git не найден", hint("winget install Git.Git", "sudo apt install -y git"))

# ---------------------------------------------------------------- движки
print("== Шахматные движки")
sf = shutil.which("stockfish")
ok(f"stockfish: {sf}") if sf else soft(
    "stockfish не найден в PATH", "не страшно: setup.py скачает официальный бинарник в engines/"
)
lc0 = shutil.which("lc0")
ok(f"lc0: {lc0}") if lc0 else soft(
    "lc0 не найден в PATH",
    hint(
        "не страшно: setup.py скачает готовый CPU-бинарник для Windows",
        "setup.py соберёт lc0 из исходников (2–5 минут); нужны g++ и git: sudo apt install g++ git",
    ),
)

# ---------------------------------------------------------------- GPU и LLM
print("== Видеокарта и LLM")
gpu = run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"])
if gpu:
    for line in gpu.splitlines():
        ok(f"GPU: {line}")
    vram = re.search(r"(\d+)\s*MiB", gpu)
    if vram:
        gb = int(vram.group(1)) / 1024
        tier = (
            "qwen3.5:9b / gemma4:e4b / qwen3.5:4b"
            if gb >= 7.5
            else "gemma4:e4b (q4) / qwen3.5:4b"
            if gb >= 5.5
            else "gemma4:e2b / qwen3.5:2b"
        )
        print(f"        видеопамять ~{gb:.1f} ГБ -> кандидаты: {tier}")
else:
    soft("nvidia-smi не отвечает", "установите драйвер NVIDIA, иначе LLM пойдёт на CPU (медленно)")

if shutil.which("ollama"):
    ok(f"ollama {run(['ollama', '--version']) or ''}".strip())
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3) as r:
            models = [m["name"] for m in json.load(r).get("models", [])]
        ok("сервис Ollama отвечает на :11434")
        print(f"        скачанные модели: {', '.join(models) or 'нет'}")
    except (OSError, ValueError, KeyError, TypeError):
        bad(
            "Ollama установлена, но сервис не отвечает",
            hint(
                "запустите приложение Ollama (иконка в трее)", "sudo systemctl enable --now ollama"
            ),
        )
else:
    bad(
        "ollama не найдена",
        hint("winget install Ollama.Ollama", "curl -fsSL https://ollama.com/install.sh | sh"),
    )

print()
if fails:
    print(f"Итого: {fails} критичных, {warns} предупреждений. Исправьте FAIL перед запуском.")
    sys.exit(1)
print(f"Итого: критичных проблем нет, предупреждений: {warns}.")
