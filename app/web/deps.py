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
from app.models.user import User


def load_current_user(request: Request, user: OptionalUser) -> User | None:
    request.state.current_user = user
    return user


WebUser = Annotated[User | None, Depends(load_current_user)]
