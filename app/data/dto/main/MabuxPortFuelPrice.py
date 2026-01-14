from pydantic import BaseModel, Field
from typing import List, Optional
import datetime

# Define the model for MabuxPortFuelPrice
class MabuxPortFuelPrice(BaseModel):
    mabux_id: int
    locode: str
    countryName: str
    portName: str
    fuelName: str
    fuelNameShort: str
    date: datetime.date
    value: Optional[float]
    unit: str
    indexed: bool
    isoAlphaCode: str
    fuelDeliveryMethodATitle: str
    fuelDeliveryMethodAbbr: str
    hasWeeklyPrice: bool

    @classmethod
    def from_mobux_price(cls, port_dict: dict, date: datetime.date, value_info: dict, ):
        # Extract the port data

        mabux_id = port_dict.get('id')
        if mabux_id is None:
            return None

        port_name = port_dict.get('name')
        locode = port_dict.get('unLocode', "")
        has_weekly_price = port_dict.get('hasWeeklyPrice')

        # Extract the fuel delivery method
        fuel_delivery_method_dict = port_dict.get("fuelDeliveryMethod", {})
        if isinstance(fuel_delivery_method_dict, str):
            fuel_delivery_method_dict = {}

        fuel_del_title = fuel_delivery_method_dict.get('title', "")
        fuel_del_abbr = fuel_delivery_method_dict.get('abbr', "")

        # Extract country data
        country_dict = port_dict.get('country', {})
        if isinstance(country_dict, str):
            country_dict = {}

        country_name = country_dict.get('name', "")
        country_iso_alpha2code = country_dict.get("isoAlpha2Code", "")


        fuel_dict = value_info["fuel"]
        f_name = fuel_dict.get("name", "")
        f_name_short = fuel_dict.get("nameShort", "")
        f_unit = fuel_dict.get("unit", "")
        f_indexed = fuel_dict.get("indexed")

        value = value_info.get("value")
        if value is None:
            return None

        return cls(
            mabux_id=mabux_id,
            locode=locode,
            countryName=country_name,
            isoAlphaCode=country_iso_alpha2code,
            portName=port_name,
            fuelName=f_name,
            fuelNameShort=f_name_short,
            date=date,
            value=value,
            unit=f_unit,
            indexed=f_indexed,
            fuelDeliveryMethodATitle=fuel_del_title,
            fuelDeliveryMethodAbbr=fuel_del_abbr,
            hasWeeklyPrice=has_weekly_price
        )



class MabuxPortFuelPriceDB(MabuxPortFuelPrice):
    id: str

    @classmethod
    def from_dict(cls, d: dict):

        price_date = d.get("price_date")
        if isinstance(price_date, str):
            price_date = datetime.datetime.strptime(price_date, "%Y-%m-%d")


        return cls(
            id=str(d.get("id")),
            mabux_id = d.get("mabux_id"),
            locode = d.get("locode"),
            countryName = d.get("country_name"),
            isoAlphaCode = d.get("iso_alpha_code"),
            portName = d.get("port_name"),
            fuelName = d.get("fuel_name"),
            fuelNameShort = d.get("fuel_name_short"),
            date = price_date,
            value = d.get("value"),
            unit = d.get("unit"),
            indexed = d.get("indexed"),
            fuelDeliveryMethodATitle = d.get("fuel_delivery_method_title"),
            fuelDeliveryMethodAbbr = d.get("fuel_delivery_method_abbr"),
            hasWeeklyPrice = d.get("has_weekly_price"),
        )



    def to_dict(self) -> dict:
        """Convert to dictionary with database-friendly field names."""
        # Use Pydantic's model_dump() with field aliases
        return {
            "id": self.id,
            "mabux_id": self.mabux_id,
            "locode": self.locode,
            "country_name": self.countryName,
            "iso_alpha_code": self.isoAlphaCode,
            "port_name": self.portName,
            "fuel_name": self.fuelName,
            "fuel_name_short": self.fuelNameShort,
            "price_date": self.date.strftime("%Y-%m-%d"),
            "value": self.value,
            "unit": self.unit,
            "indexed": self.indexed,
            "fuel_delivery_method_title": self.fuelDeliveryMethodATitle,
            "fuel_delivery_method_abbr": self.fuelDeliveryMethodAbbr,
            "has_weekly_price": self.hasWeeklyPrice,
        }