"""Response model for the health endpoint."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    database: str

    model_config = {"json_schema_extra": {"examples": [{"status": "ok", "database": "ok"}]}}
