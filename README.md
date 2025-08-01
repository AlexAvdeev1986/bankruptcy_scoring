# Система скоринга по банкротству

Проект представляет собой систему для оценки потенциальных банкротов с возможностью обработки больших объемов данных (до 150 млн строк). Система выполняет нормализацию данных, обогащение информации из внешних источников, расчет скоринга и экспорт целевых лидов.

## Структура проекта

```
bankruptcy_scoring/
├── app/               # Основное приложение
├── data/              # Папка для данных
│   ├── input/         # Входные CSV файлы
│   ├── output/        # Результаты экспорта
│   └── logs/          # Логи приложения
├── migrations/        # Миграции базы данных
├── .env               # Конфигурация среды
├── requirements.txt   # Зависимости Python
├── Dockerfile         # Конфигурация Docker
├── docker-compose.yml # Конфигурация Docker Compose
├── entrypoint.sh      # Скрипт запуска приложения
└── README.md          # Документация
```

## Требования

- Python 3.11+
- PostgreSQL 15+
- Docker (для контейнерного запуска)
- Podman (для альтернативного контейнерного запуска)

## Локальная установка и запуск

### 1. Создание виртуального окружения

Рекомендуется использовать Python 3.11 с виртуальным окружением:

```bash
# Для Linux/macOS
python3.11 -m venv venv
source venv/bin/activate

# Для Windows
python -m venv venv
venv\Scripts\activate
```

### 2. Установка зависимостей

```bash
pip install -r requirements.txt
```
pip install playwright
### 3. Установка Playwright

Система использует Playwright для работы с внешними источниками:

```bash
playwright install chromium
```

### 4. Настройка базы данных

1. Установите PostgreSQL 15+
Создайте пользователя и базу данных
sudo -u postgres psql
Затем введите следующие команды в консоли PostgreSQL:
CREATE USER your_username WITH PASSWORD 'your_password';
CREATE DATABASE your_database;
GRANT ALL PRIVILEGES ON DATABASE your_database TO your_username;

2. Создайте базу данных и пользователя:


sudo -u postgres psql

```bash
CREATE USER user WITH PASSWORD 'password';
CREATE DATABASE bankruptcy_db;
GRANT ALL PRIVILEGES ON DATABASE bankruptcy_db TO user;
GRANT ALL PRIVILEGES ON SCHEMA public TO "user";
GRANT CREATE ON SCHEMA public TO "user";
GRANT USAGE ON SCHEMA public TO "user";
REVOKE ALL ON SCHEMA public FROM "user";
GRANT ALL ON SCHEMA public TO "user";
CREATE TABLE test_table(id INT);
```
Проверьте, что нет ограничений на уровне таблиц:```
```bash
\dn+ public
```
Для fedora
sudo dnf install -y postgresql-devel python3-devel
pip install psycopg2-binary
4. Проверка установки
python3 -c "import psycopg2; print(psycopg2.__version__)"

3. Примените миграции:

# Инициализируйте Alembic в папке migrations
`3. Инструкции по миграциям
Инициализация Alembic (если еще не сделано):

```bash
alembic init migrations
Настройка Alembic (migrations/env.py):

python
from app.config import settings
from app.models import Base

# Добавьте в начало файла
config.set_main_option("sqlalchemy.url", str(settings.DATABASE_URL_SYNC))

# В функции run_migrations_online()
target_metadata = Base.metadata

##Создание первой миграции:

```bash
alembic revision --autogenerate -m "Initial tables"
Применение миграций:

```bash
alembic upgrade head
Проверка статуса:

```bash
alembic current
Откат миграции:

```bash
alembic downgrade -1
```

### 5. Настройка окружения

Создайте файл `.env` в корне проекта со следующим содержимым:

```ini
DATABASE_URL=postgresql://user:password@localhost/bankruptcy_db
INPUT_DATA_PATH=./data/input
OUTPUT_DATA_PATH=./data/output
LOGS_PATH=./data/logs
```

### 6. Запуск приложения

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Приложение будет доступно по адресу: http://localhost:8000

## Запуск через Podman

### 1. Сборка образа

```bash
podman build -t bankruptcy_scoring .
```

### 2. Создание сети

```bash
podman network create scoring_network
```

### 3. Запуск базы данных

```bash
podman run -d --name db --network scoring_network \
  -e POSTGRES_DB=bankruptcy_db \
  -e POSTGRES_USER=user \
  -e POSTGRES_PASSWORD=password \
  -v pgdata:/var/lib/postgresql/data \
  postgres:15
```

### 4. Запуск приложения

```bash
podman run -d --name web --network scoring_network \
  -p 8000:8000 \
  -e DATABASE_URL=postgresql://user:password@db/bankruptcy_db \
  -v ./data:/app/data \
  bankruptcy_scoring
```

Приложение будет доступно по адресу: http://localhost:8000

## Запуск через Docker Compose

```bash
docker-compose up --build
```

Приложение будет доступно по адресу: http://localhost:8000

## Использование системы

1. Поместите CSV-файлы в папку `data/input`
2. Откройте веб-интерфейс: http://localhost:8000
3. Настройте фильтры:
   - Выберите регионы
   - Укажите минимальную сумму долга
   - Настройте дополнительные фильтры
4. Нажмите "Запустить скоринг"
5. Дождитесь завершения обработки (прогресс отображается в реальном времени)
6. Скачайте результаты в формате CSV

## Особенности системы

- Пакетная обработка данных (батчи по 10 000 записей)
- Асинхронные запросы к внешним API
- Ротация прокси для обхода ограничений
- Автоматическое определение источника данных по имени файла
- Поддержка больших объемов данных (до 150 млн строк)
- Логирование ошибок в базу данных
- Экспорт результатов в CSV с потоковой выгрузкой

## API Endpoints

- `GET /` - Главная страница
- `POST /start-scoring` - Запуск процесса скоринга
- `GET /status` - Статус обработки
- `GET /download` - Скачивание результатов
- `GET /logs` - Просмотр логов ошибок
- `GET /stats` - Статистика базы данных
- `GET /files` - Список загруженных файлов

## Технологический стек

- **Backend**: Python 3.11, FastAPI, SQLAlchemy
- **База данных**: PostgreSQL 15
- **Фронтенд**: Jinja2, Bootstrap
- **Обработка данных**: Pandas, NumPy
- **Внешние API**: ФССП, Федресурс, Росреестр
- **Контейнеризация**: Docker/Podman