"""HA-Rejseplanen - API 2.0 klient."""
from __future__ import annotations

from datetime import date as date_cls
from typing import Any

import aiohttp

BASE = "https://www.rejseplanen.dk/api"


class RejseplanenError(Exception):
    """Generisk API-fejl."""


class RejseplanenAuthError(RejseplanenError):
    """Ugyldig accessId."""


class RejseplanenClient:
    """Tynd klient - én metode pr. endpoint, ingen polling."""

    def __init__(self, session: aiohttp.ClientSession, access_id: str) -> None:
        self._session = session
        self._access_id = access_id

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        query = {
            "accessId": self._access_id,
            "format": "json",
            "lang": "da",
            **params,
        }
        async with self._session.get(f"{BASE}/{path}", params=query) as resp:
            if resp.status in (401, 403):
                raise RejseplanenAuthError("Ugyldig accessId")
            # content_type=None: acceptér selvom serveren melder text/xml ved fejl
            data = await resp.json(content_type=None)

        # HAFAS melder nogle fejl i selve svaret med HTTP 200
        if "errorCode" in data:
            code = data["errorCode"]
            if code in ("API_AUTH", "AUTH"):
                raise RejseplanenAuthError(data.get("errorText", ""))
            raise RejseplanenError(f"{code}: {data.get('errorText', '')}")
        return data

    async def lookup_stop(self, name: str) -> dict[str, Any] | None:
        """Slå første stop op for en fritekst-søgning."""
        data = await self._get("location.name", {"input": name})
        for loc in data.get("stopLocationOrCoordLocation", []):
            if "StopLocation" in loc:
                return loc["StopLocation"]
        return None

    async def resolve_location(self, name: str) -> dict[str, Any] | None:
        """Find en lokation ud fra fritekst - stop ELLER adresse.

        Returnerer et dict der beskriver stedet:
          {"kind": "stop",  "name": ..., "ext_id": ...}
          {"kind": "coord", "name": ..., "lat": ..., "lon": ...}
        Tager det FOERSTE resultat, uanset om det er stop eller adresse -
        saa "Kochsgade 20" bliver en adresse, "Odense St." bliver et stop.
        Returnerer None hvis intet blev fundet.
        """
        data = await self._get("location.name", {"input": name})
        for loc in data.get("stopLocationOrCoordLocation", []):
            if "StopLocation" in loc:
                s = loc["StopLocation"]
                return {"kind": "stop", "name": s["name"], "ext_id": s["extId"]}
            if "CoordLocation" in loc:
                c = loc["CoordLocation"]
                return {
                    "kind": "coord",
                    "name": c["name"],
                    "lat": c["lat"],
                    "lon": c["lon"],
                }
        return None

    async def search_stops(self, name: str, limit: int = 10) -> list[dict[str, Any]]:
        """Returner flere stop for en fritekst-soegning."""
        data = await self._get("location.name", {"input": name, "maxNo": limit})
        stops = []
        for loc in data.get("stopLocationOrCoordLocation", []):
            if "StopLocation" in loc:
                stop = loc["StopLocation"]
                stops.append({"name": stop["name"], "ext_id": stop["extId"]})
        return stops

    async def find_trip(
        self,
        origin: dict[str, Any],
        destination: dict[str, Any],
        arrive_by: str | None = None,
        depart_at: str | None = None,
        min_change_time: int | None = None,
        date: str | None = None,
    ) -> list[dict[str, Any]]:
        """Raa trip-soegning. origin/destination er resolve_location-dicts
        (kind = "stop" eller "coord"). Returnerer listen af Trip-objekter."""
        params: dict[str, Any] = {}
        params.update(self._location_params(origin, "origin"))
        params.update(self._location_params(destination, "dest"))

        # Default til i dag hvis intet er angivet - undgaar gaarsdagens afgange
        if date is None:
            date = date_cls.today().isoformat()
        params["date"] = date

        if arrive_by:
            params["searchForArrival"] = 1
            params["time"] = arrive_by
        elif depart_at:
            params["time"] = depart_at
        if min_change_time is not None:
            params["minChangeTime"] = min_change_time

        data = await self._get("trip", params)
        return data.get("Trip", [])

    @staticmethod
    def _location_params(loc: dict[str, Any], prefix: str) -> dict[str, Any]:
        """Byg trip-parametre for et sted, alt efter stop eller koordinat.
        prefix er "origin" eller "dest"."""
        if loc["kind"] == "stop":
            return {f"{prefix}ExtId": loc["ext_id"]}
        # coord: HAFAS bruger originCoordLat/Long/Name (og dest tilsvarende)
        return {
            f"{prefix}CoordLat": loc["lat"],
            f"{prefix}CoordLong": loc["lon"],
            f"{prefix}CoordName": loc["name"],
        }

    async def departures(
        self, stop_ext_id: str, duration: int = 90
    ) -> list[dict[str, Any]]:
        """Afgangstavle for et stop (on-demand, ingen polling)."""
        data = await self._get(
            "departureBoard", {"id": stop_ext_id, "duration": duration}
        )
        return data.get("Departure", [])