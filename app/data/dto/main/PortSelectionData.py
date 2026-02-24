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


    def to_dict(self):
        return {
            "departure_candidate": self.departure_candidate.dict() if self.departure_candidate else None ,
            "destination_candidate": self.destination_candidate.dict() if self.destination_candidate else None ,
            "departure_suggestions": [p.dict() for p in self.departure_suggestions] if self.departure_suggestions else [],
            "destination_suggestions": [p.dict() for p in self.destination_suggestions] if self.destination_suggestions else [],
            "departure_nearby": [p.dict() for p in self.departure_nearby] if self.departure_nearby else [],
            "destination_nearby": [p.dict() for p in self.destination_nearby] if self.destination_nearby else [],
        }

    @classmethod
    def from_dict(cls, data: dict):
        _depc = data.get("departure_candidate")
        _desc = data.get("destination_candidate")

        _deps = data.get("departure_suggestions")
        _dests = data.get("destination_suggestions")

        _depn = data.get("departure_nearby")
        _destn = data.get("destination_nearby")

        return cls(
            departure_candidate=SeaPortDB.from_db_row(_depc) if _depc else None,
            destination_candidate=SeaPortDB.from_db_row(_desc) if _desc else None,
            departure_suggestions=[SeaPortDB.from_db_row(r) for r in _deps] if _deps else None,
            destination_suggestions=[SeaPortDB.from_db_row(r) for r in _dests] if _dests else None,
            departure_nearby=SeaPortDB.from_db_row(_depn) if _depn else None,
            destination_nearby=SeaPortDB.from_db_row(_destn) if _destn else None,

        )
