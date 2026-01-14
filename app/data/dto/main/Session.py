import json
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.data.dto.main.SessionData import SessionData


class Session(BaseModel):
    user_id: UUID = Field(..., description="User ID")
    current_task: Optional[str] = Field(None, description="Current task")
    current_step: Optional[str] = Field(None, description="Current step")
    route_id: Optional[UUID] = Field(None, description="Route ID")
    data: SessionData = Field(description="Temporary storage for searching routes")

    last_activity: datetime = Field(default_factory=datetime.now)
    admin_status : bool = Field(False)


class SessionDB(Session):
    id: UUID

    def exceeded(self, expiry_minutes: int = 30) -> bool:
        time_diff = datetime.now() - self.last_activity
        return time_diff.total_seconds() > (expiry_minutes * 60)

    @classmethod
    def from_db_row(cls, row) -> "SessionDB":
        return cls(
            id=row["id"],
            user_id=row["user_id"],
            current_task=row["current_task"],
            current_step=row["current_step"],
            route_id=row["route_id"],
            last_activity=row["last_activity"],
            data=SessionData.from_dict(json.loads(row["data"])),
            admin_status=row["admin_status"],
        )
