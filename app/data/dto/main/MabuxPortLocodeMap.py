from pydantic import BaseModel, Field

class MabuxPortLocodeMap(BaseModel):
    mabux_id: int
    port_name: str
    country_name: str
    mabux_locode: str
    real_locode: str

    @classmethod
    def from_dict(cls, d: dict) -> 'MabuxPortLocodeMap':
        return cls(
            mabux_id=d["mabux_id"],
            port_name=d["port_name"],
            country_name=d["country_name"],
            mabux_locode=d["mabux_locode"],
            real_locode=d["real_locode"]
        )

class MabuxPortLocodeMapDB(MabuxPortLocodeMap):
    id: int

    @classmethod
    def from_dict(cls, d: dict) -> 'MabuxPortLocodeMapDB':
        return cls(
            id=d["id"],
            mabux_id=d["mabux_id"],
            port_name=d["port_name"],
            country_name=d["country_name"],
            mabux_locode=d["mabux_locode"],
            real_locode=d["real_locode"]
        )