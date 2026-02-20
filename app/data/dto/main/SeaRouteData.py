import json
from typing import Optional, List

from pydantic import BaseModel, Field

from app.data.dto.main.Coordinates import Coordinates
from app.data.dto.main.PortSelectionData import PortSelectionData


class SeaRouteData(BaseModel):
    port_selection: PortSelectionData = Field(default_factory=PortSelectionData)
    departure_to_destination_coordinates : List[Coordinates] = Field(default_factory=list)
    pdf_requested: bool = Field(default_factory=bool)
    quote_requested: bool = Field(default_factory=bool)
    is_updating: bool = Field(default_factory=bool)

    @classmethod
    def from_json(cls, json_data: Optional[str]) -> "SeaRouteData":
        """Create SeaRouteData from JSON string"""
        if not json_data:
            return cls()
        try:
            data = json.loads(json_data) if isinstance(json_data, str) else json_data

            return cls(**data)
        except:
            return cls()
