# Stage 1: Build frontend
FROM node:22-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python base (shared between app and test)
FROM python:3.13-slim AS base
WORKDIR /app

# Copy and install Python dependencies first (cache layer)
COPY pyproject.toml ./
# Create minimal package structure for pip install
RUN mkdir -p app && touch app/__init__.py && \
    pip install --no-cache-dir . && \
    rm -rf app

# Copy application code
COPY app/ ./app/

# Stage 3: Test runner
FROM base AS test
RUN pip install --no-cache-dir ".[test]"
COPY tests/ ./tests/
CMD ["pytest", "-v", "--tb=short"]

# Stage 4: Production app
FROM base AS production

# Copy built frontend
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Create data directory
RUN mkdir -p /app/data/jobs

ENV VPPE_DATA_DIR=/app/data
ENV VPPE_OLLAMA_BASE_URL=http://host.docker.internal:11434

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
