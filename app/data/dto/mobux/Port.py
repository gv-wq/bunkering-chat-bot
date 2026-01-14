from pydantic import BaseModel


class MobuxSeaPort(BaseModel):
    id: int
    name: str
    locode: str
    fuelDeliveringMethodTitle: str
    fuelDeliveringMethodAbbr: str
    countryName: str
    countryCode: str

    @classmethod
    def from_dict(cls, data: dict) -> "MobuxSeaPort":
        fuel_delivery_method = data.get("fuelDeliveryMethod")
        country = data.get("country")

        return cls(
            id=data.get("id"),
            name=data.get("name"),
            locode=data.get("unLocode"),
            fuelDeliveringMethodTitle=fuel_delivery_method.get("title"),
            fuelDeliveringMethodAbbr=fuel_delivery_method.get("abbr"),
            countryName=country.get("name"),
            countryCode=country.get("isoAlpha2Code"),
        )
