import json
from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.data.dto.main.SeaRouteData import SeaRouteData
from app.data.dto.main.BunkeringStep import BunkeringStep
from app.data.dto.main.Fuel import Fuel
from app.data.dto.main.ZonePreferences import ZonePreferences


class SeaRoute(BaseModel):
    user_id: UUID = Field(description="User ID")

    status: str = Field(default="draft", description="Route status")

    departure_port_id: Optional[str] = Field(None, description="Departure port ID")

    destination_port_id: Optional[str] = Field(None, description="Destination port ID")

    departure_date: Optional[datetime] = Field(
        None, description="Estimated departure time"
    )

    average_speed_kts: Optional[Decimal] = Field(
        None, gt=0, description="Average speed in knots"
    )

    max_deviation_nm: Optional[Decimal] = Field(
        None, ge=0, description="Maximum deviation in nautical miles"
    )
    vessel_name: Optional[str] = Field(None, description="Vessel name")
    imo_number: Optional[str] = Field(None, description="Imo number")

    zones_preferences: Optional[ZonePreferences] = Field(
        default=[], description="Routing zone preferences"
    )

    fuels: List[Fuel] = Field(
        default_factory=dict, description="Fuel types with boolean status"
    )

    bunkering_steps: List[BunkeringStep] = Field(default_factory=List[BunkeringStep])

    map_image_bytes: Optional[bytes] = Field(
        default=None, description="Route bunkering path image bytes"
    )

    departure_nearby_image: Optional[bytes] = Field(default=None, description="Departure nearby ports image")
    departure_suggestion_image: Optional[bytes] = Field(default=None, description="Destination suggested ports image")
    destination_nearby_image: Optional[bytes] = Field(default=None, description="Destination nearby ports image")
    destination_suggestion_image : Optional[bytes] = Field(default=None, description="Destination suggested ports image")

    data: SeaRouteData = Field()


class SeaRouteDB(SeaRoute):
    id: UUID
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_db_row(cls, row) -> "SeaRouteDB":
        """Create SeaRouteDB from database row"""
        # Handle zone_preferences JSON
        zone_prefs_data = row["zone_preferences"]
        if isinstance(zone_prefs_data, str):
            try:
                zone_prefs_data = json.loads(zone_prefs_data) if zone_prefs_data else {}
            except json.JSONDecodeError:
                zone_prefs_data = {}
        elif zone_prefs_data is None:
            zone_prefs_data = {}

        # Handle None values for UUID fields
        departure_port_id = str(row["departure_port_id"]) if row["departure_port_id"] else None
        destination_port_id = str(row["destination_port_id"]) if row['destination_port_id'] else None

        # Create ZonePreferences object
        zone_preferences = ZonePreferences(**zone_prefs_data)
        fuels = json.loads(row["fuels"])

        bunkering_steps_obj = json.loads(row.get("bunkering_steps", "[]"))

        bunkering_steps = [BunkeringStep.from_dict(p, i) for i, p in enumerate(bunkering_steps_obj, 1)]

        data_dict = json.loads(row["data"])
        data = SeaRouteData.from_json(data_dict)

        return cls(
            id=row["id"],
            user_id=row["user_id"],
            status=row["status"],
            departure_port_id=departure_port_id,
            destination_port_id=destination_port_id,
            departure_date= row.get("estimated_departure_time", None) ,
            average_speed_kts=row["average_speed_kts"],
            max_deviation_nm=row["max_deviation_nm"],
            zones_preferences=zone_preferences,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            fuels=fuels,
            bunkering_steps=bunkering_steps,
            map_image_bytes=row["map_image_bytes"],
            departure_nearby_image=row["departure_nearby_image"],
            departure_suggestion_image=row["departure_suggestion_image"],
            destination_nearby_image=row["destination_nearby_image"],
            destination_suggestion_image=row["destination_suggestion_image"],
            data=data,
            vessel_name = row['vessel_name'],
            imo_number = row["imo_number"],
        )
