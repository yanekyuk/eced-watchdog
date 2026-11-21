"""External OpenStreetMap / Overpass 3 km spatial verification around exact PDF project coordinates."""

from __future__ import annotations

import json
import math
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from .revisions import haversine_meters

OVERPASS_ENDPOINTS = (
    "https://overpass.openstreetmap.fr/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
GIS_USER_AGENT = "eced-watchdog/0.5 (public-interest Turkish EIA monitor)"


def coord_cache_key(lat: float, lon: float) -> str:
    return f"{lat:.4f},{lon:.4f}"


def _build_bbox_query(lat: float, lon: float, radius_m: int = 3000) -> str:
    """Build an exact-tag indexed node/way bbox query (avoids slow relation/regex scans)."""
    dlat = radius_m / 111_320.0
    dlon = radius_m / (111_320.0 * max(0.2, math.cos(math.radians(lat))))
    bb = f"{lat - dlat:.5f},{lon - dlon:.5f},{lat + dlat:.5f},{lon + dlon:.5f}"
    return (
        f"[out:json][timeout:10];\n"
        f"(\n"
        f'  way["landuse"="orchard"]({bb});\n'
        f'  way["landuse"="vineyard"]({bb});\n'
        f'  way["landuse"="forest"]({bb});\n'
        f'  way["landuse"="reservoir"]({bb});\n'
        f'  node["trees"="olive_trees"]({bb});\n'
        f'  way["trees"="olive_trees"]({bb});\n'
        f'  way["crop"="olives"]({bb});\n'
        f'  way["waterway"="river"]({bb});\n'
        f'  way["waterway"="stream"]({bb});\n'
        f'  way["waterway"="canal"]({bb});\n'
        f'  way["natural"="water"]({bb});\n'
        f'  way["natural"="wetland"]({bb});\n'
        f'  way["natural"="wood"]({bb});\n'
        f'  node["natural"="spring"]({bb});\n'
        f'  way["boundary"="protected_area"]({bb});\n'
        f'  way["leisure"="nature_reserve"]({bb});\n'
        f'  node["place"="village"]({bb});\n'
        f'  node["place"="hamlet"]({bb});\n'
        f'  node["place"="town"]({bb});\n'
        f'  node["place"="suburb"]({bb});\n'
        f'  node["place"="neighbourhood"]({bb});\n'
        f'  node["amenity"="school"]({bb});\n'
        f'  way["amenity"="school"]({bb});\n'
        f'  node["amenity"="hospital"]({bb});\n'
        f'  way["amenity"="hospital"]({bb});\n'
        f'  node["amenity"="clinic"]({bb});\n'
        f");\n"
        f"out center tags 200;"
    )


def _element_coords(el: dict[str, Any]) -> tuple[float, float] | None:
    if "lat" in el and "lon" in el:
        return (float(el["lat"]), float(el["lon"]))
    c = el.get("center")
    if isinstance(c, dict) and "lat" in c and "lon" in c:
        return (float(c["lat"]), float(c["lon"]))
    return None


def parse_overpass_elements(
    elements: list[dict[str, Any]],
    lat: float,
    lon: float,
    *,
    radius_m: int = 3000,
) -> dict[str, Any]:
    """Classify Overpass elements within radius_m into legally meaningful Turkish EIA buckets."""
    buckets: dict[str, list[dict[str, Any]]] = {
        "olive_or_orchard": [],
        "water_bodies": [],
        "protected_or_forest": [],
        "settlements": [],
        "sensitive_facilities": [],
    }

    for el in elements:
        pt = _element_coords(el)
        if not pt:
            continue
        dist_m = haversine_meters(lat, lon, pt[0], pt[1])
        if dist_m > radius_m:
            continue
        tags = el.get("tags") or {}
        name = (tags.get("name") or tags.get("name:tr") or "").strip()
        name_low = name.lower()

        lu = (tags.get("landuse") or "").lower()
        nat = (tags.get("natural") or "").lower()
        ww = (tags.get("waterway") or "").lower()
        bnd = (tags.get("boundary") or "").lower()
        lei = (tags.get("leisure") or "").lower()
        plc = (tags.get("place") or "").lower()
        amn = (tags.get("amenity") or "").lower()
        trees = (tags.get("trees") or "").lower()
        crop = (tags.get("crop") or "").lower()

        item_base = {
            "name": name,
            "distance_m": int(round(dist_m)),
            "lat": round(pt[0], 5),
            "lon": round(pt[1], 5),
        }

        if trees == "olive_trees" or crop == "olives" or "zeytin" in name_low or lu in ("orchard", "vineyard"):
            explicit_olive = trees == "olive_trees" or crop == "olives" or "zeytin" in name_low
            kind = "Zeytinlik" if explicit_olive else ("Bağ" if lu == "vineyard" else "Meyve bahçesi / dikili alan")
            buckets["olive_or_orchard"].append({**item_base, "kind": kind, "explicit_olive": explicit_olive})
        elif ww in ("river", "stream", "canal") or nat in ("water", "wetland", "spring") or lu == "reservoir":
            kind_map = {
                "river": "Nehir",
                "stream": "Dere / Akarsu",
                "canal": "Su kanalı",
                "wetland": "Sulak alan",
                "spring": "Kaynak suyu",
                "water": "Su kütlesi / gölet",
                "reservoir": "Baraj / rezervuar",
            }
            kind = kind_map.get(ww or nat or lu, "Su kaynağı")
            buckets["water_bodies"].append({**item_base, "kind": kind})
        elif bnd == "protected_area" or lei == "nature_reserve" or lu == "forest" or nat == "wood":
            is_protected = bnd == "protected_area" or lei == "nature_reserve"
            kind = "Korunan alan / doğa koruma" if is_protected else "Orman / ağaçlık alan"
            buckets["protected_or_forest"].append({**item_base, "kind": kind, "is_protected": is_protected})
        elif plc in ("village", "hamlet", "town", "suburb", "neighbourhood"):
            plc_map = {
                "village": "Köy",
                "hamlet": "Mezra",
                "town": "İlçe / belde",
                "suburb": "Semt",
                "neighbourhood": "Mahalle",
            }
            buckets["settlements"].append({**item_base, "kind": plc_map.get(plc, "Yerleşim")})
        elif amn in ("school", "kindergarten", "hospital", "clinic"):
            amn_map = {
                "school": "Okul",
                "kindergarten": "Anaokulu",
                "hospital": "Hastane",
                "clinic": "Sağlık tesisi",
            }
            buckets["sensitive_facilities"].append({**item_base, "kind": amn_map.get(amn, "Hassas tesis")})

    summary: dict[str, Any] = {}
    for bkey, rows in buckets.items():
        rows.sort(key=lambda r: r["distance_m"])
        deduped: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for r in rows:
            dk = (r["name"].lower(), r["kind"])
            if r["name"] and dk in seen:
                continue
            if r["name"]:
                seen.add(dk)
            deduped.append(r)
            if len(deduped) >= 5:
                break

        entry: dict[str, Any] = {
            "count": len(rows),
            "min_distance_m": rows[0]["distance_m"] if rows else None,
            "nearest": deduped,
        }
        if bkey == "olive_or_orchard":
            entry["explicit_olive_count"] = sum(1 for r in rows if r.get("explicit_olive"))
        if bkey == "protected_or_forest":
            entry["protected_count"] = sum(1 for r in rows if r.get("is_protected"))
        summary[bkey] = entry

    return {
        "source": "OpenStreetMap / Overpass",
        "radius_m": radius_m,
        "queried_at": datetime.now().isoformat(timespec="seconds"),
        "lat": round(lat, 5),
        "lon": round(lon, 5),
        "categories": summary,
    }


def query_osm_proximity(
    lat: float,
    lon: float,
    *,
    radius_m: int = 3000,
    timeout_sec: float = 10.0,
    endpoints: tuple[str, ...] = OVERPASS_ENDPOINTS,
) -> tuple[dict[str, Any], str]:
    """Query Overpass API (with fast mirror fallback); returns (parsed_result, endpoint_used)."""
    query = _build_bbox_query(lat, lon, radius_m=radius_m)
    last_err: Exception | None = None
    for endpoint in endpoints:
        try:
            with httpx.Client(
                timeout=httpx.Timeout(connect=5.0, read=timeout_sec, write=5.0, pool=5.0),
                headers={"User-Agent": GIS_USER_AGENT},
                follow_redirects=True,
            ) as client:
                resp = client.post(endpoint, data={"data": query})
                if resp.status_code in (429, 502, 503, 504):
                    last_err = RuntimeError(f"HTTP {resp.status_code} from {endpoint}")
                    time.sleep(0.5)
                    continue
                resp.raise_for_status()
                data = resp.json()
                return parse_overpass_elements(data.get("elements") or [], lat, lon, radius_m=radius_m), endpoint
        except Exception as exc:
            last_err = exc
            continue
    raise RuntimeError(f"Overpass query failed across mirrors: {last_err}")


def detect_spatial_omissions(
    gis_entry: dict[str, Any] | None,
    audit_checks: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Compare independent OSM 3 km features against PDF audit_checks to flag omissions by silence."""
    if not gis_entry:
        return []
    cats = gis_entry.get("categories") or {}
    checks = audit_checks or {}
    alerts: list[dict[str, Any]] = []

    olives = cats.get("olive_or_orchard") or {}
    if olives.get("count", 0) > 0:
        d = olives["min_distance_m"]
        exp_cnt = olives.get("explicit_olive_count", 0)
        lbl = "zeytinlik" if exp_cnt > 0 else "meyve bahçesi / dikili tarım alanı"
        if not checks.get("mentions_olive_law_3573"):
            alerts.append(
                {
                    "code": "omitted_olive_3km",
                    "severity": "high",
                    "title": f"PDF'te geçmeyen 3 km içi {lbl} ({olives['count']} kayıt, en yakın ~{d} m)",
                    "detail": (
                        f"OpenStreetMap verisinde proje koordinatlarının 3 km çevresinde {olives['count']} {lbl} kaydı "
                        f"görünmektedir; ancak PDF metninde 3573 sayılı Kanun veya 'zeytinlik' ifadesi tespit edilemedi. "
                        f"Uydu görüntüsü ve İlçe Tarım kayıtlarıyla doğrulayınız."
                    ),
                }
            )
        elif exp_cnt > 0:
            alerts.append(
                {
                    "code": "olive_3km_proximity",
                    "severity": "medium",
                    "title": f"3 km içinde kayıtlı zeytinlik (~{d} m)",
                    "detail": (
                        f"OpenStreetMap'te 3 km sınırında {exp_cnt} zeytinlik kaydı mevcut. "
                        f"3573 m.20 mesafesinin kırma-eleme, pasa sahası ve nakliye yollarından ölçülüp ölçülmediğini kontrol ediniz."
                    ),
                }
            )

    prot = cats.get("protected_or_forest") or {}
    if prot.get("protected_count", 0) > 0:
        d = prot["min_distance_m"]
        names = [x["name"] for x in (prot.get("nearest") or []) if x.get("is_protected") and x.get("name")]
        name_part = f" ({', '.join(names[:2])})" if names else ""
        alerts.append(
            {
                "code": "protected_area_3km",
                "severity": "high",
                "title": f"3 km içinde korunan alan / doğa koruma sahası (~{d} m){name_part}",
                "detail": "Proje çevresinde korunan alan statüsü tespit edildi; ÖÇK / SİT kurum görüşlerini doğrulayınız.",
            }
        )

    water = cats.get("water_bodies") or {}
    if water.get("count", 0) > 0 and water.get("min_distance_m") is not None and water["min_distance_m"] <= 1500:
        d = water["min_distance_m"]
        names = [x["name"] for x in (water.get("nearest") or []) if x.get("name")]
        name_part = f" ({names[0]})" if names else ""
        if not checks.get("mentions_groundwater_or_aquifer"):
            alerts.append(
                {
                    "code": "omitted_water_1500m",
                    "severity": "high" if d <= 800 else "medium",
                    "title": f"PDF'te hidrojeoloji/su taraması eksik, yakın su kaynağı var (~{d} m{name_part})",
                    "detail": (
                        f"OpenStreetMap'te proje sahasına ~{d} m mesafede akarsu/sulak alan/su kütlesi görünmektedir; "
                        f"ancak PDF metninde yeraltı suyu veya hidrojeoloji ifadesi bulunamadı."
                    ),
                }
            )

    sens = cats.get("sensitive_facilities") or {}
    if sens.get("count", 0) > 0 and sens.get("min_distance_m") is not None and sens["min_distance_m"] <= 1500:
        d = sens["min_distance_m"]
        first = (sens.get("nearest") or [{}])[0]
        fname = f" ({first.get('name')})" if first.get("name") else ""
        alerts.append(
            {
                "code": "sensitive_facility_close",
                "severity": "medium",
                "title": f"1,5 km içinde {first.get('kind', 'okul/sağlık tesisi').lower()} (~{d} m{fname})",
                "detail": "Toz, gürültü ve trafik güvenliği açısından hassas alıcı mesafesi doğrudan keşif konusu yapılabilir.",
            }
        )

    sett = cats.get("settlements") or {}
    if sett.get("count", 0) > 0 and sett.get("min_distance_m") is not None and sett["min_distance_m"] <= 1000:
        d = sett["min_distance_m"]
        first = (sett.get("nearest") or [{}])[0]
        sname = f" ({first.get('name')})" if first.get("name") else ""
        alerts.append(
            {
                "code": "settlement_1km",
                "severity": "info",
                "title": f"1 km içinde yerleşim yeri (~{d} m{sname})",
                "detail": "Yakın mahalle/köy sakinleri İYUK m.2 uyarınca doğrudan ve en güçlü dava ehliyetine sahiptir.",
            }
        )

    return alerts


def load_gis_cache(cache_path: Path) -> dict[str, dict[str, Any]]:
    if not cache_path.exists():
        return {}
    try:
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
        return raw.get("entries", raw) if isinstance(raw, dict) else {}
    except Exception:
        return {}


def save_gis_cache(cache_path: Path, entries: dict[str, dict[str, Any]]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "count": len(entries),
        "entries": entries,
    }
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def enrich_digests_gis(
    digests_dir: Path,
    cache_path: Path,
    *,
    max_new: int = 15,
    delay_sec: float = 1.2,
) -> tuple[dict[str, dict[str, Any]], int, int]:
    """Politely fetch & cache 3 km OSM proximity data for exact-coord digests not yet cached."""
    entries = load_gis_cache(cache_path)
    if max_new <= 0 or not digests_dir.exists():
        return entries, 0, 0

    pending: list[tuple[str, float, float, str]] = []
    seen_keys: set[str] = set()
    for jf in sorted(digests_dir.glob("*_analysis.json")):
        try:
            saved = json.loads(jf.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        geo = (saved.get("analysis") or {}).get("geo") or {}
        if geo.get("precision") != "exact_pdf" or geo.get("lat") is None or geo.get("lon") is None:
            continue
        lat, lon = float(geo["lat"]), float(geo["lon"])
        ck = coord_cache_key(lat, lon)
        if ck in entries or ck in seen_keys:
            continue
        seen_keys.add(ck)
        fid = jf.name.replace("_analysis.json", "")
        pending.append((fid, lat, lon, ck))

    batch = pending[:max_new]
    if not batch:
        return entries, 0, 0

    print(
        f"GIS 3 km verification: querying {len(batch)}/{len(pending)} uncached exact-coord filings via OpenStreetMap...",
        flush=True,
    )
    fetched = 0
    failed = 0
    consecutive_failures = 0
    ordered_endpoints = list(OVERPASS_ENDPOINTS)

    for idx, (fid, lat, lon, ck) in enumerate(batch, start=1):
        if idx > 1:
            time.sleep(delay_sec)
        t0 = time.time()
        try:
            res, used_ep = query_osm_proximity(lat, lon, radius_m=3000, endpoints=tuple(ordered_endpoints))
            # Pin the working mirror to the front so subsequent calls stay fast
            if used_ep in ordered_endpoints and ordered_endpoints[0] != used_ep:
                ordered_endpoints.remove(used_ep)
                ordered_endpoints.insert(0, used_ep)
            entries[ck] = res
            fetched += 1
            consecutive_failures = 0
            save_gis_cache(cache_path, entries)
            cats = res["categories"]
            print(
                f"  [{idx}/{len(batch)}] GIS #{fid} ({ck}) OK in {time.time() - t0:.1f}s "
                f"(olive/orch={cats['olive_or_orchard']['count']}, water={cats['water_bodies']['count']}, "
                f"forest/prot={cats['protected_or_forest']['count']}, sett={cats['settlements']['count']})",
                flush=True,
            )
        except Exception as exc:
            failed += 1
            consecutive_failures += 1
            print(f"  [{idx}/{len(batch)}] WARN GIS #{fid} ({ck}) after {time.time() - t0:.1f}s: {exc}", flush=True)
            if consecutive_failures >= 3:
                print(
                    "  GIS circuit-breaker: Overpass mirrors appear busy — stopping GIS batch cleanly and continuing build.",
                    flush=True,
                )
                break

    return entries, fetched, failed
