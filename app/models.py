# app/models.py
from sqlalchemy import Column, Integer, String, Float, Boolean, Text, DateTime, func
from sqlalchemy.ext.declarative import declarative_base
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

Base = declarative_base()

class Lead(Base):
    __tablename__ = "leads"
    
    lead_id = Column(String(50), primary_key=True)
    fio = Column(String(255), nullable=False)
    phone = Column(String(20))
    inn = Column(String(12))
    dob = Column(String(10))
    address = Column(Text)
    source = Column(String(50))
    created_at = Column(DateTime, default=func.now())
    tags = Column(String(255))
    email = Column(String(255))
    
    # Enriched data
    debt_amount = Column(Float, default=0.0)
    debt_type = Column(String(50))
    creditor = Column(String(255))
    debt_count = Column(Integer, default=0)
    has_property = Column(Boolean, default=False)
    has_court_order = Column(Boolean, default=False)
    is_bankrupt = Column(Boolean, default=False)
    inn_active = Column(Boolean, default=True)
    tax_debt_amount = Column(Float, default=0.0)
    
    # Scoring
    score = Column(Float)
    is_target = Column(Boolean, default=False)
    reason_1 = Column(String(255))
    reason_2 = Column(String(255))
    reason_3 = Column(String(255))
    group_name = Column(String(50))
    
    # Processing metadata
    processed_at = Column(DateTime)
    last_updated = Column(DateTime, default=func.now(), onupdate=func.now())

class ScoringHistory(Base):
    __tablename__ = "scoring_history"
    
    id = Column(Integer, primary_key=True)
    lead_id = Column(String(50))
    scoring_date = Column(DateTime, default=func.now())
    score = Column(Float)
    group_name = Column(String(50))
    reason_1 = Column(String(255))
    filters_used = Column(Text)
    processing_time_ms = Column(Integer)

class ErrorLog(Base):
    __tablename__ = "error_logs"
    
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=func.now())
    source = Column(String(50))
    error_type = Column(String(50))
    error_message = Column(Text)
    lead_id = Column(String(50))
    retry_count = Column(Integer, default=0)

# Pydantic models for API
class LeadBase(BaseModel):
    fio: str
    phone: Optional[str] = None
    inn: Optional[str] = None
    dob: Optional[str] = None
    address: Optional[str] = None
    source: str
    tags: Optional[str] = None
    email: Optional[str] = None

class ScoringRequest(BaseModel):
    regions: List[str]
    min_debt_amount: int = 250000
    exclude_bankrupts: bool = True
    exclude_no_debt: bool = True
    only_with_property: bool = False
    only_bank_mfo_debt: bool = False
    only_recent_court_orders: bool = False
    only_active_inn: bool = True
    