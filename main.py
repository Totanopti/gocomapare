from fastapi import FastAPI
from pydantic import BaseModel
import requests

app = FastAPI()

# Oxylabs credentials
OXYLABS_USERNAME = "optisage_sV9jx"
OXYLABS_PASSWORD = "Tmoney_23_25"
OXYLABS_ENDPOINT = "https://realtime.oxylabs.io/v1/queries"

# Mapping country names to Google domains
COUNTRY_DOMAINS = {
    "united_states": "com",
    "united_kingdom": "co.uk",
    "canada": "ca",
    "australia": "com.au",
    "germany": "de",
    "france": "fr",
    "nigeria": "com.ng",
    "india": "co.in",
    # Add more as needed
}

# Request model
class CompareRequest(BaseModel):
    search: str  # Can be ASIN or product name
    country: str  # Country name or code

# Detect if input is an ASIN
def is_asin(text: str) -> bool:
    return len(text.strip()) == 10 and text.isalnum()

# Get product title from Amazon by ASIN
def get_amazon_product_title(asin: str, domain: str):
    payload = {
        "source": "amazon_product",
        "domain": domain,
        "query": asin,
        "parse": True
    }
    response = requests.post(
        OXYLABS_ENDPOINT,
        auth=(OXYLABS_USERNAME, OXYLABS_PASSWORD),
        json=payload
    )
    if response.status_code != 200:
        return None
    data = response.json()
    try:
        return data["results"][0]["content"]["title"]
    except (KeyError, IndexError):
        return None

# Google Shopping Search
def oxylabs_google_search(product_name: str, domain: str):
    payload = {
        "source": "google_shopping_search",
        "domain": domain,
        "query": product_name,
        "parse": True
    }
    response = requests.post(
        OXYLABS_ENDPOINT,
        auth=(OXYLABS_USERNAME, OXYLABS_PASSWORD),
        json=payload
    )
    if response.status_code != 200:
        return {"error": f"Oxylabs error: {response.status_code}", "details": response.text}
    return response.json()

# /compare endpoint
@app.post("/compare")
def compare_products(request: CompareRequest):
    search_term = request.search.strip()
    country = request.country.lower()

    # Get domain for country
    domain = COUNTRY_DOMAINS.get(country, "com")  # default to .com if not found

    if is_asin(search_term):
        # Get product title from Amazon first
        title = get_amazon_product_title(search_term, domain)
        if not title:
            return {"error": f"Could not fetch product title from Amazon {domain}"}
        google_results = oxylabs_google_search(title, domain)
        return {
            "input_type": "ASIN",
            "asin": search_term,
            "country": country,
            "domain": domain,
            "product_title": title,
            "google_results": google_results
        }
    else:
        # Direct Google Shopping search
        google_results = oxylabs_google_search(search_term, domain)
        return {
            "input_type": "Product Name",
            "search_term": search_term,
            "country": country,
            "domain": domain,
            "google_results": google_results
        }
