from dataclasses import dataclass
from typing import List, Optional
from pydantic import BaseModel, Field


class BubblePort(BaseModel):
    locode: Optional[str] = Field(None, alias="locode")
    sr_lat: Optional[float] = Field(None, alias="sr_lat")
    sr_country_name: Optional[str] = Field(None, alias="sr_country_name")
    sr_lon: Optional[float] = Field(None, alias="sr_lon")
    created_date: Optional[str] = Field(None, alias="created_date")
    created_by: Optional[str] = Field(None, alias="created_by")
    id: Optional[str] = Field(None, alias="_id")
    search_key: Optional[str] = Field(None, alias="search_key")
    modified_date: Optional[str] = Field(None, alias="modified_date")
    name: Optional[str] = Field(None, alias="name")
    mabux_ids: Optional[List[str]] = Field(None, alias="mabux_ids")
