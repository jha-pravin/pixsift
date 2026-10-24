"""Shared request dependencies."""

from fastapi import Depends, HTTPException, Request


def require_ui_header(request: Request) -> None:
    """Mutating calls need a custom header: browsers can't send it cross-origin without a CORS preflight,
    so other websites can't drive this local API (e.g. trigger scans or open files)."""
    if request.headers.get("x-pixsift") != "1":
        raise HTTPException(403, "missing X-PixSift header")


MUTATING = [Depends(require_ui_header)]
