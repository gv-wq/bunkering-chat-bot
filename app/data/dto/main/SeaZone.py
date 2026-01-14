from pydantic import BaseModel, Field


class SeaZone(BaseModel):
    name: str = Field(description="The name of the sea zone")
    avoid: bool = Field(description="Whether the sea zone should avoid")
    description: str = Field(description="The description of the sea zone")

    @classmethod
    def from_dict(cls, d) -> "SeaZone":
        return cls(**d)


class SeaZoneDB(SeaZone):
    id: str = Field(description="The id of the sea zone")

    @classmethod
    def from_dict(cls, d) -> "SeaZoneDB":
        return cls(**d)
