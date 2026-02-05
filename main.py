from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import requests
from typing import Optional
import time

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
        "locale": "en-US"
    },
    "united_kingdom": {
        "google_domain": "co.uk",
        "amazon_domain": "co.uk",
        "geo_location": "London,England,United Kingdom",
        "locale": "en-GB"
    },
    "canada": {
        "google_domain": "ca",
        "amazon_domain": "ca",
        "geo_location": "Toronto,Ontario,Canada",
        "locale": "en-CA"
    },
    "australia": {
        "google_domain": "com.au",
        "amazon_domain": "com.au",
        "geo_location": "Sydney,New South Wales,Australia",
        "locale": "en-AU"
    },
    "germany": {
        "google_domain": "de",
        "amazon_domain": "de",
        "geo_location": "Berlin,Berlin,Germany",
        "locale": "de-DE"
    },
    "france": {
        "google_domain": "fr",
        "amazon_domain": "fr",
        "geo_location": "Paris,Île-de-France,France",
        "locale": "fr-FR"
    },
    "india": {
        "google_domain": "co.in",
        "amazon_domain": "in",
        "geo_location": "Mumbai,Maharashtra,India",
        "locale": "en-IN"
    }
}

# =========================
# Request model (CLEAN)
# =========================
class CompareRequest(BaseModel):
    search: str
    country: str
    pages: Optional[int] = 1


# =========================
# Helpers
# =========================
def is_asin(text: str) -> bool:
    return len(text.strip()) == 10 and text.strip().isalnum()


def post_with_retry(payload: dict, retries: int = 3):
    for attempt in range(retries):
        response = requests.post(
            OXYLABS_ENDPOINT,
            auth=(OXYLABS_USERNAME, OXYLABS_PASSWORD),
            json=payload,
            timeout=60
        )

        if response.status_code != 429:
            return response

        time.sleep(2 ** attempt)  # exponential backoff

    return response


def get_amazon_product_title(asin: str, domain: str) -> Optional[str]:
    payload = {
        "source": "amazon_product",
        "domain": domain,
        "query": asin,
        "parse": True
    }

    try:
        response = post_with_retry(payload)
        if response.status_code != 200:
            return None

        data = response.json()
        result = data.get("results", [{}])[0]
        content = result.get("content", {})

        return content.get("title")

    except Exception:
        return None


def google_shopping_search(product_name: str, country_config: dict, pages: int):
    payload = {
        "source": "google_shopping_search",
        "domain": country_config["google_domain"],
        "query": product_name,
        "parse": True,
        "render": "html",
        "pages": pages,
        "geo_location": country_config["geo_location"],
        "locale": country_config["locale"],
        "context": [{"key": "sort_by", "value": "r"}],
    }

    try:
        response = post_with_retry(payload)
        if response.status_code != 200:
            return {
                "error": f"API error: {response.status_code}",
                "details": response.text[:200]
            }

        return response.json()

    except Exception as e:
        return {"error": str(e)}


# =========================
# Main endpoint
# =========================
@app.post("/compare")
def compare_products(request: CompareRequest):
    search_term = request.search.strip()
    country = request.country.lower().replace(" ", "_")

    if country not in COUNTRY_CONFIG:
        raise HTTPException(
            status_code=400,
            detail=f"Country '{country}' not supported"
        )

    country_config = COUNTRY_CONFIG[country]

    # ASIN flow
    if is_asin(search_term):
        title = get_amazon_product_title(search_term, country_config["amazon_domain"])
        product_name = title or search_term
        input_type = "ASIN"
    else:
        product_name = search_term
        input_type = "Product Name"

    google_results = google_shopping_search(
        product_name=product_name,
        country_config=country_config,
        pages=request.pages
    )

    response = {
        "status": "success" if "error" not in google_results else "failed",
        "input_type": input_type,
        "search_term": product_name,
        "country": country,
        "google_domain": country_config["google_domain"],
        "geo_location": country_config["geo_location"],
        "locale": country_config["locale"],
        "google_results": google_results
    }

    # Optional product count
    if "results" in google_results:
        first = google_results["results"][0]
        content = first.get("content", {}).get("results", {})
        response["products_found"] = {
            "organic": len(content.get("organic", [])),
            "ads": sum(len(p.get("items", [])) for p in content.get("pla", []))
        }

    return response


# =========================
# Utility endpoints
# =========================
@app.get("/")
def root():
    return {
        "message": "Product Comparison API",
        "example": {
            "asin": {"search": "B0CJT9WCRD", "country": "united_states"},
            "product": {"search": "PlayStation DualSense Controller", "country": "united_states"}
        }
    }


@app.get("/countries")
def list_countries():
    return COUNTRY_CONFIG


@app.get("/health")
def health():
    return {"status": "healthy"}


# =========================
# Run locally
# =========================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
