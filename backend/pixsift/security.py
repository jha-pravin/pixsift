"""Access control for the local engine.

The engine only listens on 127.0.0.1, but other programs and user accounts on the same computer, and web
pages served from other local ports, can still reach it. So, like Jupyter, every launch has a random access
token. Opening `/?token=<token>` (the desktop app does this itself) stores it in a strict, HTTP-only cookie,
and every /api request must carry that cookie.

On top of that, browser requests that aren't same-origin are refused using the Sec-Fetch-Site header, which
also stops other sites from embedding pictures with <img> or planting a token via a link.
"""

import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

COOKIE = "pixsift_token"
_ALLOWED_FETCH_SITES = {None, "same-origin", "none"}  # missing = not a browser (or a very old one)


def new_token() -> str:
    return secrets.token_urlsafe(32)


class AccessGuard(BaseHTTPMiddleware):
    def __init__(self, app, token: str):
        super().__init__(app)
        self.token = token

    def _valid(self, value: str | None) -> bool:
        return bool(value) and secrets.compare_digest(value, self.token)

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.headers.get("sec-fetch-site") not in _ALLOWED_FETCH_SITES:
            return JSONResponse({"detail": "cross-site request refused"}, status_code=403)
        if "token" in request.query_params:
            if not self._valid(request.query_params["token"]):
                return JSONResponse({"detail": "invalid access token"}, status_code=401)
            response = RedirectResponse("/", status_code=303)  # drop the token from the address bar
            response.set_cookie(COOKIE, self.token, httponly=True, samesite="strict", path="/")
            return response
        if request.url.path.startswith("/api/") and not self._valid(request.cookies.get(COOKIE)):
            return JSONResponse({"detail": "open PixSift with the link shown when it started"}, status_code=401)
        return await call_next(request)
