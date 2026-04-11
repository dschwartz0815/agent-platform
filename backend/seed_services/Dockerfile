FROM python:3.12-slim

WORKDIR /app

# Only needs FastAPI + uvicorn + httpx (no LangGraph, Anthropic, etc.)
RUN pip install --no-cache-dir \
    fastapi==0.135.3 \
    uvicorn[standard]==0.44.0 \
    httpx==0.28.1

# Copy only what this tiny service needs
COPY seed_services/mock_a2a_agent.py /app/seed_services/mock_a2a_agent.py

CMD ["uvicorn", "seed_services.mock_a2a_agent:app", "--host", "0.0.0.0", "--port", "8001"]
