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

# Copy dependency files and install third-party deps first (layer cache)
COPY pyproject.toml ./
RUN uv sync --no-dev --no-editable --no-install-project

# Copy application source, then install the local tavern package
COPY backend/ ./backend/
COPY alembic.ini ./
RUN uv sync --no-dev --no-editable

# Copy the built frontend into the static serving directory
COPY --from=frontend-builder /app/frontend/dist ./backend/tavern/static/

EXPOSE 3000

CMD ["/app/.venv/bin/uvicorn", "tavern.main:app", "--host", "0.0.0.0", "--port", "3000"]
