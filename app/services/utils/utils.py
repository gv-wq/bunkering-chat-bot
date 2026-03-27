from datetime import datetime, timedelta, date
from typing import Dict, Optional, List, Tuple

from app.data.dto.main.SeaPort import SeaPortDB

import re


MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


DATE_PATTERNS = [

    # 15-01-2025
    re.compile(r"^(?P<day>\d{1,2})[-/\.](?P<month>\d{1,2})[-/\.](?P<year>\d{4})$"),

    # 15 Jan 2025
    re.compile(r"^(?P<day>\d{1,2})\s+(?P<month>[a-zA-Z]+)\s+(?P<year>\d{4})$"),

    # Jan 15 2025
    re.compile(r"^(?P<month>[a-zA-Z]+)\s+(?P<day>\d{1,2})\s+(?P<year>\d{4})$"),

    # 15 Jan
    re.compile(r"^(?P<day>\d{1,2})\s+(?P<month>[a-zA-Z]+)$"),

    # Jan 15
    re.compile(r"^(?P<month>[a-zA-Z]+)\s+(?P<day>\d{1,2})$"),
]

RANGE_SPLIT = re.compile(r"\s*-\s*")

def is_valid_message(msg: str) -> bool:
    # 1. Max length 30
    if len(msg) > 300:
        return False

    # 2. Check each character is allowed
    allowed_chars = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 \n .,-/+@_")
    if not all(char in allowed_chars for char in msg):
        return False

    # # 3. No SQL injection-like patterns
    # blacklist = [
    #     "select", "insert", "update", "delete", "drop",
    #     "union", "from", "where", "join", "--", ";", "/*", "*/"
    # ]
    #
    # lower_msg = msg.lower()
    # if any(word in lower_msg for word in blacklist):
    #     return False

    return True

async def parse_fuel_price_date(intent: Dict) -> Optional[datetime.date]:
    """Parse date from intent for fuel price lookup"""
    try:
        year = intent.get("year")
        month = intent.get("month")
        day = intent.get("day")

        # If no date specified, use today
        if year == "None" and month == "None" and day == "None":
            return datetime.now().date()

        year_str = year if year != "None" else str(datetime.now().year)

        month_map = {
            "January": "01", "February": "02", "March": "03", "April": "04",
            "May": "05", "June": "06", "July": "07", "August": "08",
            "September": "09", "October": "10", "November": "11", "December": "12"
        }
        month_str = month_map.get(month, month.zfill(2))

        # Create date string
        if isinstance(day, str):
            day = day.zfill(2)

        date_str = f"{year_str}-{month_str}-{day}"
        parsed_date = datetime.strptime(date_str, "%Y-%m-%d").date()

        # Validate date is not in the future (we can't have future fuel prices)
        #if parsed_date > datetime.now().date():
        #  return datetime.now().date()

        return parsed_date

    except (ValueError, AttributeError, KeyError):
        return None

def resolve_port_by_index(suggestions: List[SeaPortDB], index: int) -> Optional[SeaPortDB]:
    if not suggestions or index is None:
        return None
    adjusted_index = int(index) - 1
    if 0 <= adjusted_index < len(suggestions):
        return suggestions[adjusted_index]
    return None

def merge_ports(*lists):
    out = {}
    for lst in lists:
        for p in lst:
            out[p.locode] = p
    return list(out.values())


def apply_sizes(ports, updated_map):
    for i, p in enumerate(ports):
        if p.locode in updated_map:
            ports[i] = updated_map[p.locode]


def safe_attr(obj, attr, default=""):
    val = getattr(obj, attr, None)
    return val if val is not None else default

def safe(value, default=""):
    return value if value is not None else default

def unique_ports(ports: List[SeaPortDB]) -> List[SeaPortDB]:
    unique_locode = set()
    result = []

    for port in ports:
        if port.locode not in unique_locode:
            unique_locode.add(port.locode)
            result.append(port)

    return result

def distributed_pick(items, max_count):
    if not items or max_count <= 0:
        return []

    picked = []
    visited = set()

    def pick_range(l, r):
        if len(picked) >= max_count or l > r:
            return

        mid = (l + r) // 2

        for idx in (l, r, mid):
            if idx not in visited and 0 <= idx < len(items):
                visited.add(idx)
                picked.append(items[idx])
                if len(picked) >= max_count:
                    return

        pick_range(l, mid - 1)
        pick_range(mid + 1, r)

    pick_range(0, len(items) - 1)
    return picked[:max_count]

import re

_EMAIL_RE = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+"
    r"@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)
def is_valid_email(email: Optional[str] = None) -> bool:
    if not email or " " in email:
        return False
    return bool(_EMAIL_RE.fullmatch(email))



def locode_to_flag(locode: str) -> str:
    """
    Convert UN/LOCODE to country flag emoji.
    Example: 'FIHMN' -> 🇫🇮
    """
    if not locode or len(locode) < 2:
        return ""

    country_code = locode[:2].upper()

    # A-Z -> 🇦-🇿 (Regional Indicator Symbols)
    return "".join(chr(0x1F1E6 + ord(c) - ord('A')) for c in country_code)

def render_delivery_basis(port: SeaPortDB):
    icons = []

    if port.barge_status:
        icons.append("🚢")  # barge
    if port.truck_status:
        icons.append("🚚")  # truck
    if getattr(port, "pipe_status", False):
        icons.append("🛢️")  # pipeline

    return " ".join(icons) if icons else "—"

def adjust_from_weekend(date: date) -> date:
    while date.weekday() >= 5:
        date -= timedelta(days=1)
    return date


def chunk_coords(coords, step: int, chunk_size: int):
    sampled = coords[::step]
    for i in range(0, len(sampled), chunk_size):
        yield sampled[i: i + chunk_size]

def clean_phone_number(v: Optional[str]) -> Optional[str]:
    if not v:
        return None

    # Keep digits only
    cleaned = re.sub(r"\D", "", v)

    return cleaned or None

def parse_eta_date(message: str) -> datetime | None:

    message = message.strip().lower()

    today = datetime.today().date()

    for pattern in DATE_PATTERNS:
        match = pattern.match(message)

        if not match:
            continue

        data = match.groupdict()

        day = int(data["day"])

        month = data["month"]

        if month.isdigit():
            month = int(month)
        else:
            month = MONTHS.get(month[:3])

        if not month:
            return None

        year = data.get("year")

        if year:
            year = int(year)
        else:
            year = today.year

        try:
            parsed = datetime(year, month, day).date()
        except ValueError:
            return None

        # auto-fix past date without year
        if not data.get("year") and parsed < today:
            parsed = datetime(year + 1, month, day).date()

        return datetime.combine(parsed, datetime.min.time())

    return None


def parse_eta_range(message: str) -> Tuple[Optional[datetime], Optional[datetime], Optional[str]]:
    # message = message.strip().lower()
    #
    # # -------- SPECIAL CASES --------
    # # 15 - 21 March
    # m = re.match(r"^(?P<d1>\d{1,2})\s*-\s*(?P<d2>\d{1,2})\s+(?P<month>[a-zA-Z]+)$", message)
    # if m:
    #     d1 = m.group("d1")
    #     d2 = m.group("d2")
    #     month = m.group("month")
    #
    #     eta_from = parse_eta_date(f"{d1} {month}")
    #     eta_to = parse_eta_date(f"{d2} {month}")
    #
    #     if not eta_from or not eta_to:
    #         return None, None, "Could not parse dates."
    #
    #     if eta_to <= eta_from:
    #         return None, None, "Second date must be later."
    #
    #     return eta_from, eta_to, None
    #
    # # march 22 - 23
    # m = re.match(r"^(?P<month>[a-zA-Z]+)\s+(?P<d1>\d{1,2})\s*-\s*(?P<d2>\d{1,2})$", message)
    # if m:
    #     d1 = m.group("d1")
    #     d2 = m.group("d2")
    #     month = m.group("month")
    #
    #     eta_from = parse_eta_date(f"{d1} {month}")
    #     eta_to = parse_eta_date(f"{d2} {month}")
    #
    #     if not eta_from or not eta_to:
    #         return None, None, "Could not parse dates."
    #
    #     if eta_to <= eta_from:
    #         return None, None, "Second date must be later."
    #
    #     return eta_from, eta_to, None

    message = message.strip().lower()

    def build_dates(d1, m1, d2, m2=None):
        m2 = m2 or m1
        eta_from = parse_eta_date(f"{d1} {m1}")
        eta_to = parse_eta_date(f"{d2} {m2}")

        if not eta_from or not eta_to:
            return None, None, "Could not parse dates."

        if eta_to <= eta_from:
            return None, None, "Second date must be later."

        return eta_from, eta_to, None

    # -------- SAME MONTH (15 - 21 March) --------
    m = re.match(r"^(?P<d1>\d{1,2})\s*-\s*(?P<d2>\d{1,2})\s+(?P<m>[a-zA-Z]+)$", message)
    if m:
        return build_dates(m.group("d1"), m.group("m"), m.group("d2"))

    # -------- SAME MONTH (March 15 - 21) --------
    m = re.match(r"^(?P<m>[a-zA-Z]+)\s+(?P<d1>\d{1,2})\s*-\s*(?P<d2>\d{1,2})$", message)
    if m:
        return build_dates(m.group("d1"), m.group("m"), m.group("d2"))

    # -------- TWO FULL DATES (March 20 - March 30) --------
    m = re.match(r"^(?P<m1>[a-zA-Z]+)\s+(?P<d1>\d{1,2})\s*-\s*(?P<m2>[a-zA-Z]+)\s+(?P<d2>\d{1,2})$", message)
    if m:
        return build_dates(m.group("d1"), m.group("m1"), m.group("d2"), m.group("m2"))

    # -------- MIXED (20 March - 30) --------
    m = re.match(r"^(?P<d1>\d{1,2})\s+(?P<m>[a-zA-Z]+)\s*-\s*(?P<d2>\d{1,2})$", message)
    if m:
        return build_dates(m.group("d1"), m.group("m"), m.group("d2"))

    # -------- MIXED (March 20 - 30) --------
    m = re.match(r"^(?P<m>[a-zA-Z]+)\s+(?P<d1>\d{1,2})\s*-\s*(?P<d2>\d{1,2})$", message)
    if m:
        return build_dates(m.group("d1"), m.group("m"), m.group("d2"))

    # -------- COMPACT (20 30 March) --------
    m = re.match(r"^(?P<d1>\d{1,2})\s+(?P<d2>\d{1,2})\s+(?P<m>[a-zA-Z]+)$", message)
    if m:
        return build_dates(m.group("d1"), m.group("m"), m.group("d2"))

    # -------- COMPACT (March 20 30) --------
    m = re.match(r"^(?P<m>[a-zA-Z]+)\s+(?P<d1>\d{1,2})\s+(?P<d2>\d{1,2})$", message)
    if m:
        return build_dates(m.group("d1"), m.group("m"), m.group("d2"))

    parts = RANGE_SPLIT.split(message)

    if len(parts) != 2:
        return None, None, "I need two dates."

    eta_from = parse_eta_date(parts[0])
    eta_to = parse_eta_date(parts[1])

    if not eta_from or not eta_to:
        return None, None, "One dt was not parsed"

    if eta_to <= eta_from:
        return None, None, "First date older than second."

    return eta_from, eta_to, None


def date_range(
        dt_from: datetime.date,
        dt_to: datetime.date,
) -> List[datetime.date]:
    days = (dt_to - dt_from).days
    return [dt_from + timedelta(days=i) for i in range(days + 1)]