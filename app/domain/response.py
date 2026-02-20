from dataclasses import dataclass
from typing import Optional, List

@dataclass
class OutgoingResponse:
    text: Optional[str] = None
    keyboard: Optional[any] = None
    images: Optional[List[str]] = None
    files: Optional[List[str]] = None