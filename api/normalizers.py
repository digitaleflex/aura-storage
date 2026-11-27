"""Normalization/serialization helpers (#341)."""
from __future__ import annotations


def as_dict(row) -> dict:
    return dict(row) if not isinstance(row, dict) else row
