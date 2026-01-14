from datetime import date, datetime

from pydantic import BaseModel


class PortFuelPrice(BaseModel):

    port_id: str  # guid
    fuel_id: str  # guid
    timestamp: date
    value: float

    @classmethod
    def from_db_row(cls, row) -> "PortFuelPrice":
        return cls(
            port_id=str(row["port_id"]),
            fuel_id=str(row["fuel_id"]),
            timestamp=row["timestamp"],
            value=row["value"],
        )

    def to_dict(self):
        return {
            "port_id": self.port_id,
            "timestamp": self.timestamp.strftime("%Y-%m-%d"),
            "value": self.value,
        }

class PortFuelPriceDB(PortFuelPrice):
    id: str  # guid

    @classmethod
    def from_db_row(cls, row: dict) -> "PortFuelPriceDB":
        return cls(
            id=str(row["id"]),
            port_id=str(row["port_id"]),
            fuel_id=str(row["fuel_id"]),
            timestamp=row["timestamp"], #datetime.strptime(row["timestamp"],"%Y-%m-%d").date(),
            value=row["value"],
        )

    def to_dict(self):
        return {
            "id": self.id,
            "port_id": self.port_id,
            "fuel_id": self.fuel_id,
            "timestamp": self.timestamp.strftime("%Y-%m-%d"),
            "value": self.value,
        }
