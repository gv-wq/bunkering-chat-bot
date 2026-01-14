import json
import random
import time
import requests
from datetime import datetime
from typing import List, Optional, Tuple

from app.data.dto.bubble.FuelPrice import BubbleFuelPrice, BubleFuelPriceCollectionResponse
from app.data.dto.bubble.PortCollectionResponse import PortCollectionResponse
from app.data.dto.main.PortFuelPrice import PortFuelPrice


class BubbleApi:
    def __init__(self, base_obj_url: str, secret_key: str):
        self._base_obj_url = base_obj_url
        self._secret_key = secret_key

        self.session = requests.Session()

        # Set headers with Authorization
        # self.session.headers.update({
        #     'Accept': 'application/json, text/plain, */*',
        #     'Accept-Language': 'en-US,en;q=0.9',
        #     'Accept-Encoding': 'gzip, deflate, br',
        #     'Connection': 'keep-alive',
        #     'Host': 'bunkering-backup-20251118-1137.bubbleapps.io',
        #     'Cookie': '__cf_bm=ou5CQUX0THmhhRKaT0Yr5HshKxxbOnNHOI6d5NX92Xg-1763645039-1.0.1.1-yaB89oB5rQNcH1lq7BrbGU05IE6eQvqimi4KViJSINT130nw7CMRIZ8iFFSHjwMUf1eNR58sApzMj6JU_Txp9jkWOa3fZK7TDU5vdz.yktQ',
        #     'Authorization': f'Bearer {self._secret_key}'
        # })

    def get_headers(self):
        return {
            "Host":  "bunkering-backup-20251118-1137.bubbleapps.io", # "app.thebunkering.com", # "bunkering-backup-20251118-1137.bubbleapps.io",
            "Authorization": f"Bearer {self._secret_key}",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
          #  "Cookie": "__cf_bm=ou5CQUX0THmhhRKaT0Yr5HshKxxbOnNHOI6d5NX92Xg-1763645039-1.0.1.1-yaB89oB5rQNcH1lq7BrbGU05IE6eQvqimi4KViJSINT130nw7CMRIZ8iFFSHjwMUf1eNR58sApzMj6JU_Txp9jkWOa3fZK7TDU5vdz.yktQ",
        }



    # USER
    async def get_user(self, user_data):
        pass

    async def create_user(self, user_data):
        pass

    async def update_user(self, user_data):
        pass

    async def get_or_create_user(self, user_data):
        pass

    async def get_port_fuel_price(self, bubble_port_id: str, fuel_name: str, date: datetime.date) -> Tuple[Optional[PortFuelPrice], Optional[str]]:
        params = [
            {
                "key": "fuel_type",
                "constraint_type": "equals",
                "value": fuel_name
            },
            {
                "key": "port",
                "constraint_type": "equals",
                "value": bubble_port_id
            },
            {
                "key": "date",
                "constraint_type": "contains",
                "value": date.strftime("%Y-%m-%d")
            }
        ]


        url = self._base_obj_url + "/Price point"
        parms_str = "?constraint=" + json.dumps(params)

        response = requests.get(url, headers=self.get_headers(), params=parms_str)

        if response.status_code == 200:
            data = response.json()
            response = data.get("response", {})
            results = response.get("results", [])

            result = None
            for r in results:
                f_name = r.get("fuel_type", None)
                port_id = r.get("port", None)
                timestamp_str = r.get("timestamp", None)
                value = r.get("price", None)

                timestamp = None
                try:
                    timestamp = datetime.strptime(timestamp_str, "%Y-%m-%dT%H:%M:%S.%fZ")
                except Exception as e:
                    ...


                if not any([f_name, port_id, timestamp, value]):
                    continue


                if f_name == fuel_name and port_id == bubble_port_id and timestamp.date() == date:
                    result = value
                    break


            if result is None:
                return None, "Could not find fuel price"

            return result, None

        else:
            return None, f"Staus code: {response.status_code}"


    def get_fuel_prices_no_filter(self, offset: Optional[int] = 0) -> Tuple[Optional[BubleFuelPriceCollectionResponse], Optional[str]]:
        url = self._base_obj_url + "/Price point"
        response = requests.get(url, headers=self.get_headers(), params={"cursor": offset},)
        if response.status_code == 200:
            data = response.json()
            return BubleFuelPriceCollectionResponse.from_dict(data.get("response", {})), None
        return None, f"Staus code: {response.status_code}"



    def get_all_prices(self, delay : float = 0.5):

        prices = []
        current_cursor = 0
        while True:
            print(f"Fetching ports from cursor: {current_cursor}")

            data, err = self.get_fuel_prices_no_filter(offset=current_cursor)

            if not data:
                print("Failed to fetch data, stopping.")
                break

            results = data.results

            if not results:
                print("No more results found.")
                break

            prices.extend(results)

            current_cursor = data.cursor + len(results)
            remaining = data.remaining

            print(f"Fetched {len(results)} ports. Total so far: {len(prices)}. Remaining: {remaining}")

            if remaining <= 0:
                print("Reached the end of all ports.")
                break

            time.sleep(random.uniform(0.5, 2))

        return prices, err




        # PORTS
    def get_ports(
        self,
        obj_name: str,
        constraints: List[dict] = None,
        offset: int = 0,
        limit: int = 100,
    ) -> Tuple[Optional[PortCollectionResponse], Optional[str]]:
        """
        .../Port?constraints=[ { "key": "_id", "constraint_type": "equals", "value": "1713117905273x207394668009318180" } ]
        """
        try:
            constants_formatted = None
            if constraints:
                constraints_arr = []
                for constraint in constraints:
                    key = constraint["key"]
                    constraint_type = constraint["constraint_type"]
                    value = constraint["value"]
                    t = (
                        "{"
                        + f'"key": "{key}", "{constraint_type}": "equals", "value": "{value}" '
                        + "}"
                    )
                    constraints_arr.append(t)
                constants_formatted = "[" + ",".join(constraints_arr) + "]"

            url = self._base_obj_url + "/" + obj_name
            if constants_formatted:
                url += f"?constraints={constants_formatted}"
            #
            # headers = {
            #     'Host': 'bunkering-backup-20251118-1137.bubbleapps.io',
            #     'Authorization': f'Bearer {self._secret_key}',
            #     'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            #     'Cookie': '__cf_bm=ou5CQUX0THmhhRKaT0Yr5HshKxxbOnNHOI6d5NX92Xg-1763645039-1.0.1.1-yaB89oB5rQNcH1lq7BrbGU05IE6eQvqimi4KViJSINT130nw7CMRIZ8iFFSHjwMUf1eNR58sApzMj6JU_Txp9jkWOa3fZK7TDU5vdz.yktQ'
            # }

            response = requests.get(
                url,
                headers=self.get_headers(),
                params={
                    "cursor": offset,
                },
            )  # params={"cursor": offset,})

            if response.status_code == 200:
                data = response.json()
                #return data, None

                if obj_name == "Port":
                    return PortCollectionResponse.from_dict(data=data.get("response")), None
                else:
                    return None, "No such kind of object handlers"

            else:
                return (
                    None,
                    f"Response code: {response.status_code}. Context: {response.content}",
                )
        except Exception as ex:
            return None, str(ex)

    # def get_all_ports(self, delay: float = 0.1) -> Tuple[List[BubblePort], Optional[str]]:
    #     """
    #     Get all ports by paginating through all results
    #
    #     Args:
    #         delay: Delay between requests in seconds (to be respectful to the API)
    #     """
    #     all_ports = []
    #     current_cursor = 0
    #
    #     while True:
    #         print(f"Fetching ports from cursor: {current_cursor}")
    #
    #         data, err = self.get_ports(offset=current_cursor)
    #
    #         if not data:
    #             print("Failed to fetch data, stopping.")
    #             break
    #
    #         results = data.results
    #
    #         if not results:
    #             print("No more results found.")
    #             break
    #
    #         all_ports.extend(results)
    #
    #         current_cursor = data.cursor + len(results)
    #         remaining = data.remaining
    #
    #         print(f"Fetched {len(results)} ports. Total so far: {len(all_ports)}. Remaining: {remaining}")
    #
    #         if remaining <= 0:
    #             print("Reached the end of all ports.")
    #             break
    #
    #         time.sleep(delay)
    #
    #     return all_ports, err
    # ROUTEs
