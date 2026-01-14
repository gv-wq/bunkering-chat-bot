from typing import Optional

from pydantic import BaseModel, Field


class SearouteArea(BaseModel):
    id: Optional[int] = Field(...)
    name: Optional[str] = Field(...)
    latitude: float = Field(...)
    longitude: float = Field(...)

    @classmethod
    def from_dict(cls, area_obj: dict) -> "SearouteArea":
        properties = area_obj.get("properties", {})
        geometry = area_obj.get("geometry", {})
        coordinates = geometry.get("coordinates", [])

        return cls(
            id=properties.get("id", None),
            name=properties.get("name", None),
            latitude=coordinates[1],
            longitude=coordinates[0],
        )
