"""Shared request dependencies: app state, the UI-header check, and picture lookups."""

import os

from fastapi import Depends, HTTPException, Request

from .config import Settings
from .db import Database


def require_ui_header(request: Request) -> None:
    """Mutating calls need a custom header: browsers can't send it cross-origin without a CORS preflight,
    so other websites can't drive this local API (e.g. trigger scans or open files)."""
    if request.headers.get("x-pixsift") != "1":
        raise HTTPException(403, "missing X-PixSift header")


MUTATING = [Depends(require_ui_header)]


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_pipeline(request: Request):
    return request.app.state.pipeline


def get_watcher(request: Request):
    return request.app.state.watcher


def get_image(image_id: int, db: Database = Depends(get_db)) -> dict:
    row = db.query_one("SELECT * FROM images WHERE id=?", (image_id,))
    if not row:
        raise HTTPException(404, "image not found")
    return row


def existing_file(db: Database, row: dict) -> str:
    """The picture's path, or a clear error when its drive is unplugged or the file is gone."""
    if not os.path.isfile(row["path"]):
        drive = row.get("volume_id") and db.query_one(
            "SELECT label FROM volumes WHERE id=? AND mounted=0", (row["volume_id"],))
        if drive:
            raise HTTPException(409, f"Connect the drive “{drive['label']}” to open this picture")
        raise HTTPException(410, "file no longer exists on disk")
    return row["path"]
