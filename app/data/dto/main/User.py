from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

class User(BaseModel):
    telegram_id: int = Field(..., description="Telegram user ID")
    telegram_user_name: Optional[str] = Field(None, max_length=255, description="Telegram username")
    phone_number: Optional[str] = Field(None, max_length=50, description="Phone number")
    first_name: Optional[str] = Field(None, max_length=255, description="First name")
    last_name: Optional[str] = Field(None, max_length=255, description="Last name")
    email: Optional[str] = Field(None, description="Email address")
    registration_date: Optional[datetime] = Field(None, description="Registration date")
    current_tariff_id: Optional[UUID] = Field(None, description="Current tariff ID")
    message_count: int = Field(default=0, ge=0, description="Number of sent messages")
    route_count: int = Field(default=0, ge=0, description="Number of created routes")
    free_tier_expiry: Optional[datetime] = Field(None, description="Free tier expiry date")
    is_active: bool = Field(default=True, description="User active status")
    telegram_effective_chat_id: Optional[int] = Field(None, description="Telegram effective chat ID")
    company_name: Optional[str] = Field(None)
    filled_name: Optional[str] = Field(None)
    is_admin: bool = Field(default=False, description="User admin status")
    role: Optional[str] = Field(None, description="User role")

class UserDB(User):
    id: UUID
    created_at: datetime
    updated_at: datetime

    def is_new(self) -> bool:
        """Check if user was created recently (within last 24 hours)"""
        if not self.created_at:
            return False
        time_diff = datetime.now() - self.created_at
        return time_diff.total_seconds() < 24 * 3600

    @classmethod
    def from_db_row(cls, row) -> "UserDB":
        """Create UserDB from database row"""
        return cls(
            id=row["id"],
            telegram_id=row["telegram_id"],
            telegram_user_name=row["telegram_user_name"],
            phone_number=row["phone_number"],
            first_name=row["first_name"],
            last_name=row["last_name"],
            email=row["email"],
            registration_date=row["registration_date"],
            current_tariff_id=row["current_tariff_id"],
            message_count=row["message_count"],
            route_count=row["route_count"],
            free_tier_expiry=row["free_tier_expiry"],
            is_active=row["is_active"] if row["is_active"] else True,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            telegram_effective_chat_id=row["telegram_effective_chat_id"],
            company_name=row["company_name"],
            filled_name=row["filled_name"],
            is_admin=row["is_admin"] if row["is_admin"] else False,
            role=row["role"],
        )
