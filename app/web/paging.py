"""Page numbers for web lists (`?page=2`), on top of the API's limit/offset.

A person thinks in pages, the services think in `PageParams`; this converts
between the two and tells the template which links to draw.
"""

from dataclasses import dataclass
from math import ceil

from app.core.errors import AppError
from app.core.pagination import PageParams

# The largest page number a URL may ask for; stops absurd offsets early.
MAX_PAGE = 10_000


def page_params(page: int, size: int) -> PageParams:
    return PageParams(limit=size, offset=(page - 1) * size)


@dataclass(frozen=True)
class Pager:
    page: int
    size: int
    total: int

    @property
    def pages(self) -> int:
        return max(1, ceil(self.total / self.size))

    @property
    def has_prev(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.pages


def make_pager(page: int, size: int, total: int) -> Pager:
    """The pager for a list of `total` items.

    Raises:
        AppError: 404 `NOT_FOUND` for a page past the last one (page 1 always
            exists, so an empty list still shows its empty state).
    """
    pager = Pager(page=page, size=size, total=total)
    if page > pager.pages:
        raise AppError("NOT_FOUND", "There is no page with that number.", status_code=404)
    return pager
