from sqlalchemy import Column, String, Float, Boolean, Text, DateTime, Integer, func, Date
from sqlalchemy.ext.declarative import declarative_base
from app.database import Base
from pydantic import BaseModel
from typing import Optional, List

class Lead(Base):
    __tablename__ = "leads"
    
    lead_id = Column(String(50), primary_key=True)
    fio = Column(String(255), nullable=False)
    phone = Column(String(20))
    inn = Column(String(12))
    dob = Column(Date)
    address = Column(Text)
    source = Column(String(50))
    created_at = Column(DateTime, default=func.now())
    tags = Column(String(255))
    email = Column(String(255))
    
    # Обогащенные данные
    debt_amount = Column(Float, default=0.0)
    debt_type = Column(String(50))
    creditor = Column(String(255))
    debt_count = Column(Integer, default=0)
    has_property = Column(Boolean, default=False)
    has_court_order = Column(Boolean, default=False)
    court_order_date = Column(Date)
    is_bankrupt = Column(Boolean, default=False)
    bankruptcy_date = Column(Date)
    inn_active = Column(Boolean, default=True)
    tax_debt_amount = Column(Float, default=0.0)
    
    # Результаты скоринга
    score = Column(Float)
    is_target = Column(Boolean, default=False)
    reason_1 = Column(String(255))
    reason_2 = Column(String(255))
    reason_3 = Column(String(255))
    group_name = Column(String(50))
    
    # Метаданные обработки
    processed_at = Column(DateTime)
    last_updated = Column(DateTime, default=func.now(), onupdate=func.now())

class ScoringHistory(Base):
    __tablename__ = "scoring_history"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(String(50))
    scoring_date = Column(DateTime, default=func.now())
    score = Column(Float)
    group_name = Column(String(50))
    reason_1 = Column(String(255))
    filters_used = Column(Text)
    processing_time_ms = Column(Integer)

class ErrorLog(Base):
    __tablename__ = "error_logs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=func.now())
    source = Column(String(50))
    error_type = Column(String(50))
    error_message = Column(Text)
    lead_id = Column(String(50))
    retry_count = Column(Integer, default=0)

# Pydantic модели для API
class ScoringRequest(BaseModel):
    regions: List[str] = []
    min_debt_amount: int = 250000
    exclude_bankrupts: bool = True
    exclude_no_debt: bool = True
    only_with_property: bool = False
    only_bank_mfo_debt: bool = False
    only_recent_court_orders: bool = False
    only_active_inn: bool = True

class StatusResponse(BaseModel):
    status: str
    progress: int
    stage: str
    message: str
    duration: float
    result: Optional[dict] = None
    