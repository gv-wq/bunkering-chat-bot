from typing import Dict

from pydantic import BaseModel

from app.data.dto.mobux.FuelInfo import MabuxFuelInfo
from app.data.dto.mobux.Port import MobuxSeaPort


class MabuxPortFuelInfo(BaseModel):
    port: MobuxSeaPort
    fuelInfo: Dict[str, MabuxFuelInfo]

    @classmethod
    def from_spot_dict(cls, d: dict) -> "MabuxPortFuelInfo":
        port = MobuxSeaPort.from_dict(d["port"])
        indications = d.get("indications")
        fuels = [
            MabuxPortFuelInfo.from_dict(d.get("date"), f)
            for f in indications.get("values")
        ]
        f_info = {f.fuelShortName: f for f in fuels}

        return cls(
            port=port,
            fuelInfo=f_info,
        )
