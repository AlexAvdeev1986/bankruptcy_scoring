from logging.config import fileConfig
from sqlalchemy import create_engine
from alembic import context
import os
import sys

# Добавляем путь к проекту
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Импортируем настройки и базовый класс моделей
from app.config import settings
from app.database import Base
from app.models import Lead, ScoringHistory, ErrorLog

# Конфигурация Alembic
config = context.config

# Переопределяем URL базы данных
config.set_main_option('sqlalchemy.url', settings.DATABASE_URL)

# Настраиваем логгер
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Указываем целевую метаданную
target_metadata = Base.metadata

def run_migrations_offline():
    """Запуск миграций в офлайн-режиме."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    """Запуск миграций в онлайн-режиме."""
    connectable = create_engine(config.get_main_option("sqlalchemy.url"))

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()