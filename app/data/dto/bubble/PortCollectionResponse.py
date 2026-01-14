import json
from dataclasses import dataclass
from typing import List

from app.data.dto.bubble.BubblePort import BubblePort


@dataclass
class PortCollectionResponse:
    cursor: int
    results: List[BubblePort]
    raw_results: List[dict]
    count: int
    remaining: int

    @classmethod
    def from_json(cls, json_str: str) -> "PortCollectionResponse":
        data = json.loads(json_str)
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> "PortCollectionResponse":

        results = []
        raw_results = []
        for result_data in data["results"]:
            raw_results.append(result_data)
            result = BubblePort(
                locode=result_data.get("locode"),
                sr_lat=result_data.get("sr_lat"),
                sr_country_name=result_data.get("sr_country_name"),
                sr_lon=result_data.get("sr_lon"),
                created_date=result_data.get("Created Date"),
                created_by=result_data.get("Created By"),
                _id=result_data.get("_id"),
                search_key=result_data.get("search_key"),
                modified_date=result_data.get("Modified Date"),
                name=result_data.get("name"),
                mabux_ids=result_data.get("source_mabux_ids", []),

            )
            results.append(result)

        return cls(
            cursor=data["cursor"],
            results=results,
            raw_results=raw_results,
            count=data["count"],
            remaining=data["remaining"],
        )
