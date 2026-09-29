"""Response model for the error envelope, so Swagger documents it."""

from typing import Any

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    code: str = Field(description="Stable machine-readable code; clients switch on this.")
    message: str = Field(description="Human-readable explanation; may change wording.")
    details: dict[str, Any] = Field(default_factory=dict, description="Extra structured context.")


class ErrorResponse(BaseModel):
    error: ErrorBody

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "error": {
                        "code": "SLOT_TAKEN",
                        "message": "That time was just booked by someone else.",
                        "details": {},
                    }
                }
            ]
        }
    }
