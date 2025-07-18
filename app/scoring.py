# app/scoring.py
from typing import Dict, List, Tuple
import logging
from datetime import datetime, timedelta
from app.database import SessionLocal, AsyncSessionLocal
from app.models import Lead, ScoringHistory
import numpy as np
import asyncio
from sqlalchemy import text, update
from sqlalchemy.dialects.postgresql import insert

logger = logging.getLogger(__name__)

class ScoringEngine:
    def __init__(self):
        self.scoring_rules = {
            'high_debt': {'score': 30, 'threshold': 250000},
            'bank_mfo_debt': {'score': 20},
            'no_property': {'score': 10},
            'recent_court_order': {'score': 15, 'days': 90},
            'no_bankruptcy': {'score': 10},
            'active_inn': {'score': 5},
            'multiple_debts': {'score': 5, 'threshold': 2},
            'low_debt': {'score': -15, 'threshold': 100000},
            'tax_utility_only': {'score': -10},
            'is_bankrupt': {'score': -100},
            'dead_inn': {'score': -100}
        }
    
    def calculate_score(self, lead_data: Dict) -> Tuple[float, List[str], str]:
        """Расчет скоринга для лида"""
        score = 0
        reasons = []
        
        # +30 - если сумма долгов больше 250,000 рублей
        if lead_data.get('debt_amount', 0) > self.scoring_rules['high_debt']['threshold']:
            score += self.scoring_rules['high_debt']['score']
            reasons.append(f"Долг {lead_data.get('debt_amount', 0):.0f} руб.")
        
        # +20 - если долг от банка или МФО
        if lead_data.get('debt_type') in ['bank', 'mfo']:
            score += self.scoring_rules['bank_mfo_debt']['score']
            reasons.append("Долг перед банком/МФО")
        
        # +10 - если нет имущества
        if not lead_data.get('has_property', False):
            score += self.scoring_rules['no_property']['score']
            reasons.append("Нет недвижимости")
        
        # +15 - если есть судебный приказ за последние 3 месяца
        if lead_data.get('has_court_order', False):
            score += self.scoring_rules['recent_court_order']['score']
            reasons.append("Судебный приказ")
        
        # +10 - если нет признаков банкротства
        if not lead_data.get('is_bankrupt', False):
            score += self.scoring_rules['no_bankruptcy']['score']
            reasons.append("Не банкрот")
        
        # +5 - если ИНН активен
        if lead_data.get('inn_active', True):
            score += self.scoring_rules['active_inn']['score']
            reasons.append("Активный ИНН")
        
        # +5 - если более двух долгов
        debt_count = lead_data.get('debt_count', 1)
        if debt_count >= self.scoring_rules['multiple_debts']['threshold']:
            score += self.scoring_rules['multiple_debts']['score']
            reasons.append(f"Множественные долги ({debt_count})")
        
        # -15 - если долг менее 100,000 рублей
        if 0 < lead_data.get('debt_amount', 0) < self.scoring_rules['low_debt']['threshold']:
            score += self.scoring_rules['low_debt']['score']
            reasons.append("Малый долг")
        
        # -10 - если долги только налоговые/ЖКХ
        if lead_data.get('debt_type') in ['tax', 'utility']:
            score += self.scoring_rules['tax_utility_only']['score']
            reasons.append("Только налоги/ЖКХ")
        
        # -100 - если человек признан банкротом
        if lead_data.get('is_bankrupt', False):
            score += self.scoring_rules['is_bankrupt']['score']
            reasons.append("Банкрот")
        
        # -100 - если ИНН мертвый
        if not lead_data.get('inn_active', True):
            score += self.scoring_rules['dead_inn']['score']
            reasons.append("Неактивный ИНН")
        
        # Определяем группу для A/B тестов
        group = self._determine_group(lead_data, score)
        
        # Ограничиваем score от 0 до 100
        final_score = max(0, min(100, score))
        return final_score, reasons[:3], group
    
    def _determine_group(self, lead_data: Dict, score: float) -> str:
        """Определение группы для A/B тестов"""
        if lead_data.get('debt_amount', 0) > 500000 and lead_data.get('has_court_order'):
            return "high_debt_recent_court"
        elif lead_data.get('debt_type') in ['bank', 'mfo'] and not lead_data.get('has_property'):
            return "bank_only_no_property"
        elif score >= 70:
            return "high_score"
        elif score >= 50:
            return "medium_score"
        else:
            return "low_score"
    
    def apply_filters(self, lead_data: Dict, filters: Dict) -> bool:
        """Применение фильтров"""
        # Минимальная сумма долга
        if lead_data.get('debt_amount', 0) < filters.get('min_debt_amount', 0):
            return False
        
        # Исключать банкротов
        if filters.get('exclude_bankrupts', False) and lead_data.get('is_bankrupt', False):
            return False
        
        # Исключать контакты без долгов
        if filters.get('exclude_no_debt', False) and lead_data.get('debt_amount', 0) == 0:
            return False
        
        # Только с недвижимостью
        if filters.get('only_with_property', False) and not lead_data.get('has_property', False):
            return False
        
        # Только с банковскими/МФО долгами
        if filters.get('only_bank_mfo_debt', False) and lead_data.get('debt_type') not in ['bank', 'mfo']:
            return False
        
        # Только с судебными приказами
        if filters.get('only_recent_court_orders', False) and not lead_data.get('has_court_order', False):
            return False
        
        # Только с живыми ИНН
        if filters.get('only_active_inn', False) and not lead_data.get('inn_active', True):
            return False
        
        return True
    
    def is_target(self, score: float, filters: Dict) -> bool:
        """Определение целевого лида"""
        threshold = filters.get('min_score_threshold', settings.MIN_SCORE_THRESHOLD)
        return score >= threshold

class ScoringProcessor:
    def __init__(self):
        self.engine = ScoringEngine()
        self.batch_size = settings.BATCH_SIZE

    async def process_all_leads(self, filters: Dict):
        """Обработка всех лидов в базе"""
        logger.info("Начато вычисление скоринга")
        
        async with AsyncSessionLocal() as db:
            # Получаем общее количество лидов для обработки
            result = await db.execute(
                text("SELECT COUNT(*) FROM leads WHERE score IS NULL")
            )
            total_count = result.scalar()
            
            if total_count == 0:
                logger.info("Нет лидов для скоринга")
                return
            
            logger.info(f"Всего лидов для скоринга: {total_count}")
            
            # Разбиваем на батчи
            batch_count = (total_count // self.batch_size) + 1
            processed = 0
            
            for i in range(batch_count):
                offset = i * self.batch_size
                result = await db.execute(
                    text("SELECT * FROM leads WHERE score IS NULL ORDER BY lead_id LIMIT :limit OFFSET :offset"),
                    {'limit': self.batch_size, 'offset': offset}
                )
                leads = result.scalars().all()
                
                if not leads:
                    break
                    
                logger.info(f"Обработка батча {i+1}/{batch_count} ({len(leads)} лидов)")
                processed += await self.process_batch(leads, filters, db)
                
        logger.info(f"Скоринг завершен. Обработано лидов: {processed}/{total_count}")
        return processed
    
    async def process_batch(self, leads: List[Lead], filters: Dict, db) -> int:
        """Обработка батча лидов"""
        processed_count = 0
        scoring_data = []
        history_data = []
        
        try:
            for lead in leads:
                lead_dict = self._lead_to_dict(lead)
                
                # Применяем фильтры
                if not self.engine.apply_filters(lead_dict, filters):
                    continue
                
                # Рассчитываем скоринг
                score, reasons, group = self.engine.calculate_score(lead_dict)
                is_target = self.engine.is_target(score, filters)
                
                # Формируем данные для обновления
                scoring_data.append({
                    'lead_id': lead.lead_id,
                    'score': score,
                    'is_target': is_target,
                    'reason_1': reasons[0] if len(reasons) > 0 else None,
                    'reason_2': reasons[1] if len(reasons) > 1 else None,
                    'reason_3': reasons[2] if len(reasons) > 2 else None,
                    'group_name': group
                })
                
                # Формируем историю скоринга
                history_data.append({
                    'lead_id': lead.lead_id,
                    'score': score,
                    'group_name': group,
                    'reason_1': reasons[0] if reasons else None,
                    'filters_used': json.dumps(filters)
                })
                
                processed_count += 1
            
            # Массовое обновление в БД
            await self._bulk_update_leads(scoring_data, db)
            
            # Сохранение истории скоринга
            if history_data:
                await self._save_scoring_history(history_data, db)
            
            await db.commit()
            return processed_count
        except Exception as e:
            await db.rollback()
            logger.error(f"Ошибка при обработке батча: {e}")
            return 0
    
    async def _bulk_update_leads(self, leads_data: List[dict], db):
        """Массовое обновление лидов в БД"""
        if not leads_data:
            return
            
        # Формируем CASE выражения для массового обновления
        update_stmt = """
            UPDATE leads SET
                score = data.score,
                is_target = data.is_target,
                reason_1 = data.reason_1,
                reason_2 = data.reason_2,
                reason_3 = data.reason_3,
                group_name = data.group_name
            FROM (VALUES
        """
        
        values = []
        for data in leads_data:
            values.append(
                f"('{data['lead_id']}', {data['score']}, {data['is_target']}, "
                f"'{data['reason_1'] or ''}', '{data['reason_2'] or ''}', "
                f"'{data['reason_3'] or ''}', '{data['group_name']}')"
            )
        
        update_stmt += ",\n".join(values)
        update_stmt += """
            ) AS data(lead_id, score, is_target, reason_1, reason_2, reason_3, group_name)
            WHERE leads.lead_id = data.lead_id
        """
        
        await db.execute(text(update_stmt))
    
    async def _save_scoring_history(self, history_data: List[dict], db):
        """Сохранение истории скоринга"""
        stmt = insert(ScoringHistory).values(history_data)
        await db.execute(stmt)
    
    def _lead_to_dict(self, lead: Lead) -> Dict:
        """Конвертация объекта Lead в словарь"""
        return {
            'lead_id': lead.lead_id,
            'fio': lead.fio,
            'phone': lead.phone,
            'inn': lead.inn,
            'dob': lead.dob,
            'address': lead.address,
            'source': lead.source,
            'debt_amount': lead.debt_amount,
            'debt_type': lead.debt_type,
            'has_property': lead.has_property,
            'has_court_order': lead.has_court_order,
            'is_bankrupt': lead.is_bankrupt,
            'inn_active': lead.inn_active,
            'debt_count': lead.debt_count
        }
        