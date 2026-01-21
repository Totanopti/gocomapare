from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import requests
from typing import Optional
import json

app = FastAPI()

# Oxylabs credentials
OXYLABS_USERNAME = "optisage_sV9jx"
OXYLABS_PASSWORD = "Optisage_25_10"
OXYLABS_ENDPOINT = "https://realtime.oxylabs.io/v1/queries"

# Google Shopping domains and their geo_locations
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

# Request model
class CompareRequest(BaseModel):
    search: str
    country: str
    pages: Optional[int] = 1
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    sort_by: Optional[str] = "r"  # r=relevance, p=price low to high, pd=price high to low, rv=review score

def is_asin(text: str) -> bool:
    """Check if text is a valid ASIN"""
    text = text.strip()
    return len(text) == 10 and text.isalnum()

def get_amazon_product_title(asin: str, domain: str):
    """Get product title from Amazon by ASIN"""
    payload = {
        "source": "amazon_product",
        "domain": domain,
        "query": asin,
        "parse": True
    }
    
    try:
        response = requests.post(
            OXYLABS_ENDPOINT,
            auth=(OXYLABS_USERNAME, OXYLABS_PASSWORD),
            json=payload,
            timeout=30
        )
        
        if response.status_code != 200:
            return None
            
        data = response.json()
        
        if "results" in data and data["results"]:
            result = data["results"][0]
            
            if "content" in result:
                content = result["content"]
                if isinstance(content, dict) and "title" in content:
                    return content["title"]
        
        return None
        
    except Exception:
        return None

def google_shopping_search(product_name: str, country_config: dict, pages: int = 1, 
                          min_price: Optional[float] = None, max_price: Optional[float] = None,
                          sort_by: str = "r"):
    """Google Shopping search with proper geo-targeting"""
    
    # Build context parameters
    context = [
        {"key": "sort_by", "value": sort_by}
    ]
    
    if min_price is not None:
        context.append({"key": "min_price", "value": str(min_price)})
    if max_price is not None:
        context.append({"key": "max_price", "value": str(max_price)})
    
    payload = {
        "source": "google_shopping_search",
        "domain": country_config["google_domain"],
        "query": product_name,
        "parse": True,
        "render": "html",  # Required for product tokens
        "pages": pages,
        "geo_location": country_config["geo_location"],
        "locale": country_config["locale"],
        "context": context
    }
    
    try:
        response = requests.post(
            OXYLABS_ENDPOINT,
            auth=(OXYLABS_USERNAME, OXYLABS_PASSWORD),
            json=payload,
            timeout=60
        )
        
        if response.status_code != 200:
            return {"error": f"API error: {response.status_code}", "details": response.text[:200]}
            
        data = response.json()
        return data
        
    except Exception as e:
        return {"error": f"Request failed: {str(e)}"}

@app.post("/compare")
def compare_products(request: CompareRequest):
    search_term = request.search.strip()
    country = request.country.lower().replace(" ", "_")
    
    # Validate country
    if country not in COUNTRY_CONFIG:
        raise HTTPException(
            status_code=400,
            detail=f"Country '{country}' not supported. Supported countries: {list(COUNTRY_CONFIG.keys())}"
        )
    
    country_config = COUNTRY_CONFIG[country]
    
    print(f"\n=== Processing: '{search_term}' in {country} ===")
    print(f"Geo location: {country_config['geo_location']}")
    print(f"Locale: {country_config['locale']}")
    
    if is_asin(search_term):
        print(f"Detected ASIN: {search_term}")
        
        # Get title from Amazon
        title = get_amazon_product_title(search_term, country_config["amazon_domain"])
        
        if not title:
            # Fallback for known ASINs
            known_titles = {
                "B07PGL2N5J": "Amazon Basics Silicone Baking Mat",
                "B08N5WRWNW": "Samsung Galaxy Watch",
                "B08BX7N9SK": "Amazon Echo Dot",
                "B08H95Y452": "Kindle Paperwhite",
                "B07VGRJDFY": "PlayStation 4",
                "B08FC5L3RG": "Apple AirPods Pro",
            }
            title = known_titles.get(search_term, search_term)
        
        print(f"Using search term: {title}")
        
        # Search Google Shopping
        google_results = google_shopping_search(
            product_name=title,
            country_config=country_config,
            pages=request.pages,
            min_price=request.min_price,
            max_price=request.max_price,
            sort_by=request.sort_by
        )
        
        response = {
            "input_type": "ASIN",
            "asin": search_term,
            "country": country,
            "google_domain": country_config["google_domain"],
            "amazon_domain": f"amazon.{country_config['amazon_domain']}",
            "geo_location": country_config["geo_location"],
            "locale": country_config["locale"],
            "product_title": title,
            "search_parameters": {
                "pages": request.pages,
                "min_price": request.min_price,
                "max_price": request.max_price,
                "sort_by": request.sort_by
            },
        }
        
        if google_results and "error" not in google_results:
            response["google_results"] = google_results
            response["status"] = "success"
            
            # Check parsing status
            if "results" in google_results and google_results["results"]:
                first_result = google_results["results"][0]
                status_code = first_result.get("status_code", 0)
                response["parsing_status"] = status_code
                
                # Count products found
                if "content" in first_result and "results" in first_result["content"]:
                    organic = first_result["content"]["results"].get("organic", [])
                    pla = first_result["content"]["results"].get("pla", [])
                    response["products_found"] = {
                        "organic": len(organic),
                        "ads": sum(len(item.get("items", [])) for item in pla) if pla else 0
                    }
        else:
            response["google_results"] = google_results
            response["status"] = "failed" if "error" in google_results else "partial"
            
        return response
        
    else:
        # Direct product name search
        print(f"Direct product search: {search_term}")
        
        google_results = google_shopping_search(
            product_name=search_term,
            country_config=country_config,
            pages=request.pages,
            min_price=request.min_price,
            max_price=request.max_price,
            sort_by=request.sort_by
        )
        
        response = {
            "input_type": "Product Name",
            "search_term": search_term,
            "country": country,
            "google_domain": country_config["google_domain"],
            "geo_location": country_config["geo_location"],
            "locale": country_config["locale"],
            "search_parameters": {
                "pages": request.pages,
                "min_price": request.min_price,
                "max_price": request.max_price,
                "sort_by": request.sort_by
            },
        }
        
        if google_results and "error" not in google_results:
            response["google_results"] = google_results
            response["status"] = "success"
            
            # Check parsing status and count products
            if "results" in google_results and google_results["results"]:
                first_result = google_results["results"][0]
                status_code = first_result.get("status_code", 0)
                response["parsing_status"] = status_code
                
                if "content" in first_result and "results" in first_result["content"]:
                    organic = first_result["content"]["results"].get("organic", [])
                    pla = first_result["content"]["results"].get("pla", [])
                    response["products_found"] = {
                        "organic": len(organic),
                        "ads": sum(len(item.get("items", [])) for item in pla) if pla else 0
                    }
                    
                    # Add sample products
                    if organic:
                        response["sample_products"] = [
                            {
                                "title": p.get("title"),
                                "price": p.get("price_str"),
                                "currency": p.get("currency"),
                                "merchant": p.get("merchant", {}).get("name"),
                                "rating": p.get("rating"),
                                "token": p.get("token")[:50] + "..." if p.get("token") else None
                            }
                            for p in organic[:3]  # First 3 products
                        ]
        else:
            response["google_results"] = google_results
            response["status"] = "failed" if "error" in google_results else "partial"
            
        return response

@app.get("/")
def root():
    return {
        "message": "Product Comparison API",
        "endpoints": {
            "POST /compare": "Compare products by ASIN or name",
            "GET /countries": "List supported countries"
        },
        "example_request": {
            "as_asin": '{"search": "B07PGL2N5J", "country": "united_states"}',
            "as_product": '{"search": "wireless headphones", "country": "united_states", "pages": 2}'
        }
    }

@app.get("/countries")
def list_countries():
    countries = {}
    for country, config in COUNTRY_CONFIG.items():
        countries[country] = {
            "google_domain": config["google_domain"],
            "geo_location": config["geo_location"],
            "locale": config["locale"]
        }
    return countries

@app.get("/health")
def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    print("=" * 60)
    print("Product Comparison API Started Successfully!")
    print("=" * 60)
    print("Available at: http://localhost:8000")
    print("Docs: http://localhost:8000/docs")
    print("\nSupported countries:")
    for country in COUNTRY_CONFIG.keys():
        print(f"  - {country}")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
