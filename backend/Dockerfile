FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app/backend

COPY pyproject.toml ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY evals ./evals
COPY scripts/seed_demo_orders.py ./scripts/seed_demo_orders.py
COPY scripts/prune_agent_runs.py ./scripts/prune_agent_runs.py
COPY scripts/reindex_embedding_space.py ./scripts/reindex_embedding_space.py
COPY scripts/evaluate_benchmark.py ./scripts/evaluate_benchmark.py

RUN pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data/uploads \
    && chown -R appuser:appuser /app

USER appuser
