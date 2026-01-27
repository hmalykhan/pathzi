import requests
from django.conf import settings

GEOAPIFY_AUTOCOMPLETE_URL = "https://api.geoapify.com/v1/geocode/autocomplete"

# ✅ keep-alive session (faster after first call)
_SESSION = requests.Session()

def geoapify_autocomplete(text: str, limit: int = 8, country_code: str = ""):
    api_key = getattr(settings, "GEOAPIFY_API_KEY", "")
    if not api_key:
        raise ValueError("GEOAPIFY_API_KEY is not set.")

    params = {
        "text": text,
        "format": "json",
        "limit": limit,
        "apiKey": api_key,
    }

    if country_code:
        params["filter"] = f"countrycode:{country_code.lower()}"

    # ✅ timeout tuned to avoid long waits
    r = _SESSION.get(GEOAPIFY_AUTOCOMPLETE_URL, params=params, timeout=(1.5, 2.5))
    r.raise_for_status()
    payload = r.json()

    results = payload.get("results", [])
    out = []
    for item in results:
        out.append({
            "kind": "address",
            "place_id": item.get("place_id"),
            "label": item.get("formatted") or item.get("address_line2") or "",
            "result_type": item.get("result_type") or "",
            "lat": item.get("lat"),
            "lon": item.get("lon"),
            "city": item.get("city") or item.get("county") or "",
            "state": item.get("state") or "",
            "postcode": item.get("postcode") or "",
            "address_line1": item.get("address_line1") or "",
            "address_line2": item.get("address_line2") or "",
        })
    return out
