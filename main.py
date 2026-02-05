from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import requests
from typing import Optional
import time
import base64
import json

app = FastAPI()

# =========================
# Oxylabs credentials
# =========================
OXYLABS_USERNAME = "optisage_sV9jx"
OXYLABS_PASSWORD = "Optisage_25_10"
OXYLABS_ENDPOINT = "https://realtime.oxylabs.io/v1/queries"

# =========================
# Country configuration
# =========================
COUNTRY_CONFIG = {
    "united_states": {
        "google_domain": "com",
        "amazon_domain": "com",
        "geo_location": "New York,New York,United States",
        "locale": "en-US",
        "currency": "USD"
    },
    "philippines": {
        "google_domain": "com.ph",
        "amazon_domain": "ph",
        "geo_location": "Manila,Metro Manila,Philippines",
        "locale": "en-PH",
        "currency": "PHP"
    }
}

# =========================
# Request models
# =========================
class CompareRequest(BaseModel):
    search: str
    country: str

class SearchRequest(BaseModel):
    query: str
    country: str
    limit: Optional[int] = 5

# =========================
# Helpers
# =========================
def post_with_retry(payload: dict, retries: int = 3):
    for attempt in range(retries):
        try:
            r = requests.post(
                OXYLABS_ENDPOINT,
                auth=(OXYLABS_USERNAME, OXYLABS_PASSWORD),
                json=payload,
                timeout=60
            )
            if r.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            return r
        except:
            time.sleep(2 ** attempt)
    return None

# =========================
# Google Shopping Calls
# =========================
def google_shopping_search_general(query: str, cfg: dict):
    payload = {
        "source": "google_shopping_search",
        "domain": cfg["google_domain"],
        "query": query,
        "parse": True,
        "render": "html",
        "geo_location": cfg["geo_location"],
        "locale": cfg["locale"]
    }
    r = post_with_retry(payload)
    return r.json() if r and r.status_code == 200 else {"error": "search_failed"}

def google_shopping_product_search(title: str, cfg: dict):
    payload = {
        "source": "google_shopping_product",
        "domain": cfg["google_domain"],
        "query": title,
        "parse": True,
        "render": "html",
        "geo_location": cfg["geo_location"],
        "locale": cfg["locale"]
    }
    r = post_with_retry(payload)
    return r.json() if r and r.status_code == 200 else {"error": "product_failed"}

# =========================
# STRICT RESOLVER (IMPORTANT)
# =========================
def resolve_products(query: str, cfg: dict, limit: int):
    search = google_shopping_search_general(query, cfg)
    if "error" in search:
        return []

    resolved = []

    for block in search.get("results", []):
        for organic in block.get("content", {}).get("organic", []):
            title = organic.get("title")
            if not title:
                continue

            product_raw = google_shopping_product_search(title, cfg)
            content = product_raw.get("content", {})
            pricing = content.get("pricing", {}).get("online", [])

            offers = []
            for p in pricing:
                if p.get("seller_link"):
                    offers.append({
                        "seller": p.get("seller"),
                        "price": p.get("price"),
                        "currency": p.get("currency"),
                        "direct_url": p.get("seller_link")
                    })

            if offers:
                resolved.append({
                    "product_title": content.get("title", title),
                    "offers": offers,
                    "best_offer": min(
                        offers, key=lambda x: x["price"] if x["price"] else float("inf")
                    )
                })

            if len(resolved) >= limit:
                return resolved

    return resolved

# =========================
# ENDPOINTS
# =========================
@app.post("/search")
async def search_products(req: SearchRequest):
    country = req.country.lower().replace(" ", "_")
    if country not in COUNTRY_CONFIG:
        raise HTTPException(400, "Unsupported country")

    data = resolve_products(req.query, COUNTRY_CONFIG[country], req.limit)

    return {
        "status": "success" if data else "no_results",
        "data": data
    }

@app.post("/compare")
async def compare_products(req: CompareRequest):
    country = req.country.lower().replace(" ", "_")
    if country not in COUNTRY_CONFIG:
        raise HTTPException(400, "Unsupported country")

    results = resolve_products(req.search, COUNTRY_CONFIG[country], limit=1)

    if not results:
        return {"status": "failed", "reason": "No merchant URLs found"}

    return {
        "status": "success",
        "product": results[0]
    }

@app.get("/product/{encoded}")
async def product_lookup(encoded: str, country: str = "united_states"):
    country = country.lower().replace(" ", "_")
    if country not in COUNTRY_CONFIG:
        raise HTTPException(400, "Unsupported country")

    try:
        decoded = json.loads(base64.b64decode(encoded + "==").decode())
        query = decoded.get("query")
    except:
        raise HTTPException(400, "Invalid product ID")

    results = resolve_products(query, COUNTRY_CONFIG[country], limit=1)

    if not results:
        raise HTTPException(404, "No merchant URL found")

    return {
        "status": "success",
        "product": results[0]
    }

@app.get("/")
async def root():
    return {
        "message": "STRICT Product Comparison API",
        "rule": "Merchant URLs only (seller_link)"
    }

# =========================
# RUN
# =========================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
