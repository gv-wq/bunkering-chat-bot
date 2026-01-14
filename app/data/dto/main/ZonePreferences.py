from pydantic import BaseModel, Field


class ZonePreferences(BaseModel):
    avoid_hrd: bool = Field(default=True, description="Avoid High Risk Areas")
    avoid_seca: bool = Field(
        default=False, description="Avoid Sulfur Emission Control Areas"
    )
    avoid_eca: bool = Field(default=False, description="Avoid Emission Control Areas")
    weather_avoidance: bool = Field(default=True, description="Avoid bad weather areas")
