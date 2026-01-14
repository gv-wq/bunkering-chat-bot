import datetime
from pydantic import BaseModel, Field
from typing import List

class BubbleFuelPrice(BaseModel):
    fuelName: str = Field()
    date: datetime.date = Field()
    price: float = Field()

    @classmethod
    def from_dict(cls, d: dict) -> "BubbleFuelPrice":
        return cls(
            fuelName=d["fuel_type"],
            date=datetime.datetime.strptime(d.get("timestamp"), "%Y-%m-%dT%H:%M:%S.%fZ").date(),
            price=d.get("price"),
        )

class BubleFuelPriceCollectionResponse(BaseModel):
    cursor: int
    results: List[BubbleFuelPrice]
    count: int
    remaining: int

    @classmethod
    def from_dict(cls, data: dict) -> "BubleFuelPriceCollectionResponse":
        return cls(
            cursor=data["cursor"],
            count=data["count"],
            remaining=data["remaining"],
            results=[BubbleFuelPrice.from_dict(result) for result in data.get("results", [])]
        )



