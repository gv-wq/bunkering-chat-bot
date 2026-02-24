from typing import List

from pydantic import BaseModel, Field

from app.data.dto.main.Coordinates import Coordinates
from app.data.dto.searoute.Area import SearouteArea
from app.data.dto.searoute.SearouteWaypoint import SearouteWaypoint


# @dataclass
class SearoutePath(BaseModel):
    distance: float = Field(..., gt=0)
    departure: int = Field(...)
    arrival: int = Field(...)
    duration: float = Field(..., gt=0)
    routeAreas: List[SearouteArea] = Field(...)
    waypoints: List[SearouteWaypoint] = Field(...)
    seaRouteCoordinates: List[Coordinates] = Field(...)

    @classmethod
    def from_searoute(cls, feature: dict) -> "SearoutePath":
        properties = feature.get("properties")

        distance = properties.get("distance", None)
        departure = properties.get("departure", None)
        arrival = properties.get("arrival", None)
        duration = properties.get("duration", None)

        areas_obj = properties.get("areas", {})
        waypoints_obj = properties.get("waypoints", {} )
        geometry_dict = feature.get("geometry", {})
        coordinates_list = geometry_dict.get("coordinates", [])

        areas = [SearouteArea.from_dict(area) for area in areas_obj.get("features", [])]
        waypoints = [SearouteWaypoint.from_dict(w)  for w in waypoints_obj.get("features", [])]
        _seaRouteCoordinates = [Coordinates.from_array_lon_lat(c) for c in coordinates_list]

        return cls(
            distance=distance,
            departure=departure,
            arrival=arrival,
            duration=duration,
            routeAreas=areas,
            waypoints=waypoints,
            seaRouteCoordinates=_seaRouteCoordinates,
        )

    def to_dict(self):
        return {
            "distance": self.distance,
            "departure": self.departure,
            "arrival": self.arrival,
            "duration": self.duration,
            "routeAreas": [c.model_dump() for c in self.routeAreas],
            "waypoints": [c.to_dict() for c in self.waypoints],
            "seaRouteCoordinates": [c.model_dump() for c in self.seaRouteCoordinates]

        }
