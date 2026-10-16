"""
Deterministic, 100% Local Text-to-CRM Parser.
Zero AI API keys, zero cloud dependencies.
Extracts outreach activities, lead ranges, channels, outcomes, and dates from plain text.
Supports English, Banglish, and mixed daily outreach descriptions.
Includes outreach safety: distinguishes completed activity from future plans.
"""

import re
import datetime
from typing import Dict, Any, List, Optional, Set, Tuple

# Day of week mapping
DAY_NAMES = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
    "sombar": 0, "mongolbar": 1, "budhbar": 2, "brihospotibar": 3,
    "shukrobar": 4, "shonibar": 5, "robibar": 6
}

MONTH_NAMES = {
    "january": 1, "jan": 1, "february": 2, "feb": 2,
    "march": 3, "mar": 3, "april": 4, "apr": 4,
    "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11,
    "december": 12, "dec": 12
}


def parse_date_reference(text: str, base_date: Optional[datetime.date] = None) -> Optional[str]:
    """
    Deterministically resolves explicit and relative date expressions
    to an ISO date (YYYY-MM-DD) based on base_date (defaults to today).
    """
    if base_date is None:
        base_date = datetime.date.today()

    lower = text.lower()

    # 1. Relative offset: "in N days", "N days por", "N day por", "after N days"
    rel_match = re.search(r'\b(?:in\s+|after\s+)?(\d+)\s*(?:days?|din|diner)\s*(?:por|later|after)?\b', lower)
    if rel_match:
        days = int(rel_match.group(1))
        # Ensure it's not a lead range match
        if not re.search(r'\bleads?\s+' + rel_match.group(1), lower):
            return (base_date + datetime.timedelta(days=days)).isoformat()

    # 2. "Tomorrow", "kal", "agamikal"
    if re.search(r'\b(?:tomorrow|kal|agamikal)\b', lower) and not re.search(r'\bgoto\s+kal\b', lower):
        return (base_date + datetime.timedelta(days=1)).isoformat()

    # 3. "Day after tomorrow", "porshu", "agami porshu"
    if re.search(r'\b(?:day after tomorrow|porshu|agami porshu)\b', lower):
        return (base_date + datetime.timedelta(days=2)).isoformat()

    # 4. "Next <Weekday>", e.g. "next Monday", "next sombar"
    for day_name, target_weekday in DAY_NAMES.items():
        if re.search(rf'\b(?:next\s+|agami\s+){day_name}\b', lower):
            current_weekday = base_date.weekday()
            days_ahead = (target_weekday - current_weekday) % 7
            if days_ahead == 0:
                days_ahead = 7
            return (base_date + datetime.timedelta(days=days_ahead)).isoformat()

    # 5. Explicit date: "13 October", "13th October 2026", "October 13", "13 Oct"
    # Format: Day Month (Year)
    for m_name, m_num in MONTH_NAMES.items():
        # "13 October" or "13th October 2026"
        dm_match = re.search(rf'\b(\d{{1,2}})(?:st|nd|rd|th)?\s+{m_name}(?:\s+(\d{{4}}))?\b', lower)
        if dm_match:
            day = int(dm_match.group(1))
            year = int(dm_match.group(2)) if dm_match.group(2) else base_date.year
            try:
                dt = datetime.date(year, m_num, day)
                # If date already passed in current year and no year specified, assume current year
                return dt.isoformat()
            except ValueError:
                pass

        # "October 13" or "October 13th, 2026"
        md_match = re.search(rf'\b{m_name}\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:\s*,?\s*(\d{{4}}))?\b', lower)
        if md_match:
            day = int(md_match.group(1))
            year = int(md_match.group(2)) if md_match.group(2) else base_date.year
            try:
                dt = datetime.date(year, m_num, day)
                return dt.isoformat()
            except ValueError:
                pass

    # 6. Standard ISO format: "2026-10-13" or "13-10-2026"
    iso_match = re.search(r'\b(\d{4})-(\d{1,2})-(\d{1,2})\b', lower)
    if iso_match:
        try:
            return datetime.date(int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3))).isoformat()
        except ValueError:
            pass

    return None


def extract_lead_ids(text: str) -> List[int]:
    """
    Extracts explicit lead IDs and ranges from a sentence or phrase.
    Supports:
    - '#1-15', 'leads #1-15', '#1 to #15', 'leads 1 to 15'
    - 'lead 30 theke 45 porjonto', 'lead 30 theke 45'
    - '#52', 'lead #52', 'lead 52', '#0001'
    """
    ids: Set[int] = set()

    # Normalize text
    clean = text.replace(",", " ")

    # 1. Range: "#1-15", "1-15", "1 to 15", "30 theke 45"
    range_patterns = [
        r'(?:leads?|#)?\s*#?(\d+)\s*(?:-|to|theke)\s*#?(\d+)(?:\s*(?:porjonto|por))?',
    ]
    for pat in range_patterns:
        for m in re.finditer(pat, clean, re.IGNORECASE):
            # Check if this looks like a date range instead (e.g. 2026-10-13)
            start_pos = m.start()
            if start_pos > 0 and clean[start_pos - 1] in ('-', '/'):
                continue
            start_num = int(m.group(1))
            end_num = int(m.group(2))
            if start_num <= end_num and (end_num - start_num) < 1000:
                for i in range(start_num, end_num + 1):
                    ids.add(i)

    # 2. Individual IDs: "#52", "#0001", "lead 52", "lead #52"
    single_patterns = [
        r'#0*(\d+)\b',
        r'\bleads?\s+#?0*(\d+)\b'
    ]
    for pat in single_patterns:
        for m in re.finditer(pat, clean, re.IGNORECASE):
            ids.add(int(m.group(1)))

    return sorted(list(ids))


# Alias for database helper compatibility
extract_lead_ids_from_segment = extract_lead_ids


def detect_channel(text: str) -> Optional[str]:
    """Identify communication channel mentioned in text."""
    lower = text.lower()
    if re.search(r'\b(?:whatsapp|whats\s*app|wa)\b', lower):
        return "WhatsApp"
    if re.search(r'\b(?:email|emails?|cold\s*email|mail|gmail)\b', lower):
        return "Email"
    if re.search(r'\b(?:call|called|calling|phone\s*call)\b', lower):
        return "Phone"
    return None


def is_plan_only(text: str) -> bool:
    """
    Safety check: Identifies if statement is a future intention/plan
    rather than a completed activity.
    Example: 'Tomorrow I will email leads #1-10' -> True (DO NOT mark contacted!)
             'Today I emailed leads #1-10' -> False (Completed!)
    """
    lower = text.lower()
    plan_indicators = [
        r'\b(?:tomorrow|kal|agamikal)\s+(?:i\s+will|will|pathabo|send\s+korbo|message|email|call)\b',
        r'\b(?:will\s+send|will\s+email|will\s+message|will\s+call|will\s+contact|i\s+will\s+message|i\s+will\s+email)\b',
        r'\b(?:planning\s+to|plan\s+korsi|plan\s+korechi|going\s+to)\b',
        r'\b(?:kal\s+pathabo|kal\s+send\s+korbo|pore\s+pathabo)\b'
    ]
    return any(re.search(p, lower) for p in plan_indicators)


def is_completed_outreach(text: str) -> bool:
    """
    Check if the text reports completed outreach action.
    """
    lower = text.lower()
    # If it's a future plan, it is NOT completed
    if is_plan_only(lower):
        return False

    completed_indicators = [
        r'\b(?:sent|send\s+korechi|messaged|emailed|called|contacted)\b',
        r'\b(?:pathaisi|pathalam|pathano\s+hoyeche|disi|dilam|message\s+disi|message\s+dilam|message\s+pathaisi|korechi|korlam)\b',
        r'\b(?:outreach\s+done|completed)\b'
    ]
    return any(re.search(p, lower) for p in completed_indicators)


def detect_outcome_status(text: str) -> Optional[str]:
    """Detect replies, interest, or rejections."""
    lower = text.lower()
    if re.search(r'\b(?:not\s+interested|declined|opted\s+out|agrohi\s+na|mana\s+koreche)\b', lower):
        return "NOT INTERESTED"
    if re.search(r'\b(?:interested|agrohi|positive\s+reply)\b', lower):
        return "INTERESTED"
    if re.search(r'\b(?:replied|reply\s+received|uttor\s+dise|reply\s+pelam|replied\s+by)\b', lower):
        return "REPLIED"
    return None


def parse_outreach_note(note_text: str, note_date: Optional[str] = None) -> Dict[str, Any]:
    """
    Parse daily notes into structured CRM interpretation preview.
    Splits note into sentences/lines, evaluates actions, lead IDs, channels,
    safety checks, and calculates global and channel-specific follow-up dates.
    """
    base_date = datetime.date.fromisoformat(note_date) if note_date else datetime.date.today()

    # Split into lines and sentences
    raw_lines = [l.strip() for l in note_text.splitlines() if l.strip()]
    segments = []
    for line in raw_lines:
        parts = re.split(r'(?<=[.!?;])\s+', line)
        for p in parts:
            if p.strip():
                segments.append(p.strip())

    parsed_actions: List[Dict[str, Any]] = []
    global_followup_date: Optional[str] = None
    channel_followup_dates: Dict[str, str] = {}
    unsupported_phrases: List[str] = []

    # First pass: look for follow-up instructions
    for seg in segments:
        if re.search(r'\b(?:follow[\s-]*up|next\s+action|next\s+followup)\b', seg, re.IGNORECASE):
            d = parse_date_reference(seg, base_date=base_date)
            if d:
                seg_lids = extract_lead_ids(seg)
                seg_ch = detect_channel(seg)
                if not seg_lids and seg_ch:
                    # Channel-specific follow-up instruction, e.g. "Follow up with the WhatsApp leads in 3 days"
                    channel_followup_dates[seg_ch] = d
                else:
                    global_followup_date = d

    all_targeted_lead_ids: Set[int] = set()

    for seg in segments:
        lead_ids = extract_lead_ids(seg)
        channel = detect_channel(seg)
        outcome = detect_outcome_status(seg)
        completed = is_completed_outreach(seg)
        planned = is_plan_only(seg)
        explicit_seg_date = parse_date_reference(seg, base_date=base_date)

        if not lead_ids:
            # Check if this segment was a follow-up instruction or benign remark
            if not re.search(r'\b(?:follow[\s-]*up|next\s+action|next\s+followup|response\s+ashle)\b', seg, re.IGNORECASE):
                unsupported_phrases.append(seg)
            continue

        all_targeted_lead_ids.update(lead_ids)
        resolved_channel = channel or "WhatsApp"

        action_type = "UNKNOWN"
        if planned:
            action_type = "PLAN_ONLY"
        elif outcome:
            action_type = f"STATUS_{outcome}"
        elif completed:
            action_type = "OUTREACH_SENT"
        else:
            # Default when lead IDs + channel are specified without future plan markers
            action_type = "OUTREACH_SENT"
            completed = True

        # Resolve follow-up date for this segment:
        # 1. Explicit date in the segment itself (e.g. "Tomorrow I will..." or "...follow up in 3 days")
        # 2. Channel-specific follow-up date (only for completed/non-declined actions)
        # 3. Global follow-up date (only for completed/non-declined actions)
        if explicit_seg_date:
            seg_date = explicit_seg_date
        elif not planned and outcome != "NOT INTERESTED":
            seg_date = channel_followup_dates.get(resolved_channel) or global_followup_date
        else:
            seg_date = None

        parsed_actions.append({
            "raw_text": seg,
            "lead_ids": lead_ids,
            "lead_numbers": [f"#{i:04d}" for i in lead_ids],
            "channel": resolved_channel,
            "action_type": action_type,
            "is_completed": (completed or bool(outcome)) and not planned,
            "is_plan_only": planned,
            "outcome_status": outcome,
            "followup_date": seg_date
        })

    # Summary calculations
    wa_count = sum(len(a["lead_ids"]) for a in parsed_actions if a["channel"] == "WhatsApp" and a["is_completed"] and not a["outcome_status"])
    email_count = sum(len(a["lead_ids"]) for a in parsed_actions if a["channel"] == "Email" and a["is_completed"] and not a["outcome_status"])
    phone_count = sum(len(a["lead_ids"]) for a in parsed_actions if a["channel"] == "Phone" and a["is_completed"] and not a["outcome_status"])

    primary_channel = parsed_actions[0]["channel"] if parsed_actions else "WhatsApp"
    is_plan = all(a["is_plan_only"] for a in parsed_actions) if parsed_actions else False
    primary_followup = (
        global_followup_date
        or next(iter(channel_followup_dates.values()), None)
        or (parsed_actions[0]["followup_date"] if parsed_actions else None)
    )

    return {
        "raw_text": note_text,
        "actions": parsed_actions,
        "targeted_lead_ids": sorted(list(all_targeted_lead_ids)),
        "channel": primary_channel,
        "is_plan_only": is_plan,
        "followup_date": primary_followup,
        "unsupported_phrases": unsupported_phrases,
        "summary": {
            "whatsapp_count": wa_count,
            "email_count": email_count,
            "phone_count": phone_count,
            "total_targeted": len(all_targeted_lead_ids),
            "followup_date": primary_followup,
            "channel_followup_dates": channel_followup_dates,
            "note_date": base_date.isoformat()
        }
    }

