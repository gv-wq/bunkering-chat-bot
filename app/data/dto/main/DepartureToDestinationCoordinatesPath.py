from dataclasses import Field
from typing import List

from pydantic import BaseModel

from app.data.dto.main.Coordinates import Coordinates
from app.data.dto.main.SeaPort import SeaPort

class DepartureToDestinationCoordinatesPath(BaseModel):
    departurePort: SeaPort
    destinationPort: SeaPort
    coordinates: List[Coordinates]