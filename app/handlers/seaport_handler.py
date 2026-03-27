import asyncio
from datetime import datetime, timedelta
from typing import List, Optional

from app.data.dto.main.Event import Event
from app.data.dto.main.MabuxPortFuelPrice import MabuxPortFuelPriceDB
from app.data.dto.main.PortFuelPrice import PortFuelPrice
from app.data.dto.main.SeaPort import SeaPortDB
from app.data.dto.main.Session import SessionDB
from app.data.dto.main.SessionData import CheckFuelPrice
from app.data.dto.messenger.ResponsePayload import ResponsePayloadCollection
from app.data.enums.QuoteRequestEnum import QuoteRequestEnum
from app.data.enums.RouteTask import RouteTaskEnum
from app.data.enums.SupplierRequestSearchEnum import SupplierRequestSearchEnum
from app.handlers.navigation_handler import NavigationHandler
from app.services.ai_service import AiService
from app.services.db_service import DbService
from app.services.fuel_price_service import FuelPriceService
from app.services.template.telegram_template_service import TemplateService
from app.services.external_api.searoute_api import SearouteApi

from app.services.utils import utils

class SeaportHandler:
    def __init__(
        self,
        ai_service : AiService,
        sql_db_service : DbService,
        template_service : TemplateService,
        navigation_handler: NavigationHandler,
        searoute_api: SearouteApi,
        port_fuel_price_service: FuelPriceService,
    ):
        self.ai_service = ai_service
        self.sql_db_service = sql_db_service
        self.template_service = template_service
        self.navigation_handler = navigation_handler
        self.searoute_api = searoute_api
        self.port_fuel_price_service = port_fuel_price_service

    def _resolve_port_by_index(self, suggestions: List[SeaPortDB], index: int) -> Optional[SeaPortDB]:
        if not suggestions or index is None:
            return None
        adjusted_index = int(index) - 1
        if 0 <= adjusted_index < len(suggestions):
            return suggestions[adjusted_index]
        return None

    async def _find_fuel_price(
            self,
            port,
            fuel_name: str,
            date: datetime.date,
    ) -> Optional[MabuxPortFuelPriceDB]:
        date = utils.adjust_from_weekend(date)

        price_db, _ = await self.sql_db_service.get_port_fuel_price_by_port_locode(
            port.locode, fuel_name, date
        )
        if price_db:
            if price_db.value > 0:
                return price_db

        alt_ids, err = await self.sql_db_service.get_alternative_mabux_ids(port.locode.strip())
        if err or not alt_ids:
            return None

        for mabux_id in alt_ids:
            price_db, _ = await self.sql_db_service.get_port_fuel_price_by_port_mabux_id(
                mabux_id, fuel_name, date
            )
            if price_db:
                if price_db.value > 0:
                    return price_db

        return None
    
    def _date_range(
            self,
            dt_from: datetime.date,
            dt_to: datetime.date,
    ) -> List[datetime.date]:
        days = (dt_to - dt_from).days
        return [dt_from + timedelta(days=i) for i in range(days + 1)]

    async def _find_fuel_price_limited(
            self,
            *,
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

    async def get_port_fuel_cost_timeseries(
            self,
            *,
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

            days = list(self._date_range(dt_from, dt_to))

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


    async def handle(self, session: SessionDB, message: str) -> ResponsePayloadCollection:
        intent = await self.ai_service.parse_port_fuel_price_intend_2(session, message)
        # if err:
        #     return await self.template_service.get_port_fuel_price_template(session, "❌ Could not understand your request")

        # if intent.get("another_port_n"):
        #     if session.data.check_port_fuel_price:
        #
        #         candidate = self._resolve_port_by_index(session.data.check_port_fuel_price.port_alternatives, intent['another_port_n'])
        #         intent['port_name'] = candidate.locode if candidate else None
        #
        #
        # if intent.get("port_name", None) is None:
        #     intent['port_name'] = message.lower().strip()
        #
        #     return await self.template_service.get_port_fuel_price_template(session, "Could not fetch port name")

        if intent.get("navigation", "") == "supplier_quote_request":
            session.current_task = RouteTaskEnum.SUPPLIER_REQUEST_CREATE.value
            session.current_step = QuoteRequestEnum.VESSEL_NAME.value
            session.route_id = None
            session, err = await self.sql_db_service.update_session(session.user_id, session.current_task, session.current_step, session.route_id, session.data)
            return await self.template_service.session_template(session, err_msg=str(err) if err else None)


        port, ports, err = self.sql_db_service.search_port_with_suggestions(intent.get('locode', message))

        await self.sql_db_service.create_event(Event.port_searched(
            user_id=session.user_id,
            payload={
                "query": intent.get('locode', message),
            },
        ))

        if err or not port:
            await self.sql_db_service.create_event(Event.error(
                user_id=session.user_id,
                payload={
                    "error": err,
                },
            ))

            session.data.check_port_fuel_price = None
            session, err = await self.sql_db_service.update_session(session.user_id, RouteTaskEnum.GET_PORT_PRICE.value, None, session.route_id, session.data)
            return await self.template_service.get_port_fuel_price_template(session, "❌ Could not find the port")

        if port:
            if not port.port_size:
                searoute_port_r, err = await self.searoute_api.get_port_info(port.locode)
                if searoute_port_r and not err:
                    port_db, port_db_err = await self.sql_db_service.upsert_port_size_from_searoute(searoute_port_r)
                    if port_db and not port_db_err:
                        port = port_db

        new_ports = []
        if ports:
            for port_r in ports:
                if port_r.port_size:
                    new_ports.append(port_r)
                    continue

                searoute_port_r, err = await self.searoute_api.get_port_info(port_r.locode)
                if searoute_port_r and not err:
                    port_db, port_db_err = await self.sql_db_service.upsert_port_size_from_searoute(searoute_port_r)
                    if port_db and not port_db_err:
                        new_ports.append(port_db)

        ports = new_ports


        target_date = await utils.parse_fuel_price_date(intent)
        if target_date:

            if target_date > datetime.now().date():
                target_date = datetime.now().date()

        fuels, err = await self.sql_db_service.get_available_fuels()
        if err:
            return await self.template_service.get_port_fuel_price_template(session, "❌ Could not fetch fuel types")

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
        prices = [
            all_prices.extend(price) for price, err in results
            if price is not None
        ]

        check_port_fuel_price = CheckFuelPrice(
            port=port,
            port_alternatives=ports,
            prices=[price.model_dump() for price in all_prices]
        )

        await self.sql_db_service.create_event(Event.port_price_requested(
            user_id=session.user_id,
            payload={
                "locode": port.locode,
            },
        ))

        session.data.check_port_fuel_price = check_port_fuel_price
        session, err = await self.sql_db_service.update_session(session.user_id, RouteTaskEnum.GET_PORT_PRICE.value, None, session.route_id, session.data)
        return await self.template_service.get_port_fuel_price_template(session)







