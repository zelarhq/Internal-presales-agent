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
COPY ./requirements.txt ./requirements.txt
COPY ./pyproject.toml ./pyproject.toml
COPY ./src ./src

RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Ezydev can override these at deploy time (set real values in the panel)
ENV PORT=5001
ENV API_KEY=abc123 \
    FRONTEND_ORIGINS=http://localhost:8080 \
    PUBLIC_BASE_URL=http://localhost:5001

EXPOSE ${PORT}

# FastAPI app is in src/api/main.py -> app
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "${PORT}"]