"""The envelope every list endpoint returns."""

from pydantic import BaseModel, Field


class Page[T](BaseModel):
    items: list[T]
    total: int = Field(description="Matching items across all pages.")
    limit: int
    offset: int
