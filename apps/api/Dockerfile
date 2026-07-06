# AgentForge API image. Build context = repo root (agentforge/).
FROM python:3.11-slim

WORKDIR /app

# Install the shared core (with live provider extras) then the API deps.
COPY packages/agent-core /app/packages/agent-core
RUN pip install --no-cache-dir -e "/app/packages/agent-core[anthropic,openai]"

COPY apps/api /app/apps/api
RUN pip install --no-cache-dir -r /app/apps/api/requirements.txt

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "/app/apps/api"]
