"""
catalog-service: модели SQLAlchemy + подключение к SQLite.

База данных catalog.db создаётся автоматически в папке сервиса.
"""

from pathlib import Path

from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "catalog.db"

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    echo=False,
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

Base = declarative_base()


class Category(Base):
    """Категория каталога (овощи, фрукты, молочка...)."""

    __tablename__ = "categories"

    id = Column(Integer, primary_key=True)
    slug = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(120), nullable=False)
    description = Column(String(255), default="")
    image = Column(String(512), default="")

    products = relationship("Product", back_populates="category", lazy="selectin")

    def to_dict(self, with_products: bool = False) -> dict:
        data = {
            "id": self.id,
            "slug": self.slug,
            "name": self.name,
            "description": self.description,
            "image": self.image,
        }
        if with_products:
            data["products"] = [p.to_dict() for p in self.products]
        return data


class Product(Base):
    """Товар витрины: название, цена, вес, описание, картинка, флаг хита."""

    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    name = Column(String(160), nullable=False, index=True)
    slug = Column(String(180), unique=True, nullable=False)
    price = Column(Float, nullable=False)          # руб. за единицу
    weight = Column(String(64), default="")        # "1 кг", "500 г", "1 л"
    description = Column(Text, default="")
    image = Column(String(512), default="")
    is_hit = Column(Boolean, default=False)        # флаг «хит продаж»
    origin = Column(String(120), default="")       # страна/регион происхождения

    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False)
    category = relationship("Category", back_populates="products")

    def to_dict(self, with_category: bool = True) -> dict:
        data = {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "price": self.price,
            "weight": self.weight,
            "description": self.description,
            "image": self.image,
            "is_hit": self.is_hit,
            "origin": self.origin,
            "category_id": self.category_id,
        }
        if with_category and self.category is not None:
            data["category"] = self.category.to_dict()
        return data


def init_db() -> None:
    """Создаёт таблицы, если базы ещё нет."""
    Base.metadata.create_all(engine)
