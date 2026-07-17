"""Data model for payloads sent by Ecowitt/EasyWeather stations."""

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, field_validator


class EcowittPayload(BaseModel):
    """Ecowitt/EasyWeather station upload payload.

    Only PASSKEY and dateutc are required to store a row; everything else
    is optional so firmware/model differences (missing or extra sensors)
    don't break ingestion. Unknown fields are kept as-is (extra="allow").

    This model represents exactly what the station sends - raw imperial
    values. Metric conversion and THI live in app.utils.metric_utils and
    are applied to the row dict in the route, not here.
    """

    model_config = ConfigDict(extra="allow")

    PASSKEY: str
    dateutc: datetime

    stationtype: str | None = None
    runtime: float | None = None
    heap: float | None = None
    tempinf: float | None = None
    humidityin: float | None = None
    baromrelin: float | None = None
    baromabsin: float | None = None
    tempf: float | None = None
    humidity: float | None = None
    winddir: float | None = None
    windspeedmph: float | None = None
    windgustmph: float | None = None
    solarradiation: float | None = None
    uv: float | None = None
    rainratein: float | None = None
    eventrainin: float | None = None
    dailyrainin: float | None = None
    weeklyrainin: float | None = None
    monthlyrainin: float | None = None
    yearlyrainin: float | None = None
    totalrainin: float | None = None
    vpd: float | None = None
    wh65batt: float | None = None
    freq: str | None = None
    interval: float | None = None

    @field_validator("dateutc", mode="before")
    @classmethod
    def parse_dateutc(cls, value: object) -> object:
        # Ecowitt sends e.g. "2026-07-17 07:00:27" (no tz, always UTC).
        if isinstance(value, str):
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone.utc
            )
        return value
