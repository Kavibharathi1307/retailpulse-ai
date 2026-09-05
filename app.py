"""RetailPulse AI -- Retail Sales & Inventory Copilot (NexusTiQ24 PS03).

Single application entry point. Run with:

    python app.py

Serves both the JSON API and the built frontend on http://localhost:8000.
"""

from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.config import FRONTEND_DIR, PROJECT_ROOT, get_gemini_api_key

app = FastAPI(
    title="RetailPulse AI",
    description="Retail Sales & Inventory Copilot (PS03)",
    version="0.1.0",
)


@app.get("/api/health")
def health() -> dict:
    """Small JSON response indicating the application is running."""
    return {
        "status": "ok",
        "service": "retailpulse-ai",
        "track": "PS03",
        "gemini_configured": get_gemini_api_key() is not None,
    }


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """Serve the frontend shell at the application root."""
    return FileResponse(FRONTEND_DIR / "index.html")


ASSETS_DIR = FRONTEND_DIR / "assets"
if ASSETS_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
    )