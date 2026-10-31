#!/usr/bin/env python3
"""
build_static.py — сборка статической копии витрины для GitHub Pages.

Зачем: GitHub Pages не запускает Flask, поэтому сайт «консервируется» в HTML.

Что делает скрипт:
  1. Проверяет/запускает три микросервиса (config:5001, catalog:5002, gateway:5000);
     уже запущенные сервисы переиспользуются и НЕ останавливаются в конце;
  2. Запрашивает у шлюза все страницы: главная, каталог, 6 категорий,
     30 карточек товаров, контакты и страница 404;
  3. Переписывает внутренние ссылки под префикс GitHub Pages (--base /REPO);
  4. Пишет HTML в папку docs/ (+ .nojekyll);
  5. Останавливает только те сервисы, которые запускал сам.

Использование:
    python build_static.py                       # сайт на user.github.io (корень)
    python build_static.py --base /food-store    # сайт на user.github.io/food-store
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
GATEWAY = "http://127.0.0.1:5000"
CATALOG_API = "http://127.0.0.1:5002"
CONFIG_SERVICE = ("store-config-service", 5001)
CATALOG_SERVICE = ("catalog-service", 5002)
GATEWAY_SERVICE = ("gateway-frontend", 5000)
ALL_SERVICES = [CONFIG_SERVICE, CATALOG_SERVICE, GATEWAY_SERVICE]
IS_WINDOWS = os.name == "nt"


# ----------------------------- инфраструктура -----------------------------

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


def wait_port(port: int, timeout: float = 25.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if port_busy(port):
            return True
        time.sleep(0.3)
    return False


def start_service(name: str, port: int, python: str) -> subprocess.Popen | None:
    """Запускает сервис; None — если он уже был запущен ранее."""
    if port_busy(port):
        print(f"  · {name}: уже запущен (порт {port}) — переиспользую")
        return None

    log_path = ROOT / "_logs" / f"build-{name}.log"
    log_path.parent.mkdir(exist_ok=True)
    log = open(log_path, "w", encoding="utf-8", errors="replace")

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["FLASK_DEBUG"] = "0"
    proc = subprocess.Popen(
        [python, "app.py"],
        cwd=str(ROOT / name),
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    print(f"  · {name}: запускаю (порт {port}) ...", end=" ", flush=True)
    if wait_port(port):
        print("✅")
        return proc
    print("❌ см. " + str(log_path))
    kill_tree(proc)
    return None


def kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    else:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


def http_get(url: str, timeout: float = 15) -> str:
    """GET с обработкой HTTP-ошибок: тело 404-страницы тоже валидный HTML."""
    req = urllib.request.Request(url, headers={"User-Agent": "static-builder/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        # Страница 404 нам нужна (шаблон отдаётся и с кодом 404)
        body = exc.read().decode("utf-8", errors="replace")
        if exc.code == 404 and body.strip():
            return body
        raise


def http_get_json(url: str, timeout: float = 15) -> list | dict:
    return json.loads(http_get(url, timeout))


# ----------------------------- сборка -----------------------------

def rewrite_links(html: str, base: str) -> str:
    """
    Переписывает внутренние ссылки под префикс GitHub Pages.

    Статический хост не знает про query-фильтры, поэтому
    /catalog?category=fruits превращается в /catalog/fruits/ (реальная папка).
    Внешние ссылки (https:, tel:, mailto:, #) не трогаются.
    """
    html = re.sub(r'(href|action)="/catalog\?category=([a-z0-9\-]+)"',
                  rf'\1="{base}/catalog/\2/"', html)
    html = re.sub(r'(href|action)="/catalog(\?[^"]*)?"',
                  rf'\1="{base}/catalog/"', html)
    html = re.sub(r'(href|action)="/product/(\d+)"',
                  rf'\1="{base}/product/\2/"', html)
    html = re.sub(r'(href|action)="/contacts"',
                  rf'\1="{base}/contacts/"', html)
    html = re.sub(r'(href|action)="(/)"',
                  rf'\1="{base}/"', html)
    return html


def write_page(rel_path: str, html: str, base: str) -> None:
    target = DOCS / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rewrite_links(html, base), encoding="utf-8")


def build(base: str) -> int:
    python = pick_python()
    started: list[subprocess.Popen] = []

    print("Проверяю/запускаю микросервисы...")
    for name, port in ALL_SERVICES:
        proc = start_service(name, port, python)
        if proc is None and not port_busy(port):
            print(f"❌ {name} не запустился — сборка прервана.")
            return 1
        if proc is not None:
            started.append(proc)

    try:
        # Данные для списка страниц
        categories = http_get_json(f"{CATALOG_API}/api/categories")
        products = http_get_json(f"{CATALOG_API}/api/products")
        print(f"Получено: {len(categories)} категорий, {len(products)} товаров")

        pages: list[tuple[str, str]] = [
            ("/", "index.html"),
            ("/catalog", "catalog/index.html"),
            ("/contacts", "contacts/index.html"),
        ]
        for cat in categories:
            pages.append((f"/catalog?category={cat['slug']}",
                          f"catalog/{cat['slug']}/index.html"))
        for prod in products:
            pages.append((f"/product/{prod['id']}",
                          f"product/{prod['id']}/index.html"))
        # Страница 404 (любой несуществующий товар отдаёт шаблон 404)
        pages.append(("/product/999999", "404.html"))

        # Чистая папка docs/
        if DOCS.exists():
            shutil.rmtree(DOCS)
        DOCS.mkdir(parents=True)

        ok, fail = 0, 0
        for url_path, rel_path in pages:
            try:
                html = http_get(f"{GATEWAY}{url_path}")
            except (urllib.error.URLError, OSError) as exc:
                print(f"  ✗ {url_path}: {exc}")
                fail += 1
                continue
            write_page(rel_path, html, base)
            ok += 1

        # GitHub Pages: не применять Jekyll
        (DOCS / ".nojekyll").write_text("", encoding="utf-8")

        print(f"\nГотово: {ok} страниц собрано, ошибок: {fail}")
        print(f"Папка: {DOCS}")
        if base:
            print(f"Префикс ссылок: {base}/")
        return 0 if fail == 0 else 1

    finally:
        print(f"\nОстанавливаю сервисы ({len(started)} шт., запущенные скриптом)...")
        for proc in started:
            kill_tree(proc)
        print("Готово.")


def setup_console() -> None:
    """UTF-8 в консоли Windows — иначе cp1251 роняет ✗/✓/эмодзи."""
    if IS_WINDOWS:
        try:
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except Exception:
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main() -> int:
    setup_console()
    parser = argparse.ArgumentParser(description="Сборка статической копии для GitHub Pages")
    parser.add_argument("--base", default="",
                        help="Префикс пути сайта, например /food-store "
                             "(для user.github.io/food-store); в корень ничего не передавайте")
    args = parser.parse_args()
    base = ("/" + args.base.strip("/")) if args.base.strip("/") else ""
    return build(base)


if __name__ == "__main__":
    sys.exit(main())
