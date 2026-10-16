"""
High-Performance Local Web Server for Pinora-Like Local Lead Workspace + Simple CRM.
Built on Python's native http.server with ThreadingHTTPServer.
Exposes REST API endpoints and serves static UI dashboard.
Restricted to localhost (127.0.0.1) for complete local security.
Zero cloud exposure. Zero paid libraries.
"""

import os
import sys
import json
import socket
import datetime
import urllib.parse
import webbrowser
import threading
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Dict, Any, List

# Add parent directory to sys.path so app modules import properly
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.database import (
    init_db, get_connection, get_leads, get_lead, insert_lead, update_lead, delete_leads,
    clear_all_leads, get_telemetry_stats, get_crm_top_stats, find_potential_duplicates,
    merge_leads, merge_all_duplicates, undo_merge, backup_database, restore_database, check_integrity, preview_backup,
    log_outreach, get_contact_history, get_due_reminders, complete_reminder, snooze_reminder,
    update_whatsapp_verification, update_ads_verification, get_settings, update_setting,
    create_note, get_notes, get_note, update_note, delete_note, pin_note,
    resolve_leads_for_note_preview, apply_parsed_crm_updates, get_backups,
    check_and_run_daily_backup, DB_PATH, BACKUP_DIR, DOCS_BACKUP_DIR
)
from app.note_parser import parse_outreach_note
from app.deduplication import normalize_domain, normalize_phone
from app.engine import (
    start_mission, pause_mission, resume_mission, stop_mission, get_mission_status
)
from app.importer import stage_file_for_preview, execute_staged_import
from app.exporter import generate_csv_bytes, generate_xlsx_bytes
from app.reminders_service import check_and_notify_reminders, send_windows_notification

STATIC_DIR = BASE_DIR / "static"


class PinoraRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def log_message(self, format, *args):
        # Suppress verbose standard HTTP access logs for clean console
        pass

    def _send_json(self, data: Any, status: int = 200):
        body = json.dumps(data, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        try:
            return json.loads(raw)
        except Exception:
            return {}

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = urllib.parse.parse_qs(parsed.query)

        # Route API endpoints
        if path == "/api/telemetry":
            self._send_json(get_mission_status())
            return

        elif path == "/api/crm/stats":
            self._send_json(get_crm_top_stats())
            return

        elif path in ("/api/reminders/due", "/api/reminders"):
            due = get_due_reminders()
            self._send_json({**due, "reminders": due})
            return

        elif path == "/api/settings":
            self._send_json(get_settings())
            return

        elif path == "/api/notes":
            tab = params.get("tab", params.get("range", ["ALL"]))[0]
            search = params.get("search", [""])[0]
            date_f = params.get("date", [""])[0]
            channel_f = params.get("channel", [""])[0]
            lead_id_f = int(params.get("lead_id", [0])[0]) if params.get("lead_id", [0])[0] else None
            notes = get_notes(filter_tab=tab, search_query=search, date_filter=date_f, lead_id=lead_id_f, channel_filter=channel_f)
            self._send_json({"notes": notes, "count": len(notes)})
            return

        elif path.startswith("/api/notes/") and len(path.split("/")) == 4:
            try:
                note_id = int(path.split("/")[-1])
                note = get_note(note_id)
                if note:
                    self._send_json(note)
                else:
                    self._send_json({"error": "Note not found"}, 404)
            except Exception:
                self._send_json({"error": "Invalid note ID"}, 400)
            return

        elif path == "/api/leads":
            filters = {}
            for k in [
                "city", "postal_code", "category", "outreach_status", "crm_status",
                "ads_summary", "ads_filter", "google_ads_status", "meta_ads_status", "whatsapp_status",
                "duplicate_status", "enrichment_status"
            ]:
                if k in params:
                    filters[k] = params[k][0]
            
            for b_key in ["has_phone", "has_website", "no_website", "has_email", "missing_email", "has_social", "verified_advertisers_only"]:
                if b_key in params:
                    filters[b_key] = params[b_key][0].lower() in ("true", "1", "yes")

            if "min_rating" in params:
                filters["min_rating"] = params["min_rating"][0]
            if "min_reviews" in params:
                filters["min_reviews"] = params["min_reviews"][0]

            search_text = params.get("search", [""])[0]
            limit = int(params.get("limit", [150])[0])
            offset = int(params.get("offset", [0])[0])
            order_by = params.get("order_by", ["id DESC"])[0]

            leads, total = get_leads(filters=filters, search_text=search_text, limit=limit, offset=offset, order_by=order_by)
            self._send_json({"leads": leads, "total": total, "limit": limit, "offset": offset})
            return

        elif path.startswith("/api/leads/") and path.endswith("/history"):
            parts = path.strip("/").split("/")
            try:
                lead_id = int(parts[2])
                self._send_json({"history": get_contact_history(lead_id)})
            except Exception:
                self._send_json({"error": "Invalid lead ID"}, 400)
            return

        elif path.startswith("/api/leads/") and len(path.split("/")) == 4:
            lead_id = int(path.split("/")[-1])
            lead = get_lead(lead_id)
            if lead:
                self._send_json({**lead, "lead": lead})
            else:
                self._send_json({"error": "Lead not found"}, 404)
            return

        elif path == "/api/duplicates":
            dupes = find_potential_duplicates()
            self._send_json({"duplicates": dupes, "count": len(dupes)})
            return

        elif path == "/api/export":
            export_fmt = params.get("format", ["csv"])[0].lower()
            filters = {}
            for k in ["city", "postal_code", "category", "outreach_status", "crm_status", "duplicate_status", "enrichment_status", "ads_filter"]:
                if k in params:
                    filters[k] = params[k][0]
            for b_key in ["has_phone", "has_website", "no_website", "has_email", "missing_email", "has_social", "verified_advertisers_only"]:
                if b_key in params:
                    filters[b_key] = params[b_key][0].lower() in ("true", "1", "yes")
            
            search_text = params.get("search", [""])[0]
            leads, _ = get_leads(filters=filters, search_text=search_text, limit=50000, offset=0)

            selected_fields = params.get("fields", None)

            if export_fmt == "xlsx":
                data_bytes = generate_xlsx_bytes(leads, selected_fields)
                filename = f"leads_export_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
                content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            else:
                data_bytes = generate_csv_bytes(leads, selected_fields)
                filename = f"leads_export_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                content_type = "text/csv; charset=utf-8"

            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(len(data_bytes)))
            self.end_headers()
            self.wfile.write(data_bytes)
            return

        elif path in ("/api/database/backups", "/api/backups"):
            self._send_json({"backups": get_backups()})
            return

        elif path == "/api/database/backup-preview":
            b_path = params.get("path", [""])[0]
            try:
                self._send_json({"success": True, "preview": preview_backup(b_path)})
            except Exception as ex:
                self._send_json({"success": False, "error": str(ex)}, 400)
            return

        elif path in ("/api/database/backup", "/api/backup/now"):
            try:
                bkp = backup_database()
                self._send_json({
                    "success": True,
                    "status": "success",
                    "backup_path": bkp,
                    "filename": Path(bkp).name,
                    "verified": True
                })
            except Exception as ex:
                self._send_json({"success": False, "status": "error", "error": str(ex)}, 400)
            return

        elif path == "/api/database/integrity":
            self._send_json(check_integrity())
            return

        # Serve static files or fallback to index.html
        if path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/mission/start":
            body = self._read_json_body()
            keywords = body.get("keywords", [])
            if isinstance(keywords, str):
                keywords = [k.strip() for k in keywords.split("\n") if k.strip()]
            city = body.get("city", "").strip()
            postal_code = body.get("postal_code", "").strip() if body.get("postal_code") else ""
            country = body.get("country", "United States")
            raw_max = body.get("max_results", 0)
            try:
                max_results = int(raw_max)
            except (ValueError, TypeError):
                max_results = 0
            hunt_emails = bool(body.get("hunt_emails", True))
            auto_dedup = bool(body.get("auto_dedup", True))

            res = start_mission(keywords, city, postal_code, country, max_results, hunt_emails, auto_dedup)
            self._send_json(res)
            return

        elif path == "/api/mission/pause":
            self._send_json(pause_mission())
            return

        elif path == "/api/mission/resume":
            self._send_json(resume_mission())
            return

        elif path == "/api/mission/stop":
            self._send_json(stop_mission())
            return

        elif path == "/api/notes":
            body = self._read_json_body()
            title = body.get("title", "")
            content = body.get("content", "")
            c_date = body.get("created_date")
            c_time = body.get("created_time")
            assoc = body.get("associated_leads")
            is_pinned = int(body.get("is_pinned", 0))
            category = body.get("category", "Outreach")
            try:
                note_id = create_note(title, content, c_date, c_time, assoc, is_pinned, category=category)
                note_obj = get_note(note_id)
                self._send_json({"success": True, "id": note_id, "note_id": note_id, "note": note_obj})
            except Exception as ex:
                self._send_json({"success": False, "error": str(ex)}, 400)
            return

        elif path.startswith("/api/notes/") and path.endswith("/pin"):
            parts = path.strip("/").split("/")
            try:
                note_id = int(parts[2])
                body = self._read_json_body()
                if "is_pinned" in body:
                    is_pinned = int(body.get("is_pinned", 1))
                else:
                    existing_note = get_note(note_id)
                    is_pinned = 0 if (existing_note and existing_note.get("is_pinned")) else 1
                success = pin_note(note_id, is_pinned)
                self._send_json({"success": success, "is_pinned": is_pinned, "note": get_note(note_id)})
            except Exception as ex:
                self._send_json({"success": False, "error": str(ex)}, 400)
            return

        elif path.startswith("/api/notes/") and path.endswith("/parse"):
            parts = path.strip("/").split("/")
            try:
                note_id = int(parts[2])
                note = get_note(note_id)
                if not note:
                    self._send_json({"success": False, "error": "Note not found"}, 404)
                    return
                body = self._read_json_body()
                custom_text = body.get("content") or note["content"]
                custom_date = body.get("created_date") or note["created_date"]

                parsed = parse_outreach_note(custom_text, custom_date)
                preview = resolve_leads_for_note_preview(parsed["targeted_lead_ids"])
                parsed["resolved_leads"] = preview["resolved_leads"]
                parsed["missing_lead_ids"] = preview["missing_lead_ids"]
                parsed["missing_ids"] = preview["missing_lead_ids"]
                parsed["missing_count"] = preview["missing_count"]

                resp = {"success": True, "note_id": note_id, "interpretation": parsed, "parsed": parsed}
                resp.update(parsed)
                self._send_json(resp)
            except Exception as ex:
                self._send_json({"success": False, "error": str(ex)}, 400)
            return

        elif path.startswith("/api/notes/") and path.endswith("/apply-crm"):
            parts = path.strip("/").split("/")
            try:
                note_id = int(parts[2])
                note = get_note(note_id)
                body = self._read_json_body()
                actions = body.get("actions", [])
                followup_date = body.get("followup_date") or body.get("next_followup_date")
                note_date = body.get("note_date") or (note["created_date"] if note else None)

                # If caller sent flat { channel, next_followup_date, lead_ids, is_plan_only } without actions array:
                if not actions and body.get("lead_ids"):
                    raw_lids = [int(x) for x in body.get("lead_ids", [])]
                    # Check if we can parse the note's rich multi-action structure and filter to checked lead_ids
                    if note and note.get("content"):
                        parsed_note = parse_outreach_note(note["content"], note_date)
                        parsed_acts = parsed_note.get("actions", [])
                        if parsed_acts:
                            allowed_set = set(raw_lids)
                            override_ch = body.get("channel")
                            for pa in parsed_acts:
                                filtered_ids = [lid for lid in pa.get("lead_ids", []) if lid in allowed_set]
                                if filtered_ids:
                                    act_copy = dict(pa)
                                    act_copy["lead_ids"] = filtered_ids
                                    if override_ch and len(parsed_acts) == 1:
                                        act_copy["channel"] = override_ch
                                    if followup_date and not act_copy.get("is_plan_only") and act_copy.get("outcome_status") != "NOT INTERESTED":
                                        if not act_copy.get("followup_date") or len(parsed_acts) == 1:
                                            act_copy["followup_date"] = followup_date
                                    actions.append(act_copy)
                    if not actions:
                        is_plan = bool(body.get("is_plan_only", False))
                        actions = [{
                            "lead_ids": raw_lids,
                            "channel": body.get("channel", "WhatsApp"),
                            "is_plan_only": is_plan,
                            "is_completed": not is_plan,
                            "action_type": "PLAN_ONLY" if is_plan else "OUTREACH_SENT",
                            "followup_date": followup_date
                        }]

                result = apply_parsed_crm_updates(note_id, actions, followup_date, note_date)
                self._send_json(result)
            except Exception as ex:
                self._send_json({"success": False, "error": str(ex)}, 400)
            return

        elif path == "/api/outreach/log":
            body = self._read_json_body()
            lead_id = int(body.get("lead_id", 0))
            date_sent = body.get("date_sent", "")
            channel = body.get("channel", "WhatsApp")
            message_type = body.get("message_type", "First Outreach")
            note = body.get("note", "")
            next_followup_date = body.get("next_followup_date", None)
            try:
                hist_id = log_outreach(lead_id, date_sent, channel, message_type, note, next_followup_date)
                self._send_json({"success": True, "history_id": hist_id, "lead": get_lead(lead_id)})
            except Exception as ex:
                self._send_json({"success": False, "error": str(ex)}, 400)
            return

        elif path.startswith("/api/leads/") and path.endswith("/ads-verification"):
            parts = path.strip("/").split("/")
            try:
                lead_id = int(parts[2])
                body = self._read_json_body()
                platform = body.get("platform", "google")
                status = body.get("status", "Not Checked")
                adv_name = body.get("advertiser_name", "")
                ev_url = body.get("evidence_url", "")
                notes = body.get("notes", "")
                update_ads_verification(lead_id, platform, status, adv_name, ev_url, notes)
                self._send_json({"success": True, "lead": get_lead(lead_id)})
            except Exception as ex:
                self._send_json({"success": False, "error": str(ex)}, 400)
            return

        elif path.startswith("/api/leads/") and path.endswith("/whatsapp-verification"):
            parts = path.strip("/").split("/")
            try:
                lead_id = int(parts[2])
                body = self._read_json_body()
                status = body.get("status", "Not Checked")
                notes = body.get("notes", "")
                update_whatsapp_verification(lead_id, status, notes)
                self._send_json({"success": True, "lead": get_lead(lead_id)})
            except Exception as ex:
                self._send_json({"success": False, "error": str(ex)}, 400)
            return

        elif path.startswith("/api/reminders/") and path.endswith("/complete"):
            parts = path.strip("/").split("/")
            try:
                rem_id = int(parts[2])
                res = complete_reminder(rem_id)
                self._send_json({"success": res})
            except Exception as ex:
                self._send_json({"success": False, "error": str(ex)}, 400)
            return

        elif path.startswith("/api/reminders/") and path.endswith("/snooze"):
            parts = path.strip("/").split("/")
            try:
                rem_id = int(parts[2])
                body = self._read_json_body()
                days = int(body.get("days", 1))
                res = snooze_reminder(rem_id, days)
                self._send_json({"success": res})
            except Exception as ex:
                self._send_json({"success": False, "error": str(ex)}, 400)
            return

        elif path == "/api/reminders/test":
            send_windows_notification("🔔 PINORA CRM TEST", "Desktop notification test successful! Local reminder system is functioning properly.")
            self._send_json({"success": True})
            return

        elif path == "/api/settings":
            body = self._read_json_body()
            for k, v in body.items():
                update_setting(k, str(v))
            self._send_json({"success": True, "settings": get_settings()})
            return

        elif path == "/api/browser-open":
            body = self._read_json_body()
            target_url = body.get("url", "")
            if target_url.startswith(("http://", "https://")):
                threading.Thread(target=lambda: webbrowser.open(target_url), daemon=True).start()
                self._send_json({"success": True, "opened": target_url})
            else:
                self._send_json({"error": "Invalid URL"}, 400)
            return

        elif path == "/api/leads":
            body = self._read_json_body()
            if not body.get("business_name"):
                self._send_json({"error": "Business name is required"}, 400)
                return
            
            lead_data = {
                "business_name": body.get("business_name", "").strip(),
                "category": body.get("category", "General"),
                "specific_service": body.get("specific_service", ""),
                "country": body.get("country", "United States"),
                "city": body.get("city", ""),
                "area": body.get("area", ""),
                "postal_code": body.get("postal_code", ""),
                "address": body.get("address", ""),
                "phone": body.get("phone", "NOT AVAILABLE"),
                "normalized_phone": normalize_phone(body.get("phone")),
                "email": body.get("email", "NOT AVAILABLE"),
                "email_source_url": body.get("email_source_url", "Manual Capture"),
                "website": body.get("website", "NOT AVAILABLE"),
                "normalized_domain": normalize_domain(body.get("website")),
                "crm_status": body.get("crm_status", "NEW"),
                "outreach_status": body.get("crm_status", "NEW"),
                "whatsapp_status": body.get("whatsapp_status", "Not Checked"),
                "google_ads_status": body.get("google_ads_status", "Not Checked"),
                "meta_ads_status": body.get("meta_ads_status", "Not Checked"),
                "next_action": body.get("next_action", "Ready to Contact"),
                "next_followup_date": body.get("next_followup_date"),
                "rating": float(body["rating"]) if body.get("rating") else None,
                "reviews_count": int(body["reviews_count"]) if body.get("reviews_count") else None,
                "notes": body.get("notes", "Captured manually"),
                "source_name": body.get("source_name", "Browser-Assisted Quick Capture"),
                "source_url": body.get("source_url", "Manual Inspection"),
                "research_date": datetime.date.today().isoformat(),
                "data_confidence": "HIGH"
            }
            lead_id, dup_status = insert_lead(lead_data)
            self._send_json({"success": True, "lead_id": lead_id, "duplicate_status": dup_status})
            return

        elif path == "/api/leads/bulk-capture":
            body = self._read_json_body()
            incoming = body.get("leads", [])
            query_kw = body.get("query", "Google Maps Search")
            city = body.get("city", "")
            source_name = body.get("source_name", "Google Maps Extractor")

            inserted = 0
            duplicates = 0
            skipped_no_website = 0
            saved_ids = []

            conn = get_connection()
            try:
                for item in incoming:
                    biz_name = (item.get("business_name") or item.get("name") or "").strip()
                    if not biz_name:
                        continue

                    raw_web = (item.get("website") or "").strip()
                    if not raw_web or raw_web.upper() == "NOT AVAILABLE":
                        skipped_no_website += 1
                        continue
                    if not raw_web.startswith(("http://", "https://")):
                        raw_web = "https://" + raw_web

                    place_uid = item.get("place_id") or item.get("lead_uid") or f"gmap_{abs(hash(biz_name + str(item.get('address', ''))))}"

                    lead_data = {
                        "lead_uid": place_uid,
                        "business_name": biz_name,
                        "category": item.get("category") or query_kw.title(),
                        "specific_service": query_kw.title(),
                        "country": item.get("country", "United States"),
                        "city": item.get("city") or city or "NOT AVAILABLE",
                        "area": item.get("area", "NOT AVAILABLE"),
                        "postal_code": item.get("postal_code", "NOT AVAILABLE"),
                        "address": item.get("address", "NOT AVAILABLE"),
                        "phone": item.get("phone") or "NOT AVAILABLE",
                        "normalized_phone": normalize_phone(item.get("phone")),
                        "email": item.get("email") or "NOT AVAILABLE",
                        "email_source_url": "Google Maps Listing" if item.get("email") else "NOT AVAILABLE",
                        "website": raw_web,
                        "normalized_domain": normalize_domain(raw_web),
                        "crm_status": "NEW",
                        "outreach_status": "NEW",
                        "whatsapp_status": "Not Checked",
                        "google_ads_status": "Not Checked",
                        "meta_ads_status": "Not Checked",
                        "next_action": "Ready to Contact",
                        "rating": float(item["rating"]) if item.get("rating") else None,
                        "reviews_count": int(item["reviews_count"]) if item.get("reviews_count") else None,
                        "notes": f"Captured from Google Maps for query: {query_kw}",
                        "source_name": source_name,
                        "source_url": item.get("url") or item.get("source_url") or "Google Maps",
                        "research_date": datetime.date.today().isoformat(),
                        "data_confidence": "HIGH"
                    }

                    try:
                        lead_id, dup_status = insert_lead(lead_data, conn=conn)
                        if dup_status == "UNIQUE":
                            inserted += 1
                            saved_ids.append(lead_id)
                        else:
                            duplicates += 1
                    except Exception:
                        duplicates += 1
                conn.commit()
            finally:
                conn.close()

            self._send_json({
                "success": True,
                "total_received": len(incoming),
                "inserted_count": inserted,
                "duplicates_count": duplicates,
                "skipped_no_website": skipped_no_website,
                "saved_ids": saved_ids
            })
            return

        elif path == "/api/duplicates/merge":
            body = self._read_json_body()
            primary_id = int(body.get("primary_id", 0))
            secondary_id = int(body.get("secondary_id", 0))
            reason = body.get("reason", "Manual User Merge")
            try:
                hist_id = merge_leads(primary_id, secondary_id, reason)
                self._send_json({"success": True, "dedup_history_id": hist_id})
            except Exception as ex:
                self._send_json({"success": False, "error": str(ex)}, 400)
            return

        elif path == "/api/duplicates/merge-all":
            try:
                res = merge_all_duplicates(reason="1-Click Bulk Auto-Merge")
                self._send_json({
                    "success": True,
                    "merged_count": res["merged_count"],
                    "dedup_history_id": res["last_dedup_history_id"]
                })
            except Exception as ex:
                self._send_json({"success": False, "error": str(ex)}, 400)
            return

        elif path == "/api/duplicates/undo":
            body = self._read_json_body()
            dedup_id = int(body.get("dedup_history_id", 0))
            success = undo_merge(dedup_id)
            self._send_json({"success": success})
            return

        elif path == "/api/leads/clear":
            count = clear_all_leads()
            self._send_json({"success": True, "cleared_count": count})
            return

        elif path == "/api/import/preview":
            content_type = self.headers.get("Content-Type", "")
            length = int(self.headers.get("Content-Length", 0))
            raw_bytes = self.rfile.read(length)

            if "multipart/form-data" in content_type:
                boundary = content_type.split("boundary=")[-1].strip().encode("utf-8")
                parts = raw_bytes.split(b"--" + boundary)
                file_bytes = b""
                filename = "uploaded.csv"
                for p in parts:
                    if b'filename="' in p:
                        fn_part = p.split(b'filename="')[1].split(b'"')[0].decode("utf-8", errors="replace")
                        if fn_part:
                            filename = fn_part
                        header_sep = b"\r\n\r\n"
                        if header_sep in p:
                            file_bytes = p.split(header_sep, 1)[1].rstrip(b"\r\n")
                            break
            else:
                file_bytes = raw_bytes
                filename = "direct_upload.csv"

            try:
                preview_data = stage_file_for_preview(file_bytes, filename)
                self._send_json({"success": True, "preview": preview_data})
            except Exception as ex:
                self._send_json({"success": False, "error": str(ex)}, 400)
            return

        elif path == "/api/import/execute":
            body = self._read_json_body()
            token = body.get("token", "")
            mapping = body.get("mapping", {})
            try:
                result = execute_staged_import(token, mapping)
                self._send_json(result)
            except Exception as ex:
                self._send_json({"success": False, "error": str(ex)}, 400)
            return

        elif path == "/api/database/backup-preview":
            body = self._read_json_body()
            backup_path = body.get("backup_path", "")
            try:
                prev = preview_backup(backup_path)
                self._send_json({**prev, "success": True, "preview": prev})
            except Exception as ex:
                self._send_json({"success": False, "error": str(ex)}, 400)
            return

        elif path == "/api/leads/delete":
            body = self._read_json_body()
            lead_ids = body.get("lead_ids") or body.get("ids") or []
            if lead_ids:
                count = delete_leads(lead_ids)
                self._send_json({"success": True, "deleted_count": count})
            else:
                self._send_json({"error": "No lead IDs specified"}, 400)
            return

        elif path in ("/api/database/backup", "/api/backup/now"):
            try:
                bkp = backup_database()
                self._send_json({
                    "success": True,
                    "status": "success",
                    "backup_path": bkp,
                    "filename": Path(bkp).name,
                    "verified": True
                })
            except Exception as ex:
                self._send_json({"success": False, "status": "error", "error": str(ex)}, 400)
            return

        elif path in ("/api/database/restore", "/api/backup/restore"):
            body = self._read_json_body()
            backup_path = body.get("backup_path", "")
            try:
                restore_database(backup_path)
                self._send_json({"success": True, "status": "success", "message": "Database successfully restored."})
            except Exception as ex:
                self._send_json({"success": False, "status": "error", "error": str(ex)}, 400)
            return

        elif path == "/api/browser-search":
            body = self._read_json_body()
            keyword = body.get("keyword", "business")
            location = body.get("location", "")
            search_query = f"{keyword} {location}".strip()
            encoded_query = urllib.parse.quote_plus(search_query)
            target_url = f"https://www.google.com/search?q={encoded_query}"
            threading.Thread(target=lambda: webbrowser.open(target_url)).start()
            self._send_json({"success": True, "opened_url": target_url, "query": search_query})
            return

        elif path == "/api/shutdown":
            self._send_json({"success": True, "message": "Server shutting down..."})
            def delayed_shutdown():
                import time
                time.sleep(0.5)
                os._exit(0)
            threading.Thread(target=delayed_shutdown).start()
            return

        self._send_json({"error": "Endpoint not found"}, 404)

    def do_PUT(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/leads/") and len(path.split("/")) == 4:
            lead_id = int(path.split("/")[-1])
            body = self._read_json_body()
            update_lead(lead_id, body)
            self._send_json({"success": True, "lead": get_lead(lead_id)})
            return
        elif path.startswith("/api/notes/") and len(path.split("/")) == 4:
            note_id = int(path.split("/")[-1])
            body = self._read_json_body()
            success = update_note(note_id, body)
            self._send_json({"success": success, "note": get_note(note_id)})
            return
        self._send_json({"error": "Endpoint not found"}, 404)

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/api/leads":
            body = self._read_json_body()
            lead_ids = body.get("lead_ids") or body.get("ids") or []
            if lead_ids:
                count = delete_leads(lead_ids)
                self._send_json({"success": True, "deleted_count": count})
            else:
                self._send_json({"error": "No lead IDs specified"}, 400)
            return
        elif path.startswith("/api/notes/") and len(path.split("/")) == 4:
            note_id = int(path.split("/")[-1])
            success = delete_note(note_id)
            self._send_json({"success": success})
            return
        self._send_json({"error": "Endpoint not found"}, 404)


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0


def run_server(port: int = 3847, auto_open: bool = True):
    init_db()
    check_and_run_daily_backup()

    target_port = port
    if is_port_in_use(target_port):
        print(f"[!] Warning: Port {target_port} is currently in use.")
        for p in range(target_port + 1, target_port + 10):
            if not is_port_in_use(p):
                target_port = p
                print(f"[+] Automatically switching to open port: {target_port}")
                break

    server_address = ("127.0.0.1", target_port)
    httpd = ThreadingHTTPServer(server_address, PinoraRequestHandler)

    url = f"http://127.0.0.1:{target_port}"
    print("=" * 60)
    print("  PINORA-LIKE LOCAL LEAD WORKSPACE + CRM")
    print("  Zero Paid API Cost | Local-First Architecture")
    print("=" * 60)
    print(f"  > Dashboard running at: {url}")
    print(f"  > Database location:    {DB_PATH}")
    print(f"  > Backups directory:    {DOCS_BACKUP_DIR}")
    print(f"  > Status:               Ready and Listening")
    print("=" * 60)

    pid_file = BASE_DIR / "server.pid"
    with open(pid_file, "w") as f:
        f.write(str(os.getpid()))

    if auto_open:
        def open_browser():
            import time
            time.sleep(1.0)
            webbrowser.open(url)
        threading.Thread(target=open_browser, daemon=True).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[+] Graceful shutdown requested. Exiting...")
    finally:
        httpd.server_close()
        if pid_file.exists():
            try:
                pid_file.unlink()
            except Exception:
                pass


if __name__ == "__main__":
    port = 3847
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        port = int(sys.argv[1])
    run_server(port=port)
