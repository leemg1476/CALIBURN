FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY alembic.ini ./
COPY migrations ./migrations
RUN pip install --no-cache-dir . && useradd --uid 10001 --create-home caliburn \
    && mkdir -p /app/data && chown -R caliburn:caliburn /app/data
USER caliburn
EXPOSE 8000
CMD ["uvicorn", "caliburn.app:app", "--host", "0.0.0.0", "--port", "8000"]
