"""Google Places text search."""

import logging
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

PLACES_API_URL = "https://places.googleapis.com/v1/places:searchText"


class PlacesUnavailable(RuntimeError):
    """The search could not run (no key, refused) — unlike finding nothing."""


def search_places(
    query: str,
    api_key: str,
    location_bias: Optional[str] = None,
    max_results: int = 5,
) -> List[Dict[str, Any]]:
    """ابحث عن أماكن عبر Google Places API.

    Raises PlacesUnavailable when the search could not run; [] means it found nothing.
    """
    if not api_key:
        raise PlacesUnavailable("no Google Places API key configured")
    if not query:
        return []

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.rating,places.userRatingCount,places.internationalPhoneNumber,places.regularOpeningHours,places.websiteUri,places.priceLevel,places.googleMapsUri",
    }

    payload: Dict[str, Any] = {
        "textQuery": query,
        "maxResultCount": max_results,
        "languageCode": "ar",
    }

    if location_bias:
        payload["locationBias"] = {
            "circle": {
                "center": {"latitude": 29.9602, "longitude": 30.9188},
                "radius": 10000.0,
            }
        }

    try:
        response = requests.post(
            PLACES_API_URL, headers=headers, json=payload, timeout=5
        )
        response.raise_for_status()
        data = response.json()
        places = data.get("places", [])

        results = []
        for place in places:
            price_map = {1: "رخيص", 2: "متوسط", 3: "غالي", 4: "فاخر"}
            price = price_map.get(place.get("priceLevel", 0), "")

            opening = ""
            hours = place.get("regularOpeningHours", {})
            if hours.get("openNow") is True:
                opening = "مفتوح الآن"
            elif hours.get("openNow") is False:
                opening = "مغلق الآن"

            results.append(
                {
                    "name": place.get("displayName", {}).get("text", ""),
                    "address": place.get("formattedAddress", ""),
                    "rating": place.get("rating", 0),
                    "reviews_count": place.get("userRatingCount", 0),
                    "phone": place.get("internationalPhoneNumber", ""),
                    "website": place.get("websiteUri", ""),
                    "price_level": price,
                    "open_now": opening,
                    "maps_url": place.get("googleMapsUri", ""),
                }
            )

        logger.info(f"[Places] found {len(results)} places for: {query}")
        return results

    except requests.HTTPError as e:
        status = getattr(e.response, "status_code", 0)
        logger.error("[Places] refused (%s) for %r — the search did not run",
                     status, query)
        raise PlacesUnavailable(f"Google Places refused the request ({status})") from e
    except requests.RequestException as e:
        logger.error("[Places] unreachable for %r: %s", query, e)
        raise PlacesUnavailable("could not reach Google Places") from e


def format_places_for_reply(
    places: List[Dict[str, Any]], recommended: bool = True
) -> str:
    if not places:
        return "ما لقيت نتائج قريبة منك."

    lines = []
    for i, place in enumerate(places, 1):
        name = place.get("name", "")
        address = place.get("address", "")
        rating = place.get("rating", 0)
        reviews = place.get("reviews_count", 0)
        phone = place.get("phone", "")
        maps_url = place.get("maps_url", "")
        if maps_url:
            lines.append(f"   🗺️ {maps_url}")
        price = place.get("price_level", "")
        open_now = place.get("open_now", "")

        rating_str = f"⭐ {rating}/5 ({reviews} تقييم)" if rating else ""
        line = f"{i}. {name}"
        if rating_str:
            line += f" — {rating_str}"
        if price:
            line += f" — {price}"
        if open_now:
            line += f" — {open_now}"
        lines.append(line)
        if address:
            lines.append(f"   📍 {address}")
        if phone:
            lines.append(f"   📞 {phone}")
        lines.append("")

    if recommended and places:
        best = max(
            places, key=lambda x: (x.get("rating", 0), x.get("reviews_count", 0))
        )
        if best.get("rating", 0) > 0:
            lines.append(f"⭐ توصيتي: {best['name']} — أعلى تقييم {best['rating']}/5")

    return "\n".join(lines)
