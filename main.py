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


def post_with_retry(payload: dict, retries: int = 3) -> requests.Response:
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


def google_shopping_search(product_name: str, country_config: dict, pages: int) -> Dict[str, Any]:
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


def google_shopping_product(product_token: str, country_config: dict) -> Dict[str, Any]:
    """Get detailed product information including seller URLs"""
    payload = {
        "source": "google_shopping_product",
        "query": product_token,
        "parse": True,
        "render": "html",
        "domain": country_config["google_domain"],
        "geo_location": country_config["geo_location"],
        "locale": country_config["locale"],
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


def extract_product_tokens_from_search(search_results: Dict[str, Any]) -> List[str]:
    """Extract product tokens from search results"""
    tokens = []
    
    if "error" in search_results:
        return tokens
    
    try:
        for result in search_results.get("results", []):
            content = result.get("content", {})
            search_content = content.get("results", {})
            
            # Check organic results
            for organic in search_content.get("organic", []):
                if "product_token" in organic:
                    tokens.append(organic["product_token"])
            
            # Check PLA results (ads)
            for pla in search_content.get("pla", []):
                for item in pla.get("items", []):
                    if "product_token" in item:
                        tokens.append(item["product_token"])
    
    except Exception as e:
        print(f"Error extracting tokens: {e}")
    
    return tokens


def process_product_details(product_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract and format product details with seller URLs"""
    if "error" in product_data:
        return product_data
    
    try:
        result = product_data.get("results", [{}])[0]
        content = result.get("content", {})
        
        # Extract seller URLs from pricing information
        seller_urls = []
        if "pricing" in content and "online" in content["pricing"]:
            for seller_info in content["pricing"]["online"]:
                seller_urls.append({
                    "seller": seller_info.get("seller"),
                    "url": seller_info.get("seller_link"),
                    "price": seller_info.get("price"),
                    "currency": seller_info.get("currency"),
                    "shipping": seller_info.get("price_shipping"),
                    "condition": seller_info.get("condition")
                })
        
        return {
            "title": content.get("title"),
            "description": content.get("description"),
            "url": content.get("url"),
            "seller_urls": seller_urls,
            "total_sellers": len(seller_urls),
            "images": content.get("images", {}).get("full_size", []),
            "reviews": content.get("reviews", {}),
            "specifications": content.get("specifications", []),
            "variants": content.get("variants", []),
            "related_items": content.get("related_items", [])
        }
    
    except Exception as e:
        return {"error": f"Error processing product data: {str(e)}"}


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

    # Step 1: Search for products
    google_search_results = google_shopping_search(
        product_name=product_name,
        country_config=country_config,
        pages=request.pages
    )
    
    if "error" in google_search_results:
        return {
            "status": "failed",
            "error": google_search_results["error"],
            "details": google_search_results.get("details", "")
        }
    
    # Step 2: Extract product tokens
    product_tokens = extract_product_tokens_from_search(google_search_results)
    
    if not product_tokens:
        return {
            "status": "success",
            "message": "No products found",
            "input_type": input_type,
            "search_term": product_name,
            "country": country,
            "products_found": 0,
            "product_details": []
        }
    
    # Step 3: Get detailed info for ALL products (no max limit)
    product_details = []
    
    for i, token in enumerate(product_tokens):
        product_data = google_shopping_product(token, country_config)
        
        if "error" not in product_data:
            detailed_info = process_product_details(product_data)
            product_details.append({
                "product_index": i + 1,
                "product_token": token,
                **detailed_info
            })
        
        # Small delay between requests to avoid rate limiting
        if i < len(product_tokens) - 1:
            time.sleep(1)  # 1 second delay between requests
    
    # Prepare response
    response = {
        "status": "success",
        "input_type": input_type,
        "search_term": product_name,
        "country": country,
        "google_domain": country_config["google_domain"],
        "geo_location": country_config["geo_location"],
        "locale": country_config["locale"],
        "total_products_found": len(product_tokens),
        "products_processed": len(product_details),
        "product_details": product_details
    }
    
    # Count products from search results
    try:
        first_result = google_search_results.get("results", [{}])[0]
        content = first_result.get("content", {}).get("results", {})
        response["search_summary"] = {
            "organic_results": len(content.get("organic", [])),
            "ads_results": sum(len(p.get("items", [])) for p in content.get("pla", []))
        }
    except:
        pass
    
    return response


@app.post("/product-details")
def get_product_details(product_token: str, country: str):
    """Get detailed information for a specific product token"""
    country = country.lower().replace(" ", "_")
    
    if country not in COUNTRY_CONFIG:
        raise HTTPException(
            status_code=400,
            detail=f"Country '{country}' not supported"
        )
    
    country_config = COUNTRY_CONFIG[country]
    
    product_data = google_shopping_product(product_token, country_config)
    
    if "error" in product_data:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get product details: {product_data['error']}"
        )
    
    detailed_info = process_product_details(product_data)
    
    return {
        "status": "success",
        "product_token": product_token,
        "country": country,
        **detailed_info
    }


# =========================
# Utility endpoints
# =========================
@app.get("/")
def root():
    return {
        "message": "Product Comparison API",
        "endpoints": {
            "compare": "POST /compare - Search and compare products",
            "product_details": "POST /product-details - Get details for specific product token",
            "countries": "GET /countries - List supported countries"
        },
        "example_request": {
            "compare": {
                "search": "PlayStation DualSense Controller",
                "country": "united_states",
                "pages": 1
            },
            "product_details": {
                "product_token": "your_product_token_here",
                "country": "united_states"
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
