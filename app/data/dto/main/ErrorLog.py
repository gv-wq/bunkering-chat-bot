import sys
import traceback
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from uuid import UUID
from pydantic import BaseModel, Field


class ErrorLog(BaseModel):
    file: str
    line: int
    function: Optional[str] = None
    position: Optional[str] = None
    error_type: str
    message: str
    traceback: Dict[str, Any]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))



class ErrorLogFactory:

    @staticmethod
    def from_exception(ex : Exception, position: str = None) -> ErrorLog:
        tb_list = traceback.extract_tb(ex.__traceback__)
        last_frame = tb_list[-1] if tb_list else None

        return ErrorLog(
            file=last_frame.filename if last_frame else "unknown",
            line=last_frame.lineno if last_frame else 0,
            function=last_frame.name if last_frame else None,
            position=position,
            error_type=type(ex).__name__,
            message=str(ex),
            traceback={
                "frames": [
                    {
                        "file": f.filename,
                        "line": f.lineno,
                        "function": f.name,
                        "code": f.line,
                    }
                    for f in tb_list
                ]
            }
        )
