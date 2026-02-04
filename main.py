from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import requests
from typing import Optional, List, Dict, Any
import time
import base64

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
    get_detailed_product_info: Optional[bool] = False
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


def get_google_shopping_product_details(token: str, country_config: dict) -> Dict[str, Any]:
    """Get detailed product information using product token"""
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
                "error": f"API error: {response.status_code}",
                "details": response.text[:200]
            }

        data = response.json()
        
        # Extract product details from response
        if "results" in data and len(data["results"]) > 0:
            result = data["results"][0]
            content = result.get("content", {})
            
            return {
                "status": "success",
                "product_details": content
            }
        else:
            return {
                "status": "error",
                "message": "No product details found in response"
            }

    except Exception as e:
        return {"status": "error", "message": str(e)}


def extract_product_url_from_details(product_details: Dict[str, Any]) -> Optional[str]:
    """Extract direct product URL from detailed product information"""
    try:
        # Try different possible locations for the direct URL
        if "url" in product_details:
            return product_details["url"]
        
        if "shopping_results" in product_details:
            for result in product_details["shopping_results"]:
                if "link" in result:
                    return result["link"]
        
        if "offers" in product_details:
            for offer in product_details.get("offers", []):
                if "link" in offer:
                    return offer["link"]
        
        # Check for merchant information
        if "merchant" in product_details:
            merchant_info = product_details["merchant"]
            if isinstance(merchant_info, dict) and "url" in merchant_info:
                return merchant_info["url"]
        
        return None
    except Exception:
        return None


def decode_product_token(token: str) -> Dict[str, Any]:
    """Decode the base64 product token to see what's inside"""
    try:
        # Add padding if needed
        padding = 4 - len(token) % 4
        if padding != 4:
            token += "=" * padding
        
        decoded = base64.b64decode(token).decode('utf-8')
        return {"decoded": decoded}
    except Exception as e:
        return {"error": f"Failed to decode token: {str(e)}"}


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
        original_asin = search_term
    else:
        product_name = search_term
        input_type = "Product Name"
        original_asin = None

    google_results = google_shopping_search(
        product_name=product_name,
        country_config=country_config,
        pages=request.pages
    )

    # Process search results
    products = []
    detailed_products = []
    
    if "error" not in google_results and "results" in google_results:
        for result in google_results.get("results", []):
            content = result.get("content", {})
            
            # Process organic results
            for organic in content.get("organic", []):
                product_data = {
                    "position": organic.get("pos"),
                    "title": organic.get("title"),
                    "price": organic.get("price_str"),
                    "currency": organic.get("currency"),
                    "merchant": organic.get("merchant", {}).get("name"),
                    "rating": organic.get("rating"),
                    "reviews_count": organic.get("reviews_count"),
                    "delivery_info": organic.get("delivery"),
                    "type": "organic",
                    "google_shopping_url": organic.get("url"),  # Google Shopping page URL
                    "product_token": organic.get("token"),  # Token for detailed lookup
                    "product_id": organic.get("product_id"),
                    "thumbnail": organic.get("thumbnail")
                }
                products.append(product_data)
                
                # Get detailed product info if requested
                if request.get_detailed_product_info and organic.get("token"):
                    if len(detailed_products) < request.max_products:
                        detailed_info = get_google_shopping_product_details(
                            organic.get("token"),
                            country_config
                        )
                        
                        if detailed_info.get("status") == "success":
                            product_details = detailed_info.get("product_details", {})
                            direct_url = extract_product_url_from_details(product_details)
                            
                            detailed_products.append({
                                **product_data,
                                "detailed_info": {
                                    "direct_product_url": direct_url,
                                    "description": product_details.get("description"),
                                    "specifications": product_details.get("specifications"),
                                    "sellers": product_details.get("sellers"),
                                    "offers": product_details.get("offers")
                                }
                            })
            
            # Process PLA ads
            for pla in content.get("pla", []):
                for item in pla.get("items", []):
                    products.append({
                        "position": item.get("pos"),
                        "title": item.get("title"),
                        "price": item.get("price"),
                        "seller": item.get("seller"),
                        "type": "ad",
                        "url": item.get("url"),  # Google click-tracking URL
                        "thumbnail": item.get("thumbnail")
                    })

    response = {
        "status": "success" if "error" not in google_results else "failed",
        "input_type": input_type,
        "search_term": product_name,
        "original_asin": original_asin,
        "country": country,
        "google_domain": country_config["google_domain"],
        "geo_location": country_config["geo_location"],
        "locale": country_config["locale"],
        "summary": {
            "total_products_found": len(products),
            "organic_count": len([p for p in products if p["type"] == "organic"]),
            "ad_count": len([p for p in products if p["type"] == "ad"])
        }
    }
    
    # Add products list
    if products:
        response["products"] = products[:request.max_products]
    
    # Add detailed products if requested
    if request.get_detailed_product_info and detailed_products:
        response["detailed_products"] = detailed_products
        response["note"] = "Detailed products include direct merchant URLs from google_shopping_product API"
    
    # Add error if present
    if "error" in google_results:
        response["google_search_error"] = google_results["error"]
    
    return response


# =========================
# New endpoint for detailed product info
# =========================
@app.post("/product-details")
def get_product_details(request: ProductDetailsRequest):
    country = request.country.lower().replace(" ", "_")
    
    if country not in COUNTRY_CONFIG:
        raise HTTPException(
            status_code=400,
            detail=f"Country '{country}' not supported"
        )
    
    country_config = COUNTRY_CONFIG[country]
    results = []
    
    for token in request.tokens[:10]:  # Limit to 10 tokens per request
        decoded_token = decode_product_token(token)
        detailed_info = get_google_shopping_product_details(token, country_config)
        
        results.append({
            "token": token,
            "decoded_token_info": decoded_token,
            "product_details": detailed_info
        })
    
    return {
        "status": "success",
        "count": len(results),
        "products": results
    }


# =========================
# Utility endpoints
# =========================
@app.get("/")
def root():
    return {
        "message": "Product Comparison API",
        "endpoints": {
            "compare": "POST /compare - Search for products",
            "product_details": "POST /product-details - Get detailed product info using tokens",
            "countries": "GET /countries - List supported countries"
        },
        "example_request": {
            "asin_search": {
                "search": "B0CJT9WCRD",
                "country": "united_states",
                "pages": 1,
                "get_detailed_product_info": True
            },
            "product_search": {
                "search": "PlayStation DualSense Controller",
                "country": "united_states",
                "pages": 2
            }
        }
    }


@app.get("/countries")
def list_countries():
    return COUNTRY_CONFIG


@app.get("/health")
def health():
    try:
        # Test the API connection
        test_response = requests.post(
            OXYLABS_ENDPOINT,
            auth=(OXYLABS_USERNAME, OXYLABS_PASSWORD),
            json={"source": "google", "query": "test", "render": "html"},
            timeout=10
        )
        
        return {
            "status": "healthy",
            "api_connection": "ok" if test_response.status_code in [200, 400] else "failed",
            "api_status_code": test_response.status_code
        }
    except Exception as e:
        return {
            "status": "healthy",
            "api_connection": "failed",
            "error": str(e)
        }


# =========================
# Run locally
# =========================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
