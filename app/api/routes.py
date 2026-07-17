import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import ValidationError

from app.models.ecowitt import EcowittPayload
from app.storage.registry import aggregation_service, raw_store
from app.utils.metric_utils import to_metric

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/")
def root():
    return {"status": "ok"}


@router.post("/data/report/")
async def receive_report(request: Request):
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

    logger.info("received report from PASSKEY=%s", payload.PASSKEY)

    row = payload.model_dump()
    row["timestamp"] = row.pop("dateutc")
    row = to_metric(row)  # adds temp_c, baromrel_hpa, thi, etc. - see metric_utils.py

    await raw_store.upsert_row(station_id=payload.PASSKEY, row=row)

    # Recompute 1m/1h/1d rollups from the now-updated raw history. At
    # Ecowitt's ~once-every-30s cadence this is cheap; see
    # AggregationService's docstring if that ever needs to change.
    await aggregation_service.recompute_all(payload.PASSKEY)

    # Ecowitt stations just need a 200 with some body to consider it delivered.
    return PlainTextResponse("success")
