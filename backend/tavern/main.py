from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Tavern", version="0.1.0")

STATIC_DIR = Path(__file__).parent / "static"


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# Serve the React frontend if the static directory is populated.
if STATIC_DIR.exists() and any(STATIC_DIR.iterdir()):
    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend(full_path: str) -> FileResponse:
        index = STATIC_DIR / "index.html"
        return FileResponse(str(index))
