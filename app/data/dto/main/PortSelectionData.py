from typing import List, Optional

from pydantic import BaseModel, Field

from app.data.dto.main.SeaPort import SeaPortDB


class PortSelectionData(BaseModel):
    departure_candidate: Optional[SeaPortDB] = Field(None, title="Departure Candidate")
    destination_candidate: Optional[SeaPortDB] = Field(None, title="Destination Candidate")

    departure_suggestions: Optional[List[SeaPortDB]] = Field([], title="Departure Suggestions")
    destination_suggestions: Optional[List[SeaPortDB]] = Field([], title="Destination Suggestions")

    departure_nearby : Optional[List[SeaPortDB]] = Field(default_factory=list, title="Departure nearby")
    destination_nearby: Optional[List[SeaPortDB]] = Field(default_factory=list, title="Destination nearby")