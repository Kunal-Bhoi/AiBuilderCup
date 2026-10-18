"""Serves the built React app from api-service, so the deployment has one public URL and the
browser calls /api/v1 on the same origin (no CORS). infra/deploy.sh builds frontend/ and copies
dist/ to backend/static before deploying. Active only when that directory exists; in local
development the Vite dev server serves the frontend and proxies /api instead."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

# Paths the SPA fallback must never answer: an unknown API path is a 404, not the app's HTML.
RESERVED_PREFIXES = ("api/", "internal/", "local-storage/", "docs", "redoc", "openapi.json", "health")


def mount_frontend(app: FastAPI, directory: str) -> bool:
    root = Path(directory).resolve()
    index = root / "index.html"
    if not index.is_file():
        return False

    # Registered after every other route, so API, health and docs routes always win.
    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        if path.startswith(RESERVED_PREFIXES):
            raise HTTPException(status_code=404)
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            # Vite fingerprints everything under assets/, so those can be cached for good.
            cache = "public, max-age=31536000, immutable" if path.startswith("assets/") else "no-cache"
            return FileResponse(candidate, headers={"Cache-Control": cache})
        return FileResponse(index, headers={"Cache-Control": "no-cache"})  # client-side route

    return True
