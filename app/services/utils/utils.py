from datetime import datetime, timedelta, date
from typing import Dict, Optional, List

from app.data.dto.main.SeaPort import SeaPortDB

import re
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
