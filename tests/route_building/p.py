import math
import asyncio
import datetime
from typing import List, Dict, Optional, Tuple
from concurrent.futures import ProcessPoolExecutor

from app.services.db_service import DbService
from app.services.external_api.searoute_api import SearouteApi

from dotenv import load_dotenv

load_dotenv()

sql_db_service = DbService()



# -------------------- utils --------------------

def adjust_from_weekend(date: datetime.date) -> datetime.date:
    while date.weekday() >= 5:
        date -= datetime.timedelta(days=1)
    return date


# -------------------- fuel prices --------------------

async def find_fuel_price(
    sql_db_service,
    port,
    fuel_name: str,
    date: datetime.date,
) -> Optional[float]:
    date = adjust_from_weekend(date)

    price_db, _ = await sql_db_service.get_port_fuel_price_by_port_locode(
        port.locode, fuel_name, date
    )
    if price_db:
        return price_db.value

    alt_ids, err = await sql_db_service.get_alternative_mabux_ids(port.locode.strip())
    if err or not alt_ids:
        return None

    for mabux_id in alt_ids:
        price_db, _ = await sql_db_service.get_port_fuel_price_by_port_mabux_id(
            mabux_id, fuel_name, date
        )
        if price_db:
            return price_db.value

    return None


# -------------------- port pricing --------------------

async def build_priced_port(
    sql_db_service,
    port,
    fuels: list,
    price_date: datetime.date,
    semaphore: asyncio.Semaphore,
) -> Optional[Dict]:
    async with semaphore:
        tasks = {
            fuel.name: find_fuel_price(
                sql_db_service,
                port,
                fuel.name,
                price_date,
            )
            for fuel in fuels
        }

        prices = await asyncio.gather(*tasks.values())

        fuel_info = {}
        prices_count = 0
        prices_sum = 0.0

        for fuel_name, price in zip(tasks.keys(), prices):
            if price is not None:
                prices_count += 1
                prices_sum += price

            fuel_info[fuel_name] = {
                "fuel_name": fuel_name,
                "fuel_price": price,
                "available": price is not None,
                "quantity": None,
            }

        if prices_count == 0:
            return None

        return {
            "port": port,
            "fuel_info": fuel_info,
            "prices_count": prices_count,
            "prices_sum": prices_sum,
            "_distance_km": getattr(port, "_distance_km", None),
            "marked": False,
        }


# -------------------- coordinates chunking --------------------

def chunk_coords(coords, step: int, chunk_size: int):
    sampled = coords[::step]
    for i in range(0, len(sampled), chunk_size):
        yield sampled[i : i + chunk_size]


# -------------------- ports search (parallel over chunks) --------------------

def find_nearest_waypoint(step, waypoints):
    nearest_wp = None
    min_dist = float("inf")

    for wp in waypoints:
        d = haversine_km(
            step.get("port").latitude,
            step.get("port").longitude,
            wp.latitude,
            wp.longitude,
        )
        if d < min_dist:
            min_dist = d
            nearest_wp = wp

    return nearest_wp

def haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return 2 * R * math.asin(math.sqrt(a))

async def collect_ports_parallel(
    sea_route,
    sql_db_service,
    radius_km: float = 500.0,
    limit: int = 50,
    step: int = 5,
    chunk_size: int = 20,
    max_parallel_chunks: int = 4,
):
    seen = {}

    semaphore = asyncio.Semaphore(max_parallel_chunks)

    async def process_chunk(chunk):
        async with semaphore:
            for c in chunk:
                ports, err = await sql_db_service.search_ports_nearby_with_prices(
                    c.latitude,
                    c.longitude,
                    n=limit,
                    radius_km=radius_km,
                )
                if err or not ports:
                    continue

                for p in ports:
                    if p.locode not in seen:
                        seen[p.locode] = p

    tasks = [
        process_chunk(chunk)
        for chunk in chunk_coords(sea_route.seaRouteCoordinates, step, chunk_size)
    ]

    await asyncio.gather(*tasks)

    ports = list(seen.values())
    ports.sort(key=lambda p: getattr(p, "_distance_km", float("inf")))
    return ports

def find_nearest_coord_index(step, coordinates) -> int:
    min_dist = float("inf")
    min_idx = 0

    for i, c in enumerate(coordinates):
        d = haversine_km(
            step.get("port").latitude,
            step.get("port").longitude,
            c.latitude,
            c.longitude,
        )
        if d < min_dist:
            min_dist = d
            min_idx = i

    return min_idx


def distance_from_start_to_index(coordinates, idx: int) -> float:
    total = 0.0

    for i in range(1, idx + 1):
        prev = coordinates[i - 1]
        curr = coordinates[i]
        total += haversine_km(
            prev.latitude,
            prev.longitude,
            curr.latitude,
            curr.longitude,
        )

    return total

def enrich_ports_with_eta_and_distance(
    steps: List[dict],
    sea_route,
) -> None:
    coordinates = sea_route.seaRouteCoordinates
    waypoints = sea_route.waypoints

    for step in steps:
        # --- ETA from nearest waypoint ---
        wp = find_nearest_waypoint(step, waypoints)
        step["eta_datetime"] = wp.eta_datetime if wp else None

        # --- distance along route ---
        idx = find_nearest_coord_index(step, coordinates)
        step["distance"] = distance_from_start_to_index(coordinates, idx)

# -------------------- bunkering steps --------------------

async def build_bunkering_steps(
    sql_db_service,
    ports: List,
    fuels: list,
    price_date: datetime.date,
    max_concurrency: int = 20,
    top_n_marked: int = 3,
) -> List[Dict]:
    semaphore = asyncio.Semaphore(max_concurrency)

    tasks = [
        build_priced_port(
            sql_db_service,
            port=p,
            fuels=fuels,
            price_date=price_date,
            semaphore=semaphore,
        )
        for p in ports
    ]

    results = await asyncio.gather(*tasks)
    steps = [r for r in results if r is not None]

    # sort: (a) prices_count desc, (b) prices_sum asc
    steps.sort(
        key=lambda s: (-s["prices_count"], s["prices_sum"])
    )

    # mark cheapest
    for s in steps[:top_n_marked]:
        s["marked"] = True

    # normalize numbering
    for i, s in enumerate(steps, start=1):
        s["n"] = i

    return steps

def enrich_and_finalize_steps(
    steps: List[dict],
    sea_route,
    top_n: int = 20,
) -> List[dict]:
    """
    1) enrich steps with ETA + route distance
    2) keep only top-N cheapest (by prices_count desc, prices_sum asc)
    3) sort final list by distance along route
    """

    # --- enrich ---
    enrich_ports_with_eta_and_distance(steps, sea_route)

    # --- keep only cheapest ---
    # steps.sort(
    #     key=lambda s: (-s["prices_count"], s["prices_sum"])
    # )
    # steps = steps[:top_n]

    # --- mark cheapest inside selected ---
    for s in steps:
        s["marked"] = False
    if steps:
        best_price = steps[0]["prices_sum"]
        for s in steps:
            if s["prices_sum"] == best_price:
                s["marked"] = True


# -------------------- full pipeline --------------------

async def build_bunkering_plan_fast(
    searoute_api,
    sql_db_service,
    departure_port,
    destination_port,
    fuels,
    speed_kts: float = 10.0,
):
    sea_route, err = await searoute_api.build_sea_route(
        departure_port.latitude,
        departure_port.longitude,
        destination_port.latitude,
        destination_port.longitude,
        speed_in_knots=speed_kts,
        is_plan=True,
        departure_dt=datetime.datetime.now(),
    )
    if err:
        raise RuntimeError(err)

    ports = await collect_ports_parallel(
        sea_route=sea_route,
        sql_db_service=sql_db_service,
    )

    bunkering_steps = await build_bunkering_steps(
        sql_db_service=sql_db_service,
        ports=ports,
        fuels=fuels,
        price_date=datetime.date.today(),
    )

    enrich_and_finalize_steps(
        steps=bunkering_steps,
        sea_route=sea_route,
        top_n=20,
    )

    return bunkering_steps


async def main():
    await sql_db_service.init_pool()
    searoute_api = SearouteApi("https://api.searoutes.com/", "EWhTo2x2hihNDCPZjCaMgFDWGegJoVLnYP7mqi5L")
    route, err = await sql_db_service.get_route_by_id("f5a102f0-5769-4e85-a947-fdb0199a67e8")
    departure_port, err = await sql_db_service.get_port_by_locode("RULED")
    destination_port, err = await sql_db_service.get_port_by_locode("AEJEA")


    bunkering_steps = await build_bunkering_plan_fast(
        searoute_api=searoute_api,
        sql_db_service=sql_db_service,
        departure_port=departure_port,
        destination_port=destination_port,
        fuels=route.fuels,
    )

    pass


if __name__ == "__main__":
    asyncio.run(main())