from typing import List

from pydantic import BaseModel, Field


class PortGroup(BaseModel):
    port_locode: str = Field(...)
    group_id: int = Field(...)

    @classmethod
    def from_dict(cls, d: dict) -> 'PortGroup':
        return cls(
            port_locode=d['port_locode'],
            group_id=d['group_id']
        )

    @classmethod
    def from_list(cls, l: List[dict]) -> List['PortGroup']:
        return [cls.from_dict(e) for e in l]


class PortGroupDB(PortGroup):
    id: str = Field(...)

    @classmethod
    def from_dict(cls, d: dict) -> 'PortGroup':
        return cls(
            id=str(d['id']),
            port_locode=d['port_locode'],
            group_id=d['group_id'],
        )

    @classmethod
    def from_list(cls, l: List[dict]) -> List['PortGroup']:
        return [cls.from_dict(e) for e in l]