from typing import Dict, Any, Tuple, Optional

from app.data import emogye
from app.data.enums.RouteTask import RouteTaskEnum
from app.data.enums.RouteStep import RouteStepEnum
from app.data.dto.main.Session import SessionDB
from app.data.dto.messenger.ResponsePayload import (
    ResponsePayload,
    ResponsePayloadCollection,
)
from app.data.enums.StartStepEnum import StartStepEnum

from app.services.db_service import DbService
from app.services.ai_service import AiService
from app.services.template.telegram_template_service import TemplateService


class MainMenuHandler:
    def __init__(
        self,
        ai_service: AiService,
        sql_db_service: DbService,
        template_service: TemplateService,
    ):
        self.template_service = template_service
        self.sql_db_service = sql_db_service
        self.ai_service = ai_service

    async def to_main_menu(self, session: SessionDB):
        return await self.sql_db_service.update_session(
            session.user_id,
            RouteTaskEnum.MAIN_MENU.value,
            None,
            session.route_id,
            session.data,
        )

    async def handle_main_menu(
        self, session: SessionDB, message: str, is_admin: bool = False
    ) -> ResponsePayloadCollection:

        intent, err = await self._parse_menu_intent(message, session, is_admin)
        if err:
            return ResponsePayloadCollection(
                responses=[ResponsePayload(err=f"Menu intent parsing error: {err}")]
            )
        action = intent.get("action")

        if action == "start_task":
            task = intent.get("task")
            if task == RouteTaskEnum.CREATE_ROUTE.value:
                return await self._start_create_route(session)
            if task == RouteTaskEnum.GET_PORT_PRICE.value:
                return await self._start_find_fuel_price(session)
            if task == RouteTaskEnum.SEARCH_ROUTE.value:
                return await self._start_search_route(session)
            if task == RouteTaskEnum.ADMIN.value:
                return await self._start_admin(session)

        elif action == "navigate":
            direction = intent.get("direction")
            if direction == "back":

                return await self.template_service.main_menu_template(session,  is_admin=is_admin)
            elif direction in ["menu", "cancel"]:

                return await self.template_service.main_menu_template(session,   is_admin=is_admin)

        return await self.template_service.main_menu_template(session, "🤔 I didn’t quite get that. Please choose one of the options below." ,   is_admin=is_admin)


    async def _parse_menu_intent(
        self, message: str, session: SessionDB, admin_status: bool = False
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        """Парсит намерения в главном меню"""
        try:
            message_lower = message.strip().lower()

            start_task_port_price =  {"action": "start_task", "task": RouteTaskEnum.GET_PORT_PRICE.value}
            start_task_search_route =  {"action": "start_task", "task": RouteTaskEnum.SEARCH_ROUTE.value}
            start_admin_task = {"action": "start_task", "task": RouteTaskEnum.ADMIN.value}

            # Быстрые проверки для common commands
            quick_commands = {
                "menu": {"action": "navigate", "direction": "menu"},
                "cancel": {"action": "navigate", "direction": "cancel"},
                "1": {"action": "start_task", "task": "create_route"},
                "create": {"action": "start_task", "task": "create_route"},
                "create route": {"action": "start_task", "task": "create_route"},
                "new route": {"action": "start_task", "task": "create_route"},
                "new": {"action": "start_task", "task": "create_route"},
                "2": start_task_search_route,
                "list": start_task_search_route,
                "list routes": start_task_search_route,
                "my routes": start_task_search_route,
                "routes":start_task_search_route,
                "show routes": start_task_search_route,
                "search": start_task_search_route,
                "3": start_task_port_price,
                "price": start_task_port_price,
                "port price": start_task_port_price,
                "fuel price": start_task_port_price,
                "check": start_task_port_price,

            }
            # if admin_status:
            #     quick_commands["4"] = start_admin_task
            #     quick_commands['admin'] = start_admin_task


            if message_lower in quick_commands:
                return quick_commands[message_lower], None

            # AI анализ для сложных случаев
            return await self.ai_service.parse_menu_intent_with_ai(message, session)

        except Exception as e:
            return {"action": "unknown", "errors": [str(e)]}, str(e)

    async def _process_menu_intent(
        self, session: SessionDB, intent: Dict
    ) -> ResponsePayloadCollection:
        action = intent.get("action")

        if action == "start_task":
            task = intent.get("task")
            if task == "create_route":
                return await self._start_create_route(session)
            # elif task == 'list_routes':
            #     return await self._start_list_routes(session)
            # elif task == 'search_route':
            #     return await self._start_search_route(session)

        elif action == "navigate":
            direction = intent.get("direction")
            if direction == "back":

                return await self.template_service.main_menu_template(session)
            elif direction in ["menu", "cancel"]:

                return await self.template_service.main_menu_template(session)

        return await self.template_service.main_menu_template(
            session, "🤔 I didn’t quite get that. Please choose one of the options below."
        )

    async def _start_create_route(
        self, session: SessionDB
    ) -> ResponsePayloadCollection:

        route_data = {
            "user_id": session.user_id,
        }
        route, err = await self.sql_db_service.create_route(route_data)
        if err:
            return ResponsePayloadCollection(
                responses=[ResponsePayload(err=f"Route creation error: {err}")]
            )

        updated_session, err = await self.sql_db_service.update_session(
            session.user_id,
            RouteTaskEnum.CREATE_ROUTE.value,
            RouteStepEnum.DEPARTURE_PORT_SUGGESTION.value,
            route.id,
            session.data,
        )

        if err:
            return ResponsePayloadCollection(
                responses=[ResponsePayload(err=f"Session update error: {err}")]
            )

        return await self.template_service.port_suggestions_template(updated_session, route)

    async def _start_find_fuel_price(self, session: SessionDB) -> ResponsePayloadCollection:
        session, err = await self.sql_db_service.update_session(
            session.user_id,
            RouteTaskEnum.GET_PORT_PRICE.value,
            None,
            None,
            None)
        if err:
            return ResponsePayloadCollection(responses=[ResponsePayload(err=f"Can not start port fuel price searching because of:: {err}")])

        return await self.template_service.get_port_fuel_price_template(session)


    async def _start_search_route(self, session: SessionDB) -> ResponsePayloadCollection:
        routes, err = await self.sql_db_service.get_routes_range_with_date_filter(str(session.user_id))
        if routes:
            session.data.route_search.ids = [str(r.id) for r in routes]

        updated_session, err = await self.sql_db_service.update_session(
            session.user_id,
            RouteTaskEnum.SEARCH_ROUTE.value,
            None,
            None,
            session.data,
        )

        if err:
            return ResponsePayloadCollection(responses=[ResponsePayload(err=f"Session update error: {err}")])

        return await self.template_service.search_route_template(updated_session)

    async def _start_admin(self, session: SessionDB) -> ResponsePayloadCollection:
        users, err = await self.sql_db_service.get_users_range(0, 4)
        if users:
            session.data.user_search.ids = [str(r.id) for r in users]

        updated_session, err = await self.sql_db_service.update_session(
            session.user_id,
            RouteTaskEnum.ADMIN.value,
            None,
            None,
            session.data,
        )

        if err:
            return ResponsePayloadCollection(responses=[ResponsePayload(err=f"Session update error: {err}")])

        return await self.template_service.list_users_template(updated_session)

    async def handle_start(self, session: SessionDB, message: str, is_admin: bool) -> ResponsePayloadCollection:
        if session.current_step is None:
            session.current_step = StartStepEnum.ROLE.value
            s, err = await self.sql_db_service.update_session(session.user_id, session.current_task, StartStepEnum.ROLE.value, None, session.data)

        if session.current_step == StartStepEnum.ROLE.value:
            return await self._handle_role(session, message, is_admin)

        if session.current_step == StartStepEnum.USER_NAME.value:
            return await self._handle_user_name(session, message, is_admin)

        return await self.template_service.main_menu_template(
            session,
            message=f"Let’s continue {emogye.FINE}",
            is_admin=is_admin,
            new_user=True
        )

    async def _handle_role(self, session: SessionDB, message: str, is_admin: bool):
        intent, err = await self.ai_service.parse_new_user_intent(message)
        if err:
            return await self.template_service.new_start_template(session, err, is_admin)

        action = intent.get("action")

        if action == "update":
            await self._update_role(session, intent, is_admin)
            return await self._confirm_role(session, is_admin)

        if action == "confirm":
            return await self._confirm_role(session, is_admin)

        return await self.template_service.new_start_template(
            session, "Could not parse the role. Try again.", is_admin
        )

    async def _update_role(self, session: SessionDB, intent: dict, is_admin: bool):
        user, _ = await self.sql_db_service.get_user_by_id(session.user_id)

        # # role can be set only once
        # if user.role:
        #     return await self.template_service.new_start_template(
        #         session, "Role is already selected 👍", is_admin
        #     )

        role = intent.get("role")
        if not role:
            return await self.template_service.new_start_template(
                session, "Could not parse the role. Try again.", is_admin
            )

        _, err = await self.sql_db_service.update_user(
            str(session.user_id), {"role": role}
        )
        if err:
            return await self.template_service.new_start_template(session, str(err), is_admin)

        return await self.template_service.new_start_template(session, None, is_admin)

    async def _confirm_role(self, session: SessionDB, is_admin: bool):
        user, err = await self.sql_db_service.get_user_by_id(session.user_id)
        if err:
            return await self.template_service.new_start_template(session, str(err), is_admin)

        if not user.role:
            return await self.template_service.new_start_template(session, "You need to select a role first.", is_admin)

        await self.sql_db_service.update_session(session.user_id, RouteTaskEnum.START.value,  StartStepEnum.USER_NAME.value, None, session.data  )

        return await self.template_service.user_name_template(session)

        # -------- USER NAME STEP --------

    async def _handle_user_name(self, session: SessionDB, message: str, is_admin: bool):
        name = message.strip()

        # dash / skip / empty → go next
        if name in {"-", "skip", "next", ""}:
            session.current_step = StartStepEnum.DONE.value
            await self.sql_db_service.update_session(session.user_id, RouteTaskEnum.MAIN_MENU.value, StartStepEnum.DONE.value, None, session.data)
            session, err = await self.to_main_menu(session)
            return await self.template_service.session_template(session,
                err_msg="Let’s continue 👍",
                is_admin=is_admin,
            )


        # save first name
        _, err = await self.sql_db_service.update_user(
            str(session.user_id), {"filled_name": name}
        )
        if err:
            return await self.template_service.user_name_template(
                session, "Could not save the name. Try again."
            )

        session.current_step = StartStepEnum.DONE.value
        await self.sql_db_service.update_session(session.user_id, RouteTaskEnum.MAIN_MENU.value, None, None, session.data)

        return await self.template_service.main_menu_template(
            session,
            message=f"Nice to meet you, {name} 👍\nLet’s continue.",
            is_admin=is_admin,
            new_user=True
        )

