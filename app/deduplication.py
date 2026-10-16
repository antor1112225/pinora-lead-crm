"""
Deduplication and Normalization Engine for Pinora Lead Workspace.
Follows strict matching hierarchy:
1. Normalized official website domain
2. Normalized public phone
3. Business name and address
4. Corroborating evidence (name + city + category)
"""

import re
import urllib.parse
from difflib import SequenceMatcher
from typing import Dict, Any, Optional, Tuple, List


# Common corporate suffixes to normalize for comparison
CORP_SUFFIXES = [
    r"\binc\.?\b", r"\bincorporated\b", r"\bllc\.?\b", r"\bltd\.?\b",
    r"\blimited\b", r"\bcorp\.?\b", r"\bcorporation\b", r"\bco\.?\b",
    r"\bcompany\b", r"\bgroup\b", r"\bservices\b", r"\bservice\b"
]


def normalize_domain(url_or_domain: Optional[str]) -> str:
    """
    Extract and normalize official website domain.
    E.g. 'https://www.MiamiRoofingPro.com/contact?src=ad' -> 'miamiroofingpro.com'
    """
    if not url_or_domain or not isinstance(url_or_domain, str):
        return ""
    
    val = url_or_domain.strip().lower()
    if val in ("not available", "none", "null", "n/a", "no website"):
        return ""
    
    # Add scheme if missing so urlparse works
    if not val.startswith(("http://", "https://")):
        val = "http://" + val
        
    try:
        parsed = urllib.parse.urlparse(val)
        domain = parsed.netloc or parsed.path
        # Remove port if any
        domain = domain.split(":")[0]
        # Remove www.
        if domain.startswith("www."):
            domain = domain[4:]
        # Remove trailing slash and extra dots
        domain = domain.strip("/. ")
        # Exclude common directories / social sites from being counted as business domain
        generic_domains = {
            "facebook.com", "instagram.com", "linkedin.com", "twitter.com",
            "x.com", "youtube.com", "yelp.com", "yellowpages.com", "google.com",
            "maps.google.com", "bing.com", "yahoo.com"
        }
        if domain in generic_domains:
            return ""
        return domain
    except Exception:
        # Fallback simple regex
        m = re.search(r"(?:https?://)?(?:www\.)?([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", url_or_domain.lower())
        return m.group(1) if m else ""


def normalize_phone(phone_str: Optional[str]) -> str:
    """
    Normalize phone number to digits only or standardized E.164-like form.
    E.g. '+1 (305) 555-0199 ext 4' -> '13055550199' or standard digits.
    """
    if not phone_str or not isinstance(phone_str, str):
        return ""
    
    val = phone_str.strip().lower()
    if val in ("not available", "none", "null", "n/a"):
        return ""
    
    # Extract digits only
    digits = re.sub(r"\D", "", val)
    # If 10 digits in US/Canada, standard format is 1 + 10 digits
    if len(digits) == 10:
        digits = "1" + digits
    elif len(digits) == 11 and digits.startswith("1"):
        pass  # already standard
    return digits


def format_display_phone(norm_digits: str, original: str = "") -> str:
    """Format digits for human display if standard 11 digits (US)."""
    if len(norm_digits) == 11 and norm_digits.startswith("1"):
        return f"+1 ({norm_digits[1:4]}) {norm_digits[4:7]}-{norm_digits[7:]}"
    return original.strip() if original else norm_digits


def normalize_name(name_str: Optional[str]) -> str:
    """
    Normalize business name:
    - Lowercase
    - Remove punctuation
    - Remove legal entity suffixes (Inc, LLC, etc.)
    - Normalize whitespace
    """
    if not name_str or not isinstance(name_str, str):
        return ""
    
    val = name_str.strip().lower()
    if val in ("not available", "none", "null", "n/a"):
        return ""
    
    for suffix_pat in CORP_SUFFIXES:
        val = re.sub(suffix_pat, "", val, flags=re.IGNORECASE)
    
    # Replace punctuation with space
    val = re.sub(r"[^\w\s]", " ", val)
    # Collapse whitespace
    val = re.sub(r"\s+", " ", val).strip()
    return val


def normalize_address(address_str: Optional[str]) -> str:
    """
    Normalize physical address:
    - Lowercase
    - Abbreviate standard road terms (St, Rd, Ave, Blvd, Dr, Ste)
    - Remove punctuation
    """
    if not address_str or not isinstance(address_str, str):
        return ""
    
    val = address_str.strip().lower()
    if val in ("not available", "none", "null", "n/a"):
        return ""
    
    replacements = {
        r"\bstreet\b": "st",
        r"\broad\b": "rd",
        r"\bavenue\b": "ave",
        r"\bboulevard\b": "blvd",
        r"\bdrive\b": "dr",
        r"\bsuite\b": "ste",
        r"\bapartment\b": "apt",
        r"\bhighway\b": "hwy",
        r"\bcourt\b": "ct",
        r"\blane\b": "ln"
    }
    for pat, rep in replacements.items():
        val = re.sub(pat, rep, val, flags=re.IGNORECASE)
    
    val = re.sub(r"[^\w\s]", " ", val)
    val = re.sub(r"\s+", " ", val).strip()
    return val


def string_similarity(s1: str, s2: str) -> float:
    """Calculate SequenceMatcher similarity ratio (0.0 to 1.0)."""
    if not s1 or not s2:
        return 0.0
    return SequenceMatcher(None, s1, s2).ratio()


def evaluate_duplicate_pair(lead1: Dict[str, Any], lead2: Dict[str, Any]) -> Tuple[bool, str, float]:
    """
    Evaluate two lead records based on strict matching hierarchy.
    Returns (is_duplicate_candidate, match_reason, confidence_score)
    """
    dom1 = normalize_domain(lead1.get("website") or lead1.get("normalized_domain"))
    dom2 = normalize_domain(lead2.get("website") or lead2.get("normalized_domain"))
    phone1 = normalize_phone(lead1.get("phone") or lead1.get("normalized_phone"))
    phone2 = normalize_phone(lead2.get("phone") or lead2.get("normalized_phone"))

    name1 = normalize_name(lead1.get("business_name"))
    name2 = normalize_name(lead2.get("business_name"))
    city1 = (lead1.get("city") or "").strip().lower()
    city2 = (lead2.get("city") or "").strip().lower()
    addr1 = normalize_address(lead1.get("address"))
    addr2 = normalize_address(lead2.get("address"))

    # Hierarchy Rule 1: Normalized Official Website Domain
    if dom1 and dom2 and dom1 == dom2:
        return True, f"Identical Official Website Domain ({dom1})", 0.98

    # Hierarchy Rule 2: Normalized Public Phone Number
    if phone1 and phone2 and phone1 == phone2:
        return True, f"Identical Public Phone Number ({phone1})", 0.95

    # Hierarchy Rule 3: Business Name and Address
    if name1 and name2:
        name_sim = string_similarity(name1, name2)
        if addr1 and addr2 and addr1 == addr2 and name_sim > 0.70:
            return True, f"Matching Address and Similar Name ({name_sim:.0%})", 0.90
        
        # Hierarchy Rule 4: Corroborating evidence (High Name Match in Same City / Area)
        if city1 and city2 and city1 == city2:
            if name_sim >= 0.90:
                return True, f"High Business Name Match ({name_sim:.0%}) in Same City ({city1.title()})", 0.85
            elif name_sim >= 0.80 and (lead1.get("category") and lead2.get("category") and lead1["category"].lower() == lead2["category"].lower()):
                return True, f"Similar Name ({name_sim:.0%}) with Identical Category in {city1.title()}", 0.75

    return False, "Distinct records", 0.0
