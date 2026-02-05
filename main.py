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
# Request model
# =========================
class CompareRequest(BaseModel):
    search: str
    country: str
    pages: Optional[int] = 1
    max_details: Optional[int] = 10  # Max products to fetch full details for


# =========================
# Helpers
# =========================
def is_asin(text: str) -> bool:
    """Check if text is a valid Amazon ASIN"""
    return len(text.strip()) == 10 and text.strip().isalnum()


def post_with_retry(payload: dict, retries: int = 3):
    """Make API request with retry logic for rate limiting"""
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
    """Fetch product title from Amazon using ASIN"""
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


def google_shopping_product_details(product_token: str, country_config: dict):
    """
    Fetch detailed product information including URL using product token.
    This is the KEY function to get product URLs.
    """
    payload = {
        "source": "google_shopping_product",
        "domain": country_config["google_domain"],
        "query": product_token,  # Use the token from search results
        "parse": True,
        "render": "html",
        "geo_location": country_config["geo_location"],
        "locale": country_config["locale"]
    }

    try:
        response = post_with_retry(payload)
        if response.status_code != 200:
            print(f"Error fetching product details: {response.status_code}")
            return None

        data = response.json()
        result = data.get("results", [{}])[0]
        content = result.get("content", {})
        
        return content

    except Exception as e:
        print(f"Exception fetching product details: {str(e)}")
        return None


def google_shopping_search_with_details(product_name: str, country_config: dict, pages: int, max_details: int = 10):
    """
    Search for products and fetch full details (including URLs) for top results
    """
    # Step 1: Get search results with product tokens
    search_payload = {
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
        response = post_with_retry(search_payload)
        if response.status_code != 200:
            return {
                "error": f"API error: {response.status_code}",
                "details": response.text[:200]
            }

        search_results = response.json()

        # Step 2: Fetch full details for each product (up to max_details)
        if "results" in search_results:
            details_fetched = 0
            
            for result in search_results["results"]:
                content = result.get("content", {}).get("results", {})
                
                # Process organic results
                organic = content.get("organic", [])
                for product in organic:
                    # Stop if we've reached the limit
                    if details_fetched >= max_details:
                        break
                    
                    # **FIX: Use 'token' instead of 'product_id'**
                    product_token = product.get("token")
                    if product_token:
                        print(f"Fetching details for product: {product.get('title', 'Unknown')[:50]}...")
                        details = google_shopping_product_details(
                            product_token, 
                            country_config
                        )
                        
                        if details:
                            # Add full details to the product
                            product["product_url"] = details.get("url")
                            product["description"] = details.get("description")
                            product["pricing"] = details.get("pricing", {})
                            product["reviews"] = details.get("reviews", {})
                            product["specifications"] = details.get("specifications", [])
                            product["related_items"] = details.get("related_items", [])
                            product["variants"] = details.get("variants", [])
                            product["images"] = details.get("images", {})
                            
                            details_fetched += 1
                            print(f"✓ Successfully fetched details ({details_fetched}/{max_details})")
                        else:
                            print(f"✗ Failed to fetch details for token: {product_token[:30]}...")
                
                # Also process PLA (ads) if needed
                pla = content.get("pla", [])
                for ad_group in pla:
                    items = ad_group.get("items", [])
                    for product in items:
                        if details_fetched >= max_details:
                            break
                        
                        product_token = product.get("token")
                        if product_token:
                            print(f"Fetching details for ad product: {product.get('title', 'Unknown')[:50]}...")
                            details = google_shopping_product_details(
                                product_token, 
                                country_config
                            )
                            
                            if details:
                                product["product_url"] = details.get("url")
                                product["description"] = details.get("description")
                                product["pricing"] = details.get("pricing", {})
                                product["reviews"] = details.get("reviews", {})
                                product["specifications"] = details.get("specifications", [])
                                
                                details_fetched += 1
                                print(f"✓ Successfully fetched ad details ({details_fetched}/{max_details})")

        return search_results

    except Exception as e:
        return {"error": str(e)}


# =========================
# Main endpoint
# =========================
@app.post("/compare")
def compare_products(request: CompareRequest):
    """
    Main endpoint to compare products across platforms
    Now includes full product URLs from Google Shopping
    """
    search_term = request.search.strip()
    country = request.country.lower().replace(" ", "_")

    if country not in COUNTRY_CONFIG:
        raise HTTPException(
            status_code=400,
            detail=f"Country '{country}' not supported. Available: {list(COUNTRY_CONFIG.keys())}"
        )

    country_config = COUNTRY_CONFIG[country]

    # Handle ASIN input
    if is_asin(search_term):
        title = get_amazon_product_title(search_term, country_config["amazon_domain"])
        product_name = title or search_term
        input_type = "ASIN"
    else:
        product_name = search_term
        input_type = "Product Name"

    # Fetch Google Shopping results with full product details
    google_results = google_shopping_search_with_details(
        product_name=product_name,
        country_config=country_config,
        pages=request.pages,
        max_details=request.max_details
    )

    response = {
        "status": "success" if "error" not in google_results else "failed",
        "input_type": input_type,
        "search_term": product_name,
        "country": country,
        "google_domain": country_config["google_domain"],
        "geo_location": country_config["geo_location"],
        "locale": country_config["locale"],
        "max_details_fetched": request.max_details,
        "google_results": google_results
    }

    # Add product count summary
    if "results" in google_results:
        first = google_results["results"][0]
        content = first.get("content", {}).get("results", {})
        
        organic_products = content.get("organic", [])
        products_with_urls = sum(1 for p in organic_products if p.get("product_url"))
        
        response["products_found"] = {
            "organic": len(organic_products),
            "organic_with_urls": products_with_urls,
            "ads": sum(len(p.get("items", [])) for p in content.get("pla", []))
        }

    return response


# =========================
# Utility endpoints
# =========================
@app.get("/")
def root():
    return {
        "message": "Product Comparison API with Full Product URLs",
        "version": "2.0",
        "examples": {
            "asin": {
                "search": "B0CJT9WCRD",
                "country": "united_states",
                "pages": 1,
                "max_details": 5
            },
            "product": {
                "search": "PlayStation DualSense Controller",
                "country": "united_states",
                "pages": 1,
                "max_details": 10
            }
        },
        "note": "max_details controls how many products to fetch full URLs for (to manage API costs)"
    }


@app.get("/countries")
def list_countries():
    """List all supported countries and their configurations"""
    return {
        "supported_countries": list(COUNTRY_CONFIG.keys()),
        "configurations": COUNTRY_CONFIG
    }


@app.get("/health")
def health():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "Product Comparison API",
        "version": "2.0"
    }


# =========================
# Run locally
# =========================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
