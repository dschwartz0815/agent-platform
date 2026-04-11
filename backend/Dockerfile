FROM python:3.12-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first so this layer caches unless requirements.txt changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source — overridden by the volume mount in dev, used as-is in prod
COPY . .

EXPOSE 8000

# --reload watches /app for changes; the volume mount in docker-compose makes
# host edits visible inside the container immediately.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
