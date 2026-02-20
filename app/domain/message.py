from dataclasses import dataclass
from typing import Optional, Dict

@dataclass
class IncomingMessage:
    source: str                 # "telegram" | "whatsapp"
    user_id: str                # telegram_id or phone
    chat_id: str
    text: Optional[str]
    raw: object                 # original update (optional)
    meta: Dict = None