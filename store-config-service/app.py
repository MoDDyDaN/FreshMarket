"""
store-config-service (порт 5001)
Микросервис конфигурации магазина: контакты, часы работы и координаты разработчика.

Все данные хранятся в файле config.json рядом с этим скриптом —
разработчик может легко изменить адрес и координаты карты, не трогая код.
"""

import json
import os
from pathlib import Path

from flask import Flask, jsonify

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"

app = Flask(__name__)


def load_config() -> dict:
    """Читает конфиг магазина из config.json (каждый запрос — свежие данные)."""
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        return json.load(fh)


@app.route("/api/health")
def health():
    """Health-check для скрипта запуска и мониторинга."""
    return jsonify({"status": "ok", "service": "store-config-service"})


@app.route("/api/config")
def get_config():
    """
    Отдаёт конфигурацию магазина:
    название, адрес, контакты, часы работы и координаты (latitude / longitude).
    """
    try:
        return jsonify(load_config())
    except FileNotFoundError:
        return jsonify({"error": "config.json not found"}), 500
    except json.JSONDecodeError as exc:
        return jsonify({"error": f"Invalid config.json: {exc}"}), 500


@app.route("/api/coordinates")
def get_coordinates():
    """Мини-эндPOINT только с координатами — удобно для карты."""
    cfg = load_config()
    return jsonify(
        {
            "latitude": cfg.get("latitude"),
            "longitude": cfg.get("longitude"),
            "address": cfg.get("address"),
        }
    )


if __name__ == "__main__":
    port = int(load_config().get("service_port", 5001))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"  # лаунчер ставит 0 — без reloader
    print(f"store-config-service running on http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=debug)
