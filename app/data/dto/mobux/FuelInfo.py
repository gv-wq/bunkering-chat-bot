from datetime import datetime

from pydantic import BaseModel


class MabuxFuelInfo(BaseModel):
    date: datetime
    fuelName: str
    fuelShortName: str
    unit: str
    indexed: bool
    value: float

    @classmethod
    def from_dict(cls, date: str, d: dict) -> "MabuxFuelInfo":
        date = datetime.strptime(date, "%Y-%m-%d")
        fuel_d = d.get("fuel")

        return cls(
            date=date,
            fuelName=fuel_d["name"],
            fuelShortName=fuel_d["nameShort"],
            unit=fuel_d["unit"],
            indexed=fuel_d["indexed"],
            value=d["value"],
        )
