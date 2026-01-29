# Backend: FastAPI + Uvicorn
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps (for things like psycopg2, building wheels, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY ./pyproject.toml ./requirements.txt
COPY ./src ./src

RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Ezydev can override these at deploy time
ENV PORT=5001 \
    API_KEY=abc123 \
    FRONTEND_ORIGINS=http://localhost:8080 \
    PUBLIC_BASE_URL=http://localhost:${PORT}

EXPOSE ${PORT}

# FastAPI app is in src/api/main.py -> app
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "5001"]