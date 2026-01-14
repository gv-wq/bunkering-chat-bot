from typing import Dict, Optional, Tuple, List

from app.data import emogye
from app.data.dto.main.Session import SessionDB
from app.data.dto.main.SessionData import SessionData, RouteSearch, UserSearch, AdminUpdateTariff
from app.data.dto.main.TariffSelection import TariffSelection
from app.data.enums.RouteStep import RouteStepEnum
from app.data.enums.RouteTask import RouteTaskEnum
from app.data.enums.AdminStepEnum import AdminStepEnum
from app.data.enums.search_route_enum import SearchRouteStepEnum
from app.services.db_service import DbService


class NavigationHandler:
    def __init__(self, sql_db_service: DbService):
        self.sql_db_service = sql_db_service

        # Define step flows for each task
        self.task_flows = {
            RouteTaskEnum.CREATE_ROUTE.value: [
               # RouteStepEnum.DEPARTURE_DESTINATION.value,
                #RouteStepEnum.DEPARTURE_PORT.value,
                #RouteStepEnum.DESTINATION_PORT.value,

                RouteStepEnum.DEPARTURE_PORT_SUGGESTION.value,
                #RouteStepEnum.DEPARTURE_PORT_NEARBY.value,
                RouteStepEnum.DESTINATION_PORT_SUGGESTION.value,
                #RouteStepEnum.DESTINATION_PORT_NEARBY.value,

                RouteStepEnum.DEPARTURE_DATE.value,
                RouteStepEnum.AVERAGE_SPEED.value,
                RouteStepEnum.FUEL_SELECTION.value,
                #RouteStepEnum.ROUTE_BUILD_REQUEST.value,
                RouteStepEnum.ROUTE_PORT_LIST.value,
                RouteStepEnum.BUNKERING_QUEUE.value,
                RouteStepEnum.PDF_REQUEST.value,
                RouteStepEnum.VESSEL_NAME.value,
                RouteStepEnum.VESSEL_IMO.value,
                RouteStepEnum.USER_EMAIL.value,
                RouteStepEnum.SUPPLIER_PRICES.value,
                RouteStepEnum.COMPANY_NAME.value


            ],
            RouteTaskEnum.SEARCH_ROUTE.value: [
                SearchRouteStepEnum.LIST.value,
                SearchRouteStepEnum.VIEW.value

            ],
            RouteTaskEnum.GET_PORT_PRICE.value: [
            ],
            RouteTaskEnum.ADMIN.value: [
                AdminStepEnum.GENERAL.value,
                AdminStepEnum.UPDATE_TARIFF.value
            ]
        }

        # Define which steps are free (can be jumped to) for each task
        self.task_free_steps = {
            RouteTaskEnum.CREATE_ROUTE.value: [
                #RouteStepEnum.DEPARTURE_DESTINATION.value,
                #RouteStepEnum.DEPARTURE_PORT.value,
                #RouteStepEnum.DESTINATION_PORT.value,
                RouteStepEnum.DEPARTURE_PORT_SUGGESTION.value,
               # RouteStepEnum.DEPARTURE_PORT_NEARBY.value,
               # RouteStepEnum.DESTINATION_PORT_NEARBY.value,
                RouteStepEnum.DESTINATION_PORT_SUGGESTION.value,
                RouteStepEnum.DEPARTURE_DATE.value,
                RouteStepEnum.AVERAGE_SPEED.value,
                RouteStepEnum.FUEL_SELECTION.value,

            ],
            RouteTaskEnum.SEARCH_ROUTE.value: [

            ],
            RouteTaskEnum.GET_PORT_PRICE.value: [

            ]
        }

        # Define sequential steps for each task
        self.task_sequential_steps = {
            RouteTaskEnum.CREATE_ROUTE.value: [
               # RouteStepEnum.ROUTE_BUILD_REQUEST.value,
                RouteStepEnum.ROUTE_PORT_LIST.value,
                RouteStepEnum.BUNKERING_QUEUE.value,
                RouteStepEnum.PDF_REQUEST.value,
                RouteStepEnum.VESSEL_NAME.value,
                RouteStepEnum.VESSEL_IMO.value,
                RouteStepEnum.USER_EMAIL.value,
                RouteStepEnum.SUPPLIER_PRICES.value,
                RouteStepEnum.COMPANY_NAME.value
            ],
            RouteTaskEnum.SEARCH_ROUTE.value: [
                SearchRouteStepEnum.LIST.value,
                SearchRouteStepEnum.VIEW.value
            ],
            RouteTaskEnum.GET_PORT_PRICE.value: []
        }

    def get_task_steps(self, task_value: str) -> List[str]:
        return self.task_flows.get(task_value, [])

    def get_step_title(self, step_value: str, update_status: bool = False) -> str:
        """Get the display title for a step"""

        new_route = f"{emogye.ANCHOR} New route - "
        titles = {
            RouteStepEnum.DEPARTURE_PORT_SUGGESTION.value: f"{new_route}{emogye.ARROW_UP} Departure port search",
         #   RouteStepEnum.DEPARTURE_PORT_NEARBY.value: f"{emogye.PIN} Departure port nearby",
            RouteStepEnum.DESTINATION_PORT_SUGGESTION.value: f"{new_route}{emogye.ARROW_DOWN} Destination port search",
          #  RouteStepEnum.DESTINATION_PORT_NEARBY.value: f"{emogye.PIN} Destination port nearby",
            RouteStepEnum.DEPARTURE_DATE.value: f"{new_route}{emogye.CALENDAR} Departure date",
            RouteStepEnum.AVERAGE_SPEED.value: f"{new_route}{emogye.SPEED} Average speed",
            RouteStepEnum.FUEL_SELECTION.value: f"{new_route}{emogye.OIL_DUM} Fuel selection",
            RouteStepEnum.ROUTE_PORT_LIST.value: f"{new_route}{emogye.BOX_WITH_CHECK} Ports selection",
            RouteStepEnum.BUNKERING_QUEUE.value: f"{new_route}{emogye.HANDSHAKE} Bunkering requests",
            RouteStepEnum.PDF_REQUEST.value: f"{new_route}{emogye.PDF} PDF request",
            RouteStepEnum.VESSEL_NAME.value: f"{new_route}{emogye.SHIP} Vessel name",
            RouteStepEnum.VESSEL_IMO.value: f"{new_route}{emogye.SHIP} Vessel imo",
            RouteStepEnum.SUPPLIER_PRICES.value : f"{new_route}{emogye.STATS_LINE} Supplier prices",
            RouteStepEnum.COMPANY_NAME.value : f"{new_route}{emogye.COMPANY} Company name",
            RouteStepEnum.USER_EMAIL.value: f"{new_route}{emogye.POSTMAIL} User email",

            RouteStepEnum.MAIN_MENU.value : "Main Menu"
        }

        update_titles = {
            RouteStepEnum.DEPARTURE_PORT_SUGGESTION.value: f"{emogye.REPEAT} Step 1 of 4 - UPDATE DEPARTURE PORT",
            RouteStepEnum.DESTINATION_PORT_SUGGESTION.value: f"{emogye.REPEAT} Step 2 of 4 - UPDATE DESTINATION PORT",
            RouteStepEnum.DEPARTURE_DATE.value: f"{emogye.REPEAT} Step 3 of 4 - UPDATE DEPARTURE DATE",
            RouteStepEnum.AVERAGE_SPEED.value: f"{emogye.REPEAT} Step 4 of 4 - UPDATE AVERAGE SPEED",
        }

        return titles.get(step_value, step_value) if not update_status else update_titles.get(step_value, titles.get(step_value, step_value))

    def get_navigation_text(self, session: SessionDB) -> str:
        """Generate navigation help text based on current task and step"""
        if not session.current_task:
            return self.get_main_menu()

        flow = self.task_flows.get(session.current_task, [])
        free_steps = self.task_free_steps.get(session.current_task, [])
        sequential_steps = self.task_sequential_steps.get(session.current_task, [])

        current_step = session.current_step
        current_index = self._get_step_index(flow, current_step)

        navigation_lines = [
            "\n\nNavigation Commands:",
        ]

        # Add NEXT command with specific step name
        if current_index < len(flow) - 1:
            next_step = flow[current_index + 1]
            next_step_title = self.get_step_title(next_step)

            # Check if we can proceed to next step based on step type
            if (current_step in free_steps and next_step in free_steps) or \
                    (current_step in sequential_steps and next_step in sequential_steps) or \
                    (current_step in free_steps and next_step in sequential_steps and
                     current_step == free_steps[-1] and next_step == sequential_steps[0]):
                # navigation_lines.append(f"-  next, yes(y), fine, confirm - {next_step_title}")
                navigation_lines.append(f"- yes(y) - {next_step_title}")


        # Add BACK command only if there are previous steps
        if current_index > 0:
            prev_step = flow[current_index - 1]
            step_title = self.get_step_title(prev_step)
            navigation_lines.append(f"- back - {step_title}")


        # Add JUMP command for free steps with available targets
        if current_step in free_steps:
            available_jumps = []
            for step in free_steps:
                if step != current_step:
                    step_title = self.get_step_title(step)
                    available_jumps.append(f"- {step} - {step_title}")

            if available_jumps:
                pass
                #navigation_lines.append("-  jump stepName - Jump to free step")
                #navigation_lines.append("Available steps:")
                #navigation_lines.extend(available_jumps)
        navigation_lines.append("- menu - Main menu")
        return "\n".join(navigation_lines)

    def get_main_menu(self, admin_status: bool = False, new_user: bool = False) -> str:
        l = [

            "You can type 1–3 or write it in words.",
            "",
            f"You can now:" if new_user else "Main menu:" 
            "\n",
            f"1. Create new route {emogye.PLUS} - calculate bunker budget along the voyage",
            f"2. Show my routes {emogye.FOLDER} - review saved routes and costs",
            f"3. Check port’s fuel price & trends {emogye.STATS_LINE} - see indicative bunker prices by port and historical trends",
        ]

        if admin_status:
            l.append("4. User management: http://chat-admin.thebunkering.com")

        l.append("")
        #l.append(,)
        return "\n".join(l)



    async def to_prev_step(
            self, session: SessionDB
    ) -> Tuple[Optional[SessionDB], Optional[str]]:
        if not session.current_task:
            return await self.return_to_main_menu(session)

        flow = self.task_flows.get(session.current_task, [])
        if not flow:
            return await self.return_to_main_menu(session)

        prev_step = None
        if (session.current_task == RouteTaskEnum.SEARCH_ROUTE.value) and (session.current_step == SearchRouteStepEnum.CONFIRM_DELETE.value):
            return session, None

        current_index = self._get_step_index(flow, session.current_step)
        if current_index <= 0:
            # First step of task, return to main menu
            return await self.return_to_main_menu(session)
        prev_step = flow[current_index - 1]

        return await self.sql_db_service.update_session(
            session.user_id,
            session.current_task,
            prev_step,
            session.route_id,
            session.data,
        )

    async def to_next_step(
            self, session: SessionDB, route_data: Optional[Dict] = None
    ) -> Tuple[Optional[SessionDB], Optional[str]]:

        if not session.current_task:
            return session, "No active task"

        flow = self.task_flows.get(session.current_task, [])
        if not flow:
            return session, "Invalid task flow"

        current_index = self._get_step_index(flow, session.current_step)
        if current_index >= len(flow) - 1:
            return session, "Already at the last step"

        next_step = flow[current_index + 1]

        if not await self._can_proceed_to_next(session, next_step, route_data):
            return session, f"Cannot proceed to {next_step}"

        return await self.sql_db_service.update_session(
            session.user_id,
            session.current_task,
            next_step,
            session.route_id,
            session.data,
        )

    async def switch_session_step(
            self, session: SessionDB, target_step: str
    ) -> Tuple[Optional[SessionDB], Optional[str]]:

        if not session.current_task:
            return session, "No active task"

        flow = self.task_flows.get(session.current_task, [])
        free_steps = self.task_free_steps.get(session.current_task, [])

        if not flow or target_step not in flow:
            return session, f"Invalid step for current task: {target_step}"

        if not await self._can_switch_to_step(session, target_step, free_steps):
            return session, f"Cannot jump to {target_step}"

        return await self.sql_db_service.update_session(
            session.user_id,
            session.current_task,
            target_step,
            session.route_id,
            session.data,
        )

    async def start_task(
            self, session: SessionDB, task: str
    ) -> Tuple[Optional[SessionDB], Optional[str]]:
        """Start a new task from main menu"""
        if task not in self.task_flows:
            return session, f"Unknown task: {task}"

        flow = self.task_flows[task]
        first_step = flow[0] if flow else RouteStepEnum.MAIN_MENU.value

        return await self.sql_db_service.update_session(
            session.user_id,
            task,
            first_step,
            None,  # Reset route_id for new task
            session.data,  # Reset data for new task
        )

    def _get_step_index(self, flow: list, current_step: str) -> int:
        try:
            return flow.index(current_step)
        except ValueError:
            return 0

    async def return_to_main_menu(self, session: SessionDB) -> Tuple[Optional[SessionDB], Optional[str]]:
        """Return to main menu and clear task context"""
        return await self.sql_db_service.update_session(
            session.user_id,
            RouteStepEnum.MAIN_MENU.value,
            None,
            None,
            SessionData(check_port_fuel_price=None, route_search=RouteSearch(), tariff_selection=TariffSelection(user_message=None, chosen_tariff=None ), user_search=UserSearch.from_dict({}), admin_update_tariff=AdminUpdateTariff.from_dict({})),  # Clear session data
        )

    async def _can_proceed_to_next(
            self, session: SessionDB, next_step: str, route_data: Optional[Dict] = None
    ) -> bool:
        """Check if we can proceed to the next step"""
        if session.current_task == RouteTaskEnum.CREATE_ROUTE.value:
            return await self._validate_create_route_step(session, next_step, route_data)
        elif session.current_task == RouteTaskEnum.SEARCH_ROUTE.value:
            return await self._validate_search_route_step(session, next_step, route_data)
        elif session.current_task == RouteTaskEnum.GET_PORT_PRICE.value:
            return await self._validate_port_price_step(session, next_step, route_data)
        return True

    async def _can_switch_to_step(
            self, session: SessionDB, target_step: str, free_steps: List[str]
    ) -> bool:
        """Check if we can jump to the target step"""
        # Can only jump between free steps within the same task
        return target_step in free_steps# and
               # session.current_step in free_steps)

    async def _validate_create_route_step(
            self, session: SessionDB, next_step: str, route_data: Optional[Dict]
    ) -> bool:
        """Validation for create route task steps"""
        if not session.route_id:
            return False

        route, err = await self.sql_db_service.get_route_by_id(str(session.route_id))
        if err or not route:
            return False

        # if next_step == RouteStepEnum.DEPARTURE_PORT_NEARBY.value:
        #     return all([
        #         route.data.port_selection.departure_suggestions is not None,
        #         route.data.port_selection.departure_candidate is not None
        #     ])

        elif next_step == RouteStepEnum.DESTINATION_PORT_SUGGESTION.value:
            return all([
                route.departure_port_id is not None,
            ])

        # elif next_step == RouteStepEnum.DESTINATION_PORT_NEARBY.value:
        #     return all([
        #         route.data.port_selection.destination_suggestions is not None,
        #     ])

        if next_step == RouteStepEnum.DEPARTURE_DATE.value:
            return all([route.departure_port_id, route.destination_port_id])

        elif next_step == RouteStepEnum.AVERAGE_SPEED.value:
            return all([
                route.departure_port_id,
                route.destination_port_id,
                route.departure_date,
            ])


        elif next_step == RouteStepEnum.ROUTE_PORT_LIST.value:
            return all([
                route.departure_port_id,
                route.destination_port_id,
                route.departure_date,
                route.average_speed_kts,
            ])


        elif next_step == RouteStepEnum.VESSEL_IMO.value:
            return True if route.vessel_name else False

        return True

    async def _validate_search_route_step(
            self, session: SessionDB, next_step: str, route_data: Optional[Dict]
    ) -> bool:
        """Validation for search route task steps"""
        # Add validation logic for search route steps
        if next_step == RouteStepEnum.DEPARTURE_DATE.value:
            return bool(session.data.get('departure_port_id') and session.data.get('destination_port_id'))

        elif next_step == RouteStepEnum.AVERAGE_SPEED.value:
            return bool(session.data.get('estimated_departure_time'))

        # elif next_step == RouteStepEnum.ROUTE_BUILD_REQUEST.value:
        #     return bool(session.data.get('average_speed_kts'))

        return True

    async def _validate_port_price_step(
            self, session: SessionDB, next_step: str, route_data: Optional[Dict]
    ) -> bool:
        """Validation for port price task steps"""
        if next_step == RouteStepEnum.FUEL_SELECTION.value:
            return bool(session.data.get('port_id'))
        return True


