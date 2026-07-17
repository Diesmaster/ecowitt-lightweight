"""Convert Ecowitt's imperial-unit fields to metric, using Pint.

Ecowitt stations report in imperial units regardless of locale:
temperature in degF, pressure in inHg, wind speed in mph, rain in inches.
This module converts each of those to a metric equivalent, and also
provides the cattle Temperature-Humidity Index (THI), which is derived
from metric temperature + relative humidity.

Pint (https://pint.readthedocs.io) does the actual conversion work. Its
unit definitions come from a standalone, auditable definitions file
rather than constants buried in code, and it treats degF -> degC as the
affine conversion it actually is (not just a multiply), which is the
easiest place to get a hand-rolled conversion subtly wrong.

Pint also guards `calculate_thi` against a specific class of bug: if a
caller passes a temperature that's still in Fahrenheit (e.g. forgot to
convert), a bare float is silently accepted as-if it were Celsius and
produces a wrong-but-plausible-looking THI. Passing a `pint.Quantity`
instead removes that ambiguity - `Q_(91.8, ureg.degF)` is converted
correctly regardless of which unit it started in.
"""

from __future__ import annotations

import pint

# One registry for the whole process - UnitRegistry is relatively
# expensive to construct and is safe to share/reuse.
ureg = pint.UnitRegistry()
Q_ = ureg.Quantity


# --- Scalar conversion functions ----------------------------------------
def fahrenheit_to_celsius(value_f: float) -> float:
    """degF -> degC."""
    return Q_(value_f, ureg.degF).to(ureg.degC).magnitude


def inhg_to_hpa(value_inhg: float) -> float:
    """inHg -> hPa (mbar)."""
    return Q_(value_inhg, ureg.inHg).to(ureg.hPa).magnitude


def inhg_to_kpa(value_inhg: float) -> float:
    """inHg -> kPa."""
    return Q_(value_inhg, ureg.inHg).to(ureg.kPa).magnitude


def mph_to_ms(value_mph: float) -> float:
    """mph -> m/s."""
    return Q_(value_mph, ureg.mph).to(ureg.meter / ureg.second).magnitude


def mph_to_kmh(value_mph: float) -> float:
    """mph -> km/h."""
    return Q_(value_mph, ureg.mph).to(ureg.kilometer / ureg.hour).magnitude


def inches_to_mm(value_in: float) -> float:
    """in (or in/hr for rain rate) -> mm (or mm/hr)."""
    return Q_(value_in, ureg.inch).to(ureg.mm).magnitude


# --- Cattle Temperature-Humidity Index (THI) -----------------------------
#
#   THI = (1.8*T + 32) - [(0.55 - 0.0055*RH) * (1.8*T - 26)]
#
#   T  = air temperature in degrees Celsius
#   RH = relative humidity in percent (e.g. 75, not 0.75)
def calculate_thi(
    temperature_c: float | pint.Quantity,
    relative_humidity: float | pint.Quantity,
) -> float:
    """Calculate the cattle Temperature-Humidity Index.

    Args:
        temperature_c: air temperature. Pass a bare float/int to mean
            "already in degrees Celsius" (backwards compatible), or a
            `pint.Quantity` in any temperature unit (e.g.
            `Q_(91.8, ureg.degF)`) to have Pint convert it correctly -
            this is the safest option and avoids accidentally feeding
            in Fahrenheit.
        relative_humidity: relative humidity in percent (0-100). Pass a
            bare float/int, or a `pint.Quantity` in `ureg.percent`.

    Returns:
        THI as a float.
    """
    temp_q = (
        temperature_c
        if isinstance(temperature_c, pint.Quantity)
        else Q_(temperature_c, ureg.degC)
    )
    t_c = temp_q.to(ureg.degC).magnitude

    rh_pct = (
        relative_humidity.to(ureg.percent).magnitude
        if isinstance(relative_humidity, pint.Quantity)
        else relative_humidity
    )

    return (1.8 * t_c + 32) - ((0.55 - 0.0055 * rh_pct) * (1.8 * t_c - 26))


# --- Field-level mapping --------------------------------------------------
# Ecowitt field name -> (converter, metric field name)
# Fields not listed here are already metric/unitless and pass through
# unchanged: humidity, humidityin, winddir, solarradiation (W/m^2),
# uv, PASSKEY, dateutc, stationtype, runtime, heap, freq, model, interval,
# wh65batt.
TEMPERATURE_FIELDS: dict[str, str] = {
    "tempf": "temp_c",
    "tempinf": "tempin_c",
}

PRESSURE_FIELDS: dict[str, str] = {
    "baromrelin": "baromrel_hpa",
    "baromabsin": "baromabs_hpa",
}

WIND_SPEED_FIELDS: dict[str, str] = {
    "windspeedmph": "windspeed_ms",
    "windgustmph": "windgust_ms",
}

RAIN_FIELDS: dict[str, str] = {
    "rainratein": "rainrate_mm",
    "eventrainin": "eventrain_mm",
    "dailyrainin": "dailyrain_mm",
    "weeklyrainin": "weeklyrain_mm",
    "monthlyrainin": "monthlyrain_mm",
    "yearlyrainin": "yearlyrain_mm",
    "totalrainin": "totalrain_mm",
}

# Ecowitt reports VPD in inHg by default, same as the barometric fields.
VPD_FIELDS: dict[str, str] = {
    "vpd": "vpd_kpa",
}


def to_metric(payload: dict, *, keep_original: bool = True) -> dict:
    """Return a copy of `payload` with metric fields added.

    Also adds `thi` whenever both `tempf` and `humidity` are present in
    the input, computed from the freshly-converted `temp_c`.

    Only known imperial fields are converted; anything else (including
    fields this module doesn't recognize, e.g. new firmware sensors) is
    passed through untouched. Missing or None values are skipped rather
    than raising, since not every station reports every field.

    Args:
        payload: a dict shaped like an EcowittPayload.model_dump().
        keep_original: if True (default), the original imperial field
            stays in the output alongside its metric counterpart. If
            False, the imperial field is removed once converted.

    Returns:
        A new dict; `payload` itself is not mutated.
    """
    result = dict(payload)

    def _convert(fields: dict[str, str], converter) -> None:
        for src_key, dst_key in fields.items():
            if src_key not in result:
                continue
            value = result[src_key]
            if value is None:
                continue
            result[dst_key] = converter(float(value))
            if not keep_original:
                del result[src_key]

    _convert(TEMPERATURE_FIELDS, fahrenheit_to_celsius)
    _convert(PRESSURE_FIELDS, inhg_to_hpa)
    _convert(WIND_SPEED_FIELDS, mph_to_ms)
    _convert(RAIN_FIELDS, inches_to_mm)
    _convert(VPD_FIELDS, inhg_to_kpa)

    humidity = result.get("humidity")
    if "temp_c" in result and humidity is not None:
        result["thi"] = calculate_thi(
            Q_(result["temp_c"], ureg.degC),
            Q_(float(humidity), ureg.percent),
        )

    return result
