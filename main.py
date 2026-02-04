from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import requests
from typing import Optional, List, Dict, Any
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
# Request models
# =========================
class CompareRequest(BaseModel):
    search: str
    country: str
    pages: Optional[int] = 1
    get_real_urls: Optional[bool] = True  # NEW: Option to get real product URLs
    max_products: Optional[int] = 10

class ProductDetailsRequest(BaseModel):
    tokens: List[str]
    country: str


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


def get_product_details_from_token(token: str, country_config: dict) -> Dict[str, Any]:
    """Get detailed product information including real URLs using product token"""
    payload = {
        "source": "google_shopping_product",
        "domain": country_config["google_domain"],
        "query": token,
        "parse": True,
        "render": "html",
        "locale": country_config["locale"],
        "geo_location": country_config["geo_location"]
    }

    try:
        response = post_with_retry(payload)
        if response.status_code != 200:
            return {
                "status": "error",
                "message": f"API error: {response.status_code}"
            }

        data = response.json()
        
        # Extract real product URL from detailed response
        if "results" in data and len(data["results"]) > 0:
            result = data["results"][0]
            content = result.get("content", {})
            
            # Look for real product URL in different possible locations
            real_product_url = None
            
            # Check for direct URL in offers or shopping results
            if "shopping_results" in content:
                for shopping_result in content.get("shopping_results", []):
                    if "link" in shopping_result:
                        real_product_url = shopping_result["link"]
                        break
            
            # Check offers
            if not real_product_url and "offers" in content:
                for offer in content.get("offers", []):
                    if "link" in offer:
                        real_product_url = offer["link"]
                        break
            
            # Check product URL directly
            if not real_product_url and "url" in content:
                real_product_url = content["url"]
            
            return {
                "status": "success",
                "real_product_url": real_product_url,
                "full_details": content
            }
        else:
            return {
                "status": "error",
                "message": "No product details found"
            }

    except Exception as e:
        return {"status": "error", "message": str(e)}


def extract_organic_products(google_results: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract organic products from Google Shopping search results"""
    products = []
    
    if "error" in google_results:
        return products
    
    if "results" not in google_results:
        return products
    
    for result in google_results.get("results", []):
        content = result.get("content", {})
        
        # Process organic results
        for organic in content.get("organic", []):
            product = {
                "position": organic.get("pos"),
                "title": organic.get("title"),
                "price": organic.get("price_str"),
                "currency": organic.get("currency"),
                "merchant": organic.get("merchant", {}).get("name") if isinstance(organic.get("merchant"), dict) else organic.get("merchant"),
                "rating": organic.get("rating"),
                "reviews_count": organic.get("reviews_count"),
                "delivery_info": organic.get("delivery"),
                "type": "organic",
                "google_shopping_url": organic.get("url"),  # Google's internal page
                "product_token": organic.get("token"),  # IMPORTANT: Token for getting real URL
                "product_id": organic.get("product_id"),
                "thumbnail": organic.get("thumbnail")
            }
            products.append(product)
    
    return products


# =========================
# Main endpoint - UPDATED TO GET REAL URLs
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

    # Extract organic products
    products = extract_organic_products(google_results)
    
    # If requested, get real product URLs using tokens
    if request.get_real_urls and products:
        for i, product in enumerate(products[:request.max_products]):
            token = product.get("product_token")
            if token:
                # Get detailed product info including real URL
                details = get_product_details_from_token(token, country_config)
                if details.get("status") == "success":
                    products[i]["real_product_url"] = details.get("real_product_url")
                    products[i]["details_status"] = "success"
                else:
                    products[i]["real_product_url"] = None
                    products[i]["details_status"] = "failed"
                    products[i]["details_error"] = details.get("message")
            else:
                products[i]["real_product_url"] = None
                products[i]["details_status"] = "no_token"

    # Build response
    response = {
        "status": "success" if "error" not in google_results else "failed",
        "input_type": input_type,
        "search_term": product_name,
        "country": country,
        "google_domain": country_config["google_domain"],
        "geo_location": country_config["geo_location"],
        "locale": country_config["locale"],
        "summary": {
            "total_products_found": len(products),
            "organic_count": len([p for p in products if p["type"] == "organic"]),
            "products_with_real_urls": len([p for p in products if p.get("real_product_url")])
        }
    }
    
    # Add products to response
    if products:
        # Limit to max_products
        limited_products = products[:request.max_products]
        
        # Format the response to include real URLs
        formatted_products = []
        for product in limited_products:
            formatted_product = {
                "position": product.get("position"),
                "title": product.get("title"),
                "price": product.get("price"),
                "merchant": product.get("merchant"),
                "rating": product.get("rating"),
                "reviews_count": product.get("reviews_count"),
                "google_shopping_url": product.get("google_shopping_url"),  # Google's page
                "real_product_url": product.get("real_product_url"),  # Actual product URL (if available)
                "product_token": product.get("product_token"),
                "thumbnail": product.get("thumbnail")
            }
            formatted_products.append(formatted_product)
        
        response["products"] = formatted_products
    
    # Add error if present
    if "error" in google_results:
        response["search_error"] = google_results["error"]
    
    return response


# =========================
# New endpoint to get real URLs for tokens
# =========================
@app.post("/get-real-urls")
def get_real_urls(request: ProductDetailsRequest):
    """Get real product URLs for a list of tokens"""
    country = request.country.lower().replace(" ", "_")
    
    if country not in COUNTRY_CONFIG:
        raise HTTPException(
            status_code=400,
            detail=f"Country '{country}' not supported"
        )
    
    country_config = COUNTRY_CONFIG[country]
    results = []
    
    for token in request.tokens[:20]:  # Limit to 20 tokens
        details = get_product_details_from_token(token, country_config)
        
        results.append({
            "token": token,
            "real_product_url": details.get("real_product_url") if details.get("status") == "success" else None,
            "status": details.get("status"),
            "message": details.get("message")
        })
    
    return {
        "status": "success",
        "count": len(results),
        "results": results
    }


# =========================
# Utility endpoints
# =========================
@app.get("/")
def root():
    return {
        "message": "Product Comparison API with Real URLs",
        "usage": "Use /compare with get_real_urls=true to get actual product URLs",
        "example": {
            "with_real_urls": {
                "search": "B0CJT9WCRD",
                "country": "united_states",
                "get_real_urls": true,
                "max_products": 5
            }
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
