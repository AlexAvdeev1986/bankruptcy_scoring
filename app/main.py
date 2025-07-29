from fastapi import FastAPI, Request, Form, BackgroundTasks, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from datetime import datetime
import asyncio
import logging
from typing import List
from app.config import settings
from app.utils import PipelineManager
from app.models import StatusResponse, ScoringRequest
from app.database import Base, engine
import time
import os

# Настройка логгера
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(settings.LOGS_PATH, "app.log"))
    ]
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Система скоринга по банкротству",
    description="Система для оценки потенциальных банкротов",
    version="1.0.0"
)

# Настройка шаблонов
templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Инициализация компонентов
pipeline = PipelineManager()

# Состояние обработки
class ProcessingState:
    def __init__(self):
        self.status = "idle"  # idle, running, completed, error
        self.progress = 0
        self.current_stage = ""
        self.message = ""
        self.start_time = None
        self.result = None
        self.filters = None

state = ProcessingState()


@app.on_event("startup")
def startup_event():
    """Инициализация при запуске"""
    # Создание таблиц (если не используются миграции)
    with engine.begin() as conn:
        Base.metadata.create_all(conn)
    logger.info("Application started")
    pipeline.file_manager.ensure_directories()

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Главная страница"""
    files = pipeline.file_manager.get_input_files_info()
    return templates.TemplateResponse("index.html", {
        "request": request,
        "status": state.status,
        "progress": state.progress,
        "stage": state.current_stage,
        "message": state.message,
        "files": files
    })

@app.post("/start-scoring")
async def start_scoring(
    background_tasks: BackgroundTasks,
    regions: List[str] = Form([]),
    min_debt_amount: int = Form(settings.MIN_DEBT_AMOUNT),
    exclude_bankrupts: bool = Form(True),
    exclude_no_debt: bool = Form(True),
    only_with_property: bool = Form(False),
    only_bank_mfo_debt: bool = Form(False),
    only_recent_court_orders: bool = Form(False),
    only_active_inn: bool = Form(True)
):
    if state.status == "running":
        raise HTTPException(400, "Обработка уже запущена")
    
    filters = {
        'regions': regions,
        'min_debt_amount': min_debt_amount,
        'exclude_bankrupts': exclude_bankrupts,
        'exclude_no_debt': exclude_no_debt,
        'only_with_property': only_with_property,
        'only_bank_mfo_debt': only_bank_mfo_debt,
        'only_recent_court_orders': only_recent_court_orders,
        'only_active_inn': only_active_inn
    }
    
    state.status = "running"
    state.progress = 0
    state.current_stage = ""
    state.message = "Запуск обработки"
    state.start_time = time.time()
    state.result = None
    state.filters = filters
    
    background_tasks.add_task(run_processing_pipeline, filters)
    return {"status": "running", "message": "Обработка запущена"}

async def run_processing_pipeline(filters: dict):
    stages = [
        ("normalization", "Нормализация данных", {}),
        ("enrichment", "Обогащение данных", {}),
        ("scoring", "Расчет скоринга", {"filters": filters}),
        ("export", "Экспорт результатов", {})
    ]
    
    total_stages = len(stages)
    state.progress = 0
    
    try:
        for i, (stage_name, stage_message, stage_args) in enumerate(stages):
            state.current_stage = stage_name
            state.message = stage_message
            state.progress = int((i / total_stages) * 100)
            
            if stage_name == "enrichment" or stage_name == "scoring":
                func = getattr(pipeline, f"run_{stage_name}")
                await func(**stage_args)
            else:
                func = getattr(pipeline, f"run_{stage_name}")
                func(**stage_args)
            
            state.progress = int(((i + 1) / total_stages) * 100)
        
        # Получаем результат экспорта
        output_file = await pipeline.run_export()
        if not output_file:
            raise Exception("Ошибка при экспорте результатов")
        
        # Получаем статистику
        stats = await pipeline.get_database_stats()
        
        state.status = "completed"
        state.message = f"Обработка завершена. Найдено {stats['target_leads']} целевых лидов"
        state.result = {
            "output_file": output_file,
            "target_count": stats['target_leads'],
            "stats": stats
        }
    
    except Exception as e:
        state.status = "error"
        state.message = f"Ошибка: {str(e)}"
        state.result = None
        logger.exception("Ошибка в процессе обработки")

@app.get("/status", response_model=StatusResponse)
async def get_status():
    duration = time.time() - state.start_time if state.start_time else 0
    return StatusResponse(
        status=state.status,
        progress=state.progress,
        stage=state.current_stage,
        message=state.message,
        duration=duration,
        result=state.result
    )

@app.get("/download")
async def download_results():
    if not state.result or not state.result.get("output_file"):
        raise HTTPException(404, "Файл результатов не найден")
    
    return FileResponse(
        state.result["output_file"],
        filename="scoring_ready.csv",
        media_type="text/csv"
    )

@app.get("/logs")
async def get_logs(limit: int = 100):
    logs = await pipeline.log_manager.get_error_logs(limit)
    return logs

@app.get("/stats")
async def get_stats():
    stats = await pipeline.get_database_stats()
    return stats

@app.get("/files")
async def get_files():
    files = pipeline.file_manager.get_input_files_info()
    return files

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
    