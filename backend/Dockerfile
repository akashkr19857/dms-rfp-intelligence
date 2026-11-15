# Not built on the dev laptop (no Docker there). Build from the project root: docker compose build api
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend backend
COPY data/manifest.json data/download_data.py data/make_knowledge_base.py data/
RUN python data/download_data.py
WORKDIR /app/backend
EXPOSE 8200
CMD ["sh", "-c", "python scripts/seed.py && uvicorn app.main:app --host 0.0.0.0 --port 8200"]
