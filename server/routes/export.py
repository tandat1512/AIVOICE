"""Export route."""

from __future__ import annotations

import asyncio
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from server.schemas.export_schema import ExportRequest
from server.services.export_service import ExportService


def create_export_router(service: ExportService) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["export"])

    @router.post("/export")
    async def export_file(req: ExportRequest) -> Response:
        try:
            exported = await asyncio.to_thread(service.export, req)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"export failed: {exc}") from exc

        filename = quote(exported.filename)
        return Response(
            content=exported.content,
            media_type=exported.media_type,
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
        )

    return router
