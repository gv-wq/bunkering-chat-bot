import json
from typing import Optional, List

from pydantic import BaseModel, Field

from app.data.dto.main.Coordinates import Coordinates
from app.data.dto.main.PortSelectionData import PortSelectionData
from app.data.dto.searoute.SearoutePath import SearoutePath


class SeaRouteData(BaseModel):
    port_selection: PortSelectionData = Field(default_factory=PortSelectionData)
    departure_to_destination_coordinates : List[Coordinates] = Field(default_factory=list)
    full_response : Optional[SearoutePath] = Field()
    pdf_requested: bool = Field(default_factory=bool)
    quote_requested: bool = Field(default_factory=bool)
    is_updating: bool = Field(default_factory=bool)

    @classmethod
    def from_json(cls, json_data: Optional[dict]) -> "SeaRouteData":
        """Create SeaRouteData from JSON string"""
        if not json_data:
            return cls(full_response=None)
        try:
            f = json_data.get("full_response", None)
            return cls(
                port_selection= PortSelectionData.from_dict(json_data.get("port_selection", {})),
                departure_to_destination_coordinates=[Coordinates.from_dict(c) for c in json_data.get("departure_to_destination_coordinates", [])],
                pdf_requested=json_data.get("pdf_requested", False),
                quote_requested=json_data.get("quote_requested", False),
                is_updating=json_data.get("is_updating", False),
                full_response=SearoutePath.from_searoute(f) if f else f,
            )
        except:
            return cls(full_response=None)

    def to_dict(self):
        return {
            "port_selection": self.port_selection.to_dict(),
            "departure_to_destination_coordinates" : [c.model_dump() for c in self.departure_to_destination_coordinates],
            "full_response": self.full_response.to_dict() if self.full_response else None,
            "pdf_requested": self.pdf_requested,
            "quote_requested": self.quote_requested,
            "is_updating": self.is_updating,

        }