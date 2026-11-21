"""Shared error types and dependencies."""

from __future__ import annotations

from fastapi import Request

from pipeline.store import Store


class ApiError(Exception):
    """Error rendered as ``{"status": ..., "message": ...}``."""

    def __init__(self, status_code: int, message: str, status: str = "ERROR"):
        self.status_code = status_code
        self.message = message
        self.status = status
        super().__init__(message)


def get_store(request: Request) -> Store:
    return request.app.state.store
