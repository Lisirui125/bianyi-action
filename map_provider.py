import os
import re
from html import unescape
from math import asin, cos, radians, sin, sqrt
from urllib.parse import parse_qs, quote, unquote, urlparse

try:
    import requests
except ModuleNotFoundError:
    requests = None


AMAP_GEO_URL = "https://restapi.amap.com/v3/geocode/geo"
AMAP_AROUND_URL = "https://restapi.amap.com/v3/place/around"
AMAP_TEXT_URL = "https://restapi.amap.com/v3/place/text"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
DUCKDUCKGO_HTML_URL = "https://html.duckduckgo.com/html/"
BING_SEARCH_URL = "https://www.bing.com/search"
NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
OSRM_ROUTE_URL = "https://router.project-osrm.org/route/v1/driving"


def haversine_km(lat1, lng1, lat2, lng2):
    earth_radius = 6371.0
    lat1, lng1, lat2, lng2 = map(radians, [lat1, lng1, lat2, lng2])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
    return 2 * earth_radius * asin(sqrt(a))


def route_distance_km(origin, place):
    if requests is None or not origin or place.get("lat") is None or place.get("lng") is None:
        return None
    if os.getenv("ROUTE_DISTANCE_PROVIDER", "osrm").strip().lower() in ["0", "false", "off", "none"]:
        return None

    coords = f"{origin['lng']},{origin['lat']};{place['lng']},{place['lat']}"
    try:
        resp = requests.get(
            f"{OSRM_ROUTE_URL}/{coords}",
            params={"overview": "false", "alternatives": "false", "steps": "false"},
            headers={"User-Agent": "bianyi-action-mvp/0.1"},
            timeout=5,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception:
        return None

    routes = payload.get("routes") or []
    if not routes or routes[0].get("distance") is None:
        return None
    return round(float(routes[0]["distance"]) / 1000, 2)


def enrich_route_distances(places, origin, limit=5):
    if not origin:
        return places
    for place in places[:limit]:
        route_km = route_distance_km(origin, place)
        if route_km is not None:
            place["route_distance_km"] = route_km
            place["straight_line_distance_km"] = place.get("distance_km")
            place["distance_km"] = route_km
            place["distance_verified"] = True
            place["distance_type"] = "driving_route_by_osrm"
            place["distance_note"] = "基于免费 OSRM 路线服务计算的驾车路线距离；无实时路况，实际路线以地图 App 为准。"
        elif place.get("distance_km") is not None:
            place.setdefault("straight_line_distance_km", place.get("distance_km"))
            place.setdefault("distance_type", "straight_line")
            place.setdefault("distance_note", "直线距离，实际路线以地图 App 为准。")
    places.sort(key=lambda item: item["distance_km"] if item.get("distance_km") is not None else 9999)
    return places


def amap_marker_url(place):
    return (
        "https://uri.amap.com/marker"
        f"?position={place['lng']},{place['lat']}"
        f"&name={quote(place['name'])}"
        "&src=bianyi-agent&coordinate=gaode&callnative=1"
    )


def amap_nav_url(place):
    return (
        "https://uri.amap.com/navigation"
        f"?to={place['lng']},{place['lat']},{quote(place['name'])}"
        "&mode=car&policy=1&src=bianyi-agent&coordinate=gaode&callnative=1"
    )


def amap_taxi_url(place):
    return (
        "https://uri.amap.com/drive/takeTaxi"
        f"?dlat={place['lat']}&dlon={place['lng']}&dname={quote(place['name'])}"
        "&src=bianyi-agent&callnative=1"
    )


def get_amap_key():
    return os.getenv("AMAP_API_KEY", "").strip()


def geocode_location(address):
    key = get_amap_key()
    if requests is None or not key or not address:
        return None

    resp = requests.get(
        AMAP_GEO_URL,
        params={"key": key, "address": address, "output": "json"},
        timeout=8,
    )
    payload = resp.json()
    if payload.get("status") != "1" or not payload.get("geocodes"):
        return None
    geocode = payload["geocodes"][0]
    lng, lat = [float(item) for item in geocode["location"].split(",")]
    return {
        "lat": lat,
        "lng": lng,
        "city": geocode.get("city") if isinstance(geocode.get("city"), str) else "",
        "district": geocode.get("district") or "",
        "adcode": geocode.get("adcode") or "",
        "formatted_address": geocode.get("formatted_address") or address,
    }


def geocode_location_free(address):
    if requests is None or not address:
        return None

    try:
        resp = requests.get(
            NOMINATIM_SEARCH_URL,
            params={
                "q": address,
                "format": "jsonv2",
                "limit": 1,
                "addressdetails": 1,
                "accept-language": "zh-CN,zh,en",
            },
            headers={"User-Agent": "bianyi-action-mvp/0.1 contact:local-demo"},
            timeout=6,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception:
        return None

    if not payload:
        return None

    item = payload[0]
    address_info = item.get("address") or {}
    return {
        "lat": float(item["lat"]),
        "lng": float(item["lon"]),
        "city": address_info.get("city") or address_info.get("town") or address_info.get("county") or "",
        "district": address_info.get("suburb") or address_info.get("city_district") or address_info.get("county") or "",
        "adcode": "",
        "formatted_address": item.get("display_name") or address,
        "source": "nominatim",
    }


def normalize_location_queries(location_text):
    text = re.sub(r"\s+", "", location_text or "")
    if not text:
        return []
    variants = [text]
    cleaned = re.sub(r"(附近|周边|旁边|边上|这边|一带|左右)$", "", text)
    if cleaned and cleaned != text:
        variants.append(cleaned)
    city_district_match = re.search(r"([\u4e00-\u9fa5]+市[\u4e00-\u9fa5]+区)", cleaned or text)
    if city_district_match:
        variants.append(city_district_match.group(1))
    county_match = re.search(r"([\u4e00-\u9fa5]+县)", cleaned or text)
    if county_match:
        variants.append(county_match.group(1))

    deduped = []
    for item in variants:
        if item and item not in deduped:
            deduped.append(item)
    return deduped


def extract_china_coordinate(text):
    if not text:
        return None
    text = unescape(text)
    patterns = [
        r"(?:经度|lng|longitude|lon)[：:\s]*([0-9]{2,3}\.\d+)[,，\s;；]+(?:纬度|lat|latitude)?[：:\s]*([0-9]{1,2}\.\d+)",
        r"(?:纬度|lat|latitude)[：:\s]*([0-9]{1,2}\.\d+)[,，\s;；]+(?:经度|lng|longitude|lon)?[：:\s]*([0-9]{2,3}\.\d+)",
        r"([0-9]{2,3}\.\d{4,})[,，\s]+([0-9]{1,2}\.\d{4,})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if not match:
            continue
        first = float(match.group(1))
        second = float(match.group(2))
        if 70 <= first <= 140 and 15 <= second <= 55:
            return {"lng": first, "lat": second}
        if 70 <= second <= 140 and 15 <= first <= 55:
            return {"lng": second, "lat": first}
    return None


def web_geocode_coordinate(query):
    if requests is None or not web_search_enabled() or not query:
        return None
    try:
        resp = requests.post(
            DUCKDUCKGO_HTML_URL,
            data={"q": f"{query} 经纬度 坐标"},
            headers={"User-Agent": "Mozilla/5.0 bianyi-action-mvp/0.1"},
            timeout=6,
        )
        resp.raise_for_status()
    except Exception:
        return None

    text = strip_html(resp.text)
    coord = extract_china_coordinate(text)
    if not coord:
        return None
    return {
        "lat": coord["lat"],
        "lng": coord["lng"],
        "city": "",
        "district": "",
        "adcode": "",
        "formatted_address": query,
        "source": "web_coordinate_search",
    }


def resolve_origin(location_text, lat=None, lng=None, prefer_amap=False):
    if lat is not None and lng is not None:
        return {
            "lat": float(lat),
            "lng": float(lng),
            "formatted_address": location_text,
            "source": "client_location",
        }

    queries = normalize_location_queries(location_text)

    if prefer_amap:
        for query in queries:
            origin = geocode_location(query)
            if origin:
                origin["source"] = "amap_geocode"
                origin["input_location"] = location_text
                return origin

    for query in queries:
        origin = geocode_location_free(query)
        if origin:
            origin["input_location"] = location_text
            return origin
    for query in queries:
        origin = web_geocode_coordinate(query)
        if origin:
            origin["input_location"] = location_text
            return origin
    return None


def resolve_place_coordinate(location_text, title, address):
    queries = []
    if address:
        queries.append(address)
        queries.append(f"{location_text} {address}")
    queries.append(f"{location_text} {title}")
    queries.append(title)

    seen = set()
    for query in queries:
        query = re.sub(r"\s+", " ", query or "").strip()
        if not query or query in seen:
            continue
        seen.add(query)
        origin = geocode_location_free(query)
        if origin:
            return origin
        origin = web_geocode_coordinate(query)
        if origin:
            return origin
    return None


def keywords_for_strategy(classification, departments):
    if classification["route_strategy"] == "nearest_emergency":
        return ["急诊", "医院"]
    if classification["route_strategy"] == "nearest_primary":
        return ["社区卫生服务中心", "社康中心", "医院"]
    if classification["route_strategy"] == "national_specialty":
        primary = departments[0] if departments else "专科医院"
        return [primary, "医院"]
    primary = departments[0] if departments else "医院"
    return [primary, "医院"]


def web_search_enabled():
    return os.getenv("WEB_SEARCH_FALLBACK", "true").strip().lower() not in ["0", "false", "no", "off"]


def infer_emergency(name, poi_type):
    text = f"{name} {poi_type}"
    if "社区卫生服务中心" in text or "社康" in text or "诊所" in text:
        return False
    return "医院" in text or "急救" in text or "急诊" in text


def normalize_poi(poi, origin=None):
    lng, lat = [float(item) for item in poi["location"].split(",")]
    distance_km = None
    if origin:
        distance_km = round(haversine_km(origin["lat"], origin["lng"], lat, lng), 2)
    name = poi.get("name", "")
    poi_type = poi.get("type", "")
    place = {
        "id": poi.get("id") or "",
        "name": name,
        "city": poi.get("cityname") or "",
        "district": poi.get("adname") or "",
        "level": "地图POI",
        "type": "map_poi",
        "address": poi.get("address") if isinstance(poi.get("address"), str) else "",
        "lat": lat,
        "lng": lng,
        "departments": [],
        "specialties": [poi_type] if poi_type else [],
        "has_emergency": infer_emergency(name, poi_type),
        "insurance_designated": None,
        "recommended_entrance": "请以医院现场导诊、地图信息或医院公告为准",
        "phone_note": poi.get("tel") if isinstance(poi.get("tel"), str) and poi.get("tel") else "请以地图或医院官网实时信息为准",
        "distance_km": distance_km,
        "distance_verified": distance_km is not None,
        "distance_type": "straight_line",
        "distance_note": "直线距离，实际路线以地图 App 为准。",
        "source": "amap",
    }
    return place


def normalize_osm_element(element, origin=None):
    tags = element.get("tags", {})
    lat = element.get("lat")
    lng = element.get("lon")
    if lat is None or lng is None:
        center = element.get("center") or {}
        lat = center.get("lat")
        lng = center.get("lon")
    if lat is None or lng is None:
        return None

    lat = float(lat)
    lng = float(lng)
    name = tags.get("name") or tags.get("name:zh") or tags.get("operator") or "未命名医疗机构"
    amenity = tags.get("amenity") or ""
    healthcare = tags.get("healthcare") or ""
    address_parts = [
        tags.get("addr:province"),
        tags.get("addr:city"),
        tags.get("addr:district"),
        tags.get("addr:street"),
        tags.get("addr:housenumber"),
    ]
    address = tags.get("addr:full") or "".join(part for part in address_parts if part)
    distance_km = round(haversine_km(origin["lat"], origin["lng"], lat, lng), 2) if origin else None
    osm_type = element.get("type", "node")
    osm_id = element.get("id")
    place = {
        "id": f"osm:{osm_type}:{osm_id}",
        "name": name,
        "city": tags.get("addr:city") or "",
        "district": tags.get("addr:district") or "",
        "level": "OSM医疗POI",
        "type": "osm_poi",
        "address": address,
        "lat": lat,
        "lng": lng,
        "departments": [],
        "specialties": [item for item in [amenity, healthcare] if item],
        "has_emergency": amenity == "hospital" or healthcare == "hospital" or tags.get("emergency") == "yes",
        "insurance_designated": None,
        "recommended_entrance": "请以医院现场导诊、地图信息或医院公告为准",
        "phone_note": tags.get("phone") or tags.get("contact:phone") or "请以地图或医院官网实时信息为准",
        "distance_km": distance_km,
        "distance_verified": distance_km is not None,
        "distance_type": "straight_line",
        "distance_note": "直线距离，实际路线以地图 App 为准。",
        "source": "openstreetmap",
        "source_url": f"https://www.openstreetmap.org/{osm_type}/{osm_id}" if osm_id else "https://www.openstreetmap.org/",
    }
    return place


def geocode_candidate_place(location_text, title, address):
    return resolve_place_coordinate(location_text, title, address)


def strip_html(text):
    text = re.sub(r"<[^>]+>", "", text or "")
    return unescape(re.sub(r"\s+", " ", text)).strip()


def unwrap_duckduckgo_url(url):
    if not url:
        return ""
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if "uddg" in qs and qs["uddg"]:
        return unquote(qs["uddg"][0])
    return url


def build_web_hospital_queries(location_text, classification, departments):
    locations = normalize_location_queries(location_text) or [location_text]
    keywords = keywords_for_strategy(classification, departments)
    queries = []
    for location in locations:
        if classification["route_strategy"] == "nearest_emergency":
            queries.extend([
                f"{location} 附近 急诊 医院",
                f"{location} 急救 医院",
                f"{location} 医院",
            ])
        elif classification["route_strategy"] == "nearest_primary":
            queries.extend([
                f"{location} 附近 社区卫生服务中心",
                f"{location} 社区卫生服务中心",
                f"{location} 附近 医院",
                f"{location} 医院",
            ])
        else:
            queries.extend([
                f"{location} 附近 {' '.join(keywords)}",
                f"{location} 附近 医院",
                f"{location} 医院",
            ])

    deduped = []
    for query in queries:
        if query not in deduped:
            deduped.append(query)
    return deduped


def parse_web_hospital_results(html, location_text, departments, origin=None, limit=5, geocode_limit=2):
    result_pattern = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>.*?'
        r'(?:<a[^>]+class="result__snippet"[^>]*>|<div[^>]+class="result__snippet"[^>]*>)(?P<snippet>.*?)</(?:a|div)>',
        re.S,
    )
    places = []
    seen = set()
    geocode_attempts = 0
    for match in result_pattern.finditer(html):
        title = strip_html(match.group("title"))
        snippet = strip_html(match.group("snippet"))
        source_url = unwrap_duckduckgo_url(unescape(match.group("href")))
        combined = f"{title} {snippet}"
        if not any(word in combined for word in ["医院", "卫生服务中心", "门诊", "急诊", "诊所", "社康"]):
            continue
        if any(word in title for word in ["电话", "地址", "名单", "名录", "列表", "本地宝", "查询", "大全"]) and not any(
            title.endswith(suffix) for suffix in ["医院", "卫生服务中心", "诊所", "门诊部"]
        ):
            continue
        if title in seen:
            continue
        seen.add(title)
        address_match = re.search(r"(地址[:：]?\s*[^。；;，,]{6,80})", combined)
        address = address_match.group(1).replace("地址", "").replace(":", "").replace("：", "").strip() if address_match else ""
        geocoded = None
        if origin and geocode_attempts < geocode_limit:
            geocode_attempts += 1
            geocoded = geocode_candidate_place(location_text, title, address)
        lat = geocoded["lat"] if geocoded else None
        lng = geocoded["lng"] if geocoded else None
        distance_km = round(haversine_km(origin["lat"], origin["lng"], lat, lng), 2) if origin and geocoded else None
        places.append(
            {
                "id": f"web:{len(places) + 1}",
                "name": title,
                "city": geocoded.get("city", "") if geocoded else "",
                "district": geocoded.get("district", "") if geocoded else "",
                "level": "网页搜索结果",
                "type": "web_search_result",
                "address": address or (geocoded.get("formatted_address", "") if geocoded else ""),
                "lat": lat,
                "lng": lng,
                "departments": [],
                "specialties": departments,
                "has_emergency": "急诊" in combined or "急救" in combined,
                "insurance_designated": None,
                "recommended_entrance": "网页搜索结果未验证入口，请以医院现场导诊、地图信息或医院公告为准",
                "phone_note": "网页搜索结果未验证电话，请以医院官网或地图实时信息为准",
                "distance_km": distance_km,
                "distance_verified": distance_km is not None,
                "distance_type": "straight_line_by_free_geocode" if distance_km is not None else "unknown",
                "distance_note": "基于免费地理编码计算的直线距离，非行车距离；需用地图 App 二次确认。" if distance_km is not None else "未获得可计算距离的经纬度。",
                "source": "web_search",
                "source_url": source_url,
                "geocode_source": geocoded.get("source") if geocoded else "",
                "snippet": snippet[:240],
                "confidence": "medium" if distance_km is None else "medium_with_geocoded_distance",
            }
        )
        if len(places) >= limit:
            break
    return places


def search_html(query):
    try:
        resp = requests.post(
            DUCKDUCKGO_HTML_URL,
            data={"q": query},
            headers={"User-Agent": "Mozilla/5.0 bianyi-action-mvp/0.1"},
            timeout=8,
        )
        resp.raise_for_status()
        return resp.text, None
    except Exception as exc:
        last_error = exc

    try:
        resp = requests.get(
            BING_SEARCH_URL,
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0 bianyi-action-mvp/0.1"},
            timeout=8,
        )
        resp.raise_for_status()
        return resp.text, None
    except Exception as exc:
        return "", exc or last_error


def search_web_hospitals(location_text, classification, departments, radius=5000, origin=None):
    if requests is None:
        return {
            "places": [],
            "status": "missing_dependency",
            "message": "当前 Python 环境未安装 requests，无法执行网页搜索兜底。",
        }
    if not web_search_enabled():
        return {
            "places": [],
            "status": "web_disabled",
            "message": "WEB_SEARCH_FALLBACK 已关闭，未执行网页搜索兜底。",
        }

    places = []
    used_query = ""
    last_error = None
    for query in build_web_hospital_queries(location_text, classification, departments):
        html, error = search_html(query)
        if error:
            last_error = error
            continue
        places = parse_web_hospital_results(html, location_text, departments, origin=origin)
        used_query = query
        if places:
            break

    if last_error and not places:
        return {
            "places": [],
            "status": "web_failed",
            "origin": origin,
            "message": f"网页搜索兜底失败：{last_error}",
        }

    if origin and any(place.get("distance_km") is not None for place in places):
        places = enrich_route_distances(places, origin)

    return {
        "places": places,
        "status": "ok" if places else "no_results",
        "origin": origin,
        "message": "地图数据源无结果，已使用网页搜索兜底；能解析坐标的候选已按免费地理编码直线距离排序，仍需地图 App 核验。" if places else "网页搜索也未找到可结构化的医疗机构结果。",
        "query": used_query,
    }


def search_osm_nearby_hospitals(location_text, classification, departments, lat=None, lng=None, radius=5000):
    if requests is None:
        return {
            "places": [],
            "status": "missing_dependency",
            "message": "当前 Python 环境未安装 requests，无法调用 OSM/Overpass。",
        }
    origin = resolve_origin(location_text, lat=lat, lng=lng, prefer_amap=False)
    if not origin:
        return {
            "places": [],
            "status": "missing_location",
            "message": "免费地理编码未能把用户位置解析为经纬度。请让用户输入更精确地址，或由小程序/浏览器传入定位 lat/lng。",
        }

    radius = max(500, min(int(radius), 20000))
    query = f"""
    [out:json][timeout:12];
    (
      node(around:{radius},{origin['lat']},{origin['lng']})["amenity"~"^(hospital|clinic|doctors)$"];
      node(around:{radius},{origin['lat']},{origin['lng']})["healthcare"~"^(hospital|clinic|doctor)$"];
    );
    out tags 30;
    """
    try:
        resp = requests.get(
            OVERPASS_URL,
            params={"data": query},
            headers={"User-Agent": "bianyi-action-mvp/0.1"},
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        return {
            "places": [],
            "status": "osm_failed",
            "origin": origin,
            "message": f"OSM/Overpass 查询失败：{exc}",
        }

    places = []
    seen = set()
    for element in payload.get("elements", []):
        place = normalize_osm_element(element, origin=origin)
        if not place or place["id"] in seen:
            continue
        seen.add(place["id"])
        places.append(place)

    if classification["route_strategy"] == "nearest_primary":
        places.sort(key=lambda item: (0 if any(k in item["name"] for k in ["社区", "卫生服务", "诊所", "clinic"]) else 1, item["distance_km"] or 999))
    elif classification["route_strategy"] == "nearest_emergency":
        places.sort(key=lambda item: (0 if item["has_emergency"] else 1, item["distance_km"] or 999))
    else:
        places.sort(key=lambda item: item["distance_km"] or 999)
    places = enrich_route_distances(places, origin)

    return {
        "places": places[:5],
        "status": "ok" if places else "no_results",
        "origin": origin,
        "message": "已通过 OpenStreetMap Overpass 免费公共数据源返回候选机构，并按直线距离排序。" if places else "OSM 在该半径内未找到医疗机构；中国区数据可能不完整。",
    }


def search_nearby_hospitals(location_text, classification, departments, lat=None, lng=None, radius=5000):
    provider = os.getenv("MAP_PROVIDER", "auto").strip().lower()

    if provider in ["web", "search", "web_search"]:
        origin = resolve_origin(location_text, lat=lat, lng=lng, prefer_amap=False)
        return search_web_hospitals(location_text, classification, departments, radius=radius, origin=origin)

    if provider in ["osm", "openstreetmap"]:
        result = search_osm_nearby_hospitals(location_text, classification, departments, lat=lat, lng=lng, radius=radius)
        if result.get("places"):
            return result
        if web_search_enabled():
            web_result = search_web_hospitals(location_text, classification, departments, radius=radius, origin=result.get("origin"))
            if web_result.get("places"):
                return web_result
        return result

    if requests is None:
        return {
            "places": [],
            "status": "missing_dependency",
            "message": "当前 Python 环境未安装 requests，无法调用地图 API。请运行 pip install requests。",
        }

    key = get_amap_key()
    if not key:
        if provider == "auto":
            result = search_osm_nearby_hospitals(location_text, classification, departments, lat=lat, lng=lng, radius=radius)
            if result.get("places"):
                return result
            if web_search_enabled():
                web_result = search_web_hospitals(location_text, classification, departments, radius=radius, origin=result.get("origin"))
                if web_result.get("places"):
                    return web_result
            return result
        return {
            "places": [],
            "status": "missing_key",
            "message": "未配置 AMAP_API_KEY，无法调用高德地图 API 搜索最近医院。",
        }

    origin = resolve_origin(location_text, lat=lat, lng=lng, prefer_amap=True)

    if not origin:
        return {
            "places": [],
            "status": "geocode_failed",
            "message": "无法把用户位置解析为经纬度，请传入小程序定位 lat/lng。",
        }

    keywords = keywords_for_strategy(classification, departments)
    pois = []
    for keyword in keywords:
        params = {
            "key": key,
            "location": f"{origin['lng']},{origin['lat']}",
            "keywords": keyword,
            "radius": radius,
            "offset": 20,
            "page": 1,
            "extensions": "base",
            "output": "json",
        }
        resp = requests.get(AMAP_AROUND_URL, params=params, timeout=8)
        payload = resp.json()
        if payload.get("status") == "1":
            pois.extend(payload.get("pois", []))

    seen = set()
    places = []
    for poi in pois:
        poi_id = poi.get("id") or poi.get("name")
        if not poi_id or poi_id in seen or not poi.get("location"):
            continue
        seen.add(poi_id)
        places.append(normalize_poi(poi, origin=origin))

    if classification["route_strategy"] == "nearest_primary":
        places.sort(key=lambda item: (0 if ("社区" in item["name"] or "社康" in item["name"]) else 1, item["distance_km"] or 999))
    elif classification["route_strategy"] == "nearest_emergency":
        places.sort(key=lambda item: (0 if item["has_emergency"] else 1, item["distance_km"] or 999))
    else:
        places.sort(key=lambda item: item["distance_km"] or 999)
    places = enrich_route_distances(places, origin)

    if not places and web_search_enabled():
        web_result = search_web_hospitals(location_text, classification, departments, radius=radius, origin=origin)
        if web_result.get("places"):
            return web_result

    return {
        "places": places[:5],
        "status": "ok" if places else "no_results",
        "origin": origin,
        "message": "已通过高德地图周边搜索返回候选机构。" if places else "高德地图周边搜索未返回候选机构。",
    }
