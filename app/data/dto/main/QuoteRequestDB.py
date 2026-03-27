import json
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field

from app.data.dto.main.FuelData import FuelData
from app.data.dto.main.port_quote_request import PortQuoteRequest

class QuoteRequestData(BaseModel):
     port_search: PortQuoteRequest = Field()

     @classmethod
     def from_dict(cls, d:dict) -> 'QuoteRequestData':
         return cls(port_search=PortQuoteRequest.from_dict(d.get("port_search", {}),),)

     def to_dict(self) -> dict:
         return {
             "port_search": self.port_search.to_dict(),
         }

     def to_json(self) -> str:
         return json.dumps(self.to_dict())

class QuoteRequest(BaseModel):
    user_id: str = Field()
    status: str = Field()
    port_id: Optional[str] = Field(None, alias="port_id")
    vessel_name: Optional[str] = Field(None, alias="vessel_name")
    vessel_imo: Optional[str] = Field(None, alias="vessel_imo")
    eta_from: Optional[datetime] = Field(None, description="Estimated time from")
    eta_to: Optional[datetime] = Field(None, description="Estimated time to")
    fuels: List[FuelData] = Field([], alias="fuels")
    company_name: Optional[str] = Field(None)
    remark: Optional[str] = Field("")
    deleted: bool = Field(False)
    data: QuoteRequestData = Field(alias="data")

    @classmethod
    def from_dict(cls, d: dict) -> "QuoteRequest":
        return cls(
            user_id=str(d["user_id"]),
            status=d["status"],
            port_id=str(d.get('port_id')) if d.get("port_id") else None,
            vessel_name=d.get("vessel_name", None),
            vessel_imo=d.get("vessel_imo", None),
            eta_from=d.get("eta_from", None),
            eta_to=d.get("eta_to", None),
            fuels=[FuelData.from_dict(e) for e in json.loads(d["fuels"])],
            remark=d["remark"],
            company_name=d['company_name'],
            deleted=d["deleted"],
            data=QuoteRequestData.from_dict(json.loads(d.get("data", "{}"))),
        )

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "status": self.status,
            "port_id": self.port_id,
            "vessel_name": self.vessel_name,
            "vessel_imo": self.vessel_imo,
            "eta_from": self.eta_from.strftime("%Y-%m-%d %H:%M:%S") if self.eta_from else None,
            "eta_to": self.eta_to.strftime("%Y-%m-%d %H:%M:%S") if self.eta_to else None,
            "fuels": [f.model_dump() for f in self.fuels],
            "remark": self.remark,
            "company_name": self.company_name,
            "deletet": self.deleted,
            "data": self.data.to_dict() if self.data else None,
        }

class QuoteRequestDB(QuoteRequest):
    id: str = Field(alias="id")

    @classmethod
    def from_dict(cls, d: dict) -> "QuoteRequest":
        base = QuoteRequest.from_dict(d)
        return cls(id=str(d["id"]), **base.to_dict())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            **super().to_dict(),
        }




