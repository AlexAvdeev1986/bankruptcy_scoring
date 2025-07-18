# app/external_sources.py
import aiohttp
import asyncio
import random
import logging
from typing import Dict, List, Optional
from fake_useragent import UserAgent
from app.config import settings
from app.database import AsyncSessionLocal, SessionLocal
from app.models import Lead, ErrorLog
import backoff
import json
from datetime import datetime
import re

logger = logging.getLogger(__name__)

class ExternalDataEnricher:
    def __init__(self):
        self.ua = UserAgent()
        self.proxies = self._load_proxies()
        self.session = None
        self.semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_REQUESTS)
        self.batch_size = settings.BATCH_SIZE
        self.total_enriched = 0

    def _load_proxies(self) -> List[str]:
        """Загрузка списка прокси из файла или БД"""
        # В реальной системе загрузка из внешнего источника
        return [f"http://proxy{i}:8080" for i in range(1, 301)]
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Получение сессии с ротацией прокси"""
        if self.session is None or self.session.closed:
            headers = {'User-Agent': self.ua.random}
            
            connector = aiohttp.TCPConnector(limit_per_host=20)
            timeout = aiohttp.ClientTimeout(total=settings.REQUEST_TIMEOUT)
            
            self.session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers=headers
            )
        return self.session

    @backoff.on_exception(backoff.expo,
                          (aiohttp.ClientError, asyncio.TimeoutError),
                          max_tries=settings.MAX_RETRIES)
    async def safe_request(self, url: str, params: dict) -> dict:
        """Безопасный запрос с повторными попытками"""
        async with self.semaphore:
            session = await self._get_session()
            proxy = random.choice(self.proxies) if settings.PROXY_ROTATION_ENABLED else None
            
            try:
                async with session.get(url, params=params, proxy=proxy) as response:
                    if response.status == 200:
                        return await response.json()
                    elif response.status == 429:
                        await asyncio.sleep(random.uniform(1, 3))
                        raise Exception("Too many requests")
                    else:
                        raise Exception(f"HTTP error {response.status}")
            except Exception as e:
                logger.warning(f"Ошибка запроса к {url}: {e}")
                raise

    async def enrich_fssp_data(self, inn: str = None, fio: str = None, dob: str = None) -> Dict:
        """Обогащение данными из ФССП"""
        result = {
            'debt_amount': 0.0,
            'debt_type': None,
            'creditor': None,
            'debt_count': 0,
            'has_debt': False
        }
        
        try:
            # Формируем запрос
            search_params = {}
            if inn:
                search_params['inn'] = inn
            elif fio and dob:
                search_params['fio'] = fio
                search_params['dob'] = dob
            
            if not search_params:
                return result
                
            data = await self.safe_request(
                f"{settings.FSSP_BASE_URL}/api/search",
                search_params
            )
            
            return self._parse_fssp_response(data)
        except Exception as e:
            logger.error(f"Ошибка при обращении к ФССП: {e}")
            return result
    
    def _parse_fssp_response(self, data: Dict) -> Dict:
        """Парсинг ответа ФССП"""
        result = {
            'debt_amount': 0.0,
            'debt_type': None,
            'creditor': None,
            'debt_count': 0,
            'has_debt': False
        }
        
        if 'result' in data and data['result']:
            debts = []
            for item in data['result']:
                debt_sum = float(item.get('debt_sum', 0))
                if debt_sum > 0:
                    debts.append({
                        'amount': debt_sum,
                        'type': item.get('debt_type', 'unknown'),
                        'creditor': item.get('creditor', 'unknown')
                    })
            
            if debts:
                result['debt_amount'] = sum(d['amount'] for d in debts)
                result['debt_count'] = len(debts)
                result['has_debt'] = True
                
                # Определяем основной тип долга
                debt_types = [d['type'] for d in debts]
                if 'bank' in debt_types or 'mfo' in debt_types:
                    result['debt_type'] = 'bank'
                elif 'tax' in debt_types:
                    result['debt_type'] = 'tax'
                elif 'utility' in debt_types:
                    result['debt_type'] = 'utility'
                else:
                    result['debt_type'] = debt_types[0] if debt_types else 'unknown'
                
                # Основной взыскатель (самый крупный долг)
                main_debt = max(debts, key=lambda x: x['amount'], default=None)
                if main_debt:
                    result['creditor'] = main_debt['creditor']
        
        return result
    
    async def check_fedresurs_bankruptcy(self, inn: str) -> bool:
        """Проверка банкротства через Федресурс"""
        try:
            data = await self.safe_request(
                f"{settings.FEDRESURS_API_URL}/search",
                {'inn': inn}
            )
            
            return self._parse_fedresurs_response(data)
        except Exception as e:
            logger.error(f"Ошибка при проверке Федресурс: {e}")
            return False
    
    def _parse_fedresurs_response(self, data: Dict) -> bool:
        """Парсинг ответа Федресурс"""
        if 'data' in data and data['data']:
            for item in data['data']:
                if item.get('status') == 'active':
                    return True
        return False
    
    async def check_rosreestr_property(self, inn: str) -> bool:
        """Проверка недвижимости через Росреестр"""
        try:
            data = await self.safe_request(
                f"{settings.ROSREESTR_API_URL}/property",
                {'inn': inn}
            )
            
            return len(data.get('properties', [])) > 0
        except Exception as e:
            logger.error(f"Ошибка при проверке Росреестр: {e}")
            return False
    
    async def check_court_orders(self, fio: str) -> bool:
        """Проверка судебных приказов"""
        try:
            # Упрощенное имя для поиска (только фамилия и инициалы)
            name_parts = fio.split()
            if len(name_parts) < 2:
                return False
                
            search_name = f"{name_parts[0]} {name_parts[1][0]}."
            if len(name_parts) > 2:
                search_name += f".{name_parts[2][0]}."
                
            data = await self.safe_request(
                f"{settings.COURT_API_URL}/search",
                {'query': search_name, 'type': 'individual'}
            )
            
            return self._parse_court_response(data)
        except Exception as e:
            logger.error(f"Ошибка при проверке судебных приказов: {e}")
            return False
    
    def _parse_court_response(self, data: dict) -> bool:
        """Парсинг ответа суда"""
        if 'results' in data and data['results']:
            for item in data['results']:
                # Проверяем, что это судебный приказ и он активен
                if item.get('type') == 'court_order' and item.get('status') == 'active':
                    return True
        return False
    
    async def check_inn_status(self, inn: str) -> bool:
        """Проверка статуса ИНН"""
        try:
            data = await self.safe_request(
                f"{settings.TAX_API_URL}/inn.do",
                {'inn': inn}
            )
            
            return data.get('status') == 'active'
        except Exception as e:
            logger.error(f"Ошибка при проверке ИНН: {e}")
            return True  # По умолчанию считаем активным
    
    async def enrich_lead_data(self, lead: Lead):
        """Обогащение данных одного лида"""
        try:
            # Получаем данные из ФССП
            fssp_data = await self.enrich_fssp_data(
                inn=lead.inn,
                fio=lead.fio,
                dob=lead.dob
            )
            
            # Обновляем поля лида
            lead.debt_amount = fssp_data['debt_amount']
            lead.debt_type = fssp_data['debt_type']
            lead.creditor = fssp_data['creditor']
            lead.debt_count = fssp_data['debt_count']
            
            # Проверяем банкротство
            if lead.inn:
                lead.is_bankrupt = await self.check_fedresurs_bankruptcy(lead.inn)
                lead.has_property = await self.check_rosreestr_property(lead.inn)
                lead.inn_active = await self.check_inn_status(lead.inn)
            
            # Проверяем судебные приказы
            lead.has_court_order = await self.check_court_orders(lead.fio)
            
            self.total_enriched += 1
            if self.total_enriched % 1000 == 0:
                logger.info(f"Обогащено {self.total_enriched} лидов")
                
            return True
        except Exception as e:
            logger.error(f"Ошибка при обогащении лида {lead.lead_id}: {e}")
            return False
    
    async def enrich_batch(self, lead_ids: list):
        """Обогащение батча лидов"""
        async with AsyncSessionLocal() as db:
            try:
                # Получаем лиды для обогащения
                result = await db.execute(
                    text("SELECT * FROM leads WHERE lead_id = ANY(:ids)"),
                    {'ids': lead_ids}
                )
                leads = result.scalars().all()
                
                # Асинхронное обогащение
                tasks = [self.enrich_lead_data(lead) for lead in leads]
                await asyncio.gather(*tasks)
                
                # Сохраняем изменения
                await db.commit()
                return True
            except Exception as e:
                await db.rollback()
                logger.error(f"Ошибка при обогащении батча: {e}")
                return False

    async def enrich_all_leads(self):
        """Обогащение всех лидов в базе"""
        logger.info("Начато обогащение данных")
        self.total_enriched = 0
        
        async with AsyncSessionLocal() as db:
            # Получаем общее количество лидов для обогащения
            result = await db.execute(
                text("SELECT COUNT(*) FROM leads WHERE debt_amount IS NULL")
            )
            total_count = result.scalar()
            
            if total_count == 0:
                logger.info("Нет лидов для обогащения")
                return
            
            logger.info(f"Всего лидов для обогащения: {total_count}")
            
            # Разбиваем на батчи
            batch_count = (total_count // self.batch_size) + 1
            
            for i in range(batch_count):
                offset = i * self.batch_size
                result = await db.execute(
                    text("SELECT lead_id FROM leads WHERE debt_amount IS NULL ORDER BY lead_id LIMIT :limit OFFSET :offset"),
                    {'limit': self.batch_size, 'offset': offset}
                )
                lead_ids = [row[0] for row in result.all()]
                
                if not lead_ids:
                    break
                    
                logger.info(f"Обработка батча {i+1}/{batch_count} ({len(lead_ids)} лидов)")
                await self.enrich_batch(lead_ids)
                
        logger.info(f"Обогащение завершено. Всего обработано: {self.total_enriched} лидов")
    
    async def close(self):
        """Закрытие сессии"""
        if self.session:
            await self.session.close()
            