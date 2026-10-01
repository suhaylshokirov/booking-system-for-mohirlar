"""The envelope every list endpoint returns."""

from pydantic import BaseModel, Field


class Page[T](BaseModel):
    items: list[T]
    total: int = Field(description="Matching items across all pages.")
    limit: int
    offset: int


def page_response(item_model: type[BaseModel]) -> dict:
    """A `responses=` entry giving a list endpoint an example page of one `item_model`.

    Takes the first example the item model declares, so the page example can never
    disagree with the item's own. For `Page[...]` endpoints, which Swagger would
    otherwise show with empty placeholder values.
    """
    extra = item_model.model_config.get("json_schema_extra") or {}
    item = extra["examples"][0]
    page = {"items": [item], "total": 1, "limit": 20, "offset": 0}
    return {
        200: {
            "description": "One page of results.",
            "content": {"application/json": {"example": page}},
        }
    }
