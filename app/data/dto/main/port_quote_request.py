
from typing import Optional, List
from pydantic import BaseModel, Field

from app.data.dto.main.SeaPort import SeaPortDB

class PortQuoteRequest(BaseModel):
    query: Optional[str] = Field(None)
    port: Optional[SeaPortDB] = Field(None)
    ports: Optional[List[SeaPortDB]] = Field(None)

    @classmethod
    def from_dict(cls, d: dict):

        port = d.get("port")

        return cls(
            query=d.get("query"),
            port=SeaPortDB.from_db_row(port) if port else None,
            ports=[SeaPortDB.from_db_row(e) for e in d.get("ports", [])],
        )

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "port": self.port.model_dump() if self.port else None,
            "ports": [p.model_dump() for p in self.ports],
        }

