#!/usr/bin/env python3
"""
start_store.py — единый лаунчер витрины FreshMarket.

ДВОЙНОЙ КЛИК по файлу (или `python start_store.py`):
    1. Запускает все три микросервиса:
         store-config-service :5001  (конфиг магазина)
         catalog-service      :5002  (каталог + SQLite)
         gateway-frontend     :5000  (сайт-витрина)
    2. Ждёт, пока каждый сервис отвечает, и открывает сайт в браузере.

ЗАКРЫТИЕ ОКНА (крестик), Enter в этом окне или Ctrl+C:
    1. Корректно останавливает ВСЕ сервисы, включая дочерние процессы.
    2. Порты 5000/5001/5002 освобождаются гарантированно.

Как гарантируется остановка при закрытии окна (Windows):
    * дочерние процессы наследуют консоль — при закрытии окна Windows
      рассылает CTRL_CLOSE_EVENT всем процессам консоли и завершает их;
    * дополнительно лаунчер ловит CTRL_CLOSE/LOGOFF/SHUTDOWN через
      SetConsoleCtrlHandler (ctypes) и сам запускает остановку;
    * все дочерние процессы помещаются в Job Object с флагом
      KILL_ON_JOB_CLOSE — при любом завершении лаунчера (в т.ч. убийство
      через Диспетчер задач) Windows убивает всё дерево процессов;
    * on-Exit страховка через atexit + SIGINT/SIGTERM.

Лаунчер написан только на stdlib — дополнительные пакеты не нужны.
Использует Python из .venv проекта, если окружение уже создано.
"""

from __future__ import annotations

import atexit
import ctypes
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "_logs"
SITE_URL = "http://127.0.0.1:5000"

# (папка сервиса, точка входа, порт)
SERVICES = [
    ("store-config-service", "app.py", 5001),
    ("catalog-service", "app.py", 5002),
    ("gateway-frontend", "app.py", 5000),
]

IS_WINDOWS = os.name == "nt"
STARTUP_TIMEOUT = 25.0  # секунд на поднятие каждого сервиса


def setup_console() -> None:
    """Переводит консоль в UTF-8, чтобы эмодзи и русский текст не падали (cp1251)."""
    if IS_WINDOWS:
        CP_UTF8 = 65001
        try:
            ctypes.windll.kernel32.SetConsoleOutputCP(CP_UTF8)
            ctypes.windll.kernel32.SetConsoleCP(CP_UTF8)
        except Exception:
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


def pick_python() -> str:
    """Интерпретатор проекта: предпочитаем .venv, иначе текущий Python."""
    candidates = []
    if IS_WINDOWS:
        candidates.append(ROOT / ".venv" / "Scripts" / "python.exe")
    else:
        candidates.append(ROOT / ".venv" / "bin" / "python3")
    candidates.append(Path(sys.executable))
    for cand in candidates:
        if cand.exists():
            return str(cand)
    return sys.executable


def port_busy(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def wait_port(port: int, timeout: float = STARTUP_TIMEOUT) -> bool:
    """Ждёт, пока сервис поднимется на своём порту."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if port_busy(port):
            return True
        time.sleep(0.3)
    return False


def kill_tree(proc: subprocess.Popen) -> None:
    """Убивает процесс вместе с детьми/внуками (Flask reloader и пр.)."""
    if proc.poll() is not None:
        return
    if IS_WINDOWS:
        # /T — дерево процессов, /F — принудительно
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            capture_output=True,
        )
    else:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


# ---------------------------------------------------------------------------
# Job Object (Windows): дочерние процессы умирают вместе с лаунчером
# ---------------------------------------------------------------------------


def create_kill_job():
    if not IS_WINDOWS:
        return None
    try:
        from ctypes import wintypes

        k32 = ctypes.windll.kernel32
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
        JobObjectExtendedLimitInformation = 9

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
                ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        job = k32.CreateJobObjectW(None, None)
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        k32.SetInformationJobObject(
            job, JobObjectExtendedLimitInformation,
            ctypes.byref(info), ctypes.sizeof(info),
        )
        return job
    except Exception as exc:  # pragma: no cover — страховка
        print(f"  (Job Object недоступен: {exc})")
        return None


# ---------------------------------------------------------------------------
# Остановка всех сервисов (идемпотентная)
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_stopped = False
_procs: list[tuple[str, subprocess.Popen]] = []


def stop_all(reason: str = "") -> None:
    """Останавливает все запущенные сервисы. Повторный вызов безопасен."""
    global _stopped
    with _lock:
        if _stopped:
            return
        _stopped = True

    if not _procs:
        return
    if reason:
        print(f"\n⏸  {reason}", flush=True)
    print("Останавливаю сервисы...", flush=True)

    for name, proc in _procs:
        if proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass

    deadline = time.monotonic() + 3
    for name, proc in _procs:
        try:
            proc.wait(timeout=max(0.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            pass
        if proc.poll() is None:
            kill_tree(proc)  # добор деревa процессов
        print(f"   • {name}: остановлен", flush=True)

    print("✅ Все сервисы остановлены. Портосвобождено. Можно закрывать окно.", flush=True)


def install_signal_handlers() -> None:
    atexit.register(stop_all)

    def _handler(signum, _frame):
        stop_all("Получен сигнал остановки.")
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)

    if IS_WINDOWS:
        # Корректная остановка при закрытии/отключении окна консоли
        CTRL_C, CTRL_BREAK, CTRL_CLOSE, CTRL_LOGOFF, CTRL_SHUTDOWN = 0, 1, 2, 5, 6
        HANDLED = {CTRL_C, CTRL_BREAK, CTRL_CLOSE, CTRL_LOGOFF, CTRL_SHUTDOWN}
        HANDLER_TYPE = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_uint)

        @HANDLER_TYPE
        def _console_handler(ctrl_type):
            if ctrl_type in HANDLED:
                names = {2: "окно закрыто", 5: "выход из системы", 6: "завершение работы"}
                stop_all(f"Windows завершает консоль ({names.get(ctrl_type, 'Ctrl+C')}).")
                return True
            return False

        # сохраняем ссылку, чтобы callback не был собран сборщиком мусора
        install_signal_handlers._cb = _console_handler
        ctypes.windll.kernel32.SetConsoleCtrlHandler(_console_handler, True)


# ---------------------------------------------------------------------------
# Запуск сервисов
# ---------------------------------------------------------------------------


def start_service(name: str, entry: str, port: int, python: str, job) -> bool:
    cwd = ROOT / name
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["FLASK_DEBUG"] = "0"  # без reloader — один процесс на сервис, чище и надёжнее

    log_path = LOG_DIR / f"{name}.log"
    log_file = open(log_path, "w", encoding="utf-8", errors="replace")

    proc = subprocess.Popen(
        [python, entry],
        cwd=str(cwd),
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )

    if job is not None:
        try:
            ctypes.windll.kernel32.AssignProcessToJobObject(job, proc._handle)
        except Exception:
            pass  # не критично — есть другие уровни защиты

    _procs.append((name, proc))

    print(f"  ▸ {name} (порт {port}) ... ", end="", flush=True)
    if wait_port(port):
        print("✅ запущен")
        return True
    print(f"❌ не поднялся за {STARTUP_TIMEOUT:.0f} с")
    print(f"    лог: {log_path}")
    return False


def main() -> int:
    setup_console()  # UTF-8 до первой печати — иначе cp1251 роняет эмодзи
    if IS_WINDOWS:
        try:
            ctypes.windll.kernel32.SetConsoleTitleW("FreshMarket — запуск витрины")
        except Exception:
            pass

    print("=" * 62)
    print("  🛒 FreshMarket — единый запуск всех микросервисов")
    print("=" * 62)
    print("  Сервисы: config:5001 · catalog:5002 · витрина:5000")
    print("  Логи:   ", LOG_DIR)
    print()

    python = pick_python()

    # 1) зависимости
    check = subprocess.run(
        [python, "-c", "import flask, sqlalchemy, requests"],
        capture_output=True,
    )
    if check.returncode != 0:
        print("❌ Не найдены зависимости (flask/sqlalchemy/requests).")
        print(f'   Установите: "{python}" -m pip install -r requirements.txt')
        input("\nНажмите Enter для выхода...")
        return 1

    # 2) порты не должны быть заняты
    busy = [f"{n} ({p})" for n, _, p in SERVICES if port_busy(p)]
    if busy:
        print("❌ Порты уже заняты:", ", ".join(busy))
        print("   Возможно, магазин уже запущен — закройте его окно и повторите.")
        input("\nНажмите Enter для выхода...")
        return 1

    # 3) обработчики остановки + Job Object
    install_signal_handlers()
    job = create_kill_job()
    LOG_DIR.mkdir(exist_ok=True)

    # 4) запуск сервисов (конфиг → каталог → витрина)
    print("Запускаю микросервисы...")
    for name, entry, port in SERVICES:
        if not start_service(name, entry, port, python, job):
            print("\nЗапуск прерван из-за ошибки сервиса.")
            stop_all()
            input("\nНажмите Enter для выхода...")
            return 1

    print()
    print("=" * 62)
    print("  🎉 Магазин запущен! Открываю витрину в браузере...")
    print(f"     {SITE_URL}")
    print("=" * 62)
    print("  ⚠️  Не закрывайте это окно, пока магазин работает.")
    print("  Остановка: закройте окно (крестик) или нажмите Enter.")
    print()

    webbrowser.open(SITE_URL)
    time.sleep(0.5)

    try:
        input(">>> Нажмите ENTER для остановки всех сервисов... ")
    except (EOFError, KeyboardInterrupt):
        pass

    stop_all("Остановка по команде пользователя.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
