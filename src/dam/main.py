from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from dam.config import get_settings
from dam.routers import assets, boards, me, projects, search, uploads
from dam.viewer import Forbidden

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Design Asset Manager API",
        version="0.1.0",
        lifespan=lifespan,
        openapi_tags=[{"name": t} for t in ("me", "projects", "uploads", "assets", "search", "boards")],
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.web_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for r in (me, projects, uploads, assets, search, boards):
        app.include_router(r.router)

    @app.get("/health", include_in_schema=False)
    async def health() -> dict:
        return {"ok": True}

    # RFC 9457 problem details for every error shape.
    @app.exception_handler(Forbidden)
    async def forbidden(_: Request, exc: Forbidden) -> JSONResponse:
        return _problem(403, "Forbidden", str(exc))

    @app.exception_handler(HTTPException)
    async def http_exc(_: Request, exc: HTTPException) -> JSONResponse:
        return _problem(exc.status_code, _title(exc.status_code), str(exc.detail), exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _problem(422, "Unprocessable Content", str(exc.errors()[:3]))

    return app


def _title(status: int) -> str:
    return {
        400: "Bad Request",
        401: "Unauthorized",
        403: "Forbidden",
        404: "Not Found",
        405: "Method Not Allowed",
        409: "Conflict",
        413: "Content Too Large",
        415: "Unsupported Media Type",
        422: "Unprocessable Content",
    }.get(status, "Error")


def _problem(status: int, title: str, detail: str | None, headers=None) -> JSONResponse:
    return JSONResponse(
        {"type": "about:blank", "title": title, "status": status, "detail": detail},
        status_code=status,
        headers=headers,
        media_type="application/problem+json",
    )


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run("dam.main:app", host="0.0.0.0", port=8000, reload=get_settings().env == "dev")
