FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home app
COPY api ./api
USER app
EXPOSE 8000
CMD ["sh", "-c", "python -m uvicorn api.main:app --host ${API_HOST:-0.0.0.0} --port ${API_PORT:-8000}"]
