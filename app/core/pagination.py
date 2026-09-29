"""One paging convention for every list endpoint: `limit` and `offset`.

Routers take `PageParamsDep`, services pass the query and the params to
`paginate`, and the router wraps the result in `schemas.pagination.Page`.
Every list is therefore bounded: nobody can ask for a million rows at once.
"""

from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Query
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

DEFAULT_LIMIT = 20
MAX_LIMIT = 100
# Postgres OFFSET is a bigint; the cap only stops absurd numbers from reaching
# the database as an error.
MAX_OFFSET = 1_000_000_000


@dataclass(frozen=True)
class PageParams:
    limit: int
    offset: int


def get_page_params(
    limit: Annotated[
        int, Query(ge=1, le=MAX_LIMIT, description="Page size (1 to 100).")
    ] = DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0, le=MAX_OFFSET, description="How many items to skip.")] = 0,
) -> PageParams:
    return PageParams(limit=limit, offset=offset)


PageParamsDep = Annotated[PageParams, Depends(get_page_params)]


def paginate(db: Session, query: Select[Any], params: PageParams) -> tuple[list[Any], int]:
    """One page of `query` and the total number of rows it matches.

    `query` must already have a deterministic `ORDER BY` (end it with the id):
    without one, pages can overlap or skip rows between requests.
    """
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    items = db.scalars(query.limit(params.limit).offset(params.offset)).all()
    return list(items), total or 0
