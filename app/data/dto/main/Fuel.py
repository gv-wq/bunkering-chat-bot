import re
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class Fuel(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Fuel type name")
    description: Optional[str] = Field(None, description="Fuel type description")

    @field_validator("name")
    def validate_name(cls, v):
        v = v.strip()
        if len(v) == 0:
            raise ValueError("Fuel type name cannot be empty")
        # Check for common fuel type patterns
        if not re.match(r"^[a-zA-Z0-9\s\.\-cSt]+$", v):
            raise ValueError("Fuel type name contains invalid characters")
        return v

    @field_validator("description")
    def validate_description(cls, v):
        if v is not None and len(v.strip()) == 0:
            return None
        return v

    @classmethod
    def from_db_row(cls, row) -> "Fuel":
        return cls(name=row["name"], description=row["description"])


class FuelDB(Fuel):
    id: str = Field(
        ...,
    )

    @classmethod
    def from_db_row(cls, row) -> "FuelDB":
        return cls(id=str(row["id"]), name=row["name"], description=row["description"])


class FuelSeaPortPrice(FuelDB):
    port_id: str = Field(...)
    price: Optional[float] = Field(default=None, description="Fuel price")
