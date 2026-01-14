from pydantic import BaseModel, Field


class PortIntent(BaseModel):
    action: str = Field(..., title="Action")
    departure_port: str = Field(..., title="Departure Port")
    destination_port: str = Field(..., title="Destination Port")
