from typing import Optional

from pydantic import BaseModel, Field


class TariffSelection(BaseModel):
    user_message: Optional[str] = Field(None)
    chosen_tariff: Optional[str] = Field(None)

    @classmethod
    def from_dict(cls, data: dict) -> "TariffSelection":

        return cls(
            user_message=data.get("user_message", None),
            chosen_tariff=data.get("chosen_tariff", None),
        )
