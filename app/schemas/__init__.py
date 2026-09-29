"""Pydantic request/response models for the JSON API.

They validate *shape* (types, lengths, ranges, timezone-aware datetimes).
Business rules that need the database or the clock live in app/services.
"""
