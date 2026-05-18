from sqlalchemy import Column, Integer, String, Text, DateTime, func, Index
from .db import Base

class HSCode(Base):
    __tablename__ = "hs_codes"
    id = Column(Integer, primary_key=True)
    code = Column(String(10), index=True, unique=True)   # 2/4/6/8/10 цифр без точек
    title_ru = Column(String(512))
    title_en = Column(String(512), nullable=True)
    level = Column(String(16))                           # section|chapter|heading|subheading|item
    parent = Column(String(10), index=True, nullable=True)
    chapter = Column(String(2), index=True, nullable=True)
    heading = Column(String(4), index=True, nullable=True)
    subheading = Column(String(10), index=True, nullable=True)
    # Полный «таможенный» текст: склеенный путь от главы к текущему узлу (заполняется ETL).
    title_full = Column(Text, nullable=True)

Index("ix_hs_parent", HSCode.parent)
Index("ix_hs_chapter", HSCode.chapter)

class Note(Base):
    __tablename__ = "notes"
    id = Column(Integer, primary_key=True)
    level = Column(String(16))     # section|chapter
    ref_id = Column(String(8))     # I..XXI или 01..99
    text = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
