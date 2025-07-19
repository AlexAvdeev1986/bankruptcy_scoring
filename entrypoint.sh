#!/bin/bash

# Применение миграций
alembic upgrade head

# Запуск приложения
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4