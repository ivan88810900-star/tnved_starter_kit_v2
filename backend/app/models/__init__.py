from sqlalchemy import Column, Integer, String, Text, Float, DateTime
from sqlalchemy.sql import func
from ..db import Base
from ..models_hs import HSCode, Note  # re-export for tests expecting these in models

# HSCode and Note models moved to models_hs.py

class TariffRate(Base):
    __tablename__ = "tariff_rates"
    id = Column(Integer, primary_key=True)
    hs_code = Column(String(20), index=True)
    duty = Column(String(50))  # Таможенная пошлина
    vat = Column(String(50))   # НДС
    add = Column(String(50), nullable=True)  # Дополнительные сборы
    source_version = Column(String(20))

class DataSource(Base):
    __tablename__ = "data_sources"
    id = Column(Integer, primary_key=True)
    key = Column(String(100), unique=True)
    version = Column(String(20))
    authority = Column(String(100))
    url = Column(String(500))
    checksum = Column(String(64))
    imported_at = Column(DateTime, default=func.now())

class NTMMeasure(Base):
    __tablename__ = "ntm_measures"
    id = Column(Integer, primary_key=True)
    hs_code_prefix = Column(String(10), index=True)
    title = Column(String(200))
    basis = Column(String(100))
    country = Column(String(50), nullable=True)
    notes = Column(Text)

class EcoRate(Base):
    __tablename__ = "eco_rates"
    id = Column(Integer, primary_key=True)
    material = Column(String(100))
    category = Column(String(50))
    rate_per_kg = Column(Float)
    basis = Column(String(100))

from .tnved import Chapter, Commodity, Section  # noqa: E402  — регистрация таблиц ТН ВЭД
