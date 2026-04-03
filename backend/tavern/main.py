from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from tavern.api import campaigns, characters, health, turns, ws
from tavern.api.errors import APIError, api_error_handler

app = FastAPI(title="Tavern", version="0.1.0")

app.add_exception_handler(APIError, api_error_handler)  # type: ignore[arg-type]

# Health endpoint at root level (no /api prefix per ADR-0005)
app.include_router(health.router)

# REST API routes under /api
app.include_router(campaigns.router, prefix="/api")
app.include_router(characters.router, prefix="/api")
app.include_router(turns.router, prefix="/api")
app.include_router(ws.router, prefix="/api")

STATIC_DIR = Path(__file__).parent / "static"

# Serve the React frontend if the static directory is populated.
if (STATIC_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend(full_path: str) -> FileResponse:
        index = STATIC_DIR / "index.html"
        return FileResponse(str(index))
