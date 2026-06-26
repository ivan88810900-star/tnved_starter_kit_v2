import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

load_dotenv()

DB_URL = os.getenv("DB_URL", "sqlite:///./tnved.db")

engine = create_engine(DB_URL, echo=False, future=True, connect_args={"check_same_thread": False})
print("[DB] engine url:", engine.url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

def init_db():
    # Импортируем все модели для регистрации в Base.metadata (в т.ч. app.models.tnved)
    from . import models_hs, models, models_vat  # noqa: F401
    # Создаем все таблицы
    Base.metadata.create_all(bind=engine)

def get_db():
    """Зависимость FastAPI для предоставления сессии БД в обработчиках."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
