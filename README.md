# 🛒 Food Store Microservices — витрина интернет-магазина продуктов

Демонстрационный сайт-витрина (каталог, карточки товаров, категории, карта магазина)
на **микросервисной архитектуре** — три независимых Flask-сервиса в одной папке.
Корзина, заказы и регистрации нет — только витрина ассортимента.

## 📁 Структура проекта

```
food_store_microservices/
│
├── store-config-service/        # ⚙️ Микросервис конфигурации (порт 5001)
│   ├── app.py                   #    Flask-приложение, эндпоинт /api/config
│   ├── config.json              #    ← ЗДЕСЬ МЕНЯЮТСЯ КОНТАКТЫ И КООРДИНАТЫ
│   ├── requirements.txt
│   └── Dockerfile
│
├── catalog-service/             # 📦 Микросервис каталога (порт 5002)
│   ├── app.py                   #    API: /api/categories, /api/products, ...
│   ├── models.py                #    SQLAlchemy-модели Category и Product (SQLite)
│   ├── seeder.py                #    Автозаполнение базы ассортиментом
│   ├── requirements.txt
│   └── Dockerfile
│
├── gateway-frontend/            # 🌐 Веб-витрина / шлюз (порт 5000)
│   ├── app.py                   #    Flask + запросы к двум микросервисам
│   ├── templates/               #    Jinja2 + Tailwind CSS (CDN) + Google Maps
│   │   ├── base.html            #    Layout: шапка, подвал
│   │   ├── index.html           #    Главная: баннер, категории, хиты, карта
│   │   ├── catalog.html         #    Каталог с фильтрами и поиском
│   │   ├── product.html         #    Карточка товара + похожие товары
│   │   ├── contacts.html        #    Контакты + интерактивная карта
│   │   ├── _product_card.html   #    Переиспользуемая карточка товара
│   │   └── 404.html
│   ├── requirements.txt
│   └── Dockerfile
│
├── run_all.py                   # 🚀 Параллельный запуск всех сервисов
├── docker-compose.yml           # 🐳 Альтернатива: запуск через Docker
└── requirements.txt             # Общие зависимости (на выбор)
```

## 🔗 Схема взаимодействия

```
Браузер ──▶ gateway-frontend (5000)
                │
                ├── HTTP GET /api/config ──▶ store-config-service (5001) ──▶ config.json
                │
                └── HTTP GET /api/products ──▶ catalog-service (5002) ──▶ catalog.db (SQLite)
```

Шлюз объединяет данные и рендерит HTML. Падение одного микросервиса не роняет сайт:
страницы отдаются с заглушками (продукты из кеша/пустые списки).

## 🚀 Быстрый старт (Windows / macOS / Linux)

### Вариант A — один скрипт на всё (рекомендуется)

```bash
cd food_store_microservices

# 1. Создать и активировать виртуальное окружение
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

# 2. Установить зависимости
pip install -r requirements.txt

# 3. Запустить все три сервиса сразу
python run_all.py
```

Откройте **http://127.0.0.1:5000** 🎉

### Вариант B — каждый сервис в своём терминале

Откройте **три терминала** из папки проекта и в каждом активируйте окружение:

```bash
# Терминал 1 — конфиг-сервис
cd store-config-service
pip install -r requirements.txt
python app.py          # → http://127.0.0.1:5001

# Терминал 2 — каталог (сам создаст и заполнит catalog.db)
cd catalog-service
pip install -r requirements.txt
python app.py          # → http://127.0.0.1:5002

# Терминал 3 — витрина
cd gateway-frontend
pip install -r requirements.txt
python app.py          # → http://127.0.0.1:5000
```

### Вариант C — Docker Compose

```bash
cd food_store_microservices
docker compose up --build
```

## 🧭 Как изменить данные магазина и координаты

Откройте файл **`store-config-service/config.json`** и отредактируйте:

```json
{
  "store_name": "FreshMarket",
  "address": "г. Москва, ул. Разработчиков, д. 1, к. 2",
  "phone": "+7 (999) 123-45-67",
  "latitude": 55.751244,     // ← широта метки на карте
  "longitude": 37.618423,    // ← долгота метки на карте
  "google_maps_api_key": "",  // ← необязательный ключ Google Maps API
  "social_links": {
    "telegram": "",           // ← сюда вставить ссылку на Telegram-канал
    "max": ""                 // ← сюда вставить ссылку на канал в Max
  },
  "supplier_link": ""          // ← ссылка с плашки «Ищите поставщика в ресторан?»
}
```

Файл читается **на каждый запрос API**, поэтому после сохранения достаточно
обновить страницу `/contacts` — карта **Google Maps** покажет новые координаты.
Перезапускать сервис не нужно.

По умолчанию карта встраивается iframe-эмбедом Google Maps (без API-ключа).
Если есть свой ключ Google Maps API — впишите его в `google_maps_api_key`
в том же файле, и карта переключится на официальный Map Embeds API.

## 📡 API микросервисов

### store-config-service (5001)

| Метод | Путь              | Описание                                  |
|-------|-------------------|-------------------------------------------|
| GET   | `/api/health`     | Health-check                              |
| GET   | `/api/config`     | Полный конфиг магазина (JSON)             |
| GET   | `/api/coordinates`| Только координаты и адрес                  |

### catalog-service (5002)

| Метод | Путь                             | Описание                                          |
|-------|----------------------------------|---------------------------------------------------|
| GET   | `/api/health`                    | Health-check                                      |
| GET   | `/api/categories`                | Список категорий                                  |
| GET   | `/api/products`                  | Товары. Параметры: `?category=<slug>&q=<поиск>&hits=true` |
| GET   | `/api/products/<id>`             | Карточка товара                                   |
| GET   | `/api/products/<id>/related`     | Похожие товары той же категории                   |

Примеры:

```bash
curl http://127.0.0.1:5002/api/products?category=fruits
curl http://127.0.0.1:5002/api/products?q=сыр
curl http://127.0.0.1:5002/api/products?hits=true
```

## 🗄️ База данных каталога

* SQLite, файл `catalog-service/catalog.db` создаётся автоматически.
* Модели: `Category` (slug, name, description, image) и
  `Product` (name, price, weight, description, image, is_hit, origin, category_id).
* Сидер (`seeder.py`) заполняет базу **30 товарами** в 5 категориях:
  овощи, фрукты и ягоды, молочные продукты, выпечка, напитки.
* Полная пересоздация базы: `cd catalog-service && python seeder.py`.

## 🎨 Что используется на фронтенде

* **Tailwind CSS (CDN)** — стилизация без сборки;
* **Jinja2** — шаблоны и наследование layout;
* **Google Maps** — интерактивная карта с меткой магазина (iframe-эмбед);
* Картинки товаров — прямые ссылки с **Unsplash** (с плейсхолдером-фолбэком).

## 🛡️ Устойчивость шлюза

* Таймауты HTTP-запросов к микросервисам — 3 с.
* Конфиг магазина кешируется на 60 с в памяти шлюза.
* Если `catalog-service` недоступен — каталог покажет дружелюбную заглушку,
  а не ошибку 500. Если недоступен `store-config-service` — используются
  резервные значения конфига из кода шлюза.
