from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from datetime import datetime
from livereload import Server

app = FastAPI()

env = Environment(
    loader=FileSystemLoader("templates"),
    autoescape=select_autoescape(["html", "xml"])
)

import base64

with open("map.jpeg", "rb") as f:
    image = base64.b64encode(f.read()).decode("utf-8")

with open("p.png", "rb") as fp:
    prices_image_bytes = base64.b64encode(fp.read()).decode("utf-8")

def build_context():
    return {
        "request_id": "12345",
        "generation_date": datetime.now().strftime("%d %B %Y"),
        "total_cost": 12345,
        "user": {
            "first_name": "Semyon",
            "last_name": "Shirikov",
            "telegram_user_name": "semyon_spb"
        },
        "vessel_name": "Evergreen",
        "vessel_imo": "IMO1234567",
        "eta": "June 20, 2026",
        "port": {
            "port_name": "Singapore port",
            "country_name": "Singapore",
            "port_size": "Lange",
            "is_barge": True,
            "is_truck": True,
            "locode": "LOCODE",
            "latitude": 1234,
            "longitude": 1234,
            "agent_contact_list": "The agent required the additional information about the schedule of supplies."

        },
        "fuels": [
            {"fuel_name": "VLSFO", "quantity": 500, "price": 650, "cost": 325000},
            {"fuel_name": "MGO", "quantity": 50, "price": 850, "cost": 42500}
        ],
        "remark": "Urgent supply",
        "image": image,
        "map_link": "https://example.com",
        "prices_image_bytes": prices_image_bytes
    }


@app.get("/", response_class=HTMLResponse)
def preview():

    template = env.get_template("supplier_request.html")
    html = template.render(**build_context())

    return html