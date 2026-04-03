"""Consistent error responses for the Tavern REST API.

All 4xx errors follow the same shape (ADR-0005):
    {"error": "snake_case_code", "message": "human-readable detail", "status": 404}

Register the exception handler in main.py:
    app.add_exception_handler(APIError, api_error_handler)
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class APIError(Exception):
    """Raise this anywhere in a route to return a structured error response."""

    def __init__(self, status_code: int, error: str, message: str) -> None:
        self.status_code = status_code
        self.error = error
        self.message = message
        super().__init__(message)


async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:  # noqa: ARG001
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.error, "message": exc.message, "status": exc.status_code},
    )


# ---------------------------------------------------------------------------
# Convenience constructors
# ---------------------------------------------------------------------------


def not_found(resource: str, resource_id: Any) -> APIError:
    name = resource.replace("_", " ")
    return APIError(
        status_code=404,
        error=f"{resource}_not_found",
        message=f"{name.title()} with id {resource_id} does not exist",
    )


def bad_request(error: str, message: str) -> APIError:
    return APIError(status_code=400, error=error, message=message)


def conflict(error: str, message: str) -> APIError:
    return APIError(status_code=409, error=error, message=message)
