"""
catalog-service (порт 5002)
Микросервис каталога: категории и товары из собственной базы SQLite.

API:
  GET /api/health                — health-check
  GET /api/categories            — список категорий
  GET /api/products              — список товаров (?category=<slug>&q=<поиск>&hits=true)
  GET /api/products/<id>         — карточка товара
  GET /api/products/<id>/related — похожие товары из той же категории
"""

import os

from flask import Flask, jsonify, request

from models import Category, Product, SessionLocal
from seeder import seed

app = Flask(__name__)


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "service": "catalog-service"})


@app.route("/api/categories")
def categories():
    """Все категории каталога."""
    session = SessionLocal()
    try:
        items = session.query(Category).order_by(Category.name).all()
        return jsonify([c.to_dict() for c in items])
    finally:
        session.close()


@app.route("/api/products")
def products():
    """
    Товары с фильтрами:
      ?category=<slug> — фильтр по категории,
      ?q=<текст>       — поиск по названию/описанию,
      ?hits=true       — только хиты продаж.
    """
    category_slug = request.args.get("category", "").strip()
    query_text = request.args.get("q", "").strip()
    hits_only = request.args.get("hits", "").lower() in ("true", "1", "yes")

    session = SessionLocal()
    try:
        query = session.query(Product)

        if category_slug:
            query = query.join(Category).filter(Category.slug == category_slug)
        if query_text:
            like = f"%{query_text}%"
            query = query.filter(Product.name.ilike(like) | Product.description.ilike(like))
        if hits_only:
            query = query.filter(Product.is_hit.is_(True))

        items = query.order_by(Product.is_hit.desc(), Product.name).all()
        return jsonify([p.to_dict() for p in items])
    finally:
        session.close()


@app.route("/api/products/<int:product_id>")
def product_detail(product_id: int):
    """Подробная карточка товара."""
    session = SessionLocal()
    try:
        product = session.get(Product, product_id)
        if product is None:
            return jsonify({"error": "Product not found"}), 404
        return jsonify(product.to_dict())
    finally:
        session.close()


@app.route("/api/products/<int:product_id>/related")
def product_related(product_id: int):
    """До 4 похожих товаров из той же категории (для блока «Похожие товары»)."""
    session = SessionLocal()
    try:
        product = session.get(Product, product_id)
        if product is None:
            return jsonify({"error": "Product not found"}), 404

        related = (
            session.query(Product)
            .filter(Product.category_id == product.category_id, Product.id != product.id)
            .limit(4)
            .all()
        )
        return jsonify([p.to_dict() for p in related])
    finally:
        session.close()


if __name__ == "__main__":
    seed()  # авто-сид при первом запуске
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"  # лаунчер ставит 0 — без reloader
    print("catalog-service running on http://127.0.0.1:5002")
    app.run(host="127.0.0.1", port=5002, debug=debug)
