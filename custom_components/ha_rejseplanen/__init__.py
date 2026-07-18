"""HA-Rejseplanen - stateless service-integration."""
from __future__ import annotations

from datetime import date as date_cls, datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import RejseplanenClient, RejseplanenError
from .const import CONF_ACCESS_ID, DOMAIN

# Brugervenlige kategorier -> hvilke catOut-vaerdier de daekker.
# Saa "tog" rammer alle togtyper, ikke kun én kode.
TRANSPORT_KATEGORIER = {
    "tog": {"RA", "RE", "IC", "ICL", "LYN", "TOG", "S", "REG", "L", "M"},
    "bus": {"BUS", "EXB", "NB", "TB"},
    "faerge": {"FAERGE", "FÆRGE", "SHIP", "F"},
    "metro": {"M", "METRO"},
    "letbane": {"LET", "TRAM", "L"},
}


def _leg_kategori(cat_out: str) -> str | None:
    """Oversaet en catOut-vaerdi til en brugerkategori (tog/bus/faerge...)."""
    if not cat_out:
        return None
    upper = cat_out.upper()
    for kategori, koder in TRANSPORT_KATEGORIER.items():
        if upper in koder:
            return kategori
    return None


def _parse_trips(
    raw_trips: list, limit: int, seneste_ankomst: str | None = None,
    detailed: bool = False, max_changes: int | None = None,
    avoid: list[str] | None = None,
) -> list[dict]:
    """Parse Trip-objekter til automations-venlige dicts.

    seneste_ankomst: hvis sat ("YYYY-MM-DD HH:MM"), beholdes kun rejser der
    ankommer PAA samme dato OG senest paa tidspunktet. Sorteres saa de SENESTE
    rejser (taettest paa graensen) kommer foerst.
    Uden arrive_by sorteres tidligste foerst (naeste afgang fra nu).

    detailed: tilfoej 'leg_details' med tider, stop og gaaure (WALK).
    max_changes: frasorter rejser med flere skift end dette.
    avoid: liste af kategorier (tog/bus/faerge...) - rejser der bruger nogen
           af dem frasorteres.
    """
    seneste_dato = seneste_ankomst[:10] if seneste_ankomst else None
    avoid_set = {a.lower() for a in avoid} if avoid else set()

    parsed = []
    for trip in raw_trips:
        dest = trip["Destination"]
        ankomst = f'{dest["date"]} {dest["time"][:5]}'

        # Stram arrive_by: kun samme dato, og ikke for sent.
        if seneste_ankomst:
            if dest["date"] != seneste_dato or ankomst > seneste_ankomst:
                continue

        # Max skift
        skift = trip.get("transferCount", 0)
        if max_changes is not None and skift > max_changes:
            continue

        origin = trip["Origin"]

        # Byg legs. Undervejs: tjek om rejsen bruger en uoensket transportform.
        legs = []
        leg_details = []
        bruger_uoensket = False
        for leg in trip["LegList"]["Leg"]:
            typ = leg.get("type")
            leg_o = leg["Origin"]
            leg_d = leg["Destination"]

            if typ == "JNY":
                product = leg["Product"][0]
                navn = product["name"]
                kategori = product.get("catOut", "")
                brugerkat = _leg_kategori(kategori)
                if brugerkat and brugerkat in avoid_set:
                    bruger_uoensket = True
                retning = leg.get("direction", "?")
                legs.append(f"{navn} ({kategori}) mod {retning}")
                if detailed:
                    leg_details.append({
                        "transport": navn,
                        "type": kategori,
                        "fra": leg_o["name"],
                        "afgang": leg_o.get("time", "")[:5],
                        "spor": (leg_o.get("rtPlatform", {}).get("text")
                                 or leg_o.get("rtTrack")),
                        "til": leg_d["name"],
                        "ankomst": leg_d.get("time", "")[:5],
                    })
            elif typ == "WALK" and detailed:
                dist = leg.get("dist") or leg.get("gis", {}).get("dist")
                leg_details.append({
                    "transport": "Gå",
                    "type": "WALK",
                    "fra": leg_o["name"],
                    "afgang": leg_o.get("time", "")[:5],
                    "til": leg_d["name"],
                    "ankomst": leg_d.get("time", "")[:5],
                    "afstand_m": dist,
                })

        # Frasorter hele rejsen hvis den bruger en uoensket transportform
        if bruger_uoensket:
            continue

        trip_dict = {
            "afgang": f'{origin["date"]} {origin["time"][:5]}',
            "fra": origin["name"],
            "spor": origin.get("rtPlatform", {}).get("text") or origin.get("rtTrack"),
            "ankomst": ankomst,
            "til": dest["name"],
            "varighed": trip.get("duration", "").replace("PT", "").lower(),
            "skift": skift,
            "legs": legs,
        }
        if detailed:
            trip_dict["leg_details"] = leg_details

        parsed.append(trip_dict)

    parsed.sort(key=lambda t: t["ankomst"], reverse=bool(seneste_ankomst))
    return parsed[:limit]


def _parse_departures(raw: list, limit: int) -> list[dict]:
    """Parse departureBoard-afgange til automations-venlige dicts."""
    afgange = []
    for dep in raw[:limit]:
        product = dep.get("ProductAtStop", {})
        afgange.append({
            "linje": product.get("displayNumber") or dep.get("name", ""),
            "type": product.get("catOut", ""),
            "retning": dep.get("direction", ""),
            # Realtid hvis den findes, ellers planlagt tid
            "tid": (dep.get("rtTime") or dep.get("time", ""))[:5],
            "dato": dep.get("rtDate") or dep.get("date", ""),
            "spor": dep.get("rtTrack") or dep.get("track"),
            "aflyst": dep.get("cancelled", False),
        })
    return afgange


def _home_location(hass: HomeAssistant) -> dict | None:
    """Hent HA's hjemzone som en coord-lokation (samme form som resolve_location)."""
    home = hass.states.get("zone.home")
    if not home:
        return None
    lat = home.attributes.get("latitude")
    lon = home.attributes.get("longitude")
    if lat is None or lon is None:
        return None
    return {"kind": "coord", "name": "Hjem", "lat": lat, "lon": lon}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Byg klienten og registrer actions. Ingen polling."""
    client = RejseplanenClient(
        async_get_clientsession(hass), entry.data[CONF_ACCESS_ID]
    )
    entry.runtime_data = client

    async def handle_search_stops(call: ServiceCall) -> ServiceResponse:
        try:
            stops = await client.search_stops(call.data["query"])
        except RejseplanenError as err:
            return {"error": str(err), "stops": []}
        return {"stops": stops}

    async def handle_find_trip(call: ServiceCall) -> ServiceResponse:
        data = call.data
        arrive_by = data.get("arrive_by")
        buffer = data.get("buffer", 0)
        max_results = data.get("max_results", 1)
        detailed = data.get("detailed", False)
        max_changes = data.get("max_changes")
        avoid = data.get("avoid")

        # Buffer: traek minutter fra ankomsttiden foer soegning
        if arrive_by and buffer:
            t = datetime.strptime(arrive_by, "%H:%M") - timedelta(minutes=buffer)
            arrive_by = t.strftime("%H:%M")

        try:
            dest = await client.resolve_location(data["destination"])
            if not dest:
                return {
                    "error": f"Ingen lokation fundet for '{data['destination']}'",
                    "trips": [],
                }

            origin_name = data.get("origin")
            if origin_name:
                origin = await client.resolve_location(origin_name)
                if not origin:
                    return {
                        "error": f"Ingen lokation fundet for '{origin_name}'",
                        "trips": [],
                    }
            else:
                origin = _home_location(hass)
                if not origin:
                    return {
                        "error": "Ingen origin angivet og hjemzone mangler koordinater",
                        "trips": [],
                    }

            soge_dato = data.get("date") or date_cls.today().isoformat()

            raw_trips = await client.find_trip(
                origin=origin,
                destination=dest,
                arrive_by=arrive_by,
                depart_at=data.get("depart_at"),
                min_change_time=data.get("min_change_time"),
                date=soge_dato,
            )
        except RejseplanenError as err:
            return {"error": str(err), "trips": []}

        seneste_ankomst = f"{soge_dato} {arrive_by}" if arrive_by else None

        return {
            "origin": origin["name"],
            "destination": dest["name"],
            "trips": _parse_trips(
                raw_trips, max_results, seneste_ankomst, detailed,
                max_changes, avoid,
            ),
        }

    async def handle_departures(call: ServiceCall) -> ServiceResponse:
        data = call.data
        max_results = data.get("max_results", 5)
        try:
            stop = await client.resolve_location(data["stop"])
            if not stop or stop["kind"] != "stop":
                return {"error": f"'{data['stop']}' er ikke et stop", "departures": []}
            raw = await client.departures(stop["ext_id"], data.get("duration", 90))
        except RejseplanenError as err:
            return {"error": str(err), "departures": []}
        return {
            "stop": stop["name"],
            "departures": _parse_departures(raw, max_results),
        }

    hass.services.async_register(
        DOMAIN, "search_stops", handle_search_stops,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, "find_trip", handle_find_trip,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, "departures", handle_departures,
        supports_response=SupportsResponse.ONLY,
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.services.async_remove(DOMAIN, "search_stops")
    hass.services.async_remove(DOMAIN, "find_trip")
    hass.services.async_remove(DOMAIN, "departures")
    return True