from dataclasses import Field
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SearouteWaypoint(BaseModel):
    eta_datetime: Optional[datetime] = Field(...)
    value: Optional[str] = Field(...)
    distance: Optional[float] = Field(...)
    type: Optional[str] = Field(...)
    class_name : Optional[str] = Field(...)
    latitude: Optional[float] = Field(...)
    longitude: Optional[float] = Field(...)

    @classmethod
    def from_dict(cls, d: dict) -> "SearouteWaypoint":
        props = d.get("properties", {})

        geometry = d.get("geometry", {})
        coordinates = geometry.get("coordinates", [])


        return cls(
            eta_datetime=datetime.fromtimestamp(props["timestamp"] / 1000),
            value=props.get("value"),
            distance=props.get("distance"),
            type=props.get("type"),
            class_name=props.get("class_name"),
            latitude=coordinates[1],
            longitude=coordinates[0],
        )
