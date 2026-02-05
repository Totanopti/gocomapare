from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import requests
from typing import Optional
import time
import json
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
        "locale": "en-US",
        "currency": "USD"
    },
    "united_kingdom": {
        "google_domain": "co.uk",
        "amazon_domain": "co.uk",
        "geo_location": "London,England,United Kingdom",
        "locale": "en-GB",
        "currency": "GBP"
    },
    "canada": {
        "google_domain": "ca",
        "amazon_domain": "ca",
        "geo_location": "Toronto,Ontario,Canada",
        "locale": "en-CA",
        "currency": "CAD"
    },
    "australia": {
        "google_domain": "com.au",
        "amazon_domain": "com.au",
        "geo_location": "Sydney,New South Wales,Australia",
        "locale": "en-AU",
        "currency": "AUD"
    },
    "germany": {
        "google_domain": "de",
        "amazon_domain": "de",
        "geo_location": "Berlin,Berlin,Germany",
        "locale": "de-DE",
        "currency": "EUR"
    },
    "france": {
        "google_domain": "fr",
        "amazon_domain": "fr",
        "geo_location": "Paris,Île-de-France,France",
        "locale": "fr-FR",
        "currency": "EUR"
    },
    "india": {
        "google_domain": "co.in",
        "amazon_domain": "in",
        "geo_location": "Mumbai,Maharashtra,India",
        "locale": "en-IN",
        "currency": "INR"
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
    pages: Optional[int] = 1
    detailed: Optional[bool] = True

class SearchRequest(BaseModel):
    query: str
    country: str
    pages: Optional[int] = 1

# =========================
# Helpers
# =========================
def is_asin(text: str) -> bool:
    """Check if input is an Amazon ASIN"""
    text = text.strip().upper()
    # ASIN format: 10 characters, alphanumeric
    return len(text) == 10 and text.isalnum()

def post_with_retry(payload: dict, retries: int = 3, delay: int = 2):
    """Post request with retry logic"""
    for attempt in range(retries):
        try:
            response = requests.post(
                OXYLABS_ENDPOINT,
                auth=(OXYLABS_USERNAME, OXYLABS_PASSWORD),
                json=payload,
                timeout=60,
                headers={"Content-Type": "application/json"}
            )

            if response.status_code == 429:  # Rate limited
                wait_time = delay * (2 ** attempt)  # Exponential backoff
                time.sleep(wait_time)
                continue
                
            return response

        except requests.exceptions.RequestException as e:
            if attempt == retries - 1:
                raise e
            time.sleep(delay * (2 ** attempt))
    
    return None

def get_amazon_product_title(asin: str, domain: str) -> Optional[str]:
    """Get product title from Amazon using ASIN"""
    payload = {
        "source": "amazon_product",
        "domain": domain,
        "query": asin,
        "parse": True,
        "render": "html"
    }

    try:
        response = post_with_retry(payload)
        if not response or response.status_code != 200:
            return None

        data = response.json()
        if "results" in data and len(data["results"]) > 0:
            result = data["results"][0]
            content = result.get("content", {})
            return content.get("title")
        
        return None

    except Exception:
        return None

def decode_google_shopping_query(encoded_query: str) -> dict:
    """Decode base64 encoded Google Shopping query"""
    try:
        # Add padding if needed
        padding = 4 - len(encoded_query) % 4
        if padding != 4:
            encoded_query += "=" * padding
        
        decoded_bytes = base64.b64decode(encoded_query)
        return json.loads(decoded_bytes)
    except Exception:
        return {}

# =========================
# Google Shopping Functions
# =========================
def google_shopping_product_search(product_name: str, country_config: dict):
    """
    Search for specific product details and pricing from multiple merchants
    """
    payload = {
        "source": "google_shopping_product",
        "domain": country_config["google_domain"],
        "query": product_name,
        "parse": True,
        "render": "html",
        "geo_location": country_config["geo_location"],
        "locale": country_config["locale"],
        "context": [
            {"key": "sort_by", "value": "p"},  # Sort by price
            {"key": "force_headers", "value": False},
            {"key": "force_cookies", "value": False}
        ]
    }

    try:
        response = post_with_retry(payload)
        if not response:
            return {"error": "No response from API"}
        
        if response.status_code != 200:
            return {
                "error": f"API error: {response.status_code}",
                "details": response.text[:500]
            }

        return response.json()

    except Exception as e:
        return {"error": str(e)}

def google_shopping_search_general(query: str, country_config: dict, pages: int = 1):
    """
    General Google Shopping search for multiple products
    """
    payload = {
        "source": "google_shopping_search",
        "domain": country_config["google_domain"],
        "query": query,
        "parse": True,
        "render": "html",
        "pages": pages,
        "geo_location": country_config["geo_location"],
        "locale": country_config["locale"],
        "context": [
            {"key": "sort_by", "value": "r"},  # Sort by relevance
            {"key": "force_headers", "value": False},
            {"key": "force_cookies", "value": False}
        ]
    }

    try:
        response = post_with_retry(payload)
        if not response:
            return {"error": "No response from API"}
        
        if response.status_code != 200:
            return {
                "error": f"API error: {response.status_code}",
                "details": response.text[:500]
            }

        return response.json()

    except Exception as e:
        return {"error": str(e)}

# =========================
# Data Processing Functions
# =========================
def extract_product_comparison(google_results: dict):
    """
    Extract structured comparison data from Google Shopping product response
    """
    if "error" in google_results:
        return google_results

    if "content" not in google_results:
        return {"error": "No content in response", "raw": google_results}

    content = google_results["content"]
    
    # Basic product info
    product_data = {
        "product_title": content.get("title", "Unknown Product"),
        "description": content.get("description", ""),
        "images": content.get("images", {}),
        "reviews": content.get("reviews", {}),
        "specifications": [],
        "price_comparison": [],
        "related_products": [],
        "total_merchants": 0,
        "price_range": {"min": None, "max": None, "currency": None}
    }

    # Extract specifications
    specs = content.get("specifications", [])
    for section in specs:
        if "items" in section:
            product_data["specifications"].extend(section["items"])

    # Extract price comparisons
    pricing = content.get("pricing", {})
    online_prices = pricing.get("online", [])
    
    prices = []
    for price_data in online_prices:
        seller_info = {
            "seller": price_data.get("seller", "Unknown Seller"),
            "price": price_data.get("price"),
            "currency": price_data.get("currency", ""),
            "condition": price_data.get("condition", "Unknown"),
            "direct_url": price_data.get("seller_link"),
            "details": price_data.get("details", ""),
            "source": "google_shopping"
        }
        
        product_data["price_comparison"].append(seller_info)
        
        # Track price range
        if price_data.get("price"):
            prices.append(price_data["price"])
            product_data["price_range"]["currency"] = price_data.get("currency")

    # Calculate price range
    if prices:
        product_data["price_range"]["min"] = min(prices)
        product_data["price_range"]["max"] = max(prices)
        product_data["total_merchants"] = len(prices)

    # Extract related products
    related = content.get("related_items", [])
    for section in related:
        if "items" in section:
            product_data["related_products"].extend(section["items"][:5])  # Limit to 5

    return product_data

def extract_search_results(google_results: dict):
    """
    Extract search results from Google Shopping search
    """
    if "error" in google_results:
        return google_results

    results = []
    
    if "results" in google_results:
        for result in google_results["results"]:
            content = result.get("content", {})
            
            # Organic results
            for organic in content.get("organic", []):
                product_info = {
                    "title": organic.get("title"),
                    "price": organic.get("price"),
                    "currency": organic.get("currency"),
                    "reviews_count": organic.get("reviews_count"),
                    "rating": organic.get("rating"),
                    "thumbnail": organic.get("thumbnail"),
                    "url": organic.get("url"),
                    "type": "organic"
                }
                if product_info["title"]:
                    results.append(product_info)
            
            # Product Listing Ads (PLA)
            for pla in content.get("pla", []):
                for item in pla.get("items", []):
                    product_info = {
                        "title": item.get("title"),
                        "price": item.get("price"),
                        "currency": item.get("currency"),
                        "reviews_count": item.get("reviews_count"),
                        "rating": item.get("rating"),
                        "thumbnail": item.get("thumbnail"),
                        "url": item.get("url"),
                        "type": "ad"
                    }
                    if product_info["title"]:
                        results.append(product_info)

    return {
        "products": results[:20],  # Limit to 20 results
        "total_found": len(results)
    }

# =========================
# Main Endpoints
# =========================
@app.post("/compare")
async def compare_products(request: CompareRequest):
    """
    Compare prices for a specific product across multiple merchants
    Returns detailed product information with price comparisons
    """
    search_term = request.search.strip()
    country = request.country.lower().replace(" ", "_")
    detailed = request.detailed

    if country not in COUNTRY_CONFIG:
        raise HTTPException(
            status_code=400,
            detail=f"Country '{country}' not supported. Available: {list(COUNTRY_CONFIG.keys())}"
        )

    country_config = COUNTRY_CONFIG[country]
    currency = country_config.get("currency", "USD")

    # Determine if input is ASIN
    if is_asin(search_term):
        title = get_amazon_product_title(search_term, country_config["amazon_domain"])
        product_name = title or search_term
        input_type = "ASIN"
        source = "Amazon ASIN"
    else:
        product_name = search_term
        input_type = "Product Name"
        source = "Direct Search"

    # Get product comparison data
    if detailed:
        google_results = google_shopping_product_search(product_name, country_config)
        comparison_data = extract_product_comparison(google_results)
        
        if "error" in comparison_data:
            # Fallback to general search if product search fails
            google_results = google_shopping_search_general(product_name, country_config, 1)
            comparison_data = extract_search_results(google_results)
            search_type = "general_search"
    else:
        google_results = google_shopping_search_general(product_name, country_config, request.pages)
        comparison_data = extract_search_results(google_results)
        search_type = "general_search"

    # Prepare response
    response = {
        "status": "success" if "error" not in comparison_data else "partial" if "products" in comparison_data else "failed",
        "metadata": {
            "input_type": input_type,
            "source": source,
            "search_term": product_name,
            "original_search": search_term,
            "country": country,
            "country_details": {
                "google_domain": country_config["google_domain"],
                "amazon_domain": country_config["amazon_domain"],
                "geo_location": country_config["geo_location"],
                "locale": country_config["locale"],
                "currency": currency
            },
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "detailed": detailed
        },
        "data": comparison_data
    }

    # Add success metrics
    if "error" not in comparison_data:
        if "price_comparison" in comparison_data:
            response["metrics"] = {
                "merchants_found": comparison_data.get("total_merchants", 0),
                "has_direct_urls": any(p.get("direct_url") for p in comparison_data.get("price_comparison", [])),
                "has_reviews": bool(comparison_data.get("reviews", {}).get("rating")),
                "has_specifications": len(comparison_data.get("specifications", [])) > 0
            }
        elif "products" in comparison_data:
            response["metrics"] = {
                "products_found": comparison_data.get("total_found", 0),
                "organic_results": len([p for p in comparison_data.get("products", []) if p.get("type") == "organic"]),
                "ad_results": len([p for p in comparison_data.get("products", []) if p.get("type") == "ad"])
            }

    return response

@app.post("/search")
async def search_products(request: SearchRequest):
    """
    Search for multiple products (general search)
    Returns list of products without detailed comparison
    """
    query = request.query.strip()
    country = request.country.lower().replace(" ", "_")
    
    if country not in COUNTRY_CONFIG:
        raise HTTPException(
            status_code=400,
            detail=f"Country '{country}' not supported. Available: {list(COUNTRY_CONFIG.keys())}"
        )

    country_config = COUNTRY_CONFIG[country]
    
    # Perform general search
    google_results = google_shopping_search_general(query, country_config, request.pages)
    search_data = extract_search_results(google_results)
    
    response = {
        "status": "success" if "error" not in search_data else "failed",
        "metadata": {
            "query": query,
            "country": country,
            "pages": request.pages,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        },
        "data": search_data
    }
    
    return response

@app.get("/product/{product_id}")
async def get_product_by_id(product_id: str, country: str = "united_states"):
    """
    Get product details by encoded Google Shopping product ID
    """
    country = country.lower().replace(" ", "_")
    
    if country not in COUNTRY_CONFIG:
        raise HTTPException(
            status_code=400,
            detail=f"Country '{country}' not supported"
        )

    country_config = COUNTRY_CONFIG[country]
    
    # Decode the product ID (base64 encoded query)
    decoded_query = decode_google_shopping_query(product_id)
    
    if not decoded_query:
        raise HTTPException(
            status_code=400,
            detail="Invalid product ID format"
        )
    
    # Extract query from decoded data
    query = decoded_query.get("query", "")
    if not query:
        raise HTTPException(
            status_code=400,
            detail="No search query in product ID"
        )
    
    # Get product details
    google_results = google_shopping_product_search(query, country_config)
    comparison_data = extract_product_comparison(google_results)
    
    return {
        "status": "success" if "error" not in comparison_data else "failed",
        "product_id": product_id,
        "decoded_query": decoded_query,
        "data": comparison_data
    }

# =========================
# Utility Endpoints
# =========================
@app.get("/")
async def root():
    """API Root"""
    return {
        "message": "Product Comparison API v2.0",
        "endpoints": {
            "compare": "POST /compare - Compare prices for a specific product",
            "search": "POST /search - Search for multiple products",
            "product": "GET /product/{id} - Get product by ID",
            "countries": "GET /countries - List supported countries",
            "health": "GET /health - API health check"
        },
        "features": [
            "ASIN to product name conversion",
            "Price comparison across multiple merchants",
            "Direct merchant URLs (no Google redirects)",
            "Product specifications and reviews",
            "Multi-country support"
        ]
    }

@app.get("/countries")
async def list_countries():
    """List all supported countries"""
    return {
        "countries": list(COUNTRY_CONFIG.keys()),
        "details": COUNTRY_CONFIG
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    # Test API connectivity
    test_payload = {
        "source": "google_shopping_product",
        "domain": "com",
        "query": "test",
        "parse": False,
        "render": "html"
    }
    
    try:
        response = requests.post(
            OXYLABS_ENDPOINT,
            auth=(OXYLABS_USERNAME, OXYLABS_PASSWORD),
            json=test_payload,
            timeout=10
        )
        api_status = "healthy" if response.status_code == 200 else "unhealthy"
    except:
        api_status = "unreachable"
    
    return {
        "status": "running",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "api_connectivity": api_status,
        "supported_countries": len(COUNTRY_CONFIG)
    }

@app.get("/decode/{encoded_string}")
async def decode_string(encoded_string: str):
    """Decode a base64 encoded string (for debugging)"""
    try:
        decoded = decode_google_shopping_query(encoded_string)
        return {
            "encoded": encoded_string,
            "decoded": decoded,
            "valid": bool(decoded)
        }
    except Exception as e:
        return {
            "error": str(e),
            "encoded": encoded_string
        }

# =========================
# Run the application
# =========================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
