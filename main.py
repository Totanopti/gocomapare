from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import requests
from typing import Optional, List, Dict, Any
import time
import base64
import logging

app = FastAPI()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
    cleaned = text.strip().upper()
    # ASINs are 10 characters, alphanumeric
    return len(cleaned) == 10 and all(c.isalnum() for c in cleaned)


def post_with_retry(payload: dict, retries: int = 3):
    for attempt in range(retries):
        try:
            logger.info(f"Attempt {attempt + 1} to Oxylabs API")
            response = requests.post(
                OXYLABS_ENDPOINT,
                auth=(OXYLABS_USERNAME, OXYLABS_PASSWORD),
                json=payload,
                timeout=60
            )
            
            logger.info(f"Response status: {response.status_code}")
            
            if response.status_code != 429:
                return response

            time.sleep(2 ** attempt)  # exponential backoff
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error: {e}")
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)

    return response


def get_amazon_product_title(asin: str, domain: str) -> Optional[str]:
    payload = {
        "source": "amazon_product",
        "domain": domain,
        "query": asin,
        "parse": True
    }

    try:
        logger.info(f"Fetching Amazon product title for ASIN: {asin}")
        response = post_with_retry(payload)
        
        if response.status_code != 200:
            logger.error(f"Amazon API error: {response.status_code}")
            return None

        data = response.json()
        logger.info(f"Amazon API response keys: {list(data.keys())}")
        
        if "results" in data and len(data["results"]) > 0:
            result = data["results"][0]
            content = result.get("content", {})
            
            # Try different possible title fields
            title = content.get("title") or content.get("product_title")
            
            if title:
                logger.info(f"Found Amazon title: {title[:50]}...")
                return title
            else:
                logger.warning("No title found in Amazon response")
                logger.debug(f"Content keys: {list(content.keys())}")
                return None
        else:
            logger.warning("No results in Amazon response")
            return None

    except Exception as e:
        logger.error(f"Amazon title fetch error: {e}")
        return None


def google_shopping_search(product_name: str, country_config: dict, pages: int):
    logger.info(f"Google Shopping search for: {product_name}")
    
    # Clean up the product name for better search results
    search_query = product_name.replace(" - ", " ").replace("  ", " ")
    
    payload = {
        "source": "google_shopping_search",
        "domain": country_config["google_domain"],
        "query": search_query,
        "parse": True,
        "render": "html",
        "pages": pages,
        "geo_location": country_config["geo_location"],
        "locale": country_config["locale"],
        "context": [{"key": "sort_by", "value": "r"}],
        "user_agent_type": "desktop"
    }

    try:
        logger.info(f"Payload sent to Google Shopping: {payload['query']}")
        response = post_with_retry(payload)
        
        if response.status_code != 200:
            error_msg = f"API error: {response.status_code}"
            logger.error(f"{error_msg} - Response: {response.text[:200]}")
            return {
                "error": error_msg,
                "details": response.text[:200],
                "status_code": response.status_code
            }

        data = response.json()
        logger.info(f"Google Shopping response received")
        
        # Debug logging
        if "results" in data:
            logger.info(f"Number of results in response: {len(data['results'])}")
            for i, result in enumerate(data["results"]):
                logger.info(f"Result {i}: keys = {list(result.keys())}")
                if "content" in result:
                    content = result["content"]
                    logger.info(f"  Content keys: {list(content.keys())}")
                    if "organic" in content:
                        logger.info(f"  Organic items: {len(content['organic'])}")
                    if "pla" in content:
                        logger.info(f"  PLA items: {len(content['pla'])}")
        else:
            logger.warning("No 'results' key in response")
            logger.info(f"Response keys: {list(data.keys())}")
        
        return data

    except Exception as e:
        logger.error(f"Google Shopping search error: {e}")
        return {"error": str(e), "type": "exception"}


def get_google_shopping_product_details(token: str, country_config: dict) -> Dict[str, Any]:
    """Get detailed product information using product token"""
    logger.info(f"Getting product details for token")
    
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
                "message": f"API error: {response.status_code}",
                "status_code": response.status_code
            }

        data = response.json()
        logger.info(f"Product details response keys: {list(data.keys())}")
        
        # Extract product details from response
        if "results" in data and len(data["results"]) > 0:
            result = data["results"][0]
            content = result.get("content", {})
            
            logger.info(f"Product details content keys: {list(content.keys())}")
            
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


def extract_products_from_results(google_results: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract products from Google Shopping search results"""
    products = []
    
    if "error" in google_results:
        logger.warning(f"Error in results: {google_results.get('error')}")
        return products
    
    if "results" not in google_results:
        logger.warning("No 'results' key in google_results")
        return products
    
    for result in google_results.get("results", []):
        content = result.get("content", {})
        
        # Process organic results
        for organic in content.get("organic", []):
            product_data = {
                "position": organic.get("pos"),
                "title": organic.get("title"),
                "price": organic.get("price_str"),
                "currency": organic.get("currency"),
                "merchant": organic.get("merchant", {}).get("name") if isinstance(organic.get("merchant"), dict) else organic.get("merchant"),
                "rating": organic.get("rating"),
                "reviews_count": organic.get("reviews_count"),
                "delivery_info": organic.get("delivery"),
                "type": "organic",
                "google_shopping_url": organic.get("url"),
                "product_token": organic.get("token"),
                "product_id": organic.get("product_id"),
                "thumbnail": organic.get("thumbnail")
            }
            
            # Filter out products with minimal data
            if product_data["title"] or product_data["price"]:
                products.append(product_data)
            else:
                logger.debug(f"Skipping product with insufficient data: {product_data}")
        
        # Process PLA ads
        for pla in content.get("pla", []):
            for item in pla.get("items", []):
                product_data = {
                    "position": item.get("pos"),
                    "title": item.get("title"),
                    "price": item.get("price"),
                    "seller": item.get("seller"),
                    "type": "ad",
                    "url": item.get("url"),
                    "thumbnail": item.get("thumbnail"),
                    "product_token": None  # Ads usually don't have tokens
                }
                
                if product_data["title"] or product_data["price"]:
                    products.append(product_data)
    
    logger.info(f"Extracted {len(products)} products from search results")
    return products


# =========================
# Main endpoint - FIXED VERSION
# =========================
@app.post("/compare")
def compare_products(request: CompareRequest):
    search_term = request.search.strip()
    country = request.country.lower().replace(" ", "_")
    
    logger.info(f"Received compare request: {search_term} for {country}")

    if country not in COUNTRY_CONFIG:
        raise HTTPException(
            status_code=400,
            detail=f"Country '{country}' not supported"
        )

    country_config = COUNTRY_CONFIG[country]
    logger.info(f"Using country config: {country}")

    # ASIN flow
    product_name = search_term
    input_type = "Product Name"
    original_asin = None
    
    if is_asin(search_term):
        logger.info(f"Detected ASIN: {search_term}")
        input_type = "ASIN"
        original_asin = search_term
        
        # Get Amazon product title
        title = get_amazon_product_title(search_term, country_config["amazon_domain"])
        if title:
            product_name = title
            logger.info(f"Using Amazon title: {product_name}")
        else:
            logger.warning(f"Could not get Amazon title for {search_term}, using ASIN as search term")
            product_name = search_term
    
    # Try multiple search strategies if first fails
    search_attempts = [
        product_name,  # Original search term
        product_name.split(" - ")[0],  # Remove variant/suffix
        " ".join(product_name.split(" ")[:5]),  # First 5 words
    ]
    
    google_results = None
    final_products = []
    
    for attempt, search_query in enumerate(search_attempts):
        if final_products:  # Stop if we found products
            break
            
        logger.info(f"Search attempt {attempt + 1}: '{search_query}'")
        
        google_results = google_shopping_search(
            product_name=search_query,
            country_config=country_config,
            pages=request.pages
        )
        
        # Extract products
        products = extract_products_from_results(google_results)
        
        if products:
            logger.info(f"Found {len(products)} products on attempt {attempt + 1}")
            final_products = products
            product_name = search_query  # Use successful search term
            break
        else:
            logger.warning(f"No products found on attempt {attempt + 1}")
    
    # Build response
    response = {
        "status": "success" if "error" not in google_results else "partial",
        "input_type": input_type,
        "search_term": product_name,
        "original_asin": original_asin,
        "country": country,
        "google_domain": country_config["google_domain"],
        "geo_location": country_config["geo_location"],
        "locale": country_config["locale"],
        "summary": {
            "total_products_found": len(final_products),
            "organic_count": len([p for p in final_products if p.get("type") == "organic"]),
            "ad_count": len([p for p in final_products if p.get("type") == "ad"])
        }
    }
    
    # Add debug info
    if "error" in google_results:
        response["search_error"] = {
            "message": google_results.get("error"),
            "details": google_results.get("details"),
            "status_code": google_results.get("status_code")
        }
    
    # Add products if found
    if final_products:
        response["products"] = final_products[:request.max_products]
        
        # Get detailed product info if requested
        if request.get_detailed_product_info:
            detailed_products = []
            for product in final_products[:min(5, request.max_products)]:  # Limit to 5 for performance
                token = product.get("product_token")
                if token:
                    detailed_info = get_google_shopping_product_details(token, country_config)
                    if detailed_info.get("status") == "success":
                        product["detailed_info"] = detailed_info.get("product_details", {})
                        detailed_products.append(product)
            
            if detailed_products:
                response["detailed_products"] = detailed_products
                response["note"] = f"Got detailed info for {len(detailed_products)} products"
    else:
        response["note"] = "No products found. Try a simpler search term."
        response["debug"] = {
            "search_attempts": search_attempts,
            "search_query_used": product_name,
            "api_response_keys": list(google_results.keys()) if isinstance(google_results, dict) else []
        }
    
    logger.info(f"Response: {len(final_products)} products found")
    return response


# =========================
# New endpoint for direct search testing
# =========================
@app.post("/test-search")
def test_search(search_query: str, country: str = "united_states"):
    """Simple endpoint to test search functionality"""
    country = country.lower().replace(" ", "_")
    
    if country not in COUNTRY_CONFIG:
        raise HTTPException(status_code=400, detail="Country not supported")
    
    country_config = COUNTRY_CONFIG[country]
    
    # Direct Google search without Amazon lookup
    google_results = google_shopping_search(
        product_name=search_query,
        country_config=country_config,
        pages=1
    )
    
    products = extract_products_from_results(google_results)
    
    return {
        "search_query": search_query,
        "country": country,
        "products_found": len(products),
        "products": products[:10],
        "raw_response_keys": list(google_results.keys()) if isinstance(google_results, dict) else [],
        "has_error": "error" in google_results
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
            "test-search": "POST /test-search - Simple search test",
            "product_details": "POST /product-details - Get detailed product info",
            "countries": "GET /countries - List supported countries"
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
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
