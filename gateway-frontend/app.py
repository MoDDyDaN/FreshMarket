"""
gateway-frontend (порт 5000)
Главный веб-интерфейс витрины. Шлюз объединяет данные двух микросервисов:
  - store-config-service (5001) — конфиг магазина, контакты, координаты;
  - catalog-service     (5002) — категории и товары из SQLite.

Страницы:
  /               — главная: баннер, категории, хиты, блок с картой;
  /catalog        — каталог с фильтрами по категории и поиском;
  /product/<id>   — подробная карточка товара;
  /contacts       — интерактивная карта (Leaflet/OSM) с меткой магазина.

Клиентские вызовы защищены таймаутами и кешем: падение одного сервиса
не роняет весь сайт (страницы рендерятся с пустыми данными/заглушкой).
"""

import os
import time

import requests
from flask import Flask, abort, render_template, request

app = Flask(__name__)

CONFIG_URL = os.environ.get("CONFIG_SERVICE_URL", "http://127.0.0.1:5001")
CATALOG_URL = os.environ.get("CATALOG_SERVICE_URL", "http://127.0.0.1:5002")
HTTP_TIMEOUT = 3  # секунды — быстрый таймаут, чтобы шлюз не зависал

# Резервный конфиг на случай, если store-config-service недоступен.
# Координаты совпадают с store-config-service/config.json по умолчанию.
FALLBACK_STORE = {
    "store_name": "FreshMarket",
    "tagline": "Свежие продукты каждый день",
    "address": "адрес недоступен — запустите store-config-service",
    "phone": "—",
    "email": "—",
    "working_hours": {"weekdays": "—", "weekends": "—", "delivery": "—"},
    "latitude": 55.751244,
    "longitude": 37.618423,
    "social_links": {"telegram": "", "max": ""},
    "supplier_link": "",
    "developer": {"name": "Ashot", "role": "System Architect"},
}

# ----------------------------- клиенты микросервисов -----------------------------

_store_cache = {"data": None, "ts": 0.0}
_STORE_CACHE_TTL = 60  # секунд — кеш конфига, чтобы не дёргать сервис на каждый рендер


def get_store_config() -> dict:
    """Конфиг магазина из store-config-service (с минутным кешем и заглушкой)."""
    now = time.monotonic()
    if _store_cache["data"] is not None and now - _store_cache["ts"] < _STORE_CACHE_TTL:
        return _store_cache["data"]

    try:
        resp = requests.get(f"{CONFIG_URL}/api/config", timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        data = dict(FALLBACK_STORE)

    _store_cache["data"] = data
    _store_cache["ts"] = now
    return data


def _catalog_get(path: str, params: dict | None = None) -> list | dict | None:
    """Базовый GET к catalog-service. При ошибке возвращает None."""
    try:
        resp = requests.get(f"{CATALOG_URL}{path}", params=params, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError):
        return None


# ----------------------------- контекст шаблонов -----------------------------


def google_map_embed_url(store: dict) -> str:
    """
    URL iframe-эмбеда Google Maps по координатам из конфига магазина.

    * С ключом (поле google_maps_api_key) — официальный Google Map Embeds API;
    * без ключа — универсальный эмбед Google Maps, который работает сразу.

    Смена latitude/longitude в config.json автоматически меняет метку на карте.
    """
    lat, lon = store.get("latitude"), store.get("longitude")
    key = (store.get("google_maps_api_key") or "").strip()
    if key:
        return f"https://www.google.com/maps/embed/v1/place?key={key}&q={lat},{lon}&zoom=15"
    return f"https://maps.google.com/maps?q={lat},{lon}&z=15&output=embed"


@app.context_processor
def inject_store():
    """Доступ к конфигу магазина в любом шаблоне (название, телефон...)."""
    store = get_store_config()
    return {
        "store": store,
        "working_hours": store.get("working_hours", {}),
        "map_url": google_map_embed_url(store),
        "social": store.get("social_links") or {},
        "supplier_link": (store.get("supplier_link") or "").strip(),
    }


# ----------------------------- маршруты -----------------------------


@app.route("/")
def index():
    """Главная: баннер + категории + хиты + карта."""
    categories = _catalog_get("/api/categories") or []
    hits = _catalog_get("/api/products", params={"hits": "true"}) or []
    return render_template(
        "index.html",
        categories=categories,
        hits=hits[:8],
        page_title="Главная",
    )


@app.route("/catalog")
def catalog():
    """Каталог: все товары + фильтр по категории + поиск."""
    category_slug = request.args.get("category", "").strip()
    query_text = request.args.get("q", "").strip()

    params = {}
    if category_slug:
        params["category"] = category_slug
    if query_text:
        params["q"] = query_text

    products = _catalog_get("/api/products", params=params)
    if products is None:
        products = []  # каталог-сервис недоступен — покажем пустую витрину

    categories = _catalog_get("/api/categories") or []
    active_category = next((c for c in categories if c["slug"] == category_slug), None)

    return render_template(
        "catalog.html",
        products=products,
        categories=categories,
        active_slug=category_slug,
        active_category=active_category,
        query=query_text,
        page_title=active_category["name"] if active_category else "Каталог",
    )


@app.route("/product/<int:product_id>")
def product(product_id: int):
    """Карточка товара + блок похожих."""
    data = _catalog_get(f"/api/products/{product_id}")
    if data is None or "error" in data:
        abort(404)

    related = _catalog_get(f"/api/products/{product_id}/related") or []
    return render_template(
        "product.html",
        product=data,
        related=related,
        page_title=data["name"],
    )


@app.route("/contacts")
def contacts():
    """Контакты + интерактивная карта по координатам из конфига."""
    return render_template("contacts.html", page_title="Контакты")


@app.errorhandler(404)
def not_found(_error):
    return render_template("404.html", page_title="Страница не найдена"), 404


if __name__ == "__main__":
    port = int(os.environ.get("GATEWAY_PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"  # лаунчер ставит 0 — без reloader
    print(f"gateway-frontend running on http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=debug)
