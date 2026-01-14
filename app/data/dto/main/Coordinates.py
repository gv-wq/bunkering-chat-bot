from pydantic import BaseModel, Field


class Coordinates(BaseModel):
    latitude: float = Field(...)
    longitude: float = Field(...)

    @classmethod
    def from_array_lon_lat(cls, array: list) -> "Coordinates":
        return cls(
            latitude=array[1],
            longitude=array[0],
        )

    @classmethod
    def from_array_lat_lon(cls, array: list) -> "Coordinates":
        return cls(
            latitude=array[0],
            longitude=array[1],
        )

    @classmethod
    def from_dict(cls, d: dict) -> "Coordinates":
        return cls(latitude=d["latitude"], longitude=d["longitude"])