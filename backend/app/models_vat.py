from sqlalchemy import Column, Integer, String, Text, DateTime, func, Index
from .db import Base


class VatRule(Base):
    __tablename__ = "vat_rules"
    id = Column(Integer, primary_key=True)
    code_prefix = Column(String(10), index=True)   # 2/4/6/8/10 – без точек
    rate = Column(Integer)                         # 0, 10, 20
    source = Column(String(64))                    # "PP-908", "PP-688", "PP-1042", etc.
    title = Column(String(512))                    # наименование из перечня
    note = Column(Text, nullable=True)


Index("ix_vat_rules_prefix", VatRule.code_prefix)





