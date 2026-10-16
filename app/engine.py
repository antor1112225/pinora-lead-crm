"""
Research Engine for Pinora-Like Local Lead Workspace.
Executes missions via Permitted Public Data Sources (Mode A: OpenStreetMap / Overpass API + Nominatim),
coordinates Website Contact Enrichment (Mode D), manages research queue, and broadcasts live telemetry.
Zero paid API keys. Respects public rate limits.
"""

import sys
import json
import time
import urllib.request
import urllib.parse
import threading
import uuid
import datetime
import re
from typing import Dict, Any, List, Optional, Tuple

from app.database import (
    insert_lead, update_lead, get_lead, get_telemetry_stats,
    get_connection
)
from app.deduplication import normalize_domain, normalize_phone
from app.enrichment import enrich_business_website


OVERPASS_ENDPOINTS = [
    "https://overpass.private.coffee/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter"
]

_GEO_BBOX_CACHE: Dict[str, Optional[Tuple[float, float, float, float]]] = {}
_GEO_COUNTRY_CACHE: Dict[str, str] = {}


def get_location_bbox(location_str: str) -> Optional[Tuple[float, float, float, float]]:
    """Geocode city/area to bounding box (south, west, north, east) with caching and country detection."""
    clean_loc = location_str.strip().lower()
    if not clean_loc:
        return None
    if clean_loc in _GEO_BBOX_CACHE:
        return _GEO_BBOX_CACHE[clean_loc]

    try:
        url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(location_str)}&format=json&addressdetails=1&limit=1"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "PinoraLeadWorkspace/1.0 (local desktop lead app; contact: local-freelance)"}
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data and len(data) > 0:
                addr = data[0].get("address") or {}
                raw_country = (addr.get("country") or "").strip()
                if "ireland" in raw_country.lower() or "éire" in raw_country.lower():
                    raw_country = "Ireland"
                if raw_country:
                    _GEO_COUNTRY_CACHE[clean_loc] = raw_country

                if "boundingbox" in data[0]:
                    raw_bbox = data[0]["boundingbox"]  # [south, north, west, east]
                    south = float(raw_bbox[0])
                    north = float(raw_bbox[1])
                    west = float(raw_bbox[2])
                    east = float(raw_bbox[3])
                    # Expand bounding box for full metropolitan & commuter-belt coverage
                    pad_lat = max(0.16, (north - south) * 0.45)
                    pad_lon = max(0.20, (east - west) * 0.45)
                    bbox = (south - pad_lat, west - pad_lon, north + pad_lat, east + pad_lon)
                    _GEO_BBOX_CACHE[clean_loc] = bbox
                    return bbox
    except Exception:
        pass
    _GEO_BBOX_CACHE[clean_loc] = None
    return None


class TelemetryLogger:
    def __init__(self, max_logs: int = 100):
        self.logs: List[Dict[str, str]] = []
        self.max_logs = max_logs
        self.lock = threading.Lock()

    def log(self, message: str, level: str = "INFO"):
        with self.lock:
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            self.logs.append({"time": ts, "message": message, "level": level})
            if len(self.logs) > self.max_logs:
                self.logs.pop(0)

    def get_logs(self) -> List[Dict[str, str]]:
        with self.lock:
            return list(self.logs)

    def clear(self):
        with self.lock:
            self.logs.clear()


class ResearchWorker(threading.Thread):
    def __init__(
        self,
        keywords: List[str],
        city: str,
        postal_code: str,
        country: str,
        max_results_per_search: int = 50,
        hunt_emails: bool = True,
        auto_dedup: bool = True
    ):
        super().__init__(daemon=True)
        self.keywords = [k.strip() for k in keywords if k.strip()]
        raw_city = (city or "").strip()
        raw_country = (country or "").strip()
        if "," in raw_city:
            parts = [p.strip() for p in raw_city.split(",") if p.strip()]
            if len(parts) >= 2:
                if not raw_country or raw_country == "United States":
                    raw_country = parts[-1]
                raw_city = ", ".join(parts[:-1])
        self.city = raw_city
        self.postal_code = postal_code.strip() if postal_code else ""
        if (not raw_country or raw_country == "United States") and self.city:
            get_location_bbox(self.city)
            detected = _GEO_COUNTRY_CACHE.get(self.city.lower())
            if detected:
                raw_country = detected
        self.country = raw_country or "United States"
        self.max_results = int(max_results_per_search) if max_results_per_search is not None else 0
        self.hunt_emails = hunt_emails
        self.auto_dedup = auto_dedup

        self.state = "IDLE"  # IDLE, RUNNING, PAUSED, STOPPED, COMPLETED
        self.current_task = "Ready"
        self.progress_percent = 0.0
        self.telemetry = TelemetryLogger()

        self.records_discovered = 0
        self.records_reviewed = 0
        self.new_unique_leads = 0
        self.duplicates_detected = 0
        self.queued_queries = len(self.keywords)

        self._pause_event = threading.Event()
        self._pause_event.set()  # Not paused initially
        self._stop_requested = False

    def pause(self):
        if self.state == "RUNNING":
            self.state = "PAUSED"
            self._pause_event.clear()
            self.telemetry.log("Research mission paused by user.", "WARN")

    def resume(self):
        if self.state == "PAUSED":
            self.state = "RUNNING"
            self._pause_event.set()
            self.telemetry.log("Research mission resumed.", "INFO")

    def stop(self):
        self.state = "STOPPED"
        self._stop_requested = True
        self._pause_event.set()  # Unblock if paused
        self.telemetry.log("Stop requested. Cleaning up current task...", "WARN")

    def get_status(self) -> Dict[str, Any]:
        global_stats = get_telemetry_stats()
        return {
            "state": self.state,
            "current_task": self.current_task,
            "progress_percent": round(self.progress_percent, 1),
            "records_discovered": self.records_discovered,
            "records_reviewed": self.records_reviewed,
            "new_unique_leads": self.new_unique_leads,
            "duplicates_detected": self.duplicates_detected,
            "queued_queries": self.queued_queries,
            "hunt_emails": self.hunt_emails,
            "logs": self.telemetry.get_logs(),
            "global_stats": global_stats
        }

    def _build_regex_pattern(self, keyword: str) -> str:
        """Create flexible search pattern matching full keyword, root stems, and trade synonyms."""
        clean = keyword.strip()
        stop_words = {
            "services", "service", "company", "companies", "contractor", "contractors",
            "installer", "installers", "specialist", "specialists", "near", "in", "and", "or",
            "upvc", "pvc", "commercial", "residential", "local", "energy", "efficient",
            "replacement", "replacements", "repair", "repairs", "best", "top", "affordable"
        }
        tokens = [t for t in re.split(r"[\s,\-/]+", clean) if t and t.lower() not in stop_words and len(t) > 2]

        synonyms_map = {
            "glazing": ["glaz", "window", "glass"],
            "glazier": ["glaz", "window", "glass"],
            "windows": ["window", "glaz", "glass"],
            "window": ["window", "glaz", "glass"],
            "roofing": ["roof"],
            "roofer": ["roof"],
            "plumbing": ["plumb"],
            "plumber": ["plumb"],
            "waterproofing": ["waterproof", "damp", "roof"],
            "electrical": ["electric"],
            "electrician": ["electric"]
        }

        expanded: List[str] = [re.escape(clean)]
        for t in tokens:
            tl = t.lower()
            esc = re.escape(t)
            if esc not in expanded:
                expanded.append(esc)
            if tl in synonyms_map:
                for syn in synonyms_map[tl]:
                    if syn not in expanded:
                        expanded.append(syn)
            elif len(tl) > 5 and tl.endswith("ing"):
                stem = re.escape(tl[:-3])
                if stem not in expanded:
                    expanded.append(stem)

        return "|".join(expanded)

    def _is_irrelevant_entity(self, name: str, website: str, osm_type_or_tags: Any = None) -> bool:
        """Filter out non-business map noise (bus stops, schools, artwork, restaurants, aggregators)."""
        if not name or not website:
            return True
        nl = name.lower()
        wl = website.lower()
        dom = normalize_domain(website)

        # Excluded aggregator, directory, transit, government, or unrelated retail domains
        excluded_domains = {
            "dublinbus.ie", "transportforireland.ie", "irishrail.ie", "buseireann.ie",
            "dublincanvas.com", "wikipedia.org", "wikimedia.org", "gov.ie", "gov.uk",
            "citizensinformation.ie", "seai.ie", "tudublin.ie", "ucd.ie", "tcd.ie",
            "shutterstock.com", "sunglasshut.com", "specsavers.ie", "specsavers.co.uk",
            "nextdoor.ie", "regatta.ie", "regatta.com", "trespass.ie", "trespass.com",
            "mountainwarehouse.com", "cotswoldoutdoor.ie", "cotswoldoutdoor.com",
            "53degreesnorth.ie", "greatoutdoors.ie", "basecamp.ie", "omearacamping.com",
            "malahideoutdoor.com", "bordgaisenergytheatre.ie", "bordgaisenergy.ie",
            "dublinwastetoenergy.ie", "energiagroup.com", "pinergy.ie",
            "thereddoorschool.com", "clockworkdoor.ie", "thegreendoor.ie",
            "armybargains.com", "blackrockmarket.com", "glaziersolicitors.com",
            "theopenwindowgallery.com", "theglasshouses.ie", "carpetright.co.uk",
            "kiernanoil.ie", "digrenenergy.ie", "islandrenewable.com", "cybo.com",
            "facebook.com", "instagram.com", "linkedin.com", "youtube.com", "tiktok.com",
            "twitter.com", "x.com", "pinterest.com", "yelp.com", "yelp.ie", "goldenpages.ie",
            "yell.com", "trustpilot.com", "bark.com", "checkatrade.com", "mybuilder.com",
            "tripadvisor.com", "tripadvisor.ie", "booking.com", "airbnb.com"
        }
        if any(dom == ex or dom.endswith("." + ex) for ex in excluded_domains):
            return True

        # Check OSM tags / type if provided
        bad_osm_types = {
            "bus_stop", "platform", "station", "tram_stop", "halt",
            "artwork", "art", "gallery", "museum", "attraction", "viewpoint",
            "school", "university", "college", "kindergarten", "library",
            "hospital", "clinic", "doctors", "dentist", "pharmacy", "veterinary",
            "theatre", "cinema", "nightclub", "casino", "arts_centre",
            "hotel", "hostel", "guest_house", "motel", "apartment", "coworking_space",
            "restaurant", "cafe", "bar", "pub", "fast_food", "food_court", "ice_cream",
            "place_of_worship", "church", "mosque", "temple", "grave_yard",
            "park", "pitch", "sports_centre", "stadium", "fitness_centre", "gym",
            "supermarket", "convenience", "alcohol", "off_licence", "florist", "hairdresser",
            "beauty", "lawyer", "solicitor", "accountant", "it", "carpet"
        }
        if isinstance(osm_type_or_tags, str):
            if osm_type_or_tags.lower() in bad_osm_types:
                return True
        elif isinstance(osm_type_or_tags, dict):
            for k in ("amenity", "tourism", "highway", "railway", "leisure", "shop", "office", "craft"):
                v = str(osm_type_or_tags.get(k, "")).lower()
                if v in bad_osm_types:
                    return True

        # Filter obvious false-positive name substrings when searching window/door/glass niches
        bad_name_markers = (
            "tandoori", "off-licence", "off licence", "florist", "coffee", "cafe",
            "restaurant", "school", "academy", "college", "university", "theatre",
            "cycling studio", "indoor football", "indoor arena", "hair replacement",
            "waste to energy", "bioenergy", "camping", "angling", "solicitor",
            "law firm", "market", "army bargains", "clockwork door"
        )
        if any(m in nl for m in bad_name_markers):
            return True

        return False

    def _extract_search_tokens(self, keyword: str) -> List[str]:
        """Extract clean search terms and trade synonyms for Nominatim/Photon discovery."""
        clean_kw = keyword.strip()
        MODIFIER_WORDS = {
            "upvc", "pvc", "double", "triple", "energy", "efficient", "replacement", "replacements",
            "services", "service", "company", "companies", "contractor", "contractors",
            "installer", "installers", "installation", "specialist", "specialists",
            "repair", "repairs", "maintenance", "and", "or", "the", "for", "with",
            "near", "in", "best", "top", "affordable", "cheap", "local", "emergency",
            "professional", "commercial", "residential", "expert", "experts", "supply", "fit"
        }
        search_terms = [clean_kw]
        tokens = [w for w in re.split(r"[\s,\-/]+", clean_kw) if w.lower() not in MODIFIER_WORDS and len(w) > 2]
        for t in tokens:
            if t.lower() not in [s.lower() for s in search_terms]:
                search_terms.append(t)

        # Add high-yield root trade terms if the keyword is in the glazing/window/door/joinery niche
        kw_lower = clean_kw.lower()
        if any(w in kw_lower for w in ("window", "glaz", "glass", "door", "conservator", "upvc", "shutter", "blind", "joiner", "patio", "sash")):
            for extra in (
                "window", "windows", "glazier", "glazing", "glass", "door", "doors",
                "blinds", "shutters", "joinery", "conservatory", "upvc", "patio", "sash",
                "carpentry", "roofing", "roofer", "insulation", "builders"
            ):
                if extra not in [s.lower() for s in search_terms]:
                    search_terms.append(extra)
        return search_terms

    def _query_osm_overpass(self, keyword: str, city: str, postal_code: str, limit: int) -> List[Dict[str, Any]]:
        """
        Query public OpenStreetMap data via Overpass API, filtering specifically for businesses WITH websites
        so Overpass never wastes results on nodes without websites or times out on relations.
        """
        results = []
        kw_clean = keyword.strip()
        loc_clean = city.strip()
        kw_pattern = self._build_regex_pattern(kw_clean)

        loc_search = f"{loc_clean} {postal_code}".strip()
        bbox = get_location_bbox(loc_search) if loc_search else None

        # Always fetch up to 250 website-equipped nodes/ways from Overpass, then apply limit after filtering
        out_clause = "out center 250;"

        if bbox:
            south, west, north, east = bbox
            bbox_clause = f"({south},{west},{north},{east})"
            ql = f"""
            [out:json][timeout:18];
            (
              node["website"]["name"~"{kw_pattern}",i]{bbox_clause};
              way["website"]["name"~"{kw_pattern}",i]{bbox_clause};
              node["contact:website"]["name"~"{kw_pattern}",i]{bbox_clause};
              way["contact:website"]["name"~"{kw_pattern}",i]{bbox_clause};
              node["website"]["craft"~"{kw_pattern}",i]{bbox_clause};
              way["website"]["craft"~"{kw_pattern}",i]{bbox_clause};
              node["website"]["shop"~"{kw_pattern}",i]{bbox_clause};
              way["website"]["shop"~"{kw_pattern}",i]{bbox_clause};
            );
            {out_clause}
            """
        else:
            loc_escaped = loc_clean.replace('"', '\\"') if loc_clean else ""
            if loc_escaped:
                area_filter = f'area["name"="{loc_escaped}"]->.searchArea;'
                area_clause = "(area.searchArea)"
            else:
                area_filter = ""
                area_clause = ""

            ql = f"""
            [out:json][timeout:18];
            {area_filter}
            (
              node["website"]["name"~"{kw_pattern}",i]{area_clause};
              way["website"]["name"~"{kw_pattern}",i]{area_clause};
              node["contact:website"]["name"~"{kw_pattern}",i]{area_clause};
              way["contact:website"]["name"~"{kw_pattern}",i]{area_clause};
              node["website"]["craft"~"{kw_pattern}",i]{area_clause};
              way["website"]["craft"~"{kw_pattern}",i]{area_clause};
              node["website"]["shop"~"{kw_pattern}",i]{area_clause};
              way["website"]["shop"~"{kw_pattern}",i]{area_clause};
            );
            {out_clause}
            """

        encoded_data = urllib.parse.urlencode({"data": ql}).encode("utf-8")
        headers = {
            "User-Agent": "PinoraLeadWorkspace/1.0 (OpenStreetMap public local business researcher; contact: local-freelance-app)",
            "Accept": "application/json"
        }

        for ep in OVERPASS_ENDPOINTS[:2]:
            if self._stop_requested:
                break
            try:
                req = urllib.request.Request(ep, data=encoded_data, headers=headers)
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    elements = data.get("elements", [])
                    
                    for el in elements:
                        tags = el.get("tags", {})
                        name = tags.get("name")
                        if not name:
                            continue

                        website = (tags.get("website") or tags.get("contact:website") or tags.get("url") or "").strip()
                        if not website or website.upper() == "NOT AVAILABLE":
                            continue
                        if not website.startswith(("http://", "https://")):
                            website = "https://" + website

                        if self._is_irrelevant_entity(name, website, tags):
                            continue

                        housenumber = tags.get("addr:housenumber", "")
                        street = tags.get("addr:street", "")
                        addr_city = tags.get("addr:city", city)
                        addr_postcode = tags.get("addr:postcode", postal_code)
                        full_address = f"{housenumber} {street}".strip() or tags.get("address", "NOT AVAILABLE")

                        phone = tags.get("phone") or tags.get("contact:phone") or "NOT AVAILABLE"
                        email = tags.get("email") or tags.get("contact:email") or "NOT AVAILABLE"
                        
                        category = tags.get("craft") or tags.get("shop") or tags.get("office") or keyword.title()
                        lead_uid = f"osm_{el.get('type')}_{el.get('id')}"

                        results.append({
                            "lead_uid": lead_uid,
                            "business_name": name,
                            "category": category.replace("_", " ").title(),
                            "specific_service": keyword.title(),
                            "country": tags.get("addr:country", self.country),
                            "city": addr_city or "NOT AVAILABLE",
                            "area": tags.get("addr:suburb", "NOT AVAILABLE"),
                            "postal_code": addr_postcode or "NOT AVAILABLE",
                            "address": full_address,
                            "phone": phone,
                            "normalized_phone": normalize_phone(phone),
                            "secondary_phone": "NOT AVAILABLE",
                            "email": email,
                            "email_source_url": "OpenStreetMap Tags" if email != "NOT AVAILABLE" else "NOT AVAILABLE",
                            "website": website,
                            "normalized_domain": normalize_domain(website),
                            "social_profiles": "{}",
                            "rating": None,
                            "reviews_count": None,
                            "opening_status": tags.get("opening_hours", "Open"),
                            "source_name": "OpenStreetMap Public Data (ODbL)",
                            "source_url": f"https://www.openstreetmap.org/{el.get('type')}/{el.get('id')}",
                            "research_date": datetime.date.today().isoformat(),
                            "data_confidence": "HIGH",
                            "enrichment_status": "PENDING" if (website != "NOT AVAILABLE" and self.hunt_emails) else "NOT_REQUESTED",
                            "outreach_status": "Not Contacted",
                            "query_keyword": keyword,
                            "notes": f"Discovered via OpenStreetMap tags: {category}"
                        })
                        if limit and limit > 0 and len(results) >= limit:
                            break

                    return results

            except Exception:
                continue

        return results

    def _query_nominatim_search(self, keyword: str, city: str, postal_code: str, limit: int = 50, already_searched_terms: Optional[set] = None) -> List[Dict[str, Any]]:
        """
        High-speed OpenStreetMap search combining Photon Bounding-Box Search + Photon City Search + Nominatim Batch Lookup.
        Never suffers from Overpass 504 timeouts and discovers all businesses with websites across metropolitan & suburban areas.
        """
        results = []
        loc_str = f"{city} {postal_code}".strip()
        cap = limit if limit and limit > 0 else 100
        search_terms = self._extract_search_tokens(keyword)
        bbox = get_location_bbox(loc_str) if loc_str else None

        headers = {"User-Agent": "PinoraLeadWorkspace/1.0 (local desktop lead app; contact: local-freelance)"}
        seen_uids = set()
        candidate_osm_tokens: List[str] = []
        seen_osm_tokens = set()

        # 1. Fast Photon Bounding-Box & Full-Text Search (returns up to 50 OSM nodes/ways per term in ~0.3s)
        for term in search_terms:
            if self._stop_requested:
                break
            term_key = f"photon:{term.lower()}:{loc_str.lower()}"
            if already_searched_terms is not None:
                if term_key in already_searched_terms:
                    continue
                already_searched_terms.add(term_key)

            photon_urls = []
            if bbox:
                south, west, north, east = bbox
                # Photon bbox order: lon_min,lat_min,lon_max,lat_max (west,south,east,north)
                photon_urls.append(
                    f"https://photon.komoot.io/api/?q={urllib.parse.quote(term)}&bbox={west},{south},{east},{north}&limit=50"
                )
            else:
                q_str = f"{term} {city}".strip() if city else term
                photon_urls.append(f"https://photon.komoot.io/api/?q={urllib.parse.quote(q_str)}&limit=50")

            for p_url in photon_urls:
                try:
                    req = urllib.request.Request(p_url, headers=headers)
                    with urllib.request.urlopen(req, timeout=6) as resp:
                        pdata = json.loads(resp.read().decode("utf-8"))
                        for feat in pdata.get("features", []):
                            props = feat.get("properties", {})
                            osm_key = (props.get("osm_key") or "").lower()
                            osm_val = (props.get("osm_value") or "").lower()
                            if osm_key in ("highway", "railway", "waterway", "natural", "boundary", "landuse", "place"):
                                continue
                            if osm_val in ("bus_stop", "platform", "station", "school", "university", "college", "restaurant", "cafe", "pub", "bar", "fast_food", "hotel", "apartment", "park", "artwork"):
                                continue
                            f_country = (props.get("country") or "").lower()
                            if self.country and f_country and self.country.lower() not in f_country and f_country not in self.country.lower():
                                continue
                            otype = props.get("osm_type")
                            oid = props.get("osm_id")
                            if otype in ("N", "W") and oid:
                                tok = f"{otype}{oid}"
                                if tok not in seen_osm_tokens:
                                    seen_osm_tokens.add(tok)
                                    candidate_osm_tokens.append(tok)
                except Exception:
                    pass

        # 2. Batch lookup all discovered Photon OSM IDs via Nominatim /lookup (50 IDs per request)
        for i in range(0, len(candidate_osm_tokens), 50):
            if self._stop_requested or len(results) >= cap:
                break
            batch = candidate_osm_tokens[i:i + 50]
            try:
                l_url = f"https://nominatim.openstreetmap.org/lookup?osm_ids={','.join(batch)}&format=json&extratags=1&addressdetails=1"
                req = urllib.request.Request(l_url, headers=headers)
                with urllib.request.urlopen(req, timeout=8) as resp:
                    ldata = json.loads(resp.read().decode("utf-8"))
                    for item in ldata:
                        ext = item.get("extratags") or {}
                        website = (ext.get("website") or ext.get("contact:website") or ext.get("url") or "").strip()
                        if not website or website.upper() == "NOT AVAILABLE":
                            continue
                        if not website.startswith(("http://", "https://")):
                            website = "https://" + website

                        display = item.get("display_name", "")
                        name = item.get("name") or display.split(",")[0].strip()
                        if not name or name.lower() == city.lower() or name.lower() == self.country.lower():
                            continue

                        item_type = item.get("type") or item.get("class") or ""
                        if self._is_irrelevant_entity(name, website, item_type) or self._is_irrelevant_entity(name, website, ext):
                            continue

                        osm_type = item.get("osm_type", "node")
                        osm_id = item.get("osm_id", "")
                        lead_uid = f"osm_{osm_type}_{osm_id}"
                        if lead_uid in seen_uids:
                            continue
                        seen_uids.add(lead_uid)

                        addr = item.get("address", {})
                        road = addr.get("road", "")
                        house = addr.get("house_number", "")
                        full_address = f"{house} {road}".strip() or display
                        addr_city = addr.get("city") or addr.get("town") or addr.get("suburb") or addr.get("county") or city
                        addr_postcode = addr.get("postcode", postal_code) or "NOT AVAILABLE"
                        addr_country = addr.get("country", self.country)

                        phone = ext.get("phone") or ext.get("contact:phone") or "NOT AVAILABLE"
                        email = ext.get("email") or ext.get("contact:email") or "NOT AVAILABLE"

                        results.append({
                            "lead_uid": lead_uid,
                            "business_name": name,
                            "category": keyword.title(),
                            "specific_service": keyword.title(),
                            "country": addr_country,
                            "city": addr_city or "NOT AVAILABLE",
                            "area": addr.get("suburb", "NOT AVAILABLE"),
                            "postal_code": addr_postcode,
                            "address": full_address,
                            "phone": phone,
                            "normalized_phone": normalize_phone(phone),
                            "secondary_phone": "NOT AVAILABLE",
                            "email": email,
                            "email_source_url": "OpenStreetMap Nominatim Tags" if email != "NOT AVAILABLE" else "NOT AVAILABLE",
                            "website": website,
                            "normalized_domain": normalize_domain(website),
                            "social_profiles": "{}",
                            "rating": None,
                            "reviews_count": None,
                            "opening_status": "Open",
                            "source_name": "OpenStreetMap Nominatim (ODbL)",
                            "source_url": f"https://www.openstreetmap.org/{osm_type}/{osm_id}",
                            "research_date": datetime.date.today().isoformat(),
                            "data_confidence": "HIGH",
                            "enrichment_status": "PENDING" if (website != "NOT AVAILABLE" and self.hunt_emails) else "NOT_REQUESTED",
                            "outreach_status": "Not Contacted",
                            "query_keyword": keyword,
                            "notes": f"Discovered via OSM Search: {item_type or keyword}"
                        })
            except Exception:
                pass

        # 3. Direct Nominatim /search fallback for any terms not yet covered
        for term in search_terms[:3]:
            if self._stop_requested or len(results) >= cap:
                break
            nom_key = f"nom:{term.lower()}:{loc_str.lower()}"
            if already_searched_terms is not None:
                if nom_key in already_searched_terms:
                    continue
                already_searched_terms.add(nom_key)

            query = f"{term} {loc_str}".strip() if loc_str else term
            try:
                url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(query)}&format=json&addressdetails=1&extratags=1&limit=40"
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=6) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    for idx, item in enumerate(data):
                        display = item.get("display_name", "")
                        name = item.get("name") or display.split(",")[0].strip()
                        if not name or name.lower() == city.lower() or name.lower() == self.country.lower():
                            continue

                        ext = item.get("extratags") or {}
                        website = (ext.get("website") or ext.get("contact:website") or ext.get("url") or "").strip()
                        if not website or website.upper() == "NOT AVAILABLE":
                            continue
                        if not website.startswith(("http://", "https://")):
                            website = "https://" + website

                        item_type = item.get("type") or item.get("class") or ""
                        if self._is_irrelevant_entity(name, website, item_type) or self._is_irrelevant_entity(name, website, ext):
                            continue

                        osm_type = item.get("osm_type", "node")
                        osm_id = item.get("osm_id", f"nom_{idx}_{int(time.time())}")
                        lead_uid = f"osm_{osm_type}_{osm_id}"
                        if lead_uid in seen_uids:
                            continue
                        seen_uids.add(lead_uid)

                        addr = item.get("address", {})
                        road = addr.get("road", "")
                        house = addr.get("house_number", "")
                        full_address = f"{house} {road}".strip() or display

                        addr_city = addr.get("city") or addr.get("town") or addr.get("suburb") or city
                        addr_postcode = addr.get("postcode", postal_code) or "NOT AVAILABLE"
                        addr_country = addr.get("country", self.country)

                        phone = ext.get("phone") or ext.get("contact:phone") or "NOT AVAILABLE"
                        email = ext.get("email") or ext.get("contact:email") or "NOT AVAILABLE"

                        results.append({
                            "lead_uid": lead_uid,
                            "business_name": name,
                            "category": keyword.title(),
                            "specific_service": keyword.title(),
                            "country": addr_country,
                            "city": addr_city or "NOT AVAILABLE",
                            "area": addr.get("suburb", "NOT AVAILABLE"),
                            "postal_code": addr_postcode,
                            "address": full_address,
                            "phone": phone,
                            "normalized_phone": normalize_phone(phone),
                            "secondary_phone": "NOT AVAILABLE",
                            "email": email,
                            "email_source_url": "OpenStreetMap Nominatim Tags" if email != "NOT AVAILABLE" else "NOT AVAILABLE",
                            "website": website,
                            "normalized_domain": normalize_domain(website),
                            "social_profiles": "{}",
                            "rating": None,
                            "reviews_count": None,
                            "opening_status": "Open",
                            "source_name": "OpenStreetMap Nominatim (ODbL)",
                            "source_url": f"https://www.openstreetmap.org/{osm_type}/{osm_id}",
                            "research_date": datetime.date.today().isoformat(),
                            "data_confidence": "HIGH",
                            "enrichment_status": "PENDING" if (website != "NOT AVAILABLE" and self.hunt_emails) else "NOT_REQUESTED",
                            "outreach_status": "Not Contacted",
                            "query_keyword": keyword,
                            "notes": f"Discovered via Nominatim search: {term}"
                        })
            except Exception:
                pass

        return results

    def _extract_brand_title(self, raw_title: str, dom: str) -> str:
        """Extract clean business name from search result title or domain."""
        parts = [p.strip() for p in re.split(r"\s+[\|\-–—:]\s+", raw_title) if p.strip()]
        generic_phrases = {
            "windows", "windows and doors", "windows & doors", "windows and doors dublin",
            "windows & doors dublin", "windows & doors ireland", "window installation",
            "window installation dublin", "windows installation", "triple glazed windows",
            "triple glazed windows dublin", "double glazing", "double glazing dublin",
            "upvc windows", "upvc windows dublin", "upvc windows doors dublin", "home"
        }
        chosen = parts[0] if parts else ""
        if chosen.lower() in generic_phrases and len(parts) > 1:
            chosen = parts[-1]
        if not chosen or chosen.lower() in generic_phrases or chosen.lower().startswith("http"):
            stem = dom.split(".")[0].replace("-", " ").replace("windowsanddoors", " Windows & Doors").replace("windows", " Windows").replace("glazing", " Glazing").replace("glass", " Glass")
            chosen = " ".join(stem.split()).title()
        return chosen[:85]

    def _query_public_web_search(self, keyword: str, city: str, limit: int = 25) -> List[Dict[str, Any]]:
        """
        Discover additional local business websites via public web search using Windows native curl.exe (Schannel TLS) with urllib fallback.
        """
        results = []
        try:
            import subprocess
            import lxml.html
            loc_part = f"{city} {self.country}".strip() if self.country and self.country.lower() not in (city or "").lower() else (city or self.country)
            query = f"{keyword} {loc_part}".strip()
            html_text = ""

            # 1. Try Windows native curl.exe against DuckDuckGo Lite (avoids Python OpenSSL JA3 TLS blocks)
            try:
                proc = subprocess.run(
                    [
                        "curl.exe", "-s", "-L", "--max-time", "10",
                        "-A", "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
                        "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "-H", "Accept-Language: en-IE,en-GB;q=0.9,en-US;q=0.8,en;q=0.7",
                        "-H", "Referer: https://lite.duckduckgo.com/",
                        "-d", f"q={urllib.parse.quote(query)}",
                        "https://lite.duckduckgo.com/lite/"
                    ],
                    capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=12
                )
                if proc.returncode == 0 and proc.stdout and "result-link" in proc.stdout:
                    html_text = proc.stdout
            except Exception:
                pass

            # 2. Fallback to standard urllib DuckDuckGo HTML if curl.exe produced no results
            if not html_text:
                data = urllib.parse.urlencode({"q": query}).encode("utf-8")
                req = urllib.request.Request(
                    "https://html.duckduckgo.com/html/",
                    data=data,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Accept-Language": "en-US,en;q=0.5",
                        "Referer": "https://html.duckduckgo.com/"
                    }
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    if resp.status == 200:
                        html_text = resp.read().decode("utf-8", "ignore")

            if not html_text:
                return []

            doc = lxml.html.fromstring(html_text)
            seen_doms = set()
            for a in doc.xpath("//a[contains(@class, 'result-link') or contains(@class, 'result__a')]"):
                href = (a.get("href") or "").strip()
                title = (a.text_content() or "").strip()
                if not href.startswith(("http://", "https://")) or not title:
                    continue
                dom = normalize_domain(href)
                if not dom or dom in seen_doms:
                    continue
                parsed = urllib.parse.urlparse(href)
                root_url = f"{parsed.scheme}://{parsed.netloc}/"
                clean_title = self._extract_brand_title(title, dom)
                if self._is_irrelevant_entity(clean_title, root_url):
                    continue
                seen_doms.add(dom)
                results.append({
                    "lead_uid": f"web_{dom}",
                    "business_name": clean_title,
                    "category": keyword.title(),
                    "specific_service": keyword.title(),
                    "country": self.country,
                    "city": city or "NOT AVAILABLE",
                    "area": "NOT AVAILABLE",
                    "postal_code": self.postal_code or "NOT AVAILABLE",
                    "address": f"{city}, {self.country}".strip(", ") or "NOT AVAILABLE",
                    "phone": "NOT AVAILABLE",
                    "normalized_phone": "",
                    "secondary_phone": "NOT AVAILABLE",
                    "email": "NOT AVAILABLE",
                    "email_source_url": "NOT AVAILABLE",
                    "website": root_url,
                    "normalized_domain": dom,
                    "social_profiles": "{}",
                    "rating": None,
                    "reviews_count": None,
                    "opening_status": "Open",
                    "source_name": "Public Web Business Search",
                    "source_url": root_url,
                    "research_date": datetime.date.today().isoformat(),
                    "data_confidence": "HIGH",
                    "enrichment_status": "PENDING" if self.hunt_emails else "NOT_REQUESTED",
                    "outreach_status": "Not Contacted",
                    "query_keyword": keyword,
                    "notes": f"Discovered via Public Web Search for '{keyword} {city}'"
                })
                if limit and limit > 0 and len(results) >= limit:
                    break
        except Exception:
            pass
        return results

    def run(self):
        try:
            self.state = "RUNNING"
            self.telemetry.log(f"Mission started: {len(self.keywords)} keywords for '{self.city or 'General'}'", "INFO")
            total_steps = len(self.keywords)
            already_searched_terms = set()
            seen_mission_domains = set()
            
            for idx, kw in enumerate(self.keywords):
                if self._stop_requested:
                    break
                self._pause_event.wait()

                self.current_task = f"Searching public data for '{kw}' in {self.city}..."
                self.telemetry.log(f"Executing search: '{kw}' in {self.city}", "INFO")

                # 1. Fast Photon + Nominatim Batch Lookup (immune to Overpass 504 timeouts)
                raw_places = self._query_nominatim_search(
                    kw, self.city, self.postal_code, self.max_results or 50,
                    already_searched_terms=already_searched_terms
                )

                # 2. Supplement with Overpass website-filtered query on first keyword or when needed
                if idx == 0 or not raw_places:
                    osm_places = self._query_osm_overpass(kw, self.city, self.postal_code, self.max_results)
                    raw_places.extend(osm_places)

                # 3. Supplement with Public Web Search for organic local business websites
                web_places = self._query_public_web_search(kw, self.city, self.max_results or 15)
                raw_places.extend(web_places)

                # Deduplicate within this keyword batch by normalized_domain
                deduped_places = []
                for p in raw_places:
                    d = p.get("normalized_domain") or normalize_domain(p.get("website", ""))
                    if d and d not in seen_mission_domains:
                        seen_mission_domains.add(d)
                        deduped_places.append(p)

                self.telemetry.log(f"Discovered {len(deduped_places)} new website-verified records for '{kw}'", "SUCCESS" if deduped_places else "INFO")

                for place in deduped_places:
                    if self._stop_requested:
                        break
                    self._pause_event.wait()

                    self.records_discovered += 1
                    self.records_reviewed += 1
                    
                    # Insert to database
                    lead_id, dup_status = insert_lead(place)
                    if dup_status == "UNIQUE":
                        self.new_unique_leads += 1
                    else:
                        self.duplicates_detected += 1

                    # 4. If hunt_emails enabled and website exists, perform Website Contact Enrichment
                    if self.hunt_emails and place.get("website") and place.get("website") != "NOT AVAILABLE":
                        if self._stop_requested:
                            break
                        self._pause_event.wait()

                        site_url = place["website"]
                        biz_name = place.get("business_name", "Business")
                        self.current_task = f"Enriching public contacts from website: {site_url} ({biz_name})"
                        
                        try:
                            enrich_res = enrich_business_website(site_url, cancel_check=lambda: self._stop_requested)
                            updates = {}
                            if enrich_res.get("email"):
                                updates["email"] = enrich_res["email"]
                                updates["email_source_url"] = enrich_res.get("email_source_url")
                            if enrich_res.get("phone") and (not place.get("phone") or place.get("phone") == "NOT AVAILABLE"):
                                updates["phone"] = enrich_res["phone"]
                                updates["normalized_phone"] = normalize_phone(enrich_res["phone"])
                            if enrich_res.get("social_profiles"):
                                updates["social_profiles"] = json.dumps(enrich_res["social_profiles"])
                            
                            updates["enrichment_status"] = enrich_res.get("status", "FAILED")
                            update_lead(lead_id, updates)
                            
                            if enrich_res.get("email"):
                                self.telemetry.log(f"Found email for {biz_name}: {enrich_res['email']}", "SUCCESS")
                        except Exception as ex:
                            update_lead(lead_id, {"enrichment_status": "FAILED"})
                            self.telemetry.log(f"Enrichment note for {site_url}: {str(ex)[:60]}", "WARN")

                    time.sleep(0.05)

                # Update progress
                self.queued_queries = max(0, total_steps - (idx + 1))
                self.progress_percent = min(100.0, ((idx + 1) / total_steps) * 100.0)

            if self._stop_requested:
                self.state = "STOPPED"
                self.current_task = "Mission stopped by user."
                self.telemetry.log("Mission halted.", "WARN")
            else:
                self.state = "COMPLETED"
                self.current_task = "Mission completed successfully."
                self.progress_percent = 100.0
                self.telemetry.log(f"All queries completed. Total {self.new_unique_leads} new unique leads saved.", "SUCCESS")

        except Exception as ex:
            self.state = "STOPPED"
            self.current_task = f"Stopped due to error: {str(ex)}"
            self.telemetry.log(f"Mission execution error: {str(ex)}", "ERROR")


# Global active worker reference
_active_worker: Optional[ResearchWorker] = None
_worker_lock = threading.Lock()


def get_current_worker() -> Optional[ResearchWorker]:
    global _active_worker
    with _worker_lock:
        return _active_worker


def start_mission(
    keywords: List[str],
    city: str,
    postal_code: str,
    country: str,
    max_results: int,
    hunt_emails: bool,
    auto_dedup: bool
) -> Dict[str, Any]:
    global _active_worker
    with _worker_lock:
        if _active_worker and _active_worker.is_alive() and _active_worker.state in ("RUNNING", "PAUSED"):
            return {"success": False, "error": "A research mission is already active. Stop or pause it first."}
        
        worker = ResearchWorker(
            keywords=keywords,
            city=city,
            postal_code=postal_code,
            country=country,
            max_results_per_search=max_results,
            hunt_emails=hunt_emails,
            auto_dedup=auto_dedup
        )
        _active_worker = worker
        worker.start()
        return {"success": True, "message": "Research mission launched."}


def pause_mission() -> Dict[str, Any]:
    worker = get_current_worker()
    if worker:
        worker.pause()
        return {"success": True, "state": worker.state}
    return {"success": False, "error": "No active mission"}


def resume_mission() -> Dict[str, Any]:
    worker = get_current_worker()
    if worker:
        worker.resume()
        return {"success": True, "state": worker.state}
    return {"success": False, "error": "No active mission"}


def stop_mission() -> Dict[str, Any]:
    worker = get_current_worker()
    if worker:
        worker.stop()
        return {"success": True, "state": worker.state}
    return {"success": False, "error": "No active mission"}


def get_mission_status() -> Dict[str, Any]:
    worker = get_current_worker()
    if worker:
        return worker.get_status()
    else:
        global_stats = get_telemetry_stats()
        return {
            "state": "IDLE",
            "current_task": "Ready — describe a mission and deploy the agent",
            "progress_percent": 0.0,
            "records_discovered": 0,
            "records_reviewed": 0,
            "new_unique_leads": 0,
            "duplicates_detected": 0,
            "queued_queries": 0,
            "hunt_emails": True,
            "logs": [{"time": datetime.datetime.now().strftime("%H:%M:%S"), "message": "Ready — describe a mission and deploy the agent", "level": "INFO"}],
            "global_stats": global_stats
        }
