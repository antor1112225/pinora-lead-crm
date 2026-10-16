"""
Database manager for Pinora-Like Local Lead Workspace + Simple CRM.
Uses local SQLite with WAL mode, transactions, indexing, and backup API.
Stores leads, research history, CRM outreach logs, follow-up reminders,
advertising verification evidence, daily sticky notes, and activity audit trails.
Zero cloud dependencies, zero external subscriptions.
"""

import sqlite3
import json
import os
import shutil
import datetime
import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Set

DB_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DB_DIR / "pinora_leads.db"
BACKUP_DIR = DB_DIR / "backups"
DOCS_BACKUP_DIR = Path.home() / "Documents" / "LocalLeadCRM" / "Backups"

# Valid Simple CRM Statuses
CRM_STATUSES = [
    "NEW",
    "READY TO CONTACT",
    "CONTACTED",
    "REPLIED",
    "INTERESTED",
    "FOLLOW-UP DUE",
    "QUALIFIED",
    "CLIENT",
    "NOT INTERESTED",
    "DO NOT CONTACT"
]

# Advertising Verification Status Options
ADS_STATUS_OPTIONS = [
    "YES - ACTIVE ADS FOUND",
    "NO - NO PUBLIC ADS FOUND",
    "PAUSED",
    "NEEDS REVIEW",
    "NOT CHECKED"
]

# WhatsApp Verification Statuses
WHATSAPP_STATUSES = [
    "Not Checked",
    "Available / Chat Opens",
    "Not Available",
    "Uncertain"
]


def normalize_ad_status(status: Optional[str]) -> str:
    """Normalize ad status strings to the standard options."""
    if not status:
        return "NOT CHECKED"
    s = str(status).strip()
    s_upper = s.upper()
    if "ACTIVE" in s_upper or s_upper == "YES" or "ACTIVE ADS FOUND" in s_upper:
        return "YES - ACTIVE ADS FOUND"
    if "NO PUBLIC" in s_upper or s_upper == "NO" or "NO - NO PUBLIC ADS FOUND" in s_upper:
        return "NO - NO PUBLIC ADS FOUND"
    if "PAUSED" in s_upper:
        return "PAUSED"
    if "REVIEW" in s_upper:
        return "NEEDS REVIEW"
    return "NOT CHECKED"


def calculate_ads_summary(google_status: Optional[str], meta_status: Optional[str]) -> str:
    """
    Calculate consolidated advertising verification summary.
    Possible outputs: GOOGLE + META, GOOGLE ONLY, META ONLY, PAUSED ADS, NO PUBLIC ADS FOUND, NEEDS REVIEW, NOT CHECKED
    """
    g = normalize_ad_status(google_status)
    m = normalize_ad_status(meta_status)

    if g == "YES - ACTIVE ADS FOUND" and m == "YES - ACTIVE ADS FOUND":
        return "GOOGLE + META"
    elif g == "YES - ACTIVE ADS FOUND" and m == "NO - NO PUBLIC ADS FOUND":
        return "GOOGLE ONLY"
    elif m == "YES - ACTIVE ADS FOUND" and g == "NO - NO PUBLIC ADS FOUND":
        return "META ONLY"
    elif g == "YES - ACTIVE ADS FOUND":
        return "GOOGLE ONLY"
    elif m == "YES - ACTIVE ADS FOUND":
        return "META ONLY"
    elif g == "PAUSED" or m == "PAUSED":
        return "PAUSED ADS"
    elif g == "NO - NO PUBLIC ADS FOUND" and m == "NO - NO PUBLIC ADS FOUND":
        return "NO PUBLIC ADS FOUND"
    elif g == "NEEDS REVIEW" or m == "NEEDS REVIEW":
        return "NEEDS REVIEW"
    elif g == "NOT CHECKED" and m == "NOT CHECKED":
        return "NOT CHECKED"
    else:
        return "NOT CHECKED"


def get_connection(db_path: Optional[Any] = None) -> sqlite3.Connection:
    target = Path(db_path or DB_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Optional[Path] = None):
    conn = get_connection(db_path)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS leads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lead_uid TEXT UNIQUE,
        business_name TEXT NOT NULL,
        category TEXT,
        specific_service TEXT,
        country TEXT,
        city TEXT,
        area TEXT,
        postal_code TEXT,
        address TEXT,
        phone TEXT,
        normalized_phone TEXT,
        secondary_phone TEXT,
        email TEXT,
        email_source_url TEXT,
        website TEXT,
        normalized_domain TEXT,
        social_profiles TEXT,
        rating REAL,
        reviews_count INTEGER,
        opening_status TEXT,
        source_name TEXT,
        source_url TEXT,
        research_date TEXT,
        data_confidence TEXT DEFAULT 'MEDIUM',
        completeness_score INTEGER DEFAULT 0,
        contact_status TEXT DEFAULT 'NOT AVAILABLE',
        enrichment_status TEXT DEFAULT 'NOT_REQUESTED',
        duplicate_status TEXT DEFAULT 'UNIQUE',
        outreach_status TEXT DEFAULT 'NEW',
        crm_status TEXT DEFAULT 'NEW',
        whatsapp_status TEXT DEFAULT 'Not Checked',
        whatsapp_last_checked TEXT,
        whatsapp_notes TEXT,
        google_ads_status TEXT DEFAULT 'Not Checked',
        google_advertiser_name TEXT,
        google_evidence_url TEXT,
        google_ads_last_verified TEXT,
        google_ads_notes TEXT,
        meta_ads_status TEXT DEFAULT 'Not Checked',
        meta_advertiser_name TEXT,
        meta_evidence_url TEXT,
        meta_ads_last_verified TEXT,
        meta_ads_notes TEXT,
        ads_summary TEXT DEFAULT 'NOT CHECKED',
        next_action TEXT DEFAULT 'Ready to Contact',
        next_followup_date TEXT,
        followup_count INTEGER DEFAULT 0,
        first_contact_date TEXT,
        last_contact_date TEXT,
        last_contact_channel TEXT,
        whatsapp_draft TEXT,
        email_subject_draft TEXT,
        email_body_draft TEXT,
        notes TEXT,
        created_at TEXT,
        updated_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS contact_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lead_id INTEGER NOT NULL,
        date_sent TEXT NOT NULL,
        channel TEXT NOT NULL,
        message_type TEXT NOT NULL,
        note TEXT,
        next_followup_date TEXT,
        note_id INTEGER,
        created_at TEXT,
        FOREIGN KEY(lead_id) REFERENCES leads(id) ON DELETE CASCADE
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lead_id INTEGER NOT NULL,
        reminder_date TEXT NOT NULL,
        reminder_type TEXT DEFAULT 'Follow-up',
        description TEXT,
        status TEXT DEFAULT 'PENDING',
        notified INTEGER DEFAULT 0,
        created_at TEXT,
        updated_at TEXT,
        FOREIGN KEY(lead_id) REFERENCES leads(id) ON DELETE CASCADE
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS dedup_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        primary_lead_id INTEGER,
        merged_lead_id INTEGER,
        merge_reason TEXT,
        primary_snapshot TEXT,
        merged_snapshot TEXT,
        created_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS keyword_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        keyword TEXT NOT NULL,
        city TEXT,
        postal_code TEXT,
        country TEXT,
        status TEXT DEFAULT 'QUEUED',
        results_count INTEGER DEFAULT 0,
        created_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)

    # Sticky Notes Table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS daily_notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        note_uid TEXT UNIQUE,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        category TEXT DEFAULT 'Outreach',
        created_date TEXT NOT NULL,
        created_time TEXT NOT NULL,
        updated_at TEXT,
        associated_leads TEXT,
        processing_status TEXT DEFAULT 'DRAFT',
        is_pinned INTEGER DEFAULT 0,
        parse_interpretation TEXT,
        processed_at TEXT
    )
    """)

    # System CRM Activity Log Table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS crm_activity_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action_type TEXT NOT NULL,
        description TEXT NOT NULL,
        reference_id TEXT,
        created_at TEXT NOT NULL
    )
    """)

    # Safe Schema Migrations for existing databases
    cur.execute("PRAGMA table_info(leads)")
    existing_cols = {row["name"] for row in cur.fetchall()}

    columns_to_ensure = [
        ("crm_status", "TEXT DEFAULT 'NEW'"),
        ("whatsapp_status", "TEXT DEFAULT 'Not Checked'"),
        ("whatsapp_last_checked", "TEXT"),
        ("whatsapp_notes", "TEXT"),
        ("google_ads_status", "TEXT DEFAULT 'Not Checked'"),
        ("google_advertiser_name", "TEXT"),
        ("google_evidence_url", "TEXT"),
        ("google_ads_last_verified", "TEXT"),
        ("google_ads_notes", "TEXT"),
        ("meta_ads_status", "TEXT DEFAULT 'Not Checked'"),
        ("meta_advertiser_name", "TEXT"),
        ("meta_evidence_url", "TEXT"),
        ("meta_ads_last_verified", "TEXT"),
        ("meta_ads_notes", "TEXT"),
        ("ads_summary", "TEXT DEFAULT 'NOT CHECKED'"),
        ("next_action", "TEXT DEFAULT 'Ready to Contact'"),
        ("next_followup_date", "TEXT"),
        ("followup_count", "INTEGER DEFAULT 0"),
        ("first_contact_date", "TEXT"),
        ("last_contact_date", "TEXT"),
        ("last_contact_channel", "TEXT"),
        ("whatsapp_draft", "TEXT"),
        ("email_subject_draft", "TEXT"),
        ("email_body_draft", "TEXT"),
    ]

    for col_name, col_def in columns_to_ensure:
        if col_name not in existing_cols:
            try:
                cur.execute(f"ALTER TABLE leads ADD COLUMN {col_name} {col_def}")
            except Exception:
                pass

    # Ensure note_id column on contact_history
    cur.execute("PRAGMA table_info(contact_history)")
    ch_cols = {row["name"] for row in cur.fetchall()}
    if "note_id" not in ch_cols:
        try:
            cur.execute("ALTER TABLE contact_history ADD COLUMN note_id INTEGER")
        except Exception:
            pass

    # Ensure category column on daily_notes
    cur.execute("PRAGMA table_info(daily_notes)")
    dn_cols = {row["name"] for row in cur.fetchall()}
    if "category" not in dn_cols:
        try:
            cur.execute("ALTER TABLE daily_notes ADD COLUMN category TEXT DEFAULT 'Outreach'")
        except Exception:
            pass

    # Initialize default user settings if absent
    default_settings = {
        "followup_interval_1": "3",
        "followup_interval_2": "5",
        "max_followups": "2",
        "reminders_enabled": "1",
        "backup_retention_days": "30",
        "custom_backup_dir": str(DOCS_BACKUP_DIR)
    }
    for k, v in default_settings.items():
        cur.execute("INSERT OR IGNORE INTO user_settings (key, value) VALUES (?, ?)", (k, v))

    # Indexes for fast lookups
    cur.execute("CREATE INDEX IF NOT EXISTS idx_leads_domain ON leads(normalized_domain)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_leads_phone ON leads(normalized_phone)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_leads_name ON leads(business_name)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_leads_city ON leads(city)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_leads_category ON leads(category)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_leads_crm_status ON leads(crm_status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_leads_ads_summary ON leads(ads_summary)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_leads_g_ads ON leads(google_ads_status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_leads_m_ads ON leads(meta_ads_status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_reminders_status_date ON reminders(status, reminder_date)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_contact_history_lead ON contact_history(lead_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_daily_notes_date ON daily_notes(created_date)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_daily_notes_pinned ON daily_notes(is_pinned)")

    # Remove any collected leads without websites from the live database
    cur.execute(
        "DELETE FROM leads WHERE website IS NULL OR TRIM(website) = '' OR UPPER(TRIM(website)) = 'NOT AVAILABLE'"
    )

    conn.commit()
    conn.close()


def purge_leads_without_website() -> int:
    """Remove any leads that do not have a valid website URL."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM leads WHERE website IS NULL OR TRIM(website) = '' OR UPPER(TRIM(website)) = 'NOT AVAILABLE'"
    )
    removed = cur.rowcount
    conn.commit()
    conn.close()
    return removed


def generate_outreach_drafts(lead: Dict[str, Any]) -> Dict[str, str]:
    """Generate professional, personalized outreach message drafts."""
    biz = lead.get("business_name") or "there"
    cat = lead.get("category") or "local"
    city = lead.get("city") or "your area"
    ads_st = lead.get("ads_summary") or "NEEDS REVIEW"

    if ads_st == "NO PUBLIC ADS FOUND":
        ad_hook = "noticed you don't appear to be running active Google or Meta ads right now"
    elif ads_st in ("GOOGLE ONLY", "META ONLY"):
        ad_hook = f"noticed your presence on {ads_st.replace(' ONLY', '')} and saw opportunities to expand to other high-converting channels"
    else:
        ad_hook = "came across your business while researching top local providers"

    wa_pitch = (
        f"Hi {biz}! I {ad_hook} in {city}. "
        f"We specialize in generating high-intent leads for {cat.lower()} businesses with Google & Meta Ads. "
        f"Would you be open to a 3-minute video breakdown of competitors taking market share in {city}?"
    )

    email_subject = f"Question regarding {biz} customer acquisition in {city}"
    email_body = (
        f"Hi {biz} Team,\n\n"
        f"I {ad_hook} and wanted to reach out.\n\n"
        f"We help local {cat.lower()} contractors scale local bookings with focused ad campaigns.\n"
        f"Are you currently taking on new clients in {city} this month?\n\n"
        f"Best regards,\nLocal Growth Specialist"
    )

    return {
        "whatsapp_draft": wa_pitch,
        "email_subject_draft": email_subject,
        "email_body_draft": email_body
    }


def insert_lead(lead_data: Dict[str, Any], conn: Optional[sqlite3.Connection] = None) -> Tuple[int, str]:
    """Insert a lead into SQLite with scoring and drafts."""
    should_close = False
    if conn is None:
        conn = get_connection()
        should_close = True

    try:
        cur = conn.cursor()
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        lead_uid = lead_data.get("lead_uid") or f"lead_{datetime.datetime.now().strftime('%Y%m%d%H%M%S%f')}"

        has_phone = bool(lead_data.get("phone") and lead_data["phone"] != "NOT AVAILABLE")
        has_email = bool(lead_data.get("email") and lead_data["email"] != "NOT AVAILABLE")
        has_web = bool(lead_data.get("website") and lead_data["website"] != "NOT AVAILABLE")
        has_address = bool(lead_data.get("address") and lead_data["address"] != "NOT AVAILABLE")

        comp_score = 0
        if lead_data.get("business_name"): comp_score += 25
        if has_phone: comp_score += 25
        if has_email: comp_score += 25
        if has_web: comp_score += 15
        if has_address: comp_score += 10

        contacts = []
        if has_phone: contacts.append("Phone")
        if has_email: contacts.append("Email")
        if has_web: contacts.append("Web")
        contact_status = " + ".join(contacts) if contacts else "NOT AVAILABLE"

        soc_str = "{}"
        if "social_profiles" in lead_data and lead_data["social_profiles"]:
            soc_str = json.dumps(lead_data["social_profiles"]) if isinstance(lead_data["social_profiles"], dict) else str(lead_data["social_profiles"])

        crm_st = lead_data.get("crm_status") or lead_data.get("outreach_status") or "NEW"
        g_status = normalize_ad_status(lead_data.get("google_ads_status"))
        m_status = normalize_ad_status(lead_data.get("meta_ads_status"))
        ads_sum = lead_data.get("ads_summary") or calculate_ads_summary(g_status, m_status)

        drafts = generate_outreach_drafts({
            "business_name": lead_data.get("business_name"),
            "category": lead_data.get("category"),
            "city": lead_data.get("city"),
            "ads_summary": ads_sum
        })

        # Auto-compute normalized_domain and normalized_phone if not provided
        norm_dom = lead_data.get("normalized_domain")
        if not norm_dom and lead_data.get("website"):
            from app.deduplication import normalize_domain
            norm_dom = normalize_domain(lead_data.get("website"))
            lead_data["normalized_domain"] = norm_dom

        norm_ph = lead_data.get("normalized_phone")
        if not norm_ph and lead_data.get("phone"):
            from app.deduplication import normalize_phone
            norm_ph = normalize_phone(lead_data.get("phone"))
            lead_data["normalized_phone"] = norm_ph

        dup_status = lead_data.get("duplicate_status", "UNIQUE")
        if dup_status == "UNIQUE":
            if norm_dom and norm_dom not in ("", "none", "not available"):
                cur.execute("SELECT id FROM leads WHERE normalized_domain = ? AND duplicate_status != 'MERGED'", (norm_dom,))
                if cur.fetchone():
                    dup_status = "POTENTIAL_DUPLICATE"
            if dup_status == "UNIQUE" and norm_ph and norm_ph not in ("", "none", "not available"):
                cur.execute("SELECT id FROM leads WHERE normalized_phone = ? AND duplicate_status != 'MERGED'", (norm_ph,))
                if cur.fetchone():
                    dup_status = "POTENTIAL_DUPLICATE"

        # Check if lead_uid already exists in database
        cur.execute("SELECT id FROM leads WHERE lead_uid = ?", (lead_uid,))
        existing_uid = cur.fetchone()
        if existing_uid:
            return existing_uid[0], "DUPLICATE"

        try:
            cur.execute("""
            INSERT INTO leads (
                lead_uid, business_name, category, specific_service, country,
                city, area, postal_code, address, phone, normalized_phone,
                secondary_phone, email, email_source_url, website, normalized_domain,
                social_profiles, rating, reviews_count, opening_status, source_name,
                source_url, research_date, data_confidence, completeness_score,
                contact_status, enrichment_status, duplicate_status, outreach_status,
                crm_status, whatsapp_status, google_ads_status, meta_ads_status,
                ads_summary, next_action, next_followup_date, followup_count,
                whatsapp_draft, email_subject_draft, email_body_draft,
                notes, created_at, updated_at
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """, (
                lead_uid, lead_data.get("business_name"), lead_data.get("category"),
                lead_data.get("specific_service"), lead_data.get("country", "United States"),
                lead_data.get("city"), lead_data.get("area"), lead_data.get("postal_code"),
                lead_data.get("address"), (lead_data.get("phone") or "NOT AVAILABLE"),
                lead_data.get("normalized_phone"), lead_data.get("secondary_phone"),
                (lead_data.get("email") or "NOT AVAILABLE"), lead_data.get("email_source_url"),
                (lead_data.get("website") or "NOT AVAILABLE"), lead_data.get("normalized_domain"),
                soc_str, lead_data.get("rating"), lead_data.get("reviews_count"),
                lead_data.get("opening_status"), lead_data.get("source_name", "Open Data Research"),
                lead_data.get("source_url"), lead_data.get("research_date", datetime.date.today().isoformat()),
                lead_data.get("data_confidence", "MEDIUM"), comp_score, contact_status,
                lead_data.get("enrichment_status", "NOT_REQUESTED"),
                dup_status, crm_st, crm_st,
                lead_data.get("whatsapp_status", "Not Checked"), g_status, m_status, ads_sum,
                lead_data.get("next_action", "Ready to Contact"),
                lead_data.get("next_followup_date"), lead_data.get("followup_count", 0),
                drafts["whatsapp_draft"], drafts["email_subject_draft"], drafts["email_body_draft"],
                lead_data.get("notes", ""), now_str, now_str
            ))
            lead_id = cur.lastrowid
            if should_close:
                conn.commit()
            return lead_id, dup_status
        except sqlite3.IntegrityError:
            cur.execute("SELECT id FROM leads WHERE lead_uid = ?", (lead_uid,))
            row = cur.fetchone()
            if row:
                return row[0], "DUPLICATE"
            raise
    finally:
        if should_close:
            conn.close()


def update_lead(lead_id: int, updates: Dict[str, Any], conn: Optional[sqlite3.Connection] = None):
    """Update fields for a specific lead."""
    should_close = False
    if conn is None:
        conn = get_connection()
        should_close = True

    try:
        cur = conn.cursor()
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        updates = dict(updates)
        updates["updated_at"] = now_str

        if "social_profiles" in updates and isinstance(updates["social_profiles"], dict):
            updates["social_profiles"] = json.dumps(updates["social_profiles"])

        if "website" in updates and "normalized_domain" not in updates:
            from app.deduplication import normalize_domain
            updates["normalized_domain"] = normalize_domain(updates.get("website"))

        if "phone" in updates and "normalized_phone" not in updates:
            from app.deduplication import normalize_phone
            updates["normalized_phone"] = normalize_phone(updates.get("phone"))

        # Auto-suppress reminders if moving to terminal CRM status
        if "crm_status" in updates and updates["crm_status"]:
            new_crm = str(updates["crm_status"]).strip()
            updates["crm_status"] = new_crm
            updates["outreach_status"] = new_crm
            terminal_statuses = {"CLIENT", "NOT INTERESTED", "DO NOT CONTACT", "REPLIED"}
            if new_crm in terminal_statuses:
                cur.execute("""
                    UPDATE reminders 
                    SET status = 'CANCELLED', updated_at = ? 
                    WHERE lead_id = ? AND status = 'PENDING'
                """, (now_str, lead_id))
                if "next_followup_date" not in updates:
                    updates["next_followup_date"] = None
                if "next_action" not in updates:
                    action_labels = {
                        "REPLIED": "Replied - Sequence Stopped",
                        "NOT INTERESTED": "Not Interested - Closed",
                        "DO NOT CONTACT": "Opted Out - Do Not Contact",
                        "CLIENT": "Active Client"
                    }
                    updates["next_action"] = action_labels.get(new_crm, new_crm)

        # Re-score if contact fields updated
        if any(k in updates for k in ("phone", "email", "website", "address", "business_name")):
            cur.execute("SELECT business_name, phone, email, website, address FROM leads WHERE id = ?", (lead_id,))
            row = cur.fetchone()
            curr = dict(row) if row else {}
            curr.update(updates)

            has_phone = bool(curr.get("phone") and curr["phone"] != "NOT AVAILABLE")
            has_email = bool(curr.get("email") and curr["email"] != "NOT AVAILABLE")
            has_web = bool(curr.get("website") and curr["website"] != "NOT AVAILABLE")
            has_addr = bool(curr.get("address") and curr["address"] != "NOT AVAILABLE")

            comp = 0
            if curr.get("business_name"): comp += 25
            if has_phone: comp += 25
            if has_email: comp += 25
            if has_web: comp += 15
            if has_addr: comp += 10
            updates["completeness_score"] = comp

            contacts = []
            if has_phone: contacts.append("Phone")
            if has_email: contacts.append("Email")
            if has_web: contacts.append("Web")
            updates["contact_status"] = " + ".join(contacts) if contacts else "NOT AVAILABLE"

        cur.execute("PRAGMA table_info(leads)")
        valid_cols = {row["name"] for row in cur.fetchall()}
        filtered_updates = {k: v for k, v in updates.items() if k in valid_cols}
        if not filtered_updates:
            return

        set_clause = ", ".join([f"{k} = ?" for k in filtered_updates.keys()])
        values = list(filtered_updates.values()) + [lead_id]
        cur.execute(f"UPDATE leads SET {set_clause} WHERE id = ?", values)
        if should_close:
            conn.commit()
    finally:
        if should_close:
            conn.close()


def get_lead(lead_id: int) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM leads WHERE id = ?", (lead_id,))
        row = cur.fetchone()
        if not row:
            return None
        res = dict(row)
        res["lead_number"] = f"#{res['id']:04d}"
        res["google_verification_date"] = res.get("google_ads_last_verified")
        res["meta_verification_date"] = res.get("meta_ads_last_verified")
        return res
    finally:
        conn.close()


def get_leads(
    filters: Optional[Dict[str, Any]] = None,
    search_text: Optional[str] = None,
    limit: int = 150,
    offset: int = 0,
    order_by: str = "id DESC"
) -> Tuple[List[Dict[str, Any]], int]:
    """Retrieve filtered leads with total count and stable Lead Numbers (#0001)."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        query = "SELECT * FROM leads WHERE 1=1"
        count_query = "SELECT COUNT(*) as total FROM leads WHERE 1=1"
        params: List[Any] = []

        if filters:
            if filters.get("country"):
                query += " AND LOWER(country) LIKE ?"
                count_query += " AND LOWER(country) LIKE ?"
                params.append(f"%{filters['country'].lower()}%")
            if filters.get("city"):
                query += " AND LOWER(city) LIKE ?"
                count_query += " AND LOWER(city) LIKE ?"
                params.append(f"%{filters['city'].lower()}%")
            if filters.get("postal_code"):
                query += " AND postal_code LIKE ?"
                count_query += " AND postal_code LIKE ?"
                params.append(f"%{filters['postal_code']}%")
            if filters.get("category"):
                query += " AND LOWER(category) LIKE ?"
                count_query += " AND LOWER(category) LIKE ?"
                params.append(f"%{filters['category'].lower()}%")

            # CRM & Outreach Status Filters
            if filters.get("crm_status"):
                query += " AND (crm_status = ? OR outreach_status = ?)"
                count_query += " AND (crm_status = ? OR outreach_status = ?)"
                params.extend([filters["crm_status"], filters["crm_status"]])
            elif filters.get("outreach_status"):
                query += " AND (crm_status = ? OR outreach_status = ?)"
                count_query += " AND (crm_status = ? OR outreach_status = ?)"
                params.extend([filters["outreach_status"], filters["outreach_status"]])

            # Advertiser Filter logic (Section 7)
            ads_filter = filters.get("ads_filter") or filters.get("ads_summary")
            if ads_filter and ads_filter not in ("", "ALL LEADS", "ALL"):
                af = ads_filter.strip().upper()
                if af in ("GOOGLE ADS YES", "GOOGLE_YES"):
                    cond = " AND (google_ads_status IN ('YES - ACTIVE ADS FOUND', 'Active Ads Found'))"
                    query += cond; count_query += cond
                elif af in ("META ADS YES", "META_YES"):
                    cond = " AND (meta_ads_status IN ('YES - ACTIVE ADS FOUND', 'Active Ads Found'))"
                    query += cond; count_query += cond
                elif af in ("GOOGLE + META", "GOOGLE_META"):
                    cond = " AND (google_ads_status IN ('YES - ACTIVE ADS FOUND', 'Active Ads Found') AND meta_ads_status IN ('YES - ACTIVE ADS FOUND', 'Active Ads Found'))"
                    query += cond; count_query += cond
                elif af in ("GOOGLE ONLY", "GOOGLE_ONLY"):
                    cond = " AND (google_ads_status IN ('YES - ACTIVE ADS FOUND', 'Active Ads Found') AND (meta_ads_status IS NULL OR meta_ads_status NOT IN ('YES - ACTIVE ADS FOUND', 'Active Ads Found')))"
                    query += cond; count_query += cond
                elif af in ("META ONLY", "META_ONLY"):
                    cond = " AND (meta_ads_status IN ('YES - ACTIVE ADS FOUND', 'Active Ads Found') AND (google_ads_status IS NULL OR google_ads_status NOT IN ('YES - ACTIVE ADS FOUND', 'Active Ads Found')))"
                    query += cond; count_query += cond
                elif af in ("PAUSED ADS", "PAUSED"):
                    cond = " AND (google_ads_status = 'PAUSED' OR meta_ads_status = 'PAUSED')"
                    query += cond; count_query += cond
                elif af in ("NO PUBLIC ADS FOUND", "NO_ADS"):
                    cond = " AND (ads_summary = 'NO PUBLIC ADS FOUND' OR (google_ads_status IN ('NO - NO PUBLIC ADS FOUND', 'No Public Ads Found') AND (meta_ads_status IS NULL OR meta_ads_status IN ('NO - NO PUBLIC ADS FOUND', 'No Public Ads Found', 'NOT CHECKED', 'Not Checked', ''))))"
                    query += cond; count_query += cond
                elif af in ("NEEDS REVIEW", "NEEDS_REVIEW"):
                    cond = " AND (ads_summary = 'NEEDS REVIEW' OR google_ads_status IN ('NEEDS REVIEW', 'Needs Manual Review', 'Needs Review') OR meta_ads_status IN ('NEEDS REVIEW', 'Needs Manual Review', 'Needs Review'))"
                    query += cond; count_query += cond
                elif af in ("NOT CHECKED", "NOT_CHECKED"):
                    cond = " AND (ads_summary = 'NOT CHECKED' OR ((google_ads_status IS NULL OR google_ads_status IN ('NOT CHECKED', 'Not Checked', '')) AND (meta_ads_status IS NULL OR meta_ads_status IN ('NOT CHECKED', 'Not Checked', ''))))"
                    query += cond; count_query += cond

            # Toggle: Show only verified active advertisers (at least 1 platform YES)
            if filters.get("verified_advertisers_only") is True:
                cond = " AND (google_ads_status IN ('YES - ACTIVE ADS FOUND', 'Active Ads Found') OR meta_ads_status IN ('YES - ACTIVE ADS FOUND', 'Active Ads Found'))"
                query += cond; count_query += cond

            if filters.get("google_ads_status"):
                query += " AND (google_ads_status = ? OR google_ads_status LIKE ?)"
                count_query += " AND (google_ads_status = ? OR google_ads_status LIKE ?)"
                params.extend([filters["google_ads_status"], f"%{filters['google_ads_status']}%"])
            if filters.get("meta_ads_status"):
                query += " AND (meta_ads_status = ? OR meta_ads_status LIKE ?)"
                count_query += " AND (meta_ads_status = ? OR meta_ads_status LIKE ?)"
                params.extend([filters["meta_ads_status"], f"%{filters['meta_ads_status']}%"])
            if filters.get("whatsapp_status"):
                query += " AND whatsapp_status = ?"
                count_query += " AND whatsapp_status = ?"
                params.append(filters["whatsapp_status"])

            if filters.get("duplicate_status"):
                query += " AND duplicate_status = ?"
                count_query += " AND duplicate_status = ?"
                params.append(filters["duplicate_status"])
            if filters.get("enrichment_status"):
                query += " AND enrichment_status = ?"
                count_query += " AND enrichment_status = ?"
                params.append(filters["enrichment_status"])
            if filters.get("has_phone") is True:
                query += " AND phone IS NOT NULL AND phone != '' AND phone != 'NOT AVAILABLE'"
                count_query += " AND phone IS NOT NULL AND phone != '' AND phone != 'NOT AVAILABLE'"
            if filters.get("has_website") is True:
                query += " AND website IS NOT NULL AND website != '' AND website != 'NOT AVAILABLE'"
                count_query += " AND website IS NOT NULL AND website != '' AND website != 'NOT AVAILABLE'"
            if filters.get("no_website") is True:
                query += " AND (website IS NULL OR website = '' OR website = 'NOT AVAILABLE')"
                count_query += " AND (website IS NULL OR website = '' OR website = 'NOT AVAILABLE')"
            if filters.get("has_email") is True:
                query += " AND email IS NOT NULL AND email != '' AND email != 'NOT AVAILABLE'"
                count_query += " AND email IS NOT NULL AND email != '' AND email != 'NOT AVAILABLE'"
            if filters.get("missing_email") is True:
                query += " AND (email IS NULL OR email = '' OR email = 'NOT AVAILABLE')"
                count_query += " AND (email IS NULL OR email = '' OR email = 'NOT AVAILABLE')"
            if filters.get("has_social") is True:
                query += " AND social_profiles IS NOT NULL AND social_profiles != '' AND social_profiles != '{}' AND social_profiles != '[]'"
                count_query += " AND social_profiles IS NOT NULL AND social_profiles != '' AND social_profiles != '{}' AND social_profiles != '[]'"
            if filters.get("min_rating"):
                try:
                    min_r = float(filters["min_rating"])
                    query += " AND rating >= ?"
                    count_query += " AND rating >= ?"
                    params.append(min_r)
                except ValueError:
                    pass
            if filters.get("min_reviews"):
                try:
                    min_rev = int(filters["min_reviews"])
                    query += " AND reviews_count >= ?"
                    count_query += " AND reviews_count >= ?"
                    params.append(min_rev)
                except ValueError:
                    pass
            if filters.get("hide_merged", True):
                query += " AND duplicate_status != 'MERGED'"
                count_query += " AND duplicate_status != 'MERGED'"

        if search_text and search_text.strip():
            raw_s = search_text.strip()
            # If search is a lead number like "#1" or "#0001" or a pure integer
            lead_id_match = re.match(r'^#?0*(\d+)$', raw_s)
            st = f"%{raw_s.lower()}%"
            if lead_id_match:
                lid = int(lead_id_match.group(1))
                s_clause = " AND (id = ? OR LOWER(business_name) LIKE ? OR LOWER(phone) LIKE ? OR LOWER(email) LIKE ? OR LOWER(website) LIKE ?)"
                query += s_clause
                count_query += s_clause
                params.extend([lid, st, st, st, st])
            else:
                s_clause = " AND (LOWER(business_name) LIKE ? OR LOWER(phone) LIKE ? OR LOWER(email) LIKE ? OR LOWER(website) LIKE ? OR LOWER(city) LIKE ? OR LOWER(address) LIKE ?)"
                query += s_clause
                count_query += s_clause
                params.extend([st, st, st, st, st, st])

        cur.execute(count_query, params)
        total = cur.fetchone()["total"]

        allowed_order = {
            "id DESC": "id DESC",
            "id ASC": "id ASC",
            "business_name ASC": "business_name ASC",
            "business_name DESC": "business_name DESC",
            "completeness_score DESC": "completeness_score DESC",
            "rating DESC": "rating DESC",
            "next_followup_date ASC": "next_followup_date ASC",
            "created_at DESC": "created_at DESC"
        }
        order_clause = allowed_order.get(order_by, "id DESC")
        query += f" ORDER BY {order_clause} LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cur.execute(query, params)
        rows = cur.fetchall()

        leads = []
        for r in rows:
            d = dict(r)
            d["lead_number"] = f"#{d['id']:04d}"
            leads.append(d)

        return leads, total
    finally:
        conn.close()


def get_crm_top_stats() -> Dict[str, Any]:
    """
    Retrieve top metric card counters matching Section 18:
    TOTAL LEADS | GOOGLE ADS YES | META ADS YES | GOOGLE + META | CONTACTED | FOLLOW-UPS DUE | REPLIES RECEIVED
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        today_str = datetime.date.today().isoformat()

        cur.execute("SELECT COUNT(*) as c FROM leads WHERE duplicate_status != 'MERGED'")
        total_leads = cur.fetchone()["c"]

        # GOOGLE ADS YES
        cur.execute("""
            SELECT COUNT(*) as c FROM leads 
            WHERE duplicate_status != 'MERGED' 
              AND google_ads_status IN ('YES - ACTIVE ADS FOUND', 'Active Ads Found')
        """)
        google_ads_yes = cur.fetchone()["c"]

        # META ADS YES
        cur.execute("""
            SELECT COUNT(*) as c FROM leads 
            WHERE duplicate_status != 'MERGED' 
              AND meta_ads_status IN ('YES - ACTIVE ADS FOUND', 'Active Ads Found')
        """)
        meta_ads_yes = cur.fetchone()["c"]

        # GOOGLE + META
        cur.execute("""
            SELECT COUNT(*) as c FROM leads 
            WHERE duplicate_status != 'MERGED' 
              AND google_ads_status IN ('YES - ACTIVE ADS FOUND', 'Active Ads Found')
              AND meta_ads_status IN ('YES - ACTIVE ADS FOUND', 'Active Ads Found')
        """)
        google_plus_meta = cur.fetchone()["c"]

        # CONTACTED
        cur.execute("SELECT COUNT(*) as c FROM leads WHERE duplicate_status != 'MERGED' AND crm_status = 'CONTACTED'")
        contacted = cur.fetchone()["c"]

        # FOLLOW-UPS DUE
        cur.execute("""
            SELECT COUNT(DISTINCT r.lead_id) as c FROM reminders r
            JOIN leads l ON r.lead_id = l.id
            WHERE r.status = 'PENDING' AND r.reminder_date <= ?
              AND l.duplicate_status != 'MERGED'
              AND l.crm_status NOT IN ('CLIENT', 'NOT INTERESTED', 'DO NOT CONTACT', 'REPLIED')
        """, (today_str,))
        reminders_due = cur.fetchone()["c"]

        # REPLIES RECEIVED
        cur.execute("SELECT COUNT(*) as c FROM leads WHERE duplicate_status != 'MERGED' AND crm_status = 'REPLIED'")
        replies_received = cur.fetchone()["c"]

        # Supplementary counters
        cur.execute("SELECT COUNT(*) as c FROM leads WHERE duplicate_status != 'MERGED' AND (crm_status = 'NEW' OR crm_status IS NULL)")
        new_leads = cur.fetchone()["c"]

        cur.execute("SELECT COUNT(*) as c FROM leads WHERE duplicate_status != 'MERGED' AND crm_status = 'READY TO CONTACT'")
        ready_to_contact = cur.fetchone()["c"]

        cur.execute("SELECT COUNT(*) as c FROM leads WHERE duplicate_status != 'MERGED' AND crm_status = 'QUALIFIED'")
        qualified_prospects = cur.fetchone()["c"]

        cur.execute("SELECT COUNT(*) as c FROM leads WHERE duplicate_status != 'MERGED' AND crm_status = 'CLIENT'")
        clients_count = cur.fetchone()["c"]

        cur.execute("""
            SELECT COUNT(*) as c FROM leads 
            WHERE duplicate_status != 'MERGED' 
              AND ((google_ads_status IS NULL OR google_ads_status IN ('NOT CHECKED', 'Not Checked', ''))
                   OR (meta_ads_status IS NULL OR meta_ads_status IN ('NOT CHECKED', 'Not Checked', '')))
        """)
        needs_ads_verification = cur.fetchone()["c"]

        cur.execute("SELECT COUNT(*) as c FROM daily_notes")
        notes_count = cur.fetchone()["c"]

        return {
            "total_leads": total_leads,
            "google_ads_yes": google_ads_yes,
            "meta_ads_yes": meta_ads_yes,
            "google_plus_meta": google_plus_meta,
            "contacted": contacted,
            "followups_due": reminders_due,
            "replies_received": replies_received,
            "new_leads": new_leads,
            "ready_to_contact": ready_to_contact,
            "qualified_prospects": qualified_prospects,
            "clients_count": clients_count,
            "needs_ads_verification": needs_ads_verification,
            "recent_notes_count": notes_count,
            "notes_count": notes_count
        }
    finally:
        conn.close()


def get_telemetry_stats() -> Dict[str, Any]:
    """Retrieve research engine telemetry statistics."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as c FROM leads WHERE duplicate_status != 'MERGED'")
        total_unique = cur.fetchone()["c"]

        cur.execute("SELECT COUNT(*) as c FROM leads")
        total_records = cur.fetchone()["c"]

        cur.execute("SELECT COUNT(*) as c FROM leads WHERE duplicate_status = 'POTENTIAL_DUPLICATE'")
        duplicates_detected = cur.fetchone()["c"]

        cur.execute("SELECT COUNT(*) as c FROM leads WHERE duplicate_status != 'MERGED' AND phone IS NOT NULL AND phone != '' AND phone != 'NOT AVAILABLE'")
        with_phone = cur.fetchone()["c"]

        cur.execute("SELECT COUNT(*) as c FROM leads WHERE duplicate_status != 'MERGED' AND website IS NOT NULL AND website != '' AND website != 'NOT AVAILABLE'")
        with_website = cur.fetchone()["c"]

        cur.execute("SELECT COUNT(*) as c FROM leads WHERE duplicate_status != 'MERGED' AND email IS NOT NULL AND email != '' AND email != 'NOT AVAILABLE'")
        with_email = cur.fetchone()["c"]

        cur.execute("SELECT COUNT(*) as c FROM leads WHERE enrichment_status = 'ENRICHED'")
        records_enriched = cur.fetchone()["c"]

        cur.execute("SELECT COUNT(*) as c FROM keyword_queue WHERE status = 'QUEUED'")
        items_queued = cur.fetchone()["c"]

        return {
            "records_discovered": total_records,
            "records_reviewed": total_records,
            "new_unique_leads": total_unique,
            "duplicates_detected": duplicates_detected,
            "businesses_with_phone": with_phone,
            "businesses_with_website": with_website,
            "businesses_with_email": with_email,
            "records_enriched": records_enriched,
            "queued_queries": items_queued,
            "paid_api_costs": "$0.00",
            "paid_subscription_costs": "$0.00"
        }
    finally:
        conn.close()


def log_outreach(
    lead_id: int,
    date_sent: Optional[str] = None,
    channel: str = "WhatsApp",
    message_type: str = "First Outreach",
    note: str = "",
    next_followup_date: Optional[str] = None,
    note_id: Optional[int] = None,
    **kwargs
) -> int:
    """
    Record outreach event in contact_history and schedule next follow-up reminder.
    Automatically stops previous reminders and updates lead CRM status.
    Supports automatic Day 0 -> Day +interval_1 -> Day +interval_2 follow-up calculation.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        actual_date = kwargs.get("contact_date") or date_sent or datetime.date.today().isoformat()
        actual_note = kwargs.get("notes") or note
        date_str = actual_date.strip() if isinstance(actual_date, str) and actual_date.strip() else datetime.date.today().isoformat()

        # Check if already logged for this note_id to prevent duplicate history entries
        if note_id:
            cur.execute("SELECT id FROM contact_history WHERE lead_id = ? AND note_id = ?", (lead_id, note_id))
            existing = cur.fetchone()
            if existing:
                return existing["id"]

        # Determine next action, first_contact_date, and followup count
        cur.execute("SELECT followup_count, business_name, first_contact_date FROM leads WHERE id = ?", (lead_id,))
        lead_row = cur.fetchone()
        f_count = (lead_row["followup_count"] or 0) + 1 if lead_row else 1
        biz_name = lead_row["business_name"] if lead_row else "Lead"
        first_c_date = (lead_row["first_contact_date"] if lead_row and lead_row["first_contact_date"] else None) or date_str

        # Auto-calculate next_followup_date from user_settings if not explicitly provided
        effective_next_date = next_followup_date
        if effective_next_date is None:
            cur.execute("SELECT key, value FROM user_settings")
            settings_map = {r["key"]: r["value"] for r in cur.fetchall()}
            int1 = int(settings_map.get("followup_interval_1", "3"))
            int2 = int(settings_map.get("followup_interval_2", "5"))
            max_f = int(settings_map.get("max_followups", "2"))
            try:
                base_dt = datetime.date.fromisoformat(date_str)
            except Exception:
                base_dt = datetime.date.today()

            if f_count == 1 and max_f >= 1:
                effective_next_date = (base_dt + datetime.timedelta(days=int1)).isoformat()
            elif f_count == 2 and max_f >= 2:
                effective_next_date = (base_dt + datetime.timedelta(days=int2)).isoformat()
            else:
                effective_next_date = None
        elif str(effective_next_date).strip().upper() in ("", "NONE", "NULL"):
            effective_next_date = None
        else:
            effective_next_date = str(effective_next_date).strip()

        # Insert history record
        cur.execute("""
            INSERT INTO contact_history (lead_id, date_sent, channel, message_type, note, next_followup_date, note_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (lead_id, date_str, channel, message_type, actual_note, effective_next_date, note_id, now_str))
        history_id = cur.lastrowid

        # Mark existing pending reminders for this lead as COMPLETED
        cur.execute("UPDATE reminders SET status = 'COMPLETED', updated_at = ? WHERE lead_id = ? AND status = 'PENDING'", (now_str, lead_id))

        updates: Dict[str, Any] = {
            "crm_status": "CONTACTED",
            "outreach_status": "CONTACTED",
            "first_contact_date": first_c_date,
            "last_contact_date": date_str,
            "last_contact_channel": channel,
            "followup_count": f_count
        }

        # Schedule reminder if next date is determined
        if effective_next_date:
            updates["next_followup_date"] = effective_next_date
            updates["next_action"] = f"Follow-up due ({effective_next_date})"
            rem_desc = f"Send follow-up #{f_count} to {biz_name} via {channel}"

            cur.execute("""
                INSERT INTO reminders (lead_id, reminder_date, reminder_type, description, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'PENDING', ?, ?)
            """, (lead_id, effective_next_date, f"Follow-up #{f_count}", rem_desc, now_str, now_str))
        else:
            updates["next_action"] = f"Contacted via {channel} (Sequence Complete)"
            updates["next_followup_date"] = None

        update_lead(lead_id, updates, conn=conn)
        conn.commit()
        return history_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_contact_history(lead_id: int) -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM contact_history 
            WHERE lead_id = ? 
            ORDER BY date_sent DESC, id DESC
        """, (lead_id,))
        results = []
        for r in cur.fetchall():
            d = dict(r)
            d["contact_date"] = d.get("date_sent")
            d["notes"] = d.get("note") or ""
            results.append(d)
        return results
    finally:
        conn.close()


def get_due_reminders() -> Dict[str, List[Dict[str, Any]]]:
    """Retrieve today's actions partitioned by overdue, today, tomorrow, and upcoming."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        today = datetime.date.today()
        today_str = today.isoformat()
        tomorrow_str = (today + datetime.timedelta(days=1)).isoformat()

        cur.execute("""
            SELECT r.*, l.business_name, l.phone, l.normalized_phone, l.email, 
                   l.website, l.crm_status, l.last_contact_channel, l.last_contact_date,
                   l.whatsapp_draft, l.email_subject_draft, l.email_body_draft, l.category, l.city
            FROM reminders r
            JOIN leads l ON r.lead_id = l.id
            WHERE r.status = 'PENDING'
              AND l.duplicate_status != 'MERGED'
              AND l.crm_status NOT IN ('CLIENT', 'NOT INTERESTED', 'DO NOT CONTACT', 'REPLIED')
            ORDER BY r.reminder_date ASC
        """)
        rows = [dict(r) for r in cur.fetchall()]

        categorized: Dict[str, List[Dict[str, Any]]] = {
            "overdue": [],
            "today": [],
            "tomorrow": [],
            "upcoming": []
        }

        for r in rows:
            r["lead_number"] = f"#{r['lead_id']:04d}"
            r_date = r["reminder_date"]
            if r_date < today_str:
                categorized["overdue"].append(r)
            elif r_date == today_str:
                categorized["today"].append(r)
            elif r_date == tomorrow_str:
                categorized["tomorrow"].append(r)
            else:
                categorized["upcoming"].append(r)

        categorized["due_today"] = categorized["today"]
        categorized["due_tomorrow"] = categorized["tomorrow"]
        return categorized
    finally:
        conn.close()


def complete_reminder(reminder_id: int) -> bool:
    conn = get_connection()
    try:
        cur = conn.cursor()
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        cur.execute("UPDATE reminders SET status = 'COMPLETED', updated_at = ? WHERE id = ?", (now_str, reminder_id))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def snooze_reminder(reminder_id: int, days: int = 1) -> bool:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT reminder_date FROM reminders WHERE id = ?", (reminder_id,))
        row = cur.fetchone()
        if not row:
            return False

        current_date_str = row["reminder_date"]
        try:
            cur_dt = datetime.date.fromisoformat(current_date_str)
        except Exception:
            cur_dt = datetime.date.today()

        new_dt = max(cur_dt, datetime.date.today()) + datetime.timedelta(days=days)
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()

        cur.execute("UPDATE reminders SET reminder_date = ?, notified = 0, updated_at = ? WHERE id = ?", (new_dt.isoformat(), now_str, reminder_id))
        conn.commit()
        return True
    finally:
        conn.close()


# ==============================================================================
# WHATSAPP & ADS VERIFICATION ACTIONS
# ==============================================================================

def update_whatsapp_verification(
    lead_id: int,
    status: str,
    notes: Optional[str] = None
) -> bool:
    updates = {
        "whatsapp_status": status,
        "whatsapp_last_checked": datetime.date.today().isoformat(),
        "whatsapp_notes": notes or ""
    }
    update_lead(lead_id, updates)
    return True


def update_ads_verification(
    lead_id: int,
    platform: str,  # 'google' or 'meta'
    status: str,
    advertiser_name: Optional[str] = None,
    evidence_url: Optional[str] = None,
    notes: Optional[str] = None
) -> bool:
    """Save manual ads verification result and update consolidated ads_summary."""
    today_str = datetime.date.today().isoformat()
    norm_status = normalize_ad_status(status)

    updates = {}
    st_val = status.strip() if status else "NOT CHECKED"
    if platform.lower() == "google":
        updates["google_ads_status"] = st_val
        if advertiser_name is not None: updates["google_advertiser_name"] = advertiser_name
        if evidence_url is not None: updates["google_evidence_url"] = evidence_url
        updates["google_ads_last_verified"] = today_str
        if notes is not None: updates["google_ads_notes"] = notes
    elif platform.lower() == "meta":
        updates["meta_ads_status"] = st_val
        if advertiser_name is not None: updates["meta_advertiser_name"] = advertiser_name
        if evidence_url is not None: updates["meta_evidence_url"] = evidence_url
        updates["meta_ads_last_verified"] = today_str
        if notes is not None: updates["meta_ads_notes"] = notes

    # Recalculate consolidated summary
    lead = get_lead(lead_id)
    g_status = updates.get("google_ads_status") or (lead.get("google_ads_status") if lead else "NOT CHECKED")
    m_status = updates.get("meta_ads_status") or (lead.get("meta_ads_status") if lead else "NOT CHECKED")
    updates["ads_summary"] = calculate_ads_summary(g_status, m_status)

    update_lead(lead_id, updates)
    return True


# ==============================================================================
# STICKY NOTES CRUD & SMART TEXT-TO-CRM UPDATES
# ==============================================================================

def _extract_associated_leads_str(content: str) -> str:
    """Extract referenced lead IDs from note content as a comma-separated string."""
    if not content:
        return ""
    try:
        from app.note_parser import extract_lead_ids_from_segment
        ids = extract_lead_ids_from_segment(content)
        return ",".join(str(i) for i in ids)
    except Exception:
        return ""


def _enrich_note_dict(d: Dict[str, Any]) -> Dict[str, Any]:
    """Attach normalized alias fields for frontend and API compatibility."""
    c_date = d.get("created_date") or ""
    c_time = d.get("created_time") or ""
    display_time = f"{c_date} {c_time}".strip()
    d["display_time"] = display_time
    d["created_at"] = display_time or d.get("updated_at") or ""
    d["status"] = d.get("processing_status") or "DRAFT"
    d["category"] = d.get("category") or "Outreach"

    assoc_raw = d.get("associated_leads") or ""
    if not assoc_raw and d.get("content"):
        assoc_raw = _extract_associated_leads_str(d.get("content", ""))
        d["associated_leads"] = assoc_raw

    d["linked_lead_ids"] = [
        int(x.strip()) for x in assoc_raw.split(",")
        if x.strip().isdigit()
    ]
    return d


def create_note(
    title: str,
    content: str,
    created_date: Optional[str] = None,
    created_time: Optional[str] = None,
    associated_leads: Optional[str] = None,
    is_pinned: int = 0,
    category: str = "Outreach"
) -> int:
    """Create a new daily sticky note."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        now = datetime.datetime.now()
        c_date = created_date or now.strftime("%Y-%m-%d")
        c_time = created_time or now.strftime("%H:%M:%S")
        note_uid = f"note_{now.strftime('%Y%m%d%H%M%S%f')}"
        now_iso = now.isoformat()

        assoc_val = associated_leads if associated_leads is not None else _extract_associated_leads_str(content)
        cat_val = (category or "Outreach").strip()

        cur.execute("""
            INSERT INTO daily_notes (
                note_uid, title, content, category, created_date, created_time,
                updated_at, associated_leads, processing_status, is_pinned
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'DRAFT', ?)
        """, (
            note_uid,
            title.strip() or "Daily Outreach Note",
            content.strip(),
            cat_val,
            c_date,
            c_time,
            now_iso,
            assoc_val,
            1 if is_pinned else 0
        ))
        note_id = cur.lastrowid
        conn.commit()
        return note_id
    finally:
        conn.close()


def get_notes(
    filter_tab: str = "ALL",
    search_query: str = "",
    date_filter: str = "",
    lead_id: Optional[int] = None,
    channel_filter: str = ""
) -> List[Dict[str, Any]]:
    """Retrieve daily notes with date/tab/search/lead filters."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        today = datetime.date.today()
        today_str = today.isoformat()
        yesterday_str = (today - datetime.timedelta(days=1)).isoformat()
        week_ago_str = (today - datetime.timedelta(days=7)).isoformat()

        query = "SELECT * FROM daily_notes WHERE 1=1"
        params: List[Any] = []

        # Sub-tab filter
        tab = (filter_tab or "ALL").upper()
        if tab == "TODAY":
            query += " AND created_date = ?"
            params.append(today_str)
        elif tab == "YESTERDAY":
            query += " AND created_date = ?"
            params.append(yesterday_str)
        elif tab in ("THIS_WEEK", "THIS WEEK", "WEEK"):
            query += " AND created_date >= ?"
            params.append(week_ago_str)
        elif tab in ("OLDER", "OLDER NOTES"):
            query += " AND created_date < ?"
            params.append(week_ago_str)

        if date_filter:
            query += " AND created_date = ?"
            params.append(date_filter)

        if search_query and search_query.strip():
            sq = f"%{search_query.strip().lower()}%"
            query += " AND (LOWER(title) LIKE ? OR LOWER(content) LIKE ?)"
            params.extend([sq, sq])

        if channel_filter and channel_filter.strip():
            cq = f"%{channel_filter.strip().lower()}%"
            query += " AND (LOWER(content) LIKE ? OR LOWER(category) LIKE ?)"
            params.extend([cq, cq])

        query += " ORDER BY is_pinned DESC, created_date DESC, created_time DESC, id DESC"
        cur.execute(query, params)
        rows = cur.fetchall()

        notes = []
        for r in rows:
            d = _enrich_note_dict(dict(r))
            if lead_id is not None:
                if int(lead_id) not in d["linked_lead_ids"]:
                    continue
            notes.append(d)
        return notes
    finally:
        conn.close()


def get_note(note_id: int) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM daily_notes WHERE id = ?", (note_id,))
        row = cur.fetchone()
        return _enrich_note_dict(dict(row)) if row else None
    finally:
        conn.close()


def update_note(note_id: int, updates: Dict[str, Any]) -> bool:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(daily_notes)")
        valid_cols = {r["name"] for r in cur.fetchall()}

        clean_updates: Dict[str, Any] = {}
        for k, v in updates.items():
            if k in valid_cols and k != "id":
                clean_updates[k] = v

        if "content" in clean_updates and "associated_leads" not in clean_updates:
            clean_updates["associated_leads"] = _extract_associated_leads_str(str(clean_updates["content"] or ""))

        now_iso = datetime.datetime.now().isoformat()
        clean_updates["updated_at"] = now_iso

        set_clause = ", ".join([f"{k} = ?" for k in clean_updates.keys()])
        values = list(clean_updates.values()) + [note_id]
        cur.execute(f"UPDATE daily_notes SET {set_clause} WHERE id = ?", values)
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def delete_note(note_id: int) -> bool:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM daily_notes WHERE id = ?", (note_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def pin_note(note_id: int, is_pinned: int) -> bool:
    return update_note(note_id, {"is_pinned": 1 if is_pinned else 0})


def resolve_leads_for_note_preview(lead_ids: List[int]) -> Dict[str, Any]:
    """
    Resolve lead records for smart text interpretation preview.
    Identifies existing leads and flags missing lead IDs.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        resolved = []
        missing = []

        for lid in lead_ids:
            cur.execute("SELECT id, business_name, category, phone, email, website, crm_status FROM leads WHERE id = ?", (lid,))
            row = cur.fetchone()
            if row:
                d = dict(row)
                d["lead_number"] = f"#{d['id']:04d}"
                d["found"] = True
                resolved.append(d)
            else:
                missing.append(lid)

        return {
            "resolved_leads": resolved,
            "missing_lead_ids": missing,
            "missing_count": len(missing)
        }
    finally:
        conn.close()


def apply_parsed_crm_updates(
    note_id: int,
    actions: List[Dict[str, Any]],
    followup_date: Optional[str] = None,
    note_date: Optional[str] = None
) -> Dict[str, Any]:
    """
    Atomic transaction applying confirmed smart note outreach to the CRM.
    - Updates lead CRM statuses
    - Adds audit records to contact_history
    - Schedules follow-up reminders
    - Prevents duplicate activity records (idempotent re-runs)
    - Records in crm_activity_logs
    - Marks note as PROCESSED
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        effective_date = note_date or datetime.date.today().isoformat()

        updated_lead_ids: Set[int] = set()
        cur.execute("SELECT DISTINCT lead_id FROM contact_history WHERE note_id = ?", (note_id,))
        already_logged_for_note: Set[int] = {r["lead_id"] for r in cur.fetchall()}
        logged_in_this_call: Set[int] = set()

        for act in actions:
            lids = act.get("lead_ids") or []
            if not lids and act.get("lead_id"):
                lids = [act["lead_id"]]
            channel = act.get("channel") or "WhatsApp"
            action_type = act.get("action_type") or "OUTREACH_SENT"
            is_completed = act.get("is_completed", True)
            is_plan = act.get("is_plan_only", False) or (action_type == "PLAN_ONLY")
            outcome = act.get("outcome_status")
            if not outcome and action_type.startswith("STATUS_"):
                outcome = action_type.replace("STATUS_", "", 1)
            act_followup = act.get("followup_date") or (followup_date if not is_plan and outcome != "NOT INTERESTED" else None)

            if is_plan or not is_completed:
                # Section 13: OUTREACH SAFETY: Future plan!
                # Do NOT mark as CONTACTED or log outreach history.
                # Only set scheduled reminder date if act_followup is provided.
                plan_followup = act.get("followup_date") or followup_date
                for lid in lids:
                    cur.execute("SELECT id, business_name, followup_count, crm_status FROM leads WHERE id = ?", (lid,))
                    lead_row = cur.fetchone()
                    if not lead_row:
                        continue
                    updated_lead_ids.add(lid)
                    biz_name = lead_row["business_name"] or "Lead"
                    if plan_followup:
                        cur.execute("UPDATE leads SET next_followup_date = ?, next_action = ? WHERE id = ?",
                                    (plan_followup, f"Plan: {channel} outreach on {plan_followup}", lid))
                        cur.execute("""
                            SELECT id FROM reminders
                            WHERE lead_id = ? AND reminder_date = ? AND reminder_type = ? AND status = 'PENDING'
                        """, (lid, plan_followup, f"Planned {channel}"))
                        if not cur.fetchone():
                            cur.execute("""
                                INSERT INTO reminders (lead_id, reminder_date, reminder_type, description, status, created_at, updated_at)
                                VALUES (?, ?, ?, ?, 'PENDING', ?, ?)
                            """, (lid, plan_followup, f"Planned {channel}", f"Planned {channel} outreach to {biz_name}", now_str, now_str))
                continue

            for lid in lids:
                # Check lead existence
                cur.execute("SELECT id, business_name, followup_count, first_contact_date FROM leads WHERE id = ?", (lid,))
                lead_row = cur.fetchone()
                if not lead_row:
                    continue

                updated_lead_ids.add(lid)
                biz_name = lead_row["business_name"] or "Lead"

                # Cross-call idempotency guard: if this note was already applied in a previous call, skip mutating again
                if lid in already_logged_for_note:
                    continue

                if lid not in logged_in_this_call:
                    f_count = (lead_row["followup_count"] or 0) + 1
                    msg_type = f"Follow-up #{f_count}" if f_count > 1 else "First Outreach"
                    raw_seg = (act.get("raw_text") or "").strip()
                    hist_note = f"Logged via Note #{note_id}: {raw_seg}" if raw_seg else f"Logged via Note #{note_id}"
                    cur.execute("""
                        INSERT INTO contact_history (lead_id, date_sent, channel, message_type, note, next_followup_date, note_id, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (lid, effective_date, channel, msg_type, hist_note, act_followup, note_id, now_str))
                    logged_in_this_call.add(lid)
                else:
                    f_count = lead_row["followup_count"] or 1
                    if outcome:
                        cur.execute("""
                            UPDATE contact_history
                            SET message_type = ?, next_followup_date = ?
                            WHERE lead_id = ? AND note_id = ?
                        """, (f"Status: {outcome}", act_followup if outcome != "NOT INTERESTED" else None, lid, note_id))

                # Cancel previous pending reminders for this lead
                cur.execute("UPDATE reminders SET status = 'COMPLETED', updated_at = ? WHERE lead_id = ? AND status = 'PENDING'", (now_str, lid))

                lead_updates: Dict[str, Any] = {
                    "last_contact_date": effective_date,
                    "last_contact_channel": channel,
                    "followup_count": f_count
                }
                if not lead_row["first_contact_date"]:
                    lead_updates["first_contact_date"] = effective_date

                if outcome == "INTERESTED":
                    lead_updates["crm_status"] = "INTERESTED"
                    lead_updates["outreach_status"] = "INTERESTED"
                    lead_updates["next_action"] = "Interested - Follow up on schedule"
                elif outcome == "REPLIED":
                    lead_updates["crm_status"] = "REPLIED"
                    lead_updates["outreach_status"] = "REPLIED"
                    lead_updates["next_followup_date"] = None
                    lead_updates["next_action"] = "Replied - Ready for response"
                elif outcome == "NOT INTERESTED":
                    lead_updates["crm_status"] = "NOT INTERESTED"
                    lead_updates["outreach_status"] = "NOT INTERESTED"
                    lead_updates["next_followup_date"] = None
                    lead_updates["next_action"] = "Declined"
                else:
                    lead_updates["crm_status"] = "CONTACTED"
                    lead_updates["outreach_status"] = "CONTACTED"

                # Schedule reminder if followup_date provided and not declined/replied
                if act_followup and outcome not in ("NOT INTERESTED", "REPLIED"):
                    lead_updates["next_followup_date"] = act_followup
                    lead_updates["next_action"] = f"Follow-up due ({act_followup})"
                    cur.execute("""
                        INSERT INTO reminders (lead_id, reminder_date, reminder_type, description, status, created_at, updated_at)
                        VALUES (?, ?, ?, ?, 'PENDING', ?, ?)
                    """, (lid, act_followup, f"Follow-up #{f_count}", f"Send follow-up #{f_count} to {biz_name} via {channel}", now_str, now_str))
                else:
                    if outcome not in ("INTERESTED", "REPLIED", "NOT INTERESTED"):
                        lead_updates["next_action"] = f"Contacted via {channel}"

                # Update lead record
                set_clause = ", ".join([f"{k} = ?" for k in lead_updates.keys()])
                vals = list(lead_updates.values()) + [lid]
                cur.execute(f"UPDATE leads SET {set_clause} WHERE id = ?", vals)

        # Record system activity log
        log_desc = f"Processed Daily Note #{note_id}: updated {len(updated_lead_ids)} leads"
        cur.execute("""
            INSERT INTO crm_activity_logs (action_type, description, reference_id, created_at)
            VALUES ('NOTE_PROCESSED', ?, ?, ?)
        """, (log_desc, str(note_id), now_str))

        # Mark note as PROCESSED
        cur.execute("""
            UPDATE daily_notes 
            SET processing_status = 'PROCESSED', processed_at = ?, updated_at = ?
            WHERE id = ?
        """, (now_str, now_str, note_id))

        conn.commit()
        return {
            "success": True,
            "note_id": note_id,
            "updated_leads_count": len(updated_lead_ids),
            "updated_count": len(updated_lead_ids),
            "updated_lead_ids": sorted(list(updated_lead_ids))
        }
    except Exception as ex:
        conn.rollback()
        raise ex
    finally:
        conn.close()


# ==============================================================================
# SETTINGS, DUPLICATES & MERGE OPERATIONS
# ==============================================================================

def get_settings() -> Dict[str, str]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT key, value FROM user_settings")
        return {row["key"]: row["value"] for row in cur.fetchall()}
    finally:
        conn.close()


def update_setting(key: str, value: str):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("INSERT OR REPLACE INTO user_settings (key, value) VALUES (?, ?)", (key, value))
        conn.commit()
    finally:
        conn.close()


def find_potential_duplicates() -> List[Dict[str, Any]]:
    """Return pairs of suspected duplicates based on domain, phone, or name+city."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        results = []
        seen_pairs = set()

        cur.execute("""
            SELECT l1.id as id1, l2.id as id2, 'Matching Official Domain (' || l1.normalized_domain || ')' as reason
            FROM leads l1
            JOIN leads l2 ON l1.normalized_domain = l2.normalized_domain AND l1.id < l2.id
            WHERE l1.normalized_domain IS NOT NULL AND l1.normalized_domain NOT IN ('', 'none', 'not available')
              AND l1.duplicate_status != 'MERGED' AND l2.duplicate_status != 'MERGED'
        """)
        for r in cur.fetchall():
            pair = (r["id1"], r["id2"])
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                results.append({"lead1_id": r["id1"], "lead2_id": r["id2"], "reason": r["reason"]})

        cur.execute("""
            SELECT l1.id as id1, l2.id as id2, 'Matching Phone Number (' || l1.normalized_phone || ')' as reason
            FROM leads l1
            JOIN leads l2 ON l1.normalized_phone = l2.normalized_phone AND l1.id < l2.id
            WHERE l1.normalized_phone IS NOT NULL AND l1.normalized_phone NOT IN ('', 'none', 'not available')
              AND l1.duplicate_status != 'MERGED' AND l2.duplicate_status != 'MERGED'
        """)
        for r in cur.fetchall():
            pair = (r["id1"], r["id2"])
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                results.append({"lead1_id": r["id1"], "lead2_id": r["id2"], "reason": r["reason"]})

        # Fetch full lead details for comparison modal
        output = []
        for d in results:
            l1 = get_lead(d["lead1_id"])
            l2 = get_lead(d["lead2_id"])
            if l1 and l2:
                output.append({
                    "lead1": l1,
                    "lead2": l2,
                    "reason": d["reason"]
                })
        return output
    finally:
        conn.close()


def merge_leads(primary_id: int, secondary_id: int, reason: str = "User Confirmed Duplicate") -> int:
    """Merge secondary lead into primary lead with snapshot and history preservation for full undo."""
    conn = get_connection()
    try:
        p_lead = get_lead(primary_id)
        s_lead = get_lead(secondary_id)
        if not p_lead or not s_lead:
            raise ValueError("Invalid lead IDs for merge.")

        cur = conn.cursor()
        cur.execute("SELECT id FROM contact_history WHERE lead_id = ?", (secondary_id,))
        moved_ch_ids = [r["id"] for r in cur.fetchall()]
        cur.execute("SELECT id FROM reminders WHERE lead_id = ?", (secondary_id,))
        moved_rem_ids = [r["id"] for r in cur.fetchall()]

        s_lead_snap = dict(s_lead)
        s_lead_snap["_moved_contact_history_ids"] = moved_ch_ids
        s_lead_snap["_moved_reminder_ids"] = moved_rem_ids

        p_snap = json.dumps(p_lead)
        s_snap = json.dumps(s_lead_snap)
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()

        cur.execute("""
            INSERT INTO dedup_history (primary_lead_id, merged_lead_id, merge_reason, primary_snapshot, merged_snapshot, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (primary_id, secondary_id, reason, p_snap, s_snap, now_str))
        hist_id = cur.lastrowid

        # Transfer contact history and reminders from secondary to primary
        if moved_ch_ids:
            cur.execute("UPDATE contact_history SET lead_id = ? WHERE lead_id = ?", (primary_id, secondary_id))
        if moved_rem_ids:
            cur.execute("UPDATE reminders SET lead_id = ? WHERE lead_id = ?", (primary_id, secondary_id))

        p_updates: Dict[str, Any] = {}
        p_name = (p_lead.get("business_name") or "").strip()
        s_name = (s_lead.get("business_name") or "").strip()
        if (not p_name or p_name.lower().startswith("http")) and s_name and not s_name.lower().startswith("http"):
            p_updates["business_name"] = s_name

        for fld in (
            "phone", "email", "website", "city", "area", "address", "postal_code", "rating",
            "google_ads_status", "google_advertiser_name", "google_evidence_url",
            "meta_ads_status", "meta_page_name", "meta_evidence_url",
            "facebook_url", "instagram_url", "linkedin_url", "tiktok_url", "youtube_url"
        ):
            p_val = p_lead.get(fld)
            s_val = s_lead.get(fld)
            if (not p_val or p_val in ("NOT AVAILABLE", "NOT CHECKED", "N/A")) and (s_val and s_val not in ("NOT AVAILABLE", "NOT CHECKED", "N/A")):
                p_updates[fld] = s_val

        # Clean URL-encoded %20 in phone if present
        final_phone = p_updates.get("phone") or p_lead.get("phone") or ""
        if "%20" in str(final_phone):
            p_updates["phone"] = str(final_phone).replace("%20", " ")

        # Combine notes
        comb_notes = f"{p_lead.get('notes') or ''}\n[Merged #{secondary_id}]: {s_lead.get('notes') or ''}".strip()
        p_updates["notes"] = comb_notes
        p_updates["duplicate_status"] = "UNIQUE"

        update_lead(primary_id, p_updates, conn=conn)
        update_lead(secondary_id, {"duplicate_status": "MERGED"}, conn=conn)

        conn.commit()
        return hist_id
    finally:
        conn.close()


def merge_all_duplicates(reason: str = "1-Click Bulk Auto-Merge") -> Dict[str, Any]:
    """Merge all detected duplicate candidate pairs in one click."""
    pairs = find_potential_duplicates()
    merged_count = 0
    last_hist_id = None
    merged_secondary_ids = set()

    for item in pairs:
        l1 = item.get("lead1") or {}
        l2 = item.get("lead2") or {}
        id1 = l1.get("id")
        id2 = l2.get("id")
        if not id1 or not id2:
            continue
        if id1 in merged_secondary_ids or id2 in merged_secondary_ids:
            continue

        # Prefer the record whose name is not a raw URL as primary
        n1 = (l1.get("business_name") or "").strip().lower()
        n2 = (l2.get("business_name") or "").strip().lower()
        if n1.startswith("http") and not n2.startswith("http"):
            primary_id, secondary_id = id2, id1
        else:
            primary_id, secondary_id = id1, id2

        try:
            hist_id = merge_leads(primary_id, secondary_id, reason=reason)
            merged_secondary_ids.add(secondary_id)
            merged_count += 1
            last_hist_id = hist_id
        except Exception:
            pass

    return {
        "merged_count": merged_count,
        "last_dedup_history_id": last_hist_id
    }


def undo_merge(dedup_history_id: int) -> bool:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM dedup_history WHERE id = ?", (dedup_history_id,))
        row = cur.fetchone()
        if not row:
            return False

        p_data = json.loads(row["primary_snapshot"])
        m_data = json.loads(row["merged_snapshot"])

        moved_ch_ids = m_data.pop("_moved_contact_history_ids", [])
        moved_rem_ids = m_data.pop("_moved_reminder_ids", [])

        update_lead(p_data["id"], p_data, conn=conn)
        update_lead(m_data["id"], m_data, conn=conn)

        if moved_ch_ids:
            placeholders = ", ".join(["?"] * len(moved_ch_ids))
            cur.execute(f"UPDATE contact_history SET lead_id = ? WHERE id IN ({placeholders})", [m_data["id"]] + moved_ch_ids)
        if moved_rem_ids:
            placeholders = ", ".join(["?"] * len(moved_rem_ids))
            cur.execute(f"UPDATE reminders SET lead_id = ? WHERE id IN ({placeholders})", [m_data["id"]] + moved_rem_ids)

        cur.execute("DELETE FROM dedup_history WHERE id = ?", (dedup_history_id,))
        conn.commit()
        return True
    finally:
        conn.close()


def delete_leads(lead_ids: List[int]) -> int:
    if not lead_ids:
        return 0
    conn = get_connection()
    try:
        cur = conn.cursor()
        placeholders = ", ".join(["?"] * len(lead_ids))
        cur.execute(f"DELETE FROM contact_history WHERE lead_id IN ({placeholders})", lead_ids)
        cur.execute(f"DELETE FROM reminders WHERE lead_id IN ({placeholders})", lead_ids)
        cur.execute(f"DELETE FROM leads WHERE id IN ({placeholders})", lead_ids)
        affected = cur.rowcount
        conn.commit()
        return affected
    finally:
        conn.close()


def clear_all_leads() -> int:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM contact_history")
        cur.execute("DELETE FROM reminders")
        cur.execute("DELETE FROM leads")
        affected = cur.rowcount
        cur.execute("DELETE FROM dedup_history")
        cur.execute("DELETE FROM sqlite_sequence WHERE name IN ('leads', 'contact_history', 'reminders')")
        conn.commit()
        return affected
    finally:
        conn.close()


# ==============================================================================
# LOCAL BACKUP & RESTORE WITH VERIFICATION & 30-BACKUP RETENTION
# ==============================================================================

def rotate_backups(directory: Path, max_keep: int = 30):
    """Clean up oldest verified backups exceeding max_keep retention policy."""
    try:
        if not directory.exists():
            return
        backups = sorted(
            directory.glob("*.db"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )
        if len(backups) > max_keep:
            for old_p in backups[max_keep:]:
                try:
                    old_p.unlink()
                except Exception:
                    pass
    except Exception:
        pass


def check_integrity(db_path: Optional[Path] = None) -> Dict[str, Any]:
    """Execute PRAGMA integrity_check to verify database health."""
    target = db_path or DB_PATH
    if not target.exists():
        return {"status": "Database file does not exist", "healthy": False}
    try:
        conn = sqlite3.connect(str(target))
        cur = conn.cursor()
        cur.execute("PRAGMA integrity_check")
        rows = [r[0] for r in cur.fetchall()]
        conn.close()
        healthy = len(rows) == 1 and rows[0] == "ok"
        return {
            "status": "ok" if healthy else "; ".join(rows),
            "healthy": healthy,
            "database_path": str(target),
            "size_bytes": target.stat().st_size
        }
    except Exception as ex:
        return {"status": str(ex), "healthy": False, "database_path": str(target)}


def preview_backup(backup_path: str) -> Dict[str, Any]:
    """Inspect a backup SQLite file to verify integrity and preview table counts before restore."""
    src_file = Path(backup_path)
    if not src_file.exists():
        raise FileNotFoundError(f"Backup file not found: {backup_path}")

    integrity = check_integrity(src_file)
    if not integrity["healthy"]:
        return {
            "healthy": False,
            "status": integrity["status"],
            "filename": src_file.name,
            "path": str(src_file)
        }

    conn = sqlite3.connect(str(src_file))
    try:
        cur = conn.cursor()
        counts = {}
        for tbl in ("leads", "daily_notes", "contact_history", "reminders"):
            try:
                cur.execute(f"SELECT COUNT(*) FROM {tbl}")
                counts[tbl] = cur.fetchone()[0]
            except Exception:
                counts[tbl] = 0
        st = src_file.stat()
        return {
            "healthy": True,
            "status": "ok",
            "filename": src_file.name,
            "path": str(src_file),
            "size_kb": round(st.st_size / 1024, 1),
            "created_at": datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "leads_count": counts["leads"],
            "notes_count": counts["daily_notes"],
            "contact_history_count": counts["contact_history"],
            "reminders_count": counts["reminders"],
            "counts": counts
        }
    finally:
        conn.close()


def backup_database(custom_dir: Optional[Path] = None) -> str:
    """
    Creates SQLite point-in-time backup with WAL checkpoint,
    stores in both local data/backups and Documents/LocalLeadCRM/Backups,
    verifies backup integrity, and maintains 30-backup retention.
    """
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    target_dirs = [BACKUP_DIR, DOCS_BACKUP_DIR]
    if custom_dir:
        target_dirs.append(custom_dir)

    primary_backup_file = None

    source_conn = get_connection()
    try:
        source_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

        for b_dir in target_dirs:
            try:
                b_dir.mkdir(parents=True, exist_ok=True)
                dest_file = b_dir / f"localleadcrm_backup_{timestamp}.db"
                dest_conn = sqlite3.connect(str(dest_file))
                try:
                    with dest_conn:
                        source_conn.backup(dest_conn)
                finally:
                    dest_conn.close()

                # Verify integrity of backup copy
                ver = check_integrity(dest_file)
                if not ver["healthy"]:
                    dest_file.unlink(missing_ok=True)
                    continue

                if primary_backup_file is None:
                    primary_backup_file = dest_file

                # Enforce 30-backup retention policy
                rotate_backups(b_dir, max_keep=30)
            except Exception:
                pass

        return str(primary_backup_file or (BACKUP_DIR / f"pinora_leads_backup_{timestamp}.db"))
    finally:
        source_conn.close()


def restore_database(backup_path: str) -> bool:
    """
    Safely restore database from a backup:
    1. Creates safety backup of current state first.
    2. Verifies integrity of the target backup.
    3. Restores database.
    """
    src_file = Path(backup_path)
    if not src_file.exists():
        raise FileNotFoundError(f"Backup file not found: {backup_path}")

    # Verify backup file health
    src_check = check_integrity(src_file)
    if not src_check["healthy"]:
        raise ValueError(f"Target backup failed integrity check: {src_check['status']}")

    # 1. Create safety backup first
    safety_ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    safety_file = BACKUP_DIR / f"pre_restore_safety_backup_{safety_ts}.db"
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    curr_conn = get_connection()
    try:
        curr_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        safe_conn = sqlite3.connect(str(safety_file))
        try:
            with safe_conn:
                curr_conn.backup(safe_conn)
        finally:
            safe_conn.close()
    finally:
        curr_conn.close()

    # 2. Restore target backup into DB_PATH
    b_conn = sqlite3.connect(str(src_file))
    main_conn = get_connection()
    try:
        with main_conn:
            b_conn.backup(main_conn)
        main_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return True
    finally:
        b_conn.close()
        main_conn.close()


def get_backups(custom_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Retrieve list of verified local backups."""
    dirs_to_scan = [BACKUP_DIR, DOCS_BACKUP_DIR]
    if custom_dir:
        dirs_to_scan.insert(0, custom_dir)

    all_backups = []
    seen_paths = set()

    for d in dirs_to_scan:
        if not d.exists():
            continue
        for p in d.glob("*.db"):
            sp = str(p.resolve())
            if sp in seen_paths:
                continue
            seen_paths.add(sp)
            try:
                st = p.stat()
                all_backups.append({
                    "filename": p.name,
                    "path": sp,
                    "size_bytes": st.st_size,
                    "size_kb": round(st.st_size / 1024, 1),
                    "created_at": datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    "mtime": st.st_mtime,
                    "folder": str(d)
                })
            except Exception:
                pass

    all_backups.sort(key=lambda b: b["mtime"], reverse=True)
    return all_backups


def check_and_run_daily_backup():
    """Automatic daily backup on startup if latest backup is older than 24 hours."""
    backups = get_backups()
    if not backups:
        backup_database()
        return

    latest_mtime = backups[0]["mtime"]
    now_ts = datetime.datetime.now().timestamp()
    if (now_ts - latest_mtime) > (24 * 3600):
        backup_database()
