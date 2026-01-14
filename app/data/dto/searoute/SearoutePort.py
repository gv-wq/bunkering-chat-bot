from datetime import datetime

from pydantic import BaseModel, Field
from typing import Optional


class SearoutePort(BaseModel):
    name: str = Field(...)
    locode: str = Field(...)
    country: str = Field(...)
    countryCode: str = Field(...)
    countryName: str = Field(...)
    size: str = Field(...)
    eta_datetime: Optional[datetime] = Field(None)
    distance: Optional[int] = Field(None)
    latitude: float = Field(...)
    longitude: float = Field(...)

    @classmethod
    def from_searoute(cls, data: dict) -> "SearoutePort":
        properties = data.get("properties", {})
        geometry = data.get("geometry", {})
        coordinates = geometry.get("coordinates", [])
        lat = coordinates[1]
        lng = coordinates[0]

        dt_obj = properties.get("eta_datetime")
        dt = datetime.fromtimestamp(dt_obj / 1000) if dt_obj else None

        return cls(
            name=properties.get("name"),
            locode=properties.get("locode"),
            country=properties.get("country"),
            countryCode=properties.get("countryCode"),
            countryName=properties.get("country"),
            size=properties.get("size"),
            eta_datetime =dt,
            distance=properties.get("distance", None),
            latitude=lat,
            longitude=lng,
        )

    @classmethod
    def from_dict(cls, d: dict):
        return cls(
            name=d.get("name"),
            locode=d.get("locode"),
            country=d.get("country"),
            countryCode=d.get("countryCode"),
            countryName=d.get("country"),
            size=d.get("size"),
            eta_datetime=datetime.strptime(d.get("eta_datetime"), "%Y-%m-%d").date() if d.get("eta_datetime") else None,
            distance=d.get("distance"),
            latitude=d.get("latitude"),
            longitude=d.get("longitude"),

        )
