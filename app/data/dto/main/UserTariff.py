import json
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class TariffFeatures(BaseModel):
    advanced_analytics: bool = Field(default=False)
    priority_support: bool = Field(default=False)
    custom_domains: bool = Field(default=False)
    api_access: bool = Field(default=False)


class UserTariff(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    monthly_price: float = Field(..., ge=0)
    max_routes: int = Field(..., ge=0)
    max_messages: int = Field(..., ge=0)
    features: TariffFeatures = Field(default_factory=TariffFeatures)
    is_active: bool = Field(default=True)


class UserTariffBD(UserTariff):
    id: UUID
    created_at: datetime
    updated_at: datetime

    def exceeded(self, current_routes: int, current_messages: int) -> bool:
        return (
            current_routes >= self.max_routes or current_messages >= self.max_messages
        )

    @classmethod
    def from_db_row(cls, row) -> "UserTariffBD":
        """Create UserTariffBD from database row"""
        return cls(
            id=row["id"],
            name=row["name"],
            monthly_price=row["monthly_price"],
            max_routes=row["max_routes"],
            max_messages=row["max_messages"],
            features=TariffFeatures(**json.loads(row["features"])) if row.get("features", None)  else TariffFeatures()            ,
            is_active=row["is_active"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def to_dict(self):
        return {
            "id": str(self.id),
            "name": self.name,
            "monthly_price": self.monthly_price,
            "max_routes": self.max_routes,
            "max_messages": self.max_messages,
            "features": self.features.model_dump()
        }