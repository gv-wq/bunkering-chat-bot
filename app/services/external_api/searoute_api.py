import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.data.dto.searoute.SearoutePath import SearoutePath
from app.data.dto.searoute.SearoutePort import SearoutePort
from app.services.utils.HttpClient import HTTPClient
from urllib.parse import urlencode


class SearouteApi:
    def __init__(self, base_url: str, secret_key: str):
        self.base_url = base_url  # https://api.searoutes.com/geocoding/v2
        self.secret_key = secret_key
        self.http_client = HTTPClient(
            base_url=self.base_url, default_headers=self.__get_headers()
        )

    def __get_headers(self):
        return {"x-api-key": self.secret_key}

    async def get_nearest_port_to_coordinates(self, latitude: float, longitude: float, params: Dict[str, Any] = None) -> Tuple[Optional[List[SearoutePort]], Optional[str]]:
        """
        Get nearest ports to coordinates

        Returns:
            Tuple[ports_list, error] - Always (result, None) or (None, error_message)
        """
        params = params or {}
        limit = params.get("limit", 5)
        radius = params.get("deviation", 18000)

        endpoint = f"/geocoding/v2/closest/{longitude},{latitude}"
        query_params = {
            "locationTypes": "port",
            "limit": limit,
           # "radius": radius
        }

        # Make the request using the wrapper
        result, error = await self.http_client.get_cut_by_timeout(endpoint, params=query_params, max_retries=6, timeout=500, pause=0.3)

        if error:
            return None, error

        try:
            # Process successful response
            features = result.get("features", [])
            processed_result = [
                SearoutePort.from_searoute(feature) for feature in features
            ]
            return processed_result, None

        except Exception as e:
            error_msg = f"Failed to process response data: {str(e)}"
            return None, error_msg

    async def build_sea_route(
        self,
        departure_lat: float,
        departure_lon: float,
        destination_lat: float,
        destination_lon: float,
        speed_in_knots : Optional[float],
        departure_dt: datetime.datetime,
        is_plan: bool = False,
    ) -> Tuple[Optional[SearoutePath], Optional[str]]:

        endpoint = f"/route/v2/sea/{departure_lon},{departure_lat};{destination_lon},{destination_lat}"

        if is_plan:
            endpoint += "/plan"

        # with open("./searoute_path.json", 'r') as fp:
        #     import json
        #     result = {"features": [json.loads(fp.read())]}
        #     error = None

        params = {}

        if speed_in_knots is not None:
            params["speedInKts"] = speed_in_knots

        if departure_dt is not None:
            params["departure"] = int(departure_dt.timestamp() * 1000)

        query = urlencode(params)
        url = f"{endpoint}?{query}" if query else endpoint

        #result, error = await self.http_client.get_cut_by_timeout(endpoint, params=params, max_retries=6, timeout=500, pause=0.3)
        result, error = await self.http_client.get(url)

        if error:
            return None, error

        try:
            # Process successful response
            features = result.get("features", [])
            if len(features) == 0:
                return None, 'There is no are sequence for that route from "Searoute"'

            processed_result = SearoutePath.from_searoute(features[0])
            return processed_result, None

        except Exception as e:
            error_msg = f"Failed to process response data: {str(e)}"
            return None, error_msg

    async def get_port_info(
        self, port_query
    ) -> Tuple[Optional[SearoutePort], Optional[str]]:
        # https://api.searoutes.com/geocoding/v2/port?query=INMUN
        """

                get
        https://api.searoutes.com/geocoding/v2/all

        This endpoint returns the locations that match a partial string passed as query parameter (query) or matches exactly a specific field (locode, iataCode or postalCode). Only one of these fields must be used in a request. Locations returned can be either airport, port, zipcode, railTerminal or roadTerminal.

        The query parameter locationTypes allows to filter the types returned. A list of values can be passed among port,airport,zipcode,railTerminal, roadTerminal. If this parameter is not passed in the query, all the types will be searched.

        The query parameter sizes allows to filter the sizes of the locations returned for ports and airports.

        The results are returned with this priority order : port > airport > railTerminal > zipcode > roadTerminal.

        For each location, geometry (coordinates) is returned as well as properties fields. These fields differ according to the type of the location.

        For airports : name, locode, size, iataCode, countryName, countryCode (as a two letters code).

        For zipcodes : name, country, countryName, postalCode, stateCode, stateName, countyCode, countyName.

        For ports : name, locode, size, country, countryName, subdivisionCode, subdivisionName.

        For ports, rail terminals and road terminals : name, locode, country, countryName, subdivisionCode, subdivisionName.
                :param port_query:
                :return:
        """

        result, error = await self.http_client.get(
            f"/geocoding/v2/port?query={port_query}"
        )
        if error:
            return None, error

        features = result.get("features", [])
        if len(features) == 0:
            return None, 'There is no feature info from "Searoute"'

        return SearoutePort.from_searoute(features[0]), None
