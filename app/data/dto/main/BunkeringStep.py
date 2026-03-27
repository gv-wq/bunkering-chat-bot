import json
from datetime import datetime
from typing import Any, Dict, Optional

from app.services.utils import utils

from pydantic import BaseModel, Field, field_serializer

from app.data import emoji
from app.data.dto.main.SeaPort import SeaPortDB

PRICE_ON_REQUEST = "on request"
class BunkeringStep(BaseModel):
    n: int = Field()
    port: SeaPortDB = Field()
    eta_datetime: datetime = Field(...)
    distance: float = Field(...)
    fuel_info: dict = Field(...)
    agent_required: bool = Field(default=False)
    selected: bool = Field()
    to_show: bool = Field(default=False)
    marked : bool = Field(False)

    @field_serializer('eta_datetime')
    def serialize_datetime(self, dt: datetime, _info) -> str:
        """Serialize datetime to ISO format string"""
        return dt.isoformat()

    @classmethod
    def from_dict(cls, d: Dict[str, Any], def_n : Optional[int] = None) -> "BunkeringStep":
        port_obj = d.get("port")
        port = SeaPortDB.from_db_row(port_obj)

        fuel_info = d.get("fuel_info", {})
        agent_required = d.get("agent_required", False)
        selected = d.get("selected", False)

        dt_obj = d.get("eta_datetime")

        def parse_dt(dt_obj: str | None) -> datetime:
            if not dt_obj:
                return datetime.min

            for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
                try:
                    return datetime.strptime(dt_obj, fmt)
                except ValueError:
                    pass

            raise ValueError(f"Unsupported datetime format: {dt_obj}")

        dt = parse_dt(dt_obj)

        return cls(
            n = d.get("n", def_n),
            port=port,
            distance=d.get("distance", 0),
            eta_datetime=dt,
            fuel_info=fuel_info,
            agent_required=agent_required,
            selected=selected,
            to_show=d.get("to_show", False),
            marked=d.get("marked", False)
        )

    def format_port_block(self) -> str:
        """Return a formatted port block with all fuel information."""
        p = self.port

        # Status indicators
        mark = emoji.CHECK_GRAY if self.selected else ""
        green_dot = emoji.STAR if self.marked else ""

        # Format ETA
        eta_formatted = self.eta_datetime.strftime("%B %d, %Y").replace(" 0", " ")

        lines = [
            f"{self.n}. {mark} {green_dot} {p.format_port()}",
            f"ETA: {eta_formatted}"
        ]

        # Transport availability
        transport_parts = []

        transport_parts.append(f"Fuel transporting: {utils.render_delivery_basis(p)}")


        # if p.barge_status is not None:
        #     transport_parts.append(f"Barge: {'Yes' if p.barge_status else 'No'}")
        #
        # if p.truck_status is not None:
        #     transport_parts.append(f"Truck: {'Yes' if p.truck_status else 'No'}")
        #
        # if transport_parts:
        #     lines.append(", ".join(transport_parts))

        # Agent contacts
        if p.agent_contact_list:
            lines.append(p.agent_contact_list)

        preferred_order = ["VLS FO", "MGO LS"]
        all_fuels_set = set(self.fuel_info.keys())
        ordered_fuels = []

        # preferred fuels first
        for fuel in preferred_order:
            if fuel in all_fuels_set:
                ordered_fuels.append(fuel)

        # remaining fuels alphabetically
        remaining_fuels = sorted(f for f in all_fuels_set if f not in preferred_order)
        ordered_fuels.extend(remaining_fuels)

        fuel_info = {fuel: self.fuel_info[fuel] for fuel in ordered_fuels}

        total_cost = 0
        for fuel_name, info in fuel_info.items():

            qty = info.get("quantity")
            price = info.get("fuel_price")
            cost = None
            any_ = False
            m = ""
            if qty and price:
                cost = qty * price
                total_cost += cost
                m = f" = {cost}"
                any_ = True


            lines.append(f"{emoji.SMALL_DOT} {fuel_name}: {qty  or emoji.LINE } mt * ${price or emoji.LINE}/mt {m}")

        total_cost_t = emoji.LINE
        if any_:
            total_cost_t = total_cost

        lines.append(f"Total cost: {total_cost_t}")
        lines.append("")

        return "\n".join(lines)
