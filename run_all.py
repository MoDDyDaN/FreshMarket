"""
Единый скрипт запуска всех микросервисов проекта food_store_microservices.

Запускает три процесса параллельно:
  1. store-config-service  (порт 5001)
  2. catalog-service       (порт 5002)
  3. gateway-frontend      (порт 5000) — главный сайт

Использование (из корневой папки проекта):
    python run_all.py

Остановка: Ctrl+C в консоли, где запущен скрипт (все сервисы завершатся).
"""

import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# (папка сервиса, точка входа, порт)
SERVICES = [
    ("store-config-service", "app.py", 5001),
    ("catalog-service", "app.py", 5002),
    ("gateway-frontend", "app.py", 5000),
]

HEALTH_PATH = "/api/health"  # у gateway health-эндпоинта нет — для него просто ждём порт


def stream_output(prefix: str, pipe) -> None:
    """Печатает stdout процесса с префиксом имени сервиса."""
    for line in iter(pipe.readline, ""):
        print(f"[{prefix}] {line.rstrip()}", flush=True)


def wait_for_port(port: int, name: str, timeout: float = 20.0) -> bool:
    """Ждёт, пока сервис поднимется на своём порту (простой health-poll)."""
    import socket

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.4)
    print(f"[{name}] !! сервис не поднялся за {timeout:.0f} с (порт {port})", flush=True)
    return False


def main() -> int:
    procs: list[tuple[str, subprocess.Popen]] = []

    for folder, entry, port in SERVICES:
        cwd = ROOT / folder
        if not (cwd / entry).exists():
            print(f"Ошибка: не найден {cwd / entry}", file=sys.stderr)
            return 1

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"

        proc = subprocess.Popen(
            [sys.executable, entry],
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        threading.Thread(
            target=stream_output, args=(folder, proc.stdout), daemon=True
        ).start()
        procs.append((folder, proc))
        print(f"Запускаю {folder} (порт {port}, pid {proc.pid})...")

    # Ждём, пока каждый сервис отвечает
    for (folder, _), (_, _, port) in zip(procs, SERVICES):
        wait_for_port(port, folder)

    print("\n" + "=" * 60)
    print("Все микросервисы запущены:")
    print("  🌐 Витрина (главный сайт): http://127.0.0.1:5000")
    print("  ⚙️  Конфиг магазина:        http://127.0.0.1:5001/api/config")
    print("  📦 Каталог (API):           http://127.0.0.1:5002/api/products")
    print("=" * 60)
    print("Остановка: Ctrl+C\n")

    try:
        while True:
            # Если какой-то сервис умер — завершаем остальные
            for name, proc in procs:
                code = proc.poll()
                if code is not None:
                    print(f"[{name}] завершился с кодом {code}. Останавливаю остальные...")
                    raise KeyboardInterrupt
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nОстанавливаю все сервисы...")
        for name, proc in procs:
            if proc.poll() is None:
                proc.terminate()
        for name, proc in procs:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        print("Готово. Все сервисы остановлены.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
