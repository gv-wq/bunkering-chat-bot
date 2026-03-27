import json
from decimal import Decimal
from typing import List, Optional, Tuple

from pydantic import BaseModel, Field, field_validator

from app.data import emoji


def locode_to_flag(locode: str) -> str:
    """
    Convert UN/LOCODE to country flag emoji.
    Example: 'FIHMN' -> 🇫🇮
    """
    if not locode or len(locode) < 2:
        return ""

    country_code = locode[:2].upper()

    # A-Z -> 🇦-🇿 (Regional Indicator Symbols)
    return "".join(chr(0x1F1E6 + ord(c) - ord('A')) for c in country_code)


class SeaPort(BaseModel):
    locode: str = Field(..., min_length=1, max_length=10, description="UN/LOCODE")
    country_code: Optional[str] = Field(None, max_length=10, description="Country code")
    country_name: Optional[str] = Field(None, max_length=100, description="Country name")
    port_name: Optional[str] = Field(None, max_length=200, description="Port name")
    latitude: Optional[float] = Field(None, ge=-90, le=90, description="Latitude coordinate")
    longitude: Optional[float] = Field(None, ge=-180, le=180, description="Longitude coordinate")
    rank_score: Optional[float] = Field(None, description="Rank score")
    similarity_score: Optional[float] = Field(None, description="Similarity score")
    combined_score: Optional[float] = Field(None, description="Combined score")
    match_type: str = Field(None, description="Math type")
    mabux_ids: Optional[List[int]] = Field(description="Mobux IDs")
    port_size: Optional[str] = Field(None, description="Port size")
    mabux_id: Optional[int] = Field(None, description="Mobux ID")
    barge_status: Optional[bool] = Field(None)
    truck_status: Optional[bool] = Field(None)
    agent_contact_list : Optional[str] = Field(None)
    manual_input: bool = Field(False)

    @field_validator("locode")
    def validate_locode(cls, v):
        v = v.upper().strip()
        if len(v) == 0:
            raise ValueError("LOCODE cannot be empty")
        return v

    @field_validator("port_name")
    def validate_port_name(cls, v):
        if v is not None:
            v = v.strip()
            if len(v) == 0:
                raise ValueError("Port name cannot be empty if provided")
        return v

    @field_validator("country_name")
    def validate_country_name(cls, v):
        if v is not None:
            v = v.strip()
            if len(v) == 0:
                raise ValueError("Country name cannot be empty if provided")
        return v

    class Config:
        json_encoders = {Decimal: str}

    @classmethod
    def from_db_row(cls, row) -> "SeaPort":
        """Create PortVectorBase from database row"""
        return cls(
            locode=row["locode"],
            country_code="",
            country_name=row["country_name"],
            port_name=row["port_name"],
            latitude=row["latitude"],
            longitude=row["longitude"],
            rank_score=float(row["rank_score"]) if row.get("rank_score") else None,
            similarity_score=(float(row["similarity_score"]) if row.get("similarity_score") else None),
            combined_score=(float(row["combined_score"]) if row.get("combined_score") else None),
            match_type=row.get("match_type", "unknown"),
            mabux_ids=row.get("mabux_ids", []),
            port_size=row.get("port_size", None),
            mabux_id=row.get("mabux_id", None),
            barge_status=row.get("barge_status", None),
            truck_status=row.get("truck_status", None),
            agent_contact_list=row.get("agent_contact_list", None),
            manual_input=row.get("manual_input", False),
        )

class SeaPortBubble(SeaPort):
    bubble_id: Optional[str] = Field(None, description="Bubble ID")
    search_key: Optional[str] = Field(None, description="Search key")

class SeaPortDB(SeaPortBubble):
    id: str

    @classmethod
    def from_tuple(cls, row_tuple: Tuple) -> "SeaPortDB":
        def get_safe_value(index, default=None, convert_func=None):
            try:
                value = row_tuple[index]
                if value is None:
                    return default

                if isinstance(value, Decimal):
                    value = float(value)

                if convert_func:
                    return convert_func(value)

                return value
            except (IndexError, ValueError, TypeError):
                return default


        return cls(
            id=get_safe_value(0, 0, str),
            bubble_id=get_safe_value(1, "", str),
            port_name=get_safe_value(2, ""),  # index 1
            country_name=get_safe_value(3, ""),  # index 2
            country_code="",  # index 3 - assuming this is locode
            locode=get_safe_value(4, ""),  # index 3 - same as country_code?
            latitude=get_safe_value(6, None, float),  # index 4
            longitude=get_safe_value(7, None, float),  # index 5
            rank_score=None,
            similarity_score=None,
            combined_score=None,
            match_type="trigram_similarity",
            mabux_ids=row_tuple[8],
            port_size=get_safe_value(9,  None),
            search_key=None,
            mabux_id=get_safe_value(10,  None),
            barge_status=get_safe_value(11, None),
            truck_status=get_safe_value(12,  None),
            agent_contact_list=get_safe_value(13, None),
            manual_input=get_safe_value(14, False),
        )

    @classmethod
    def from_db_row(cls, row) -> "SeaPortDB":
        """Create PortVectorBase from database row"""

        return cls(
            id = str(row['id']),
            bubble_id =  str(row['bubble_id']),
            locode=row["locode"],
            country_code="",
            country_name=row["country_name"],
            port_name=row["port_name"],
            latitude=row["latitude"],
            longitude=row["longitude"],
            rank_score=float(row["rank_score"]) if row.get("rank_score") else None,
            similarity_score=(float(row["similarity_score"]) if row.get("similarity_score") else None),
            combined_score=(float(row["combined_score"]) if row.get("combined_score") else None),
            match_type=row.get("match_type", "unknown"),
            mabux_ids= row.get("mabux_ids"),
            port_size=row.get("port_size", None),
            search_key=row.get("search_key"),
            mabux_id=row.get("mabux_id", None),
            barge_status=row.get("barge_status", None),
            truck_status=row.get("truck_status", None),
            agent_contact_list=row.get("agent_contact_list", None),
            manual_input=row.get("manual_input", False),
        )


    def to_indexed2(self, index: str, color: str, size: str, overlap: bool) -> "SeaPortIndexed2":
        return SeaPortIndexed2(
            id=self.id,
            bubble_id=self.bubble_id,
            locode=self.locode,
            country_code=self.country_code,
            country_name=self.country_name,
            port_name=self.port_name,
            latitude=self.latitude,
            longitude=self.longitude,
            rank_score=self.rank_score,
            similarity_score=self.similarity_score,
            combined_score=self.combined_score,
            match_type=self.match_type,
            mabux_ids=self.mabux_ids,
            port_size=self.port_size,
            index=index,
            color=color,
            size=size,
            overlap=overlap,
            search_key=None,
            mabux_id=self.mabux_id,
            truck_status=self.truck_status,
            barge_status=self.barge_status,
            agent_contact_list=self.agent_contact_list,
            manual_input=self.manual_input
        )

    def format_port(self, status: bool | None = None, update_status: bool = False):
        prefix = "" if not update_status else f"{emoji.PLAY} "

        if status is True:
            prefix += " <b> Departure port"
            if update_status:
                prefix += " (current)"
            prefix += ": </b> \n"
        elif status is False:
            prefix += " <b> Destination port"
            if update_status:
                prefix += " (current)"
            prefix += ": </b> \n"

        s = f"({self.port_size})" if self.port_size else "(-)"

        return "\n".join([
            f"{prefix}{locode_to_flag(self.locode)} {self.country_name} ({self.locode}) {self.port_name} {s}",
        ])

    def format_indexed(self, index):
        s = f"({self.port_size})" if self.port_size else "(-)"
        return f"{index}. {locode_to_flag(self.locode)} {self.country_name} - {self.port_name} - {self.locode} {s}\n"

class SeaPortDBIndexed(SeaPortDB):
    index: int = Field()
    selected: bool = Field()

class SeaPortIndexed2(SeaPortDB):
    index: str = Field()
    color: str = Field()
    size: str = Field()
    overlap: bool = Field(False)

