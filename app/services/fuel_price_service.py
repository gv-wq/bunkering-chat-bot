import asyncio
from datetime import datetime, timedelta, date
from typing import Optional, List

from app.data.dto.main.Fuel import FuelDB
from app.data.dto.main.MabuxPortFuelPrice import MabuxPortFuelPriceDB
from app.data.dto.main.SeaPort import SeaPortDB
from app.services.db_service import DbService
from app.services.utils import utils


class FuelPriceService:
    def __init__(self, db: DbService):
        self.db = db

    async def get_port_fuel_prices(
        self,
        port: SeaPortDB,
        fuels: List[FuelDB],
        target_date: Optional[date] = None,

    ):
        semaphore = asyncio.Semaphore(10)

        price_tasks = [
            self.get_port_fuel_cost_timeseries(
                semaphore=semaphore,
                port=port,
                fuel_name=fuel.name,
                dt_to=target_date,
            )
            for fuel in fuels
        ]
        results = await asyncio.gather(*price_tasks)

        all_prices = []
        [
            all_prices.extend(price) for price, err in results
            if price is not None
        ]
        return all_prices


    async def get_port_fuel_cost_timeseries(
            self,
            port: SeaPortDB,
            fuel_name: str,
            semaphore: asyncio.Semaphore,
            dt_from: Optional[datetime.date] = None,
            dt_to: Optional[datetime.date] = None,
    ) -> tuple[list[MabuxPortFuelPriceDB] | None, str | None]:

        try:
            today = datetime.now().date()
            dt_to = dt_to or today
            dt_from = dt_from or (dt_to - timedelta(days=30))

            if dt_from > dt_to:
                return None, f"Bad bounds, {dt_from} > {dt_to}"

            days = list(utils.date_range(dt_from, dt_to))

            tasks = [
                self._find_fuel_price_limited(
                    semaphore=semaphore,
                    port=port,
                    fuel_name=fuel_name,
                    date=day,
                )
                for day in days
            ]

            prices = await asyncio.gather(*tasks)

            prices = [p for p in prices if p is not None]

            if not prices:
                return None, None

            return prices, None

        except Exception as e:
            return None, str(e)

    async def _find_fuel_price_limited(
            self,
            semaphore: asyncio.Semaphore,
            port: SeaPortDB,
            fuel_name: str,
            date: datetime.date,
    ):
        async with semaphore:
            return await self._find_fuel_price(
                port=port,
                fuel_name=fuel_name,
                date=date,
            )

    async def _find_fuel_price(
            self,
            port,
            fuel_name: str,
            date: datetime.date,
    ) -> Optional[MabuxPortFuelPriceDB]:
        date = utils.adjust_from_weekend(date)

        price_db, _ = await self.db.get_port_fuel_price_by_port_locode(
            port.locode, fuel_name, date
        )
        if price_db:
            if price_db.value > 0:
                return price_db

        alt_ids, err = await self.db.get_alternative_mabux_ids(port.locode.strip())
        if err or not alt_ids:
            return None

        for mabux_id in alt_ids:
            price_db, _ = await self.db.get_port_fuel_price_by_port_mabux_id(
                mabux_id, fuel_name, date
            )
            if price_db:
                if price_db.value > 0:
                    return price_db

        return None