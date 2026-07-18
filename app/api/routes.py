import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import ValidationError

from app.models.ecowitt import EcowittPayload
from app.security.dependencies import require_whitelisted_station
from app.storage.registry import aggregation_service, raw_store, storage_status_cache, ws_manager
from app.utils.metric_utils import to_metric

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/")
def root():
    return {"status": "ok"}


@router.post("/data/report/")
async def receive_report(
    request: Request,
    station_id: str = Depends(require_whitelisted_station),
):
    # By the time execution reaches here, require_whitelisted_station
    # has already checked the incoming PASSKEY against the station
    # whitelist (403 if unknown) and resolved it to station_id - the
    # salted hash used from here on. The raw PASSKEY is not touched
    # again below.
    form = await request.form()

    try:
        payload = EcowittPayload.model_validate(dict(form))
    except ValidationError as exc:
        # model_validate() is called directly here rather than via a
        # FastAPI Form(...) parameter, so pydantic's ValidationError
        # doesn't automatically become a 422 the way it would for a
        # normal FastAPI-parsed body - it has to be caught explicitly,
        # or it propagates as an unhandled exception and becomes a 500.
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    logger.info("received report from station_id=%s", station_id)

    row = payload.model_dump()
    row["timestamp"] = row.pop("dateutc")
    row["PASSKEY"] = station_id  # overwrite: never persist the raw PASSKEY
    row = to_metric(row)  # adds temp_c, baromrel_hpa, thi, etc. - see metric_utils.py

    await raw_store.upsert_row(station_id=station_id, row=row)

    # Recompute 1m/1h/1d rollups from the now-updated raw history. At
    # Ecowitt's ~once-every-30s cadence this is cheap; see
    # AggregationService's docstring if that ever needs to change.
    aggregates = await aggregation_service.recompute_all(station_id)

    # Push the new reading (and each freshly-recomputed aggregate's
    # latest bucket) out to any subscribed WebSocket clients. A no-op
    # if nobody's subscribed to a given channel - see
    # WebSocketManager.broadcast().
    await ws_manager.broadcast(station_id, "raw", row)
    for interval, df in aggregates.items():
        if not df.is_empty():
            await ws_manager.broadcast(station_id, interval, df.tail(1).to_dicts()[0])

    # Every write changes disk usage, so this is the point that
    # invalidates the cache - GET endpoints just read it, they never
    # recompute it themselves.
    try:
        storage_status_cache.refresh()
    except Exception:
        # Storage monitoring is observability, not core functionality -
        # a failure here shouldn't take down data ingestion. Logged loudly
        # so it's visible, but the write above already succeeded and
        # should still be reported as such.
        logger.exception("failed to refresh storage status cache after write")

    # Ecowitt stations just need a 200 with some body to consider it delivered.
    return PlainTextResponse("success")
