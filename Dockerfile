# Stage 1: Build the React frontend
FROM node:20-slim AS frontend-builder

WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --frozen-lockfile

COPY frontend/ ./
RUN npm run build


# Stage 2: Python runtime
FROM python:3.12-slim AS runtime

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files first for layer caching
COPY pyproject.toml ./

# Install production dependencies only
RUN uv sync --no-dev --no-editable

# Copy application source
COPY backend/ ./backend/
COPY alembic.ini ./

# Copy the built frontend into the static serving directory
COPY --from=frontend-builder /app/frontend/dist ./backend/tavern/static/

EXPOSE 3000

CMD ["uv", "run", "--no-dev", "uvicorn", "tavern.main:app", "--host", "0.0.0.0", "--port", "3000"]
