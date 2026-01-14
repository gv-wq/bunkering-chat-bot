import json
from typing import List, Optional, Tuple

from app.data.dto.main.Coordinates import Coordinates
from app.data.dto.main.DepartureToDestinationCoordinatesPath import DepartureToDestinationCoordinatesPath
from app.data.dto.main.SeaPort import SeaPortDB, SeaPortDBIndexed, SeaPortIndexed2
from app.services.utils.HttpClient import HTTPClient


class MapBuilderApi:
    def __init__(
        self,
        base_url: str,
        public_url: str
    ):
        self.base_url = base_url
        self.public_url = public_url
        self.http_client = HTTPClient(
            base_url=self.base_url,
        )


    async def render_map_images(self,  coordinates: List[Coordinates], ports: List[SeaPortIndexed2], legend: Optional[bool] = False) -> Optional[List[bytes]]:
        images = []
        max_per_image = 15
        indexed_chunks = [ports[i:i + max_per_image] for i in range(0, len(ports), max_per_image)]
        for chunk in indexed_chunks:
            image, image_err = await self.render_map(coordinates, chunk, legend)
            if image and not image_err:
                images.append(image)
        return images


    async def render_map(self, coordinates: List[Coordinates], ports: List[SeaPortIndexed2], legend: Optional[bool] = False) -> Tuple[Optional[bytes], Optional[str]]:
        data = { "coordinates": [c.model_dump() for c in coordinates], "ports": [p.model_dump() for p in ports], "legend_status": legend}
        result, err = await self.http_client.post("/render_map", json_data=data, headers={"Content-Type": "application/json"})
        if err:
            return None, err

        if result.get("image_bytes", False) and not result.get("error", False):
            return eval(result.get("image_bytes")), None

        return None, result.get("error", "The mistake has happen")


    def get_search_port_map_link(self, route_id: str, is_departure: bool, is_suggestion) -> str:

        c1 = "p" if is_departure else "s"
        c2 = "s" if is_suggestion else "n"
        code = c1 + c2

        return f"{self.public_url}/ports?route_id={route_id}&code={code}".strip().lower()

    def get_route_map_link(self, route_id: str) -> str:
        return f"{self.public_url}/map?route_id={route_id.strip()}".strip().lower()






    async def build_map_image(
        self, coordinates: List[Coordinates], ports: List[SeaPortDB]
    ) -> Tuple[Optional[dict], Optional[str]]:
        data = {
            "coordinates": [c.model_dump() for c in coordinates],
            "ports": [p.model_dump() for p in ports],
        }
        result, err = await self.http_client.post(
            "/render", json_data=data, headers={"Content-Type": "application/json"}
        )
        return result, err

    async def build_ports_on_map_image(self,  ports: List[SeaPortDBIndexed], color: str):
        data = { "color": color, "ports": [p.model_dump() for p in ports] }
        return await self.http_client.post("/render_ports", json_data=data, headers={"Content-Type": "application/json"})

    async def build_routes_map_image(self, data: List[DepartureToDestinationCoordinatesPath]):
        data_dict = {"data": [d.model_dump() for d in data]}
        return await self.http_client.post("/render_routes", json_data=data_dict, headers={"Content-Type": "application/json"})
