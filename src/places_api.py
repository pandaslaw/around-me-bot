import requests
from logging import getLogger
from typing import List, Dict, Any, Optional
import json
import math
from src.config.config import app_settings

logger = getLogger(__name__)


def get_nearby_places(lat: float, lon: float, radius: int = 10000, lang: str = "en") -> List[Dict[Any, Any]]:
    """
    Get nearby places of interest using multiple APIs with fallback mechanisms.
    Searches within 10km radius and returns 5-7 nearest places to avoid empty results.
    
    :param lat: Latitude
    :param lon: Longitude  
    :param radius: Search radius in meters (default 10000m = 10km)
    :param lang: Language code (en or ru)
    :return: List of 5-7 nearest places with enriched information
    """
    logger.info(f"Searching for POIs near {lat}, {lon} within {radius}m radius")
    
    all_places = []
    
    # Try multiple APIs and collect ALL results within 10km
    # 1. Try Foursquare Places API (if API key available)
    if hasattr(app_settings, 'FOURSQUARE_API_KEY') and app_settings.FOURSQUARE_API_KEY:
        try:
            foursquare_places = _get_foursquare_places(lat, lon, radius, lang)
            if foursquare_places:
                all_places.extend(foursquare_places)
                logger.info(f"Found {len(foursquare_places)} places from Foursquare")
        except Exception as e:
            logger.warning(f"Foursquare API failed: {e}")
    
    # 2. Try improved OpenStreetMap with 10km radius
    try:
        osm_places = _get_osm_places_improved(lat, lon, radius, lang)
        if osm_places:
            all_places.extend(osm_places)
            logger.info(f"Found {len(osm_places)} places from improved OSM")
    except Exception as e:
        logger.warning(f"Improved OSM API failed: {e}")
    
    # 3. Try Nominatim search as additional source
    try:
        nominatim_places = _get_nominatim_places(lat, lon, radius, lang)
        if nominatim_places:
            all_places.extend(nominatim_places)
            logger.info(f"Found {len(nominatim_places)} places from Nominatim")
    except Exception as e:
        logger.warning(f"Nominatim API failed: {e}")
    
    # 4. Try Wikipedia geosearch for additional coverage
    try:
        wikipedia_places = _get_wikipedia_places(lat, lon, radius, lang)
        if wikipedia_places:
            all_places.extend(wikipedia_places)
            logger.info(f"Found {len(wikipedia_places)} places from Wikipedia")
    except Exception as e:
        logger.warning(f"Wikipedia API failed: {e}")
    
    if not all_places:
        logger.warning("All POI APIs failed or returned no results")
        return []
    
    # Remove duplicates based on name and proximity (within 50m)
    unique_places = _remove_duplicate_places(all_places)
    logger.info(f"After deduplication: {len(unique_places)} unique places")
    
    # Sort by distance and return 5-7 nearest places
    sorted_places = sorted(unique_places, key=lambda x: x["distance"])
    
    # Return 5-7 places depending on how many we found
    if len(sorted_places) >= 7:
        result_count = 7
    elif len(sorted_places) >= 5:
        result_count = 6
    else:
        result_count = min(5, len(sorted_places))
    
    final_places = sorted_places[:result_count]
    logger.info(f"Returning {len(final_places)} nearest places (distances: {[int(p['distance']) for p in final_places[:3]]}m...)")
    
    return final_places


def _get_foursquare_places(lat: float, lon: float, radius: int, lang: str = "en") -> List[Dict[Any, Any]]:
    """
    Get places using Foursquare Places API (100k requests/month free).
    """
    url = "https://api.foursquare.com/v3/places/search"
    headers = {
        "Authorization": f"Bearer {app_settings.FOURSQUARE_API_KEY}",
        "Accept": "application/json"
    }
    
    params = {
        "ll": f"{lat},{lon}",
        "radius": min(radius, 10000),  # Max 10km for Foursquare
        "categories": "10000,12000,13000,16000",  # Arts, Culture, Entertainment, Landmarks
        "limit": 50,  # Increased limit for 10km search
        "sort": "DISTANCE"
    }
    
    response = requests.get(url, headers=headers, params=params, timeout=15)
    response.raise_for_status()
    data = response.json()
    
    places = []
    for venue in data.get("results", []):
        distance = venue.get("distance", 0)
        if distance > radius:
            continue
            
        place = {
            "name": venue.get("name", "Unknown Place"),
            "description": ", ".join([cat.get("name", "") for cat in venue.get("categories", [])]),
            "address": venue.get("location", {}).get("formatted_address", ""),
            "latitude": venue.get("geocodes", {}).get("main", {}).get("latitude", lat),
            "longitude": venue.get("geocodes", {}).get("main", {}).get("longitude", lon),
            "distance": distance,
            "source": "foursquare",
            "category": venue.get("categories", [{}])[0].get("name", "Point of Interest") if venue.get("categories") else "Point of Interest"
        }
        places.append(place)
    
    return sorted(places, key=lambda x: x["distance"])[:10]


def _get_osm_places_improved(lat: float, lon: float, radius: int, lang: str = "en") -> List[Dict[Any, Any]]:
    """
    Improved OpenStreetMap query with broader categories and larger radius.
    """
    overpass_url = "http://overpass-api.de/api/interpreter"
    
    # More comprehensive query including shops, restaurants, and broader categories
    overpass_query = f"""
    [out:json][timeout:30];
    (
      node["tourism"~"^(attraction|museum|gallery|viewpoint|monument|memorial|artwork|castle|ruins|information|hotel|hostel)$"](around:{radius},{lat},{lon});
      node["historic"~"^(monument|memorial|castle|ruins|archaeological_site|building|manor|palace|city_gate|fort|tower)$"](around:{radius},{lat},{lon});
      node["amenity"~"^(museum|gallery|theatre|arts_centre|library|university|school|place_of_worship|restaurant|cafe|bar|pub)$"](around:{radius},{lat},{lon});
      node["leisure"~"^(park|garden|playground|sports_centre|stadium)$"](around:{radius},{lat},{lon});
      node["shop"~"^(books|art|antiques|gift|souvenir)$"](around:{radius},{lat},{lon});
      way["tourism"~"^(attraction|museum|gallery|viewpoint|monument|memorial|artwork|castle|ruins)$"](around:{radius},{lat},{lon});
      way["historic"~"^(monument|memorial|castle|ruins|archaeological_site|building|manor|palace|city_gate|fort|tower)$"](around:{radius},{lat},{lon});
      way["amenity"~"^(museum|gallery|theatre|arts_centre|library|university|place_of_worship)$"](around:{radius},{lat},{lon});
      way["leisure"~"^(park|garden|sports_centre|stadium)$"](around:{radius},{lat},{lon});
    );
    out center meta;
    """
    
    try:
        response = requests.post(overpass_url, data=overpass_query, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        places = []
        seen_names = set()  # Avoid duplicates
        
        for element in data.get("elements", []):
            # Extract coordinates
            if element["type"] == "node":
                place_lat, place_lon = element["lat"], element["lon"]
            elif element["type"] == "way" and "center" in element:
                place_lat, place_lon = element["center"]["lat"], element["center"]["lon"]
            else:
                continue
                
            tags = element.get("tags", {})
            name = _get_best_name(tags, lang)
            
            # Skip if no name or duplicate
            if not name or name == "Unknown Place" or name in seen_names:
                continue
                
            seen_names.add(name)
            distance = _calculate_distance(lat, lon, place_lat, place_lon)
            
            if distance > radius:
                continue
                
            # Determine category
            category = "Point of Interest"
            if tags.get("tourism"):
                category = f"Tourism: {tags['tourism'].title()}"
            elif tags.get("historic"):
                category = f"Historic: {tags['historic'].title()}"
            elif tags.get("amenity"):
                category = f"Amenity: {tags['amenity'].title()}"
            elif tags.get("leisure"):
                category = f"Leisure: {tags['leisure'].title()}"
                
            place = {
                "name": name,
                "description": tags.get("description", ""),
                "address": _format_address(tags),
                "latitude": place_lat,
                "longitude": place_lon,
                "distance": distance,
                "source": "openstreetmap",
                "category": category,
                "wikipedia": tags.get("wikipedia", ""),
                "wikidata": tags.get("wikidata", "")
            }
            places.append(place)
        
        # Sort by distance and return more results for 10km search
        return sorted(places, key=lambda x: x["distance"])[:30]
        
    except Exception as e:
        logger.error(f"OSM Overpass API error: {e}")
        return []


def _get_nominatim_places(lat: float, lon: float, radius: int, lang: str = "en") -> List[Dict[Any, Any]]:
    """
    Use Nominatim reverse geocoding to find nearby places.
    """
    base_url = "https://nominatim.openstreetmap.org/reverse"
    
    # Search in expanding circles
    places = []
    seen_names = set()
    
    # Try multiple radius points
    search_points = [
        (lat, lon),  # Exact location
        (lat + 0.001, lon),  # ~100m north
        (lat - 0.001, lon),  # ~100m south
        (lat, lon + 0.001),  # ~100m east
        (lat, lon - 0.001),  # ~100m west
        (lat + 0.002, lon + 0.002),  # ~200m northeast
        (lat - 0.002, lon - 0.002),  # ~200m southwest
    ]
    
    for search_lat, search_lon in search_points:
        try:
            params = {
                "lat": search_lat,
                "lon": search_lon,
                "format": "json",
                "addressdetails": 1,
                "extratags": 1,
                "namedetails": 1,
                "zoom": 18,  # High detail level
                "accept-language": lang
            }
            
            response = requests.get(base_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if not data or "display_name" not in data:
                continue
                
            # Extract place info
            name = data.get("name") or data.get("display_name", "").split(",")[0]
            if not name or name in seen_names or len(name) < 3:
                continue
                
            seen_names.add(name)
            distance = _calculate_distance(lat, lon, float(data["lat"]), float(data["lon"]))
            
            if distance > radius:
                continue
                
            place = {
                "name": name,
                "description": data.get("type", "").replace("_", " ").title(),
                "address": data.get("display_name", ""),
                "latitude": float(data["lat"]),
                "longitude": float(data["lon"]),
                "distance": distance,
                "source": "nominatim",
                "category": data.get("category", "place").title()
            }
            places.append(place)
            
        except Exception as e:
            logger.warning(f"Nominatim search failed for {search_lat}, {search_lon}: {e}")
            continue
    
    return sorted(places, key=lambda x: x["distance"])[:10]


def _get_wikipedia_places(lat: float, lon: float, radius: int, lang: str = "en") -> List[Dict[Any, Any]]:
    """
    Use Wikipedia geosearch as last resort.
    """
    wiki_lang = "en" if lang == "en" else "ru"
    url = f"https://{wiki_lang}.wikipedia.org/w/api.php"
    
    params = {
        "action": "query",
        "list": "geosearch",
        "gscoord": f"{lat}|{lon}",
        "gsradius": min(radius, 10000),  # Wikipedia max is 10km
        "gslimit": 20,
        "format": "json"
    }
    
    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        places = []
        for page in data.get("query", {}).get("geosearch", []):
            distance = page.get("dist", 0)
            if distance > radius:
                continue
                
            place = {
                "name": page.get("title", "Unknown Place"),
                "description": "Wikipedia Article",
                "address": f"~{distance}m away",
                "latitude": page.get("lat", lat),
                "longitude": page.get("lon", lon),
                "distance": distance,
                "source": "wikipedia",
                "category": "Encyclopedia Entry",
                "wikipedia_title": page.get("title", "")
            }
            places.append(place)
        
        return sorted(places, key=lambda x: x["distance"])[:8]
        
    except Exception as e:
        logger.error(f"Wikipedia geosearch failed: {e}")
        return []


def _remove_duplicate_places(places: List[Dict[Any, Any]]) -> List[Dict[Any, Any]]:
    """
    Remove duplicate places based on name similarity and proximity (within 50m).
    """
    if not places:
        return []
    
    unique_places = []
    seen_names = set()
    
    for place in places:
        name = place.get("name", "").lower().strip()
        lat = place.get("latitude", 0)
        lon = place.get("longitude", 0)
        
        # Skip if no name
        if not name or len(name) < 2:
            continue
            
        # Check for exact name duplicates
        if name in seen_names:
            continue
            
        # Check for proximity duplicates (within 50m)
        is_duplicate = False
        for existing_place in unique_places:
            existing_lat = existing_place.get("latitude", 0)
            existing_lon = existing_place.get("longitude", 0)
            
            # Calculate distance between places
            distance = _calculate_distance(lat, lon, existing_lat, existing_lon)
            
            # If within 50m and similar names, consider duplicate
            if distance < 50:
                existing_name = existing_place.get("name", "").lower().strip()
                # Check if names are similar (one contains the other or very similar)
                if (name in existing_name or existing_name in name or 
                    _names_are_similar(name, existing_name)):
                    is_duplicate = True
                    break
        
        if not is_duplicate:
            unique_places.append(place)
            seen_names.add(name)
    
    return unique_places


def _names_are_similar(name1: str, name2: str) -> bool:
    """
    Check if two place names are similar enough to be considered duplicates.
    """
    # Remove common words and punctuation
    import re
    
    def clean_name(name):
        # Remove common words and normalize
        common_words = {'the', 'of', 'and', 'church', 'museum', 'park', 'street', 'square'}
        words = re.findall(r'\w+', name.lower())
        return ' '.join([w for w in words if w not in common_words])
    
    clean1 = clean_name(name1)
    clean2 = clean_name(name2)
    
    if not clean1 or not clean2:
        return False
    
    # Check if one is contained in the other
    if clean1 in clean2 or clean2 in clean1:
        return True
    
    # Check for high similarity (simple word overlap)
    words1 = set(clean1.split())
    words2 = set(clean2.split())
    
    if len(words1) == 0 or len(words2) == 0:
        return False
    
    overlap = len(words1.intersection(words2))
    total_unique = len(words1.union(words2))
    
    # If more than 60% overlap, consider similar
    similarity = overlap / total_unique if total_unique > 0 else 0
    return similarity > 0.6


def _format_address(tags: dict) -> str:
    """
    Format address from OSM tags.
    """
    address_parts = []
    for key in ["addr:housenumber", "addr:street", "addr:city", "addr:country"]:
        if tags.get(key):
            address_parts.append(tags[key])
    return ", ".join(address_parts) if address_parts else ""


def _get_osm_places(lat: float, lon: float, radius: int) -> List[Dict[Any, Any]]:
    """
    Query OpenStreetMap Overpass API for nearby points of interest.
    """
    overpass_url = "http://overpass-api.de/api/interpreter"
    
    # Overpass QL query for tourism, historic sites, museums, and cultural venues
    # Focus on visually accessible landmarks within walking distance
    overpass_query = f"""
    [out:json][timeout:25];
    (
      node["tourism"~"^(attraction|museum|gallery|viewpoint|monument|memorial|artwork|castle|ruins)$"](around:{radius},{lat},{lon});
      node["historic"~"^(monument|memorial|castle|ruins|archaeological_site|building|manor|palace)$"](around:{radius},{lat},{lon});
      node["amenity"~"^(museum|gallery|theatre|arts_centre|library)$"](around:{radius},{lat},{lon});
      way["tourism"~"^(attraction|museum|gallery|viewpoint|monument|memorial|artwork|castle|ruins)$"](around:{radius},{lat},{lon});
      way["historic"~"^(monument|memorial|castle|ruins|archaeological_site|building|manor|palace)$"](around:{radius},{lat},{lon});
      way["amenity"~"^(museum|gallery|theatre|arts_centre|library)$"](around:{radius},{lat},{lon});
    );
    out center meta;
    """
    
    try:
        response = requests.post(overpass_url, data=overpass_query, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        places = []
        for element in data.get("elements", []):
            # Extract coordinates (handle both nodes and ways)
            if element["type"] == "node":
                place_lat, place_lon = element["lat"], element["lon"]
            elif element["type"] == "way" and "center" in element:
                place_lat, place_lon = element["center"]["lat"], element["center"]["lon"]
            else:
                continue
                
            tags = element.get("tags", {})
            
            # Get the best name in user's preferred language
            name = _get_best_name(tags, "en")  # Default to English, will be updated based on user language
            
            # Skip if no usable name
            if not name or name == "Unknown Place":
                continue
                
            # Calculate distance
            distance = _calculate_distance(lat, lon, place_lat, place_lon)
            
            # Focus on closer landmarks that are visually accessible (within 300m for better relevance)
            if distance > 300:
                continue
                
            place = {
                "name": name,
                "name_en": tags.get("name:en", name),
                "name_ru": tags.get("name:ru", name),
                "description": tags.get("description", ""),
                "tourism": tags.get("tourism", ""),
                "historic": tags.get("historic", ""),
                "amenity": tags.get("amenity", ""),
                "wikipedia": tags.get("wikipedia", ""),
                "wikidata": tags.get("wikidata", ""),
                "website": tags.get("website", ""),
                "coordinates": [place_lon, place_lat],
                "distance": distance,
                "inscription_en": tags.get("inscription:en", ""),
                "inscription_ru": tags.get("inscription:ru", ""),
                "memorial_subject": tags.get("memorial:subject", ""),
                "start_date": tags.get("start_date", ""),
                "material": tags.get("material", "")
            }
            places.append(place)
            
        # Sort by distance and relevance (prioritize closer places and those with Wikipedia info)
        places.sort(key=lambda x: (x["distance"], not bool(x["wikipedia"] or x["wikidata"])))
        logger.info(f"Found {len(places)} visually accessible POIs from OpenStreetMap")
        return places
        
    except Exception as e:
        logger.error(f"Error fetching places from OpenStreetMap: {e}")
        return []


def _get_best_name(tags: dict, preferred_lang: str = "en") -> str:
    """
    Get the best name for a place based on user's language preference.
    Priority: name:en/name:ru > inscription:en/inscription:ru > name > fallback
    """
    # Priority 1: Localized name in preferred language
    if preferred_lang == "ru" and tags.get("name:ru"):
        return tags["name:ru"]
    elif preferred_lang == "en" and tags.get("name:en"):
        return tags["name:en"]
    
    # Priority 2: Inscription in preferred language (for monuments/memorials)
    if preferred_lang == "ru" and tags.get("inscription:ru"):
        return tags["inscription:ru"]
    elif preferred_lang == "en" and tags.get("inscription:en"):
        return tags["inscription:en"]
    
    # Priority 3: Try the other language if preferred not available
    if preferred_lang == "ru" and tags.get("name:en"):
        return tags["name:en"]
    elif preferred_lang == "en" and tags.get("name:ru"):
        return tags["name:ru"]
    
    # Priority 4: Try inscriptions in other language
    if preferred_lang == "ru" and tags.get("inscription:en"):
        return tags["inscription:en"]
    elif preferred_lang == "en" and tags.get("inscription:ru"):
        return tags["inscription:ru"]
    
    # Priority 5: Default name (might be in local language)
    if tags.get("name"):
        name = tags["name"]
        # If it contains non-Latin characters and we prefer English, mark it for translation
        import re
        if preferred_lang == "en" and re.search(r'[^\x00-\x7F]', name):
            # Contains non-ASCII characters, might need translation
            return name  # Will be handled by AI translation in the overview
        return name
    
    # Fallback
    return "Unknown Place"


def _enrich_with_wikipedia(place: Dict[Any, Any], lang: str = "en") -> Dict[Any, Any]:
    """
    Enrich place data with Wikipedia information.
    """
    wikipedia_info = None
    
    # Try to get Wikipedia info from existing tags first
    if place.get("wikipedia"):
        wikipedia_info = _get_wikipedia_content(place["wikipedia"], lang)
    elif place.get("wikidata"):
        wikipedia_info = _get_wikipedia_from_wikidata(place["wikidata"], lang)
    else:
        # Search Wikipedia by name and coordinates
        wikipedia_info = _search_wikipedia_by_location(
            place["name"], place["coordinates"][1], place["coordinates"][0], lang
        )
    
    if wikipedia_info:
        place["wikipedia_title"] = wikipedia_info.get("title", "")
        place["wikipedia_extract"] = wikipedia_info.get("extract", "")
        place["wikipedia_url"] = wikipedia_info.get("url", "")
        
    return place


def _get_wikipedia_content(wikipedia_tag: str, lang: str = "en") -> Optional[Dict[str, str]]:
    """
    Get Wikipedia content from wikipedia tag (format: "lang:title").
    """
    try:
        if ":" in wikipedia_tag:
            wiki_lang, title = wikipedia_tag.split(":", 1)
        else:
            wiki_lang, title = lang, wikipedia_tag
            
        url = f"https://{wiki_lang}.wikipedia.org/w/api.php"
        params = {
            "action": "query",
            "format": "json",
            "titles": title,
            "prop": "extracts",
            "exintro": True,
            "explaintext": True,
            "exsectionformat": "plain",
            "exchars": 300  # Limit to 300 characters
        }
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if "query" in data and "pages" in data["query"]:
            pages = data["query"]["pages"]
            for page_id, page_data in pages.items():
                if page_id != "-1":  # Page exists
                    extract = page_data.get("extract", "")
                    if extract:
                        return {
                            "title": page_data.get("title", title),
                            "extract": extract,
                            "url": f"https://{lang}.wikipedia.org/wiki/{title.replace(' ', '_')}"
                        }
                        
    except Exception as e:
        logger.warning(f"Failed to get Wikipedia content for {wikipedia_tag}: {e}")
        return None


def _get_wikipedia_from_wikidata(wikidata_id: str, lang: str = "en") -> Optional[Dict[str, str]]:
    """
    Get Wikipedia article from Wikidata ID.
    """
    try:
        # Get Wikipedia title from Wikidata
        sparql_url = "https://query.wikidata.org/sparql"
        query = f"""
        SELECT ?article WHERE {{
          wd:{wikidata_id} schema:about ?article .
          ?article schema:isPartOf <https://{lang}.wikipedia.org/> .
        }}
        """
        
        response = requests.get(sparql_url, params={"query": query, "format": "json"}, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if data["results"]["bindings"]:
            article_url = data["results"]["bindings"][0]["article"]["value"]
            title = article_url.split("/")[-1]
            return _get_wikipedia_content(f"{lang}:{title}", lang)
            
    except Exception as e:
        logger.warning(f"Failed to get Wikipedia from Wikidata {wikidata_id}: {e}")
        
    return None


def _search_wikipedia_by_location(name: str, lat: float, lon: float, lang: str = "en") -> Optional[Dict[str, str]]:
    """
    Search Wikipedia articles near given coordinates using the standard Wikipedia API.
    """
    try:
        # Use the standard Wikipedia API with geosearch
        url = f"https://{lang}.wikipedia.org/w/api.php"
        params = {
            "action": "query",
            "format": "json",
            "list": "geosearch",
            "gscoord": f"{lat}|{lon}",
            "gsradius": 1000,  # 1km radius
            "gslimit": 10,
            "gsnamespace": 0  # Main namespace only
        }
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if "query" in data and "geosearch" in data["query"]:
            pages = data["query"]["geosearch"]
            
            # Look for articles with similar names first
            for page in pages:
                page_title = page.get("title", "")
                if name.lower() in page_title.lower() or page_title.lower() in name.lower():
                    return _get_wikipedia_summary(page_title, lang)
            
            # If no exact match, try the closest article
            if pages:
                closest_page = pages[0]
                return _get_wikipedia_summary(closest_page.get("title", ""), lang)
                
    except Exception as e:
        logger.warning(f"Failed to search Wikipedia by location for {name}: {e}")
        
    # Fallback: try searching by name only
    try:
        return _search_wikipedia_by_name(name, lang)
    except Exception as e:
        logger.warning(f"Failed to search Wikipedia by name for {name}: {e}")
        
    return None


def _search_wikipedia_by_name(name: str, lang: str = "en") -> Optional[Dict[str, str]]:
    """
    Search Wikipedia by article name using the standard API.
    """
    try:
        url = f"https://{lang}.wikipedia.org/w/api.php"
        params = {
            "action": "query",
            "format": "json",
            "list": "search",
            "srsearch": name,
            "srlimit": 3,
            "srnamespace": 0
        }
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if "query" in data and "search" in data["query"]:
            search_results = data["query"]["search"]
            if search_results:
                # Get the first result
                first_result = search_results[0]
                return _get_wikipedia_summary(first_result.get("title", ""), lang)
                
    except Exception as e:
        logger.warning(f"Failed to search Wikipedia by name for {name}: {e}")
        
    return None


def _get_wikipedia_summary(title: str, lang: str = "en") -> Optional[Dict[str, str]]:
    """
    Get Wikipedia article summary using the standard API.
    """
    if not title:
        return None
        
    try:
        url = f"https://{lang}.wikipedia.org/w/api.php"
        params = {
            "action": "query",
            "format": "json",
            "titles": title,
            "prop": "extracts",
            "exintro": True,
            "explaintext": True,
            "exsectionformat": "plain",
            "exchars": 300  # Limit to 300 characters
        }
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if "query" in data and "pages" in data["query"]:
            pages = data["query"]["pages"]
            for page_id, page_data in pages.items():
                if page_id != "-1":  # Page exists
                    extract = page_data.get("extract", "")
                    if extract:
                        return {
                            "title": page_data.get("title", title),
                            "extract": extract,
                            "url": f"https://{lang}.wikipedia.org/wiki/{title.replace(' ', '_')}"
                        }
                        
    except Exception as e:
        logger.warning(f"Failed to get Wikipedia summary for {title}: {e}")
        
    return None


def _calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate approximate distance between two points in meters using Haversine formula.
    """
    import math
    
    R = 6371000  # Earth's radius in meters
    
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    
    a = (math.sin(delta_lat / 2) ** 2 + 
         math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c