"""TCMB EVDS (Elektronik Veri Dağıtım Sistemi) HTTP client.

EVDS provides Turkish Central Bank time-series data: policy rates, yields,
FX, inflation, monetary aggregates, etc. Free API key (small per-IP quota,
sufficient for an individual research tool) at:
    https://evds3.tcmb.gov.tr/  (new portal, evds2 still works as alias)

IMPORTANT — 2024-04-05 breaking change:
    The `key` previously passed as a URL query parameter is now rejected.
    Authentication must be sent in the HTTP header:
        headers = {"key": api_key}
    This module sends the key in the header. If a user reports "anahtarım
    çalışmıyor" with old code/snippets, they almost certainly hit the
    query-param path. Reference:
    https://urazakgul.github.io/python-blog/posts/post_9/

Series codes are documented at:
    https://evds3.tcmb.gov.tr/tumSeriler

v0.3 improvements:
    - Uses the shared httpx.AsyncClient from http_utils (connection pooling,
      TCP/TLS reuse) instead of creating a new client per request.
    - Retry with exponential backoff is handled by the shared client layer.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import date, datetime

import httpx

from .http_utils import get_shared_client

# EVDS migrated host + path in 2025: the legacy `evds2.tcmb.gov.tr/service/evds`
# now redirects to evds3 which serves only the SPA shell. The actual REST API
# lives at evds3.tcmb.gov.tr/igmevdsms-dis. Confirmed by orhoncan/evds-mcp.
EVDS_BASE_URL = "https://evds3.tcmb.gov.tr/igmevdsms-dis"
DEFAULT_TIMEOUT = 30.0


class EVDSError(RuntimeError):
    """Raised when EVDS returns an error or the response is unparseable."""


@dataclass
class EVDSObservation:
    """A single observation in an EVDS time series."""

    date: str
    value: float | None
    series_code: str


class EVDSClient:
    """Async HTTP client for TCMB EVDS.

    The API key may be passed explicitly or read from `TCMB_EVDS_API_KEY`.

    v0.3: uses the shared httpx.AsyncClient from http_utils for connection
    pooling. No longer creates a new client per request.
    """

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        base_url: str = EVDS_BASE_URL,
    ) -> None:
        self.api_key = api_key or os.environ.get("TCMB_EVDS_API_KEY")
        if not self.api_key:
            raise EVDSError(
                "TCMB EVDS API key not set. Pass api_key= or set TCMB_EVDS_API_KEY env var. "
                "Get one free at https://evds2.tcmb.gov.tr/"
            )
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def get_series(
        self,
        series_codes: list[str],
        start: date | str,
        end: date | str | None = None,
        frequency: int | None = None,
        aggregation: str | None = None,
        formulas: str | None = None,
    ) -> list[EVDSObservation]:
        """Fetch one or more EVDS series and return flat observations.

        Args:
            series_codes: List of EVDS series codes (e.g. ["TP.MK.KUR.TRY.E.A"]).
            start: Start date (YYYY-MM-DD or date).
            end: End date (defaults to today).
            frequency: 1=daily, 2=workday, 3=weekly, 4=biweekly, 5=monthly,
                       6=quarterly, 7=semi-annual, 8=annual.
            aggregation: avg | min | max | first | last | sum.
            formulas: Optional EVDS formula codes (0..7).
        """
        if not series_codes:
            raise EVDSError("series_codes is empty")

        start_str = _fmt_date(start)
        end_str = _fmt_date(end) if end else _fmt_date(date.today())

        # TCMB EVDS quirk: query parameters are encoded as a PATH SEGMENT
        # of the form `key1=val1&key2=val2&...` appended to the endpoint
        # path. Standard `?key=val` query strings do NOT work — observed
        # via the new evds3 portal and confirmed by orhoncan/evds-mcp.
        path_parts = [
            f"series={'-'.join(series_codes)}",
            f"startDate={start_str}",
            f"endDate={end_str}",
            "type=json",
        ]
        if frequency is not None:
            path_parts.append(f"frequency={frequency}")
        if aggregation is not None:
            path_parts.append(f"aggregationTypes={aggregation}")
        if formulas is not None:
            path_parts.append(f"formulas={formulas}")

        url = f"{self.base_url}/" + "&".join(path_parts)

        headers = {"key": self.api_key, "Accept": "application/json"}

        # Use the shared client for connection reuse across EVDS calls.
        # We add retry with exponential backoff for transient failures.
        client = get_shared_client()
        last_err: Exception | None = None
        max_retries = 3

        for attempt in range(max_retries + 1):
            try:
                resp = await client.get(url, headers=headers)
                if resp.status_code in (401, 403):
                    raise EVDSError(
                        f"EVDS auth rejected (HTTP {resp.status_code}). "
                        "Verify TCMB_EVDS_API_KEY is the new-style key from "
                        "evds3.tcmb.gov.tr and that it has not been revoked."
                    )
                if resp.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
                    last_err = EVDSError(f"EVDS HTTP {resp.status_code} (transient)")
                    await asyncio.sleep(min(10.0, 1.0 * (2 ** attempt)))
                    continue
                if resp.status_code >= 400:
                    raise EVDSError(
                        f"EVDS HTTP {resp.status_code}: {resp.text[:300]}"
                    )
                try:
                    payload = resp.json()
                except ValueError as e:
                    raise EVDSError(f"EVDS returned non-JSON response: {e}") from e
                break
            except (httpx.TransportError, httpx.HTTPStatusError) as e:
                last_err = e
                if attempt >= max_retries:
                    raise EVDSError(
                        f"EVDS request failed after {max_retries + 1} attempts: {last_err}"
                    ) from e
                await asyncio.sleep(min(10.0, 1.0 * (2 ** attempt)))
                continue
        else:
            raise EVDSError(f"EVDS request failed after {max_retries + 1} attempts: {last_err}")

        items = payload.get("items")
        if not isinstance(items, list):
            raise EVDSError(f"EVDS unexpected payload: {str(payload)[:200]}")

        observations: list[EVDSObservation] = []
        for row in items:
            row_date = row.get("Tarih") or row.get("UNIXTIME") or ""
            for code in series_codes:
                # EVDS replaces dots with underscores in JSON keys.
                key = code.replace(".", "_")
                raw = row.get(key)
                if raw in (None, ""):
                    value: float | None = None
                else:
                    try:
                        value = float(raw)
                    except (TypeError, ValueError):
                        value = None
                observations.append(
                    EVDSObservation(date=str(row_date), value=value, series_code=code)
                )
        return observations


def _fmt_date(d: date | str) -> str:
    """EVDS expects DD-MM-YYYY date strings."""
    if isinstance(d, str):
        # Accept YYYY-MM-DD or DD-MM-YYYY transparently.
        try:
            parsed = datetime.strptime(d, "%Y-%m-%d").date()
        except ValueError:
            try:
                parsed = datetime.strptime(d, "%d-%m-%Y").date()
            except ValueError as e:
                raise EVDSError(f"Bad date string: {d}") from e
    else:
        parsed = d
    return parsed.strftime("%d-%m-%Y")
