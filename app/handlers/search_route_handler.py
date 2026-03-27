# from typing import Dict
import uuid

from app.data.dto.main.SeaPort import SeaPortDB
from app.data.dto.main.Session import SessionDB
from app.data.dto.messenger.ResponsePayload import ResponsePayloadCollection, ResponsePayload
from app.data.enums.RouteStep import RouteStepEnum
from app.data.enums.RouteTask import RouteTaskEnum
from app.data.enums.search_route_enum import SearchRouteStepEnum
from app.handlers.navigation_handler import NavigationHandler
from app.services.db_service import DbService
from app.services.template.telegram_template_service import TemplateService
from app.services.ai_service import AiService
from app.services.utils import utils


class SearchRouteHandler:
    def __init__(self, db_service: DbService, template_service: TemplateService, ai_service: AiService, navigation_handler: NavigationHandler,):
        self.ai_service = ai_service
        self.db_service = db_service
        self.template_service = template_service
        self.navigation_handler = navigation_handler

    async def handle(self, session: SessionDB, message: str) -> ResponsePayloadCollection:
        if session.current_step is None:
            session.current_step = SearchRouteStepEnum.LIST.value
            session, err = await self.db_service.update_session(session.user_id, session.current_task, session.current_step, None, session.data)

        if session.current_step == SearchRouteStepEnum.LIST.value:
            return await self._handle_list(session, message)

        if session.current_step == SearchRouteStepEnum.VIEW.value:
            return await self._handle_view(session, message)

        if session.current_step == SearchRouteStepEnum.CONFIRM_DELETE.value:
            return await self._handle_confirm_delete(session, message)

        return ResponsePayloadCollection(
            responses=[ResponsePayload(text="Unexpected state")]
        )

    async def _handle_list(self, session: SessionDB, message: str):
        q = message.strip().lower()
        search = session.data.route_search

        # --------------------------------------------------
        # DATE RESET
        # --------------------------------------------------
        # if q in {"reset", "clear", "reset date", "clear date"}:
        #     search.date = None
        #     await self.db_service.update_session(
        #         session.user_id,
        #         session.current_task,
        #         session.current_step,
        #         None,
        #         session.data,
        #     )
        #     await self._apply_pagination(session, "")
        #     return await self.template_service.search_route_template(
        #         session, "Date filter cleared"
        #     )


        # --------------------------------------------------
        # AI DATE (natural language)
        # --------------------------------------------------
        # parsed_date_dict, err = await self.ai_service.parse_date_info(q)
        # if parsed_date_dict:
        #     parsed_date = await utils.parse_fuel_price_date(parsed_date_dict)
        #     if parsed_date:
        #         search.date = parsed_date
        #         await self.db_service.update_session(
        #             session.user_id,
        #             session.current_task,
        #             session.current_step,
        #             None,
        #             session.data,
        #         )
        #         await self._apply_pagination(session, "")
        #         return await self.template_service.search_route_template(
        #             session, #f"Date filter set to {parsed_date}"
        #         )
        if q.startswith(("delete", "d ", "remove")):
            parts = q.split()
            if len(parts) != 2 or not parts[1].isdigit():
                return await self.template_service.search_route_template(
                    session, "Usage: delete <number>"
                )

            idx = int(parts[1]) - 1
            if idx < 0 or idx >= len(search.ids):
                return await self.template_service.search_route_template(
                    session, "Invalid route number"
                )

            session.data.route_search.id = search.ids[idx]
            session.current_step = SearchRouteStepEnum.CONFIRM_DELETE.value

            await self.db_service.update_session(
                session.user_id,
                session.current_task,
                session.current_step,
                None,
                session.data,
            )

            return ResponsePayloadCollection(
                responses=[ResponsePayload(
                    text=" <b> Are you sure?\n1. Yes\n0. Cancel </b> ", keyboard=self.navigation_handler.get_yes_no_keyboard()
                )]
            )

        # numeric → open route
        if q.isdigit():
            idx = int(q) - 1
            if idx < 0 or idx >= len(search.ids):
                return await self.template_service.search_route_template(
                    session, "Invalid route number"
                )

            route_id = search.ids[idx]
            session.data.route_search.id = route_id
            session.current_step = SearchRouteStepEnum.VIEW.value
            await self.db_service.update_session(session.user_id, session.current_task, session.current_step, None, session.data)

            route, _ = await self.db_service.get_route_by_id_2(
                session.user_id, route_id
            )
            return await self.template_service.show_route_template(route)

        # pagination
        if q in {"+", "-", "start", "end"}:
            session, err = await self._apply_pagination(session, q)
            return await self.template_service.search_route_template(session, str(err) if err else None)


        # fallback → AI
        intent, err = await self.ai_service.parse_search_route_intent(session, message)
        if err:
            return await self.template_service.search_route_template(session, err)

        return await self.template_service.search_route_template(session)

    async def _handle_view(self, session: SessionDB, message: str):
        q = message.strip().lower()

        route_id = session.data.route_search.id
        if not route_id:
            session.current_step = SearchRouteStepEnum.LIST.value
            await self.db_service.update_session(session.user_id, session.current_task, session.current_step, None, session.data)
            return await self.template_service.search_route_template(session)

        if q in ("yes", "y", "ye", "1", "u", "update"):
            # UPDATE
            session, err = await self._switch_to_update_flow(session, route_id)
            if session:
                return await self.template_service.session_template(session)

        if q in ("2", "delete", "d", "remove"):
            # DELETE → confirm
            session.current_step = SearchRouteStepEnum.CONFIRM_DELETE.value
            await self.db_service.update_session(session.user_id, session.current_task, session.current_step, None, session.data)
            return ResponsePayloadCollection(
                responses=[ResponsePayload(
                    text=" <b>Are you sure?\n1. Yes\n0. Cancel\n </b> ",
                    keyboard=self.navigation_handler.get_yes_no_keyboard()
                )]
            )

        if q in ("0", "b", "back"):
            # back to list
            session.current_step = SearchRouteStepEnum.LIST.value
            await self.db_service.update_session(session.user_id, session.current_task, session.current_step, None, session.data)
            return await self.template_service.search_route_template(session)

        return ResponsePayloadCollection(
            responses=[ResponsePayload(text="Enter yes(y), remove (r) or back")]
        )

    async def _handle_confirm_delete(self, session: SessionDB, message: str):
        q = message.strip()
        route_id = session.data.route_search.id

        if q == "1" or self.ai_service.is_validation_positive(q):
            await self.db_service.mark_route_deleted(uuid.UUID(route_id))
            session.current_step = SearchRouteStepEnum.LIST.value
            session.data.route_search.id = None
            session, err = await self.db_service.update_session(session.user_id, session.current_task, session.current_step, None, session.data)
            session, err = await self._apply_pagination(session, "")
            return await self.template_service.search_route_template(
                session, "Route deleted" if not err else str(err)
            )

        if q == "0" or self.ai_service.is_validation_negative(q):
            session.current_step = SearchRouteStepEnum.VIEW.value
            await self.db_service.update_session(session.user_id, session.current_task, session.current_step, None, session.data)
            route, _ = await self.db_service.get_route_by_id_2(
                session.user_id, route_id
            )
            return await self.template_service.show_route_template(route)

        if q in ("back", "b"):
            session.current_step = SearchRouteStepEnum.LIST.value
            session.current_step = SearchRouteStepEnum.VIEW.value
            await self.db_service.update_session(session.user_id, session.current_task, session.current_step, None, session.data)
            return await self.template_service.search_route_template(session)


        return ResponsePayloadCollection(
            responses=[ResponsePayload(text="Choose 1 or 0")]
        )

    async def _switch_to_update_flow(self, session: SessionDB, route_id: str):
        session.current_task = RouteTaskEnum.CREATE_ROUTE.value
        session.current_step = RouteStepEnum.DEPARTURE_PORT_SUGGESTION.value
        new_session ,new_session_err = await self.db_service.update_session(
            session.user_id,
            session.current_task,
            session.current_step,
            uuid.UUID(route_id),
            session.data
        )

        route, err = await self.db_service.get_route_by_id(route_id)
        if route:
            route.data.is_updating = True
            route, err = await self.db_service.update_route(route)

        return new_session, new_session_err

    async def _apply_pagination(self, session: SessionDB, value: str):
        search = session.data.route_search
        user_id = str(session.user_id)

        page_size = 4

        total, err = await self.db_service.count_routes_with_date_filter(
            user_id=user_id,
            departure_date=search.date,
        )
        search.total = total if not err else 0
        total = search.total

        if total == 0:
            search.offset = 0
            search.ids = []
            await self.db_service.update_session(
                session.user_id, session.current_task, session.current_step, None, session.data
            )
            return

        total_pages = (total - 1) // page_size  # zero-based

        if value == "+":
            search.offset = min(search.offset + 1, total_pages)

        elif value == "-":
            search.offset = max(0, search.offset - 1)

        elif value == "start":
            search.offset = 0

        elif value == "end":
            search.offset = total_pages

        # DB OFFSET
        row_offset = search.offset * page_size

        routes, err = await self.db_service.get_routes_range_with_date_filter(
            user_id=user_id,
            offset=row_offset,
            departure_date=search.date,
        )

        if err:
            return

        search.ids = [str(r.id) for r in routes]

        return await self.db_service.update_session(
            session.user_id, session.current_task, session.current_step, None, session.data
        )

