"""FastAPI application factory (#338).

Keeps app construction in one place so route modules can be registered
explicitly later. `api.main:app` remains the compatibility entrypoint.
"""
from __future__ import annotations

from fastapi import FastAPI


def create_app() -> FastAPI:
    return FastAPI(title="AURA Management API", version="0.2.0")
