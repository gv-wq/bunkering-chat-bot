import uuid

from app.data.dto.main.Session import SessionDB
from app.data.dto.messenger.ResponsePayload import ResponsePayloadCollection, ResponsePayload
from app.data.enums.QuoteRequestEnum import QuoteRequestEnum
from app.data.enums.RouteTask import RouteTaskEnum
from app.data.enums.SupplierRequestSearchEnum import SupplierRequestSearchEnum
from app.handlers.navigation_handler import NavigationHandler
from app.services.ai_service import AiService
from app.services.db_service import DbService
from app.services.fuel_price_service import FuelPriceService
from app.services.template.telegram_template_service import TemplateService


class SearchQuoteHandler:
    def __init__(self, db_service: DbService, template_service: TemplateService, ai_service: AiService, navigation_handler: NavigationHandler, port_fuel_price_service: FuelPriceService,):
        self.ai_service = ai_service
        self.db_service = db_service
        self.template_service = template_service
        self.navigation_handler = navigation_handler
        self.port_fuel_price_service: FuelPriceService = port_fuel_price_service

    async def handle(self, session: SessionDB, message: str) -> ResponsePayloadCollection:
        if session.current_step is None:
            session.current_step = SupplierRequestSearchEnum.LIST.value
            session, err = await self.db_service.update_session(session.user_id, session.current_task, session.current_step, None, session.data)

        if session.current_step == SupplierRequestSearchEnum.LIST.value:
            return await self._handle_list(session, message)

        if session.current_step == SupplierRequestSearchEnum.VIEW.value:
            return await self._handle_view(session, message)

        if session.current_step == SupplierRequestSearchEnum.CONFIRM_DELETE.value:
            return await self._handle_confirm_delete(session, message)

        return ResponsePayloadCollection(
            responses=[ResponsePayload(text="Unexpected state")]
        )

    async def _handle_list(self, session: SessionDB, message: str):

        q = message.strip().lower()
        search = session.data.quote_search

        if q in {"quote", "prices", "supplier"} or q == "get_supplier_quote" or q == "supplier quote":
            session.current_task = RouteTaskEnum.SUPPLIER_REQUEST_CREATE.value
            session.current_step = QuoteRequestEnum.VESSEL_NAME.value
            session.route_id = None
            session, err = await self.db_service.update_session(session.user_id, session.current_task, session.current_step, session.route_id, session.data)
            return await self.template_service.session_template(session, err_msg=str(err) if err else None)

        # pagination
        if q in {"+", "-", "start", "end"}:
            session, err = await self._apply_pagination(session, q)
            return await self.template_service.quote_search_template(session=session, message=err if err else None)

        if q.startswith(("del", "delete", "d ", "remove", "r")):
            parts = q.split()
            if len(parts) != 2 or not parts[1].isdigit():
                return await self.template_service.quote_search_template(session, "Usage: delete <number>")

            idx = int(parts[1]) - 1
            if idx < 0 or idx >= len(search.ids):
                return await self.template_service.quote_search_template(session, "Invalid route number")

            session.data.quote_search.id = search.ids[idx]
            session.current_step = SupplierRequestSearchEnum.CONFIRM_DELETE.value

            session, err = await self.db_service.update_session(session.user_id, session.current_task, session.current_step, None, session.data,)

            return ResponsePayloadCollection(
                responses=[ResponsePayload(
                    text=" <b> Are you sure?\n1. Yes\n0. Cancel </b> ", keyboard=self.navigation_handler.get_yes_no_keyboard()
                )]
            )

        # open
        if q.isdigit():
            idx = int(q) - 1

            if idx < 0 or idx >= len(search.ids):
                return await self.template_service.quote_search_template(session, "Invalid number")

            quote_id = search.ids[idx]
            session.current_step = SupplierRequestSearchEnum.VIEW.value
            session.data.quote_search.id = quote_id

            await self.db_service.update_session(session.user_id, session.current_task, session.current_step, None, session.data)

            quote, _ = await self.db_service.get_quote_by_id(quote_id)
            fuels, err = await self.db_service.get_available_fuels()
            if err:
                return await self.template_service.show_quote_template(quote=quote, message="❌ Could not fetch fuel types")

            prices = []
            if quote.port_id:
                port, err = await self.db_service.get_port_by_id(quote.port_id)
                if err:
                    return await self.template_service.show_quote_template(quote=quote, message= "❌ Could not fetch port info.")

                prices = await self.port_fuel_price_service.get_port_fuel_prices(port, fuels, quote.eta_to.date())

            user_db, err = await self.db_service.get_user_by_id(session.user_id)
            if err:
                return await self.template_service.show_quote_template(quote=quote, message=err)

            html_content, html_content_bytes, file_obj, subject, images, image_data = await self.template_service.render_supplier_request(user_db, quote, prices)

            return await self.template_service.show_quote_template(quote, file=file_obj)

        return await self.template_service.quote_search_template(session)

    async def _handle_view(self, session: SessionDB, message: str):

        q = message.strip().lower()

        if q in {"quote", "prices", "supplier"} or q == "get_supplier_quote" or q == "supplier quote":
            session.current_task = RouteTaskEnum.SUPPLIER_REQUEST_CREATE.value
            session.current_step = QuoteRequestEnum.VESSEL_NAME.value
            session.route_id = None
            session, err = await self.db_service.update_session(session.user_id, session.current_task, session.current_step, session.route_id, session.data)
            return await self.template_service.session_template(session, err_msg=str(err) if err else None)

        route_id = session.data.quote_search.id
        if not route_id:
            session.current_step = SupplierRequestSearchEnum.LIST.value
            await self.db_service.update_session(session.user_id, session.current_task, session.current_step, None, session.data)
            return await self.template_service.search_route_template(session)

        if q in ("2", "delete", "de", "del", "d", "remove", "rm", "rem"):
            # DELETE → confirm
            session.current_step = SupplierRequestSearchEnum.CONFIRM_DELETE.value
            await self.db_service.update_session(session.user_id, session.current_task, session.current_step, None, session.data)
            return ResponsePayloadCollection(
                responses=[ResponsePayload(
                    text=" <b>Are you sure?\n1. Yes\n0. Cancel\n </b> ",
                    keyboard=self.navigation_handler.get_yes_no_keyboard()
                )]
            )

        if q in ("back", "b", "0"):
            session.current_step = SupplierRequestSearchEnum.LIST.value

            await self.db_service.update_session(
                session.user_id,
                session.current_task,
                session.current_step,
                None,
                session.data
            )

            return await self.template_service.quote_search_template(session)

        return ResponsePayloadCollection(
            responses=[ResponsePayload(text="Enter back(b) to return")]
        )

    async def _apply_pagination(self, session: SessionDB, value: str):

        search = session.data.quote_search
        page_size = search.limit or 5

        total, _ = await self.db_service.count_quotes(str(session.user_id))
        search.total = total

        total_pages = (total - 1) // page_size if total else 0

        if value == "+":
            search.offset = min(search.offset + 1, total_pages)

        elif value == "-":
            search.offset = max(0, search.offset - 1)

        elif value == "start":
            search.offset = 0

        elif value == "end":
            search.offset = total_pages

        row_offset = search.offset * page_size

        quotes, _ = await self.db_service.get_quotes(
            str(session.user_id),
            row_offset,
            page_size
        )

        search.ids = [q.id for q in quotes]

        return await self.db_service.update_session(
            session.user_id,
            session.current_task,
            session.current_step,
            None,
            session.data
        )

    async def _handle_confirm_delete(self, session: SessionDB, message: str):
        q = message.strip()
        quote_id = session.data.quote_search.id

        if q == "1" or self.ai_service.is_validation_positive(q):
            await self.db_service.mark_quote_deleted(quote_id)
            session.current_step = SupplierRequestSearchEnum.LIST.value
            session.data.quote_search.id = None
            session, err = await self.db_service.update_session(session.user_id, session.current_task, session.current_step, None, session.data)
            session, err = await self._apply_pagination(session, "")
            return await self.template_service.quote_search_template(
                session, "Route deleted" if not err else str(err)
            )

        if q == "0" or self.ai_service.is_validation_negative(q):
            #if session.current_step == SupplierRequestSearchEnum.VIEW.value:
            #    s =  SupplierRequestSearchEnum.VIEW.value

            session.current_step = SupplierRequestSearchEnum.LIST.value
            await self.db_service.update_session(session.user_id, session.current_task, session.current_step, None, session.data)
            quote, _ = await self.db_service.get_quote_by_id(quote_id)
            return await self.template_service.show_quote_template(quote)

        # if q in ("back", "b"):
        #     session.current_step = SupplierRequestSearchEnum.LIST.value
        #
        #     #session.current_step = SupplierRequestSearchEnum.VIEW.value
        #     await self.db_service.update_session(session.user_id, session.current_task, session.current_step, None, session.data)
        #     return await self.template_service.quote_search_template(session)

        return ResponsePayloadCollection(
            responses=[ResponsePayload(text="Choose 1 or 0")]
        )