from base64 import b64encode
from typing import Dict

from app.services.utils.HttpClient import HTTPClient


class MobuxApi:
    def __init__(self, base_url: str, login_str: str, pass_str: str):
        self.base_url = base_url  # http://api.mabux.com/v3/
        self.login_str = login_str
        self.pass_str = pass_str
        self.basic_token = token = b64encode(
            f"{login_str}:{pass_str}".encode("utf-8")
        ).decode("ascii")
        self.http_client = HTTPClient(
            base_url=self.base_url, default_headers=self.__get_headers()
        )

    def __get_headers(self) -> Dict[str, str]:

        return {
            "Content-Type": "application/json",
            "Authorization": f"Basic {self.basic_token}",
        }

    # async def get_spot(self):
    #     result, err = self.http_client.get("/spot?json")
    #     if err:
    #         return None, err
    #
    #     #data = result.json()
