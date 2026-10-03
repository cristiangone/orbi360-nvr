"""Orbi360 NVR apis: SRT mosaic outputs and Telegram alerts."""

import asyncio
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from frigate.api.auth import require_role
from frigate.api.defs.tags import Tags
from frigate.orbi360 import mosaics, telegram

logger = logging.getLogger(__name__)

router = APIRouter(tags=[Tags.orbi360])


def _go2rtc_streams(request: Request) -> list[str]:
    streams = request.app.frigate_config.go2rtc.model_dump().get("streams") or {}
    return sorted(streams.keys())


def _response(
    request: Request, mosaic_list: mosaics.MosaicList, status: dict[str, str]
):
    return JSONResponse(
        content={
            "mosaics": mosaic_list.model_dump()["mosaics"],
            "status": status,
            "runtime": {m.id: mosaics.runtime(m.id) for m in mosaic_list.mosaics},
            "streams": _go2rtc_streams(request),
            "supported": mosaics.systemd_available(),
        }
    )


@router.get(
    "/orbi360/mosaics",
    dependencies=[Depends(require_role(["admin"]))],
    summary="List SRT mosaic outputs",
)
async def get_mosaics(request: Request):
    mosaic_list = await asyncio.to_thread(mosaics.load)
    status = {
        m.id: await asyncio.to_thread(mosaics.unit_status, m.id)
        for m in mosaic_list.mosaics
    }
    return _response(request, mosaic_list, status)


@router.put(
    "/orbi360/mosaics",
    dependencies=[Depends(require_role(["admin"]))],
    summary="Replace the SRT mosaic outputs and apply them",
)
async def put_mosaics(request: Request, body: dict):
    try:
        mosaic_list = mosaics.MosaicList.model_validate(body)
    except ValidationError as e:
        errors = "; ".join(err["msg"] for err in e.errors())
        return JSONResponse(
            content={"success": False, "message": errors}, status_code=400
        )

    known = set(_go2rtc_streams(request))
    unknown = sorted(
        {s for m in mosaic_list.mosaics for s in m.streams if s not in known}
    )
    if unknown:
        return JSONResponse(
            content={
                "success": False,
                "message": f"unknown go2rtc streams: {', '.join(unknown)}",
            },
            status_code=400,
        )

    await asyncio.to_thread(mosaics.save, mosaic_list)
    status = await asyncio.to_thread(mosaics.apply, mosaic_list)
    logger.info("SRT mosaics updated: %s", status)
    return _response(request, mosaic_list, status)


@router.post(
    "/orbi360/mosaics/{mosaic_id}/restart",
    dependencies=[Depends(require_role(["admin"]))],
    summary="Restart one SRT mosaic output",
)
async def restart_mosaic(mosaic_id: str):
    mosaic_list = await asyncio.to_thread(mosaics.load)
    if mosaic_id not in {m.id for m in mosaic_list.mosaics}:
        return JSONResponse(
            content={"success": False, "message": "mosaic not found"},
            status_code=404,
        )
    if not mosaics.systemd_available():
        return JSONResponse(
            content={"success": False, "message": "systemd is not available"},
            status_code=501,
        )

    await asyncio.to_thread(
        mosaics._systemctl, "restart", mosaics.UNIT_TEMPLATE.format(mosaic_id)
    )
    status = await asyncio.to_thread(mosaics.unit_status, mosaic_id)
    return JSONResponse(content={"success": True, "status": status})


def _validation_error(e: ValidationError) -> JSONResponse:
    errors = "; ".join(err["msg"] for err in e.errors())
    return JSONResponse(content={"success": False, "message": errors}, status_code=400)


@router.get(
    "/orbi360/telegram",
    dependencies=[Depends(require_role(["admin"]))],
    summary="Telegram alert settings (without the bot token)",
)
async def get_telegram():
    settings = await asyncio.to_thread(telegram.load)
    return JSONResponse(content=settings.public())


@router.put(
    "/orbi360/telegram",
    dependencies=[Depends(require_role(["admin"]))],
    summary="Save Telegram alert settings",
)
async def put_telegram(body: dict):
    try:
        settings = await asyncio.to_thread(telegram.merge, body)
    except ValidationError as e:
        return _validation_error(e)
    if settings.enabled and (not settings.bot_token or not settings.chat_id):
        return JSONResponse(
            content={
                "success": False,
                "message": "the bot token and the chat ID are required to enable alerts",
            },
            status_code=400,
        )
    await asyncio.to_thread(telegram.save, settings)
    logger.info("Telegram alerts %s", "enabled" if settings.enabled else "disabled")
    return JSONResponse(content=settings.public())


@router.post(
    "/orbi360/telegram/test",
    dependencies=[Depends(require_role(["admin"]))],
    summary="Send a test Telegram message with the given or stored settings",
)
async def test_telegram(body: dict):
    try:
        settings = await asyncio.to_thread(telegram.merge, body)
    except ValidationError as e:
        return _validation_error(e)
    error = await asyncio.to_thread(
        telegram.send,
        settings,
        "✅ Orbi360 NVR: los avisos por Telegram funcionan. "
        "Aquí llegarán las alertas de los mosaicos SRT.",
    )
    if error:
        return JSONResponse(
            content={"success": False, "message": error}, status_code=400
        )
    return JSONResponse(content={"success": True})
