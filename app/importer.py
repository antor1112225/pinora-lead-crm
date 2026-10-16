"""
CSV and Excel Import Engine for Pinora-Like Local Lead Workspace.
Supports:
- Multi-encoding detection (UTF-8, UTF-8-BOM, Latin-1, CP1252)
- Automatic header detection and intelligent column mapping
- Preview modal with sample rows
- Duplicate evaluation prior to insertion
- Comprehensive import summary with invalid-row diagnostics
- Never silently discards data
"""

import csv
import io
import os
import uuid
import datetime
from typing import Dict, Any, List, Optional, Tuple
from app.database import insert_lead, get_connection
from app.deduplication import normalize_domain, normalize_phone

# In-memory storage for staging uploaded files during preview
_STAGING_UPLOADS: Dict[str, Dict[str, Any]] = {}

COMMON_FIELD_SYNONYMS = {
    "business_name": ["business name", "name", "business", "company", "company name", "store", "title", "vendor"],
    "category": ["category", "type", "business type", "niche", "industry", "tag", "subcategory"],
    "specific_service": ["specific service", "service", "sub-niche", "specialty", "profession"],
    "phone": ["public phone", "official phone", "phone", "telephone", "tel", "phone number", "mobile", "contact phone", "primary phone"],
    "secondary_phone": ["secondary phone", "fax", "alt phone", "other phone"],
    "email": ["public email", "official email", "email", "e-mail", "email address", "contact email", "primary email"],
    "website": ["official website", "website url", "website", "site", "url", "web", "homepage", "link", "domain"],
    "address": ["business address", "address", "street", "street address", "location", "full address"],
    "city": ["city / town", "city/town", "city", "town", "locality", "municipality", "county"],
    "area": ["area", "county", "neighborhood", "district", "borough", "suburb"],
    "postal_code": ["postal code", "zip", "zip code", "zipcode", "postcode", "pin code"],
    "country": ["country", "state/country", "nation"],
    "rating": ["rating", "stars", "score", "average rating"],
    "reviews_count": ["reviews", "reviews count", "review count", "num reviews", "ratings count"],
    "notes": ["notes", "note", "comment", "description", "lead notes"],
    "crm_status": ["contact status", "status", "lead status", "crm status", "outreach status", "stage"],
    "google_ads_status": ["google ads", "google ads status", "google ad"],
    "meta_ads_status": ["meta ads", "facebook ads", "meta ads status", "fb ads"],
    "whatsapp_status": ["whatsapp", "whatsapp status", "wa status"]
}


def guess_column_mapping(headers: List[str]) -> Dict[str, str]:
    """Auto-map detected file headers to application lead fields."""
    mapping = {}
    normalized_headers = {h.strip().lower(): h for h in headers if h}

    for app_field, synonyms in COMMON_FIELD_SYNONYMS.items():
        matched = False
        for syn in synonyms:
            # Exact match
            if syn in normalized_headers:
                mapping[app_field] = normalized_headers[syn]
                matched = True
                break
        if not matched:
            # Substring match
            for syn in synonyms:
                for nh, orig_h in normalized_headers.items():
                    if syn in nh or nh in syn:
                        mapping[app_field] = orig_h
                        matched = True
                        break
                if matched:
                    break
    return mapping


def detect_and_decode(raw_bytes: bytes) -> str:
    """Detect encoding and return decoded string."""
    encodings = ["utf-8-sig", "utf-8", "latin-1", "cp1252", "iso-8859-1"]
    for enc in encodings:
        try:
            return raw_bytes.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw_bytes.decode("utf-8", errors="replace")


def stage_file_for_preview(raw_bytes: bytes, filename: str) -> Dict[str, Any]:
    """Parse uploaded file, extract headers and preview rows, and stage for import."""
    text_content = detect_and_decode(raw_bytes)
    
    # Check delimiter
    sample = text_content[:4096]
    delimiter = ","
    if "\t" in sample and sample.count("\t") > sample.count(","):
        delimiter = "\t"
    elif ";" in sample and sample.count(";") > sample.count(","):
        delimiter = ";"

    reader = csv.reader(io.StringIO(text_content), delimiter=delimiter)
    rows = list(reader)

    if not rows:
        raise ValueError("The uploaded file appears to be empty.")

    headers = [h.strip() for h in rows[0]]
    data_rows = rows[1:]

    # Extract preview (up to 10 rows)
    preview = []
    for r in data_rows[:10]:
        row_dict = {}
        for idx, h in enumerate(headers):
            row_dict[h] = r[idx] if idx < len(r) else ""
        preview.append(row_dict)

    suggested_mapping = guess_column_mapping(headers)

    token = str(uuid.uuid4())
    _STAGING_UPLOADS[token] = {
        "filename": filename,
        "headers": headers,
        "rows": data_rows,
        "created_at": datetime.datetime.now()
    }

    return {
        "token": token,
        "filename": filename,
        "headers": headers,
        "suggested_mapping": suggested_mapping,
        "preview_rows": preview,
        "total_rows": len(data_rows)
    }


def execute_staged_import(token: str, user_mapping: Dict[str, str], source_label: str = "CSV Import") -> Dict[str, Any]:
    """Process staged rows using user-confirmed column mapping."""
    if token not in _STAGING_UPLOADS:
        raise ValueError("Staged upload session expired or not found. Please re-upload the file.")

    staged = _STAGING_UPLOADS.pop(token)
    headers = staged["headers"]
    data_rows = staged["rows"]
    filename = staged["filename"]

    header_to_idx = {h: idx for idx, h in enumerate(headers)}

    imported_unique = 0
    flagged_duplicates = 0
    invalid_rows = []

    today_str = datetime.date.today().isoformat()

    conn = get_connection()
    try:
        for row_idx, row in enumerate(data_rows, start=2):  # 1-indexed line numbers
            if not any(cell.strip() for cell in row):
                continue  # Skip completely empty lines

            lead_data: Dict[str, Any] = {
                "source_name": f"{source_label} ({filename})",
                "source_url": filename,
                "research_date": today_str,
                "data_confidence": "MEDIUM"
            }

            # Extract mapped fields
            for app_field, header_name in user_mapping.items():
                if header_name and header_name in header_to_idx:
                    c_idx = header_to_idx[header_name]
                    val = row[c_idx].strip() if c_idx < len(row) else ""
                    lead_data[app_field] = val if val else "NOT AVAILABLE"

            # Validate minimum requirement: business_name and official website
            biz_name = lead_data.get("business_name")
            if not biz_name or biz_name == "NOT AVAILABLE":
                invalid_rows.append({
                    "row_number": row_idx,
                    "reason": "Missing required Business Name column value"
                })
                continue

            web = (lead_data.get("website") or "").strip()
            if not web or web.upper() == "NOT AVAILABLE":
                invalid_rows.append({
                    "row_number": row_idx,
                    "reason": "Skipped: Business has no official website URL"
                })
                continue
            if not web.startswith(("http://", "https://")):
                web = "https://" + web
            lead_data["website"] = web

            # Normalizations
            lead_data["lead_uid"] = f"import_{uuid.uuid4().hex[:12]}"
            lead_data["normalized_domain"] = normalize_domain(web) if web else ""
            
            ph = lead_data.get("phone")
            lead_data["normalized_phone"] = normalize_phone(ph) if ph else ""

            # Numerical fields
            if lead_data.get("rating") and lead_data["rating"] != "NOT AVAILABLE":
                try:
                    lead_data["rating"] = float(lead_data["rating"])
                except ValueError:
                    lead_data["rating"] = None
            else:
                lead_data["rating"] = None

            if lead_data.get("reviews_count") and lead_data["reviews_count"] != "NOT AVAILABLE":
                try:
                    lead_data["reviews_count"] = int(float(lead_data["reviews_count"]))
                except ValueError:
                    lead_data["reviews_count"] = None
            else:
                lead_data["reviews_count"] = None

            lead_id, dup_status = insert_lead(lead_data, conn=conn)
            if dup_status == "UNIQUE":
                imported_unique += 1
            else:
                flagged_duplicates += 1

        conn.commit()
    finally:
        conn.close()

    return {
        "success": True,
        "filename": filename,
        "total_processed": len(data_rows),
        "imported_unique": imported_unique,
        "flagged_duplicates": flagged_duplicates,
        "invalid_rows_count": len(invalid_rows),
        "invalid_rows": invalid_rows[:50]
    }
