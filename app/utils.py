import pandas as pd
import logging
from typing import List, Dict
from pathlib import Path
import csv
from datetime import datetime
from app.database import AsyncSessionLocal, engine
import os
import json
import asyncio
from sqlalchemy import text
import aiofiles
from app.config import settings
from app.models import ErrorLog
import shutil

logger = logging.getLogger(__name__)

class FileManager:
    def __init__(self):
        self.ensure_directories()
    
    def ensure_directories(self):
        """Создание необходимых директорий"""
        Path(settings.INPUT_DATA_PATH).mkdir(parents=True, exist_ok=True)
        Path(settings.OUTPUT_DATA_PATH).mkdir(parents=True, exist_ok=True)
        Path(settings.LOGS_PATH).mkdir(parents=True, exist_ok=True)
    
    async def export_target_leads(self, filename: str = 'scoring_ready.csv') -> str:
        """Экспорт целевых лидов в CSV с использованием потоковой выгрузки"""
        output_path = Path(settings.OUTPUT_DATA_PATH) / filename
        temp_path = output_path.with_suffix('.tmp')
        
        try:
            # Используем серверную выгрузку данных
            async with engine.connect() as conn:
                result = await conn.stream(
                    text("""
                    SELECT phone, fio, score, reason_1, reason_2, reason_3, group_name as group
                    FROM leads 
                    WHERE is_target = TRUE 
                    ORDER BY score DESC
                    """)
                )
                
                # Потоковая запись в CSV
                async with aiofiles.open(temp_path, 'w', encoding='utf-8', newline='') as f:
                    writer = csv.writer(f)
                    await writer.writerow(['phone', 'fio', 'score', 'reason_1', 'reason_2', 'reason_3', 'group'])
                    
                    batch = []
                    async for row in result:
                        batch.append(tuple(row))
                        if len(batch) >= 10000:
                            await writer.writerows(batch)
                            batch = []
                    
                    if batch:
                        await writer.writerows(batch)
                
            # Переименовываем после успешной записи
            shutil.move(temp_path, output_path)
            return str(output_path)
            
        except Exception as e:
            logger.error(f"Ошибка при экспорте данных: {e}")
            if os.path.exists(temp_path):
                os.remove(temp_path)
            return None

    def get_input_files_info(self) -> List[dict]:
        """Получение информации о загруженных файлах"""
        files_info = []
        input_path = Path(settings.INPUT_DATA_PATH)
        
        for file_path in input_path.glob("*.csv"):
            try:
                file_info = {
                    'filename': file_path.name,
                    'path': str(file_path),
                    'size_mb': os.path.getsize(file_path) / (1024 * 1024),
                    'last_modified': datetime.fromtimestamp(os.path.getmtime(file_path)).isoformat(),
                    'source': self._detect_source(file_path.name)
                }
                files_info.append(file_info)
            except Exception as e:
                logger.error(f"Ошибка при получении информации о файле {file_path}: {e}")
        
        return files_info
    
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

class LogManager:
    def __init__(self):
        self.setup_logging()
    
    def setup_logging(self):
        """Настройка логирования"""
        log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        log_file = Path(settings.LOGS_PATH) / 'scoring.log'
        
        # Логи в файл
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(logging.Formatter(log_format))
        
        # Логи в консоль
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter(log_format))
        
        # Настройка корневого логгера
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        root_logger.addHandler(file_handler)
        root_logger.addHandler(console_handler)
    
    async def get_error_logs(self, limit: int = 100) -> List[dict]:
        """Получение логов ошибок"""
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                text("""
                SELECT timestamp, source, error_type, error_message, lead_id 
                FROM error_logs 
                ORDER BY timestamp DESC 
                LIMIT :limit
                """),
                {'limit': limit}
            )
            logs = result.mappings().all()
            return [dict(log) for log in logs]
    
    async def log_error(self, source: str, error_type: str, message: str, lead_id: str = None):
        """Логирование ошибок в базу данных"""
        async with AsyncSessionLocal() as db:
            error_log = ErrorLog(
                source=source,
                error_type=error_type,
                error_message=message,
                lead_id=lead_id
            )
            db.add(error_log)
            await db.commit()

class PipelineManager:
    def __init__(self):
        self.stages = {
            'normalization': self.run_normalization,
            'enrichment': self.run_enrichment,
            'scoring': self.run_scoring,
            'export': self.run_export
        }
        self.file_manager = FileManager()
        self.log_manager = LogManager()
    
    def run_normalization(self):
        from app.normalization import DataNormalizer
        normalizer = DataNormalizer()
        return normalizer.process_all_files(settings.INPUT_DATA_PATH)
    
    async def run_enrichment(self):
        from app.external_sources import ExternalDataEnricher
        enricher = ExternalDataEnricher()
        await enricher.enrich_all_leads()
    
    async def run_scoring(self, filters: dict):
        from app.scoring import ScoringProcessor
        processor = ScoringProcessor()
        await processor.process_all_leads(filters)
    
    async def run_export(self):
        return await self.file_manager.export_target_leads()
    
    async def get_database_stats(self) -> dict:
        """Получение статистики по базе данных"""
        async with AsyncSessionLocal() as db:
            # Общее количество лидов
            result = await db.execute(text("SELECT COUNT(*) FROM leads"))
            total_leads = result.scalar()
            
            # Количество обогащенных лидов
            result = await db.execute(text("SELECT COUNT(*) FROM leads WHERE debt_amount IS NOT NULL"))
            enriched_leads = result.scalar()
            
            # Количество лидов со скорингом
            result = await db.execute(text("SELECT COUNT(*) FROM leads WHERE score IS NOT NULL"))
            scored_leads = result.scalar()
            
            # Количество целевых лидов
            result = await db.execute(text("SELECT COUNT(*) FROM leads WHERE is_target = TRUE"))
            target_leads = result.scalar()
            
            return {
                'total_leads': total_leads,
                'enriched_leads': enriched_leads,
                'scored_leads': scored_leads,
                'target_leads': target_leads
            }
            