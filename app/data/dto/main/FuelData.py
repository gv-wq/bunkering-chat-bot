from pydantic import BaseModel, Field
from typing import Optional

class FuelData(BaseModel):
    fuel_name: str = Field(default=None, description="Fuel ID")
    quantity: Optional[float] = Field(default=None, description="Fuel quantity")
    price: Optional[float] = Field(default=None, description="Fuel price")


    @classmethod
    def from_dict(cls, d: dict) -> 'FuelData':
        return cls(
            fuel_name=d["fuel_name"],
            quantity=d["quantity"],
            price=d["price"],
        )
