ARG NODE_IMAGE=node:22-alpine
ARG PYTHON_IMAGE=python:3.12-slim

FROM ${NODE_IMAGE} AS frontend-build
WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


FROM ${PYTHON_IMAGE} AS runtime
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY agents/ ./agents/
COPY core/ ./core/
COPY models/ ./models/
COPY prompts/ ./prompts/
COPY server/ ./server/
COPY workflow/ ./workflow/
COPY config.py main.py ./
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

RUN mkdir -p /app/output

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000"]
