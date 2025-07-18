# app/normalization.py
import pandas as pd
import re
import logging
from pathlib import Path
import hashlib
from app.config import settings
from app.database import SessionLocal
from app.models import Lead
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import text
import numpy as np
import os
import csv
from datetime import datetime

logger = logging.getLogger(__name__)

class DataNormalizer:
    def __init__(self):
        self.phone_pattern = re.compile(r'[^\d]')
        self.inn_pattern = re.compile(r'^\d{10,12}$')
        self.batch_size = settings.BATCH_SIZE

    def normalize_phone(self, phone: str) -> str:
        """Нормализация телефона к формату +7XXXXXXXXXX"""
        if pd.isna(phone) or not phone:
            return None
            
        phone = self.phone_pattern.sub('', str(phone))
        
        if phone.startswith('8') and len(phone) == 11:
            phone = '7' + phone[1:]
        
        if phone.startswith('7') and len(phone) == 11:
            return f'+{phone}'
        
        if len(phone) == 10:
            return f'+7{phone}'
            
        return None
    
    def normalize_fio(self, fio: str) -> str:
        """Нормализация ФИО"""
        if pd.isna(fio) or not fio:
            return None
            
        fio = re.sub(r'\s+', ' ', str(fio).strip())
        parts = fio.split()
        if len(parts) < 2:
            return fio.title()
            
        # Восстановление полного ФИО: Фамилия Имя Отчество
        last_name = parts[0].title()
        first_name = parts[1].title() if len(parts) > 1 else ""
        patronymic = parts[2].title() if len(parts) > 2 else ""
        
        return f"{last_name} {first_name} {patronymic}".strip()
    
    def validate_inn(self, inn: str) -> bool:
        """Валидация ИНН"""
        if pd.isna(inn) or not inn:
            return False
        return bool(self.inn_pattern.match(str(inn)))
    
    def _generate_lead_id(self, row: dict) -> str:
        """Генерация уникального ID для лида с использованием хеширования"""
        base = f"{row.get('fio', '')}{row.get('phone', '')}{row.get('inn', '')}"
        return hashlib.md5(base.encode('utf-8')).hexdigest()
    
    def normalize_row(self, row: dict, source: str) -> dict:
        """Нормализация одной строки данных"""
        normalized = {
            'fio': self.normalize_fio(row.get('fio')),
            'phone': self.normalize_phone(row.get('phone')),
            'inn': str(row.get('inn')).strip() if row.get('inn') else None,
            'dob': row.get('dob'),
            'address': row.get('address'),
            'source': source,
            'tags': row.get('tags'),
            'email': row.get('email'),
            'created_at': row.get('created_at')
        }
        
        # Генерация lead_id после нормализации
        normalized['lead_id'] = self._generate_lead_id(normalized)
        return normalized
    
    def bulk_insert_leads(self, leads: list):
        """Массовая вставка лидов в БД с обработкой дубликатов"""
        if not leads:
            return
            
        db = SessionLocal()
        try:
            # Используем bulk insert с обработкой конфликтов
            stmt = insert(Lead).values(leads)
            stmt = stmt.on_conflict_do_nothing(index_elements=['lead_id'])
            db.execute(stmt)
            db.commit()
            logger.info(f"Inserted {len(leads)} leads into database")
        except Exception as e:
            db.rollback()
            logger.error(f"Ошибка при вставке данных: {e}")
        finally:
            db.close()
    
    def _get_column_mapping(self, source: str) -> dict:
        """Маппинг колонок для разных источников"""
        mappings = {
            'leads': {
                'ФИО': 'fio',
                'Телефон': 'phone',
                'Дата согласия': 'created_at',
                'Email': 'email',
                'Источник': 'tags'
            },
            'fns': {
                'ИНН': 'inn',
                'ФИО': 'fio',
                'Телефон': 'phone',
                'Дата рождения': 'dob'
            },
            'gosuslugi': {
                'ИНН': 'inn',
                'ФИО': 'fio',
                'Адрес': 'address',
                'Телефон': 'phone',
                'Email': 'email',
                'Регион': 'tags'
            },
            'delivery': {
                'Телефон': 'phone',
                'Адрес': 'address',
                'Имя': 'fio',
                'Последний заказ': 'created_at'
            },
            'bank': {
                'ИНН': 'inn',
                'ФИО': 'fio',
                'Телефон': 'phone',
                'Email': 'email',
                'Сумма кредита': 'debt_amount',
                'Статус': 'tags'
            },
            'insurance': {
                'ФИО': 'fio',
                'Телефон': 'phone',
                'Дата рождения': 'dob',
                'Адрес': 'address',
                'Тип полиса': 'tags',
                'Сумма страховки': 'debt_amount'
            },
            'mfo': {
                'ФИО': 'fio',
                'Телефон': 'phone',
                'ИНН': 'inn',
                'Сумма займа': 'debt_amount',
                'Дата займа': 'created_at',
                'Статус погашения': 'tags',
                'Просрочка дней': 'debt_count'
            }
        }
        return mappings.get(source, {})
    
    def _detect_source(self, filename: str) -> str:
        """Определение источника по имени файла"""
        filename_lower = filename.lower()
        
        if 'fns' in filename_lower or 'налог' in filename_lower:
            return 'fns'
        elif 'gosuslugi' in filename_lower or 'госуслуги' in filename_lower:
            return 'gosuslugi'
        elif 'delivery' in filename_lower or 'еда' in filename_lower or 'доставка' in filename_lower:
            return 'delivery'
        elif 'bank' in filename_lower or 'банк' in filename_lower:
            return 'bank'
        elif 'insurance' in filename_lower or 'страхов' in filename_lower:
            return 'insurance'
        elif 'mfo' in filename_lower or 'мфо' in filename_lower:
            return 'mfo'
        else:
            return 'leads'
    
    def process_file(self, file_path: Path):
        """Потоковая обработка CSV файла"""
        source = self._detect_source(file_path.name)
        column_mapping = self._get_column_mapping(source)
        batch = []
        
        try:
            # Получаем размер файла для прогресса
            file_size = os.path.getsize(file_path)
            processed_bytes = 0
            
            # Используем chunksize для обработки больших файлов
            for chunk in pd.read_csv(file_path, chunksize=10000, dtype=str, encoding='utf-8', quoting=csv.QUOTE_MINIMAL):
                chunk = chunk.rename(columns=column_mapping)
                for _, row in chunk.iterrows():
                    try:
                        normalized_row = self.normalize_row(row.to_dict(), source)
                        if normalized_row['fio']:  # Пропускаем записи без ФИО
                            batch.append(normalized_row)
                            
                            # Вставляем батч при достижении размера
                            if len(batch) >= self.batch_size:
                                self.bulk_insert_leads(batch)
                                batch = []
                    except Exception as e:
                        logger.warning(f"Ошибка при обработке строки: {e}")
                
                # Обновление прогресса
                processed_bytes += chunk.memory_usage(index=True, deep=True).sum()
                progress = min(100, int(processed_bytes / file_size * 100))
                logger.info(f"File {file_path.name}: {progress}% processed")
            
            # Вставка оставшихся данных
            if batch:
                self.bulk_insert_leads(batch)
            
            return True
        except Exception as e:
            logger.error(f"Ошибка при обработке файла {file_path}: {e}")
            return False
    
    def process_all_files(self, input_path: str):
        """Обработка всех файлов в папке"""
        file_count = 0
        processed_count = 0
        input_path = Path(input_path)
        
        if not input_path.exists():
            logger.error(f"Input path does not exist: {input_path}")
            return 0
        
        for file_path in input_path.glob("*.csv"):
            if not file_path.is_file():
                continue
                
            logger.info(f"Начата обработка файла: {file_path.name}")
            if self.process_file(file_path):
                processed_count += 1
            file_count += 1
            
        logger.info(f"Обработано файлов: {processed_count}/{file_count}")
        return processed_count
    