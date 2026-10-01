"""Who is looking at the page.

`load_current_user` runs for every web route (it is attached where the web
routers are included, in `app/main.py`, so no page can forget it). It stores
the signed-in user, or `None`, on `request.state`, which `render` reads to
draw the header's account menu or its "Sign in" link.

Routes that need the user take `WebUser`; FastAPI runs the dependency once
per request, so this is the same call, not a second lookup.
"""

from typing import Annotated

from fastapi import Depends, Request

from app.api.deps import OptionalUser
from app.core.errors import AppError
from app.models.user import User, UserRole


def load_current_user(request: Request, user: OptionalUser) -> User | None:
    request.state.current_user = user
    return user


WebUser = Annotated[User | None, Depends(load_current_user)]


def require_barber_page(user: Annotated[User | None, Depends(load_current_user)]) -> User:
    """The signed-in barber, for the barber pages.

    A visitor is sent to log in and back (the 401). A customer gets the same
    404 page as an address that does not exist, so the barber area does not
    advertise itself; the JSON API, in contrast, says 403.

    Raises: 401 `UNAUTHENTICATED`; 404 `NOT_FOUND`.
    """
    if user is None:
        raise AppError("UNAUTHENTICATED", "Log in to continue.", status_code=401)
    if user.role != UserRole.BARBER:
        raise AppError("NOT_FOUND", "Page not found.", status_code=404)
    return user


WebBarber = Annotated[User, Depends(require_barber_page)]
