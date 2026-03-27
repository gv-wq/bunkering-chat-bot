import re
import uuid
from difflib import SequenceMatcher
from typing import Dict, Any, Tuple, Optional

from app.data import emoji
from app.data.dto.main.Event import Event
from app.data.dto.main.SessionData import CheckFuelPrice
from app.data.dto.main.User import UserDB
from app.data.enums.QuoteRequestEnum import QuoteRequestEnum
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
from app.services.utils import utils

PROMO_PATTERN = re.compile(r'^[A-Z]{4}$')

ROLE_MAP = {
    "Ship owner": "ship_owner",
    "Ship operator": "ship_operator",
    "Fleet / Voyage manager": "fleet_manager",
    "Bunker trader / Supplier": "bunker_trader",
    "Charterer": "charterer",
    "Technical / Other": "technical_other",
}
ROLE_OPTIONS = [
    "Ship owner",
    "Ship operator",
    "Fleet / Voyage manager",
    "Bunker trader / Supplier",
    "Charterer",
    "Technical / Other"
]



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
            None,
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
            if task == RouteTaskEnum.ROUTE_RESEARCH.value:
                return await self._start_route_research(session)

            elif task == RouteTaskEnum.GET_PORT_PRICE.value:
                return await self._start_find_fuel_price(session)

            # elif task == RouteTaskEnum.SUPPLIER_REQUEST_CREATE.value:
            #     return await self._start_get_supplier_order(session)

            elif task == RouteTaskEnum.SUPPLIER_RESEARCH.value:
                return await self._start_supplier_research(session)

            #if task == RouteTaskEnum.CREATE_ROUTE.value:
            #    return await self._start_create_route(session)
            #if task == RouteTaskEnum.GET_PORT_PRICE.value:
            #    return await self._start_find_fuel_price(session)
            #if task == RouteTaskEnum.SEARCH_ROUTE.value:
            #    return await self._start_search_route(session)
            elif task == RouteTaskEnum.ADMIN.value:
                return await self._start_admin(session)

        elif action == "navigate":
            direction = intent.get("direction")
            if direction == "back":

                if session.current_step == StartStepEnum.USER_NAME.value:
                    session.current_step = StartStepEnum.ROLE.value
                    session, err = await self.sql_db_service.update_session(session.user_id, session.current_task, session.current_step, session.route_id, session.data)
                    if err:
                        return ResponsePayloadCollection(
                            responses=[ResponsePayload(err=f"Eeeeh with: {err}")]
                        )
                    return await self.template_service.new_start_template(session, message, is_admin)

                elif session.current_step == StartStepEnum.ROLE.value:
                    return await self.template_service.new_start_template(session, message, is_admin)

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

            route_task = {"action": "start_task", "task": RouteTaskEnum.ROUTE_RESEARCH.value}
            port_price_task = {"action": "start_task", "task": RouteTaskEnum.GET_PORT_PRICE.value}
            quote_task = {"action": "start_task", "task": RouteTaskEnum.SUPPLIER_RESEARCH.value}

            quick_commands = {
                "menu": {"action": "navigate", "direction": "menu"},
                "cancel": {"action": "navigate", "direction": "cancel"},

                # 1. Analyse a route - calculate bunker budget….
                "1": route_task,
                "route": route_task,
                "create": route_task,
                "create route": route_task,
                "new route": route_task,
                "new": route_task,
                "route research": route_task,

                "list": route_task,
                "list routes": route_task,
                "my routes": route_task,
                "routes": route_task,
                "show routes": route_task,
                "search": route_task,

                # 2.Check port’s price and trends-…..
                "2": port_price_task,
                "price": port_price_task,
                "port price": port_price_task,
                "port prices": port_price_task,
                "fuel price": port_price_task,
                "check": port_price_task,
                "trends": port_price_task,


                # 3. Ask suppliers offer -request live supplier prices — free and with no obligation
                "3": quote_task,
                "ask": quote_task,
                "suppliers": quote_task,
                "offer": quote_task,
                "live": quote_task,
                "supplier offer": quote_task,
            }


            if message_lower in quick_commands:
                return quick_commands[message_lower], None

            # AI анализ для сложных случаев
            return await self.ai_service.parse_menu_intent_with_ai(message, session)

        except Exception as e:
            return {"action": "unknown", "errors": [str(e)]}, str(e)

    async def _start_route_research(self, session: SessionDB) -> ResponsePayloadCollection:
        session, err = await self.sql_db_service.update_session(session.user_id, RouteTaskEnum.ROUTE_RESEARCH.value, None, session.route_id, session.data)
        return await self.template_service.route_research_template(session, err)


    async def _start_supplier_research(self, session: SessionDB) -> ResponsePayloadCollection:
        quote_r, err = await self.sql_db_service.get_or_create_quote_request(session)
        session, err = await self.sql_db_service.update_session(session.user_id,  RouteTaskEnum.SUPPLIER_RESEARCH.value, None, uuid.UUID(quote_r.id), session.data)
        return await self.template_service.quote_research_template(session, note=err)


    async def _start_create_route(self, session: SessionDB) -> ResponsePayloadCollection:
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
        session.data.check_port_fuel_price = CheckFuelPrice(
            port=None,
            prices=[],
            port_alternatives=[]
        )

        session, err = await self.sql_db_service.update_session(
            session.user_id,
            RouteTaskEnum.GET_PORT_PRICE.value,
            None,
            None,
            session.data)
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
        user, err = await self.sql_db_service.get_user_by_id(session.user_id)
        if not user or err:
            return await self.template_service.new_start_template(session, "Could not find your user. Try again.", is_admin)

        if session.current_step is None:
            step = StartStepEnum.ROLE.value
            if user.role:
                step = StartStepEnum.USER_NAME.value

            session, err = await self.sql_db_service.update_session(session.user_id, session.current_task, step, None, session.data)

        if session.current_step == StartStepEnum.ROLE.value:
            return await self._handle_role(session, user, message, is_admin)

        if session.current_step == StartStepEnum.USER_NAME.value:
            return await self._handle_user_name(session, user,  message, is_admin)

        if session.current_step == StartStepEnum.COMPANY_NAME.value:
            return await self._handle_company_name(session, user, message, is_admin)

        if session.current_step == StartStepEnum.PHONE_NUMBER.value:
            return await self._handle_user_phone(session, user, message, is_admin)

        if session.current_step == StartStepEnum.EMAIL.value:
            return await self._handle_user_email(session, user, message, is_admin)

        if session.current_step == StartStepEnum.PROMOCODE.value:
            return await self._handle_user_promocode(session, user, message, is_admin)

        return await self.template_service.main_menu_template(
            session,
            message=f"Let’s continue {emoji.FINE}",
            is_admin=is_admin,
            new_user=True
        )

    async def _handle_role(
            self,
            session: SessionDB,
            user: UserDB,
            message: str,
            is_admin: bool
    ):

        value = message.strip().lower()

        # Strict confirm flow
        if self.ai_service.is_validation_positive(value):
            return await self._confirm_role(session, user, is_admin)

        # Parse role strictly from allowed options
        role_label, err = self.ai_service.parse_user_role(value)

        if err:
            return await self.template_service.new_start_template(session, err, is_admin)

        return await self._update_role(session, user, role_label, is_admin)

    async def _update_role(
            self,
            session: SessionDB,
            user: UserDB,
            role_label: str,
            is_admin: bool
    ):

        # Role can be set only once
        if user.role:
            existing = next(
                (k for k, v in ROLE_MAP.items() if v == user.role),
                user.role
            )

            return await self._confirm_role(session, user, is_admin)



            return await self.template_service.new_start_template(
                session,
                f"Role already selected: {existing} 👍",
                is_admin
            )

        # Safety check
        if role_label not in ROLE_OPTIONS:
            return await self.template_service.new_start_template(
                session,
                "Invalid role selection.",
                is_admin
            )

        role = ROLE_MAP[role_label]

        _, err = await self.sql_db_service.update_user(
            str(session.user_id),
            {"role": role}
        )

        if err:
            return await self.template_service.new_start_template(
                session,
                "Could not save the role. Try again.",
                is_admin
            )

        user.role = role

        return await self._confirm_role(session, user, is_admin)

    async def _confirm_role(
            self,
            session: SessionDB,
            user: UserDB,
            is_admin: bool
    ):

        # Strict: must have role before continuing
        if not user.role:
            return await self.template_service.new_start_template(
                session,
                "You must select a role first (1–6).",
                is_admin
            )

        session, err = await self.sql_db_service.update_session(session.user_id, RouteTaskEnum.START.value, StartStepEnum.USER_NAME.value, None, session.data)

        return await self.template_service.user_name_template(session, str(err) if err else None)

    # async def _handle_role(self, session: SessionDB, user: UserDB, message: str, is_admin: bool):
    #     intent, err = await self.ai_service.parse_new_user_intent(message)
    #     if err:
    #         return await self.template_service.new_start_template(session, err, is_admin)
    #
    #     action = intent.get("action")
    #
    #     if action == "update":
    #         await self._update_role(session, user, intent, is_admin)
    #         return await self._confirm_role(session, user, is_admin)
    #
    #     if action == "confirm":
    #         return await self._confirm_role(session, user, is_admin)
    #
    #     return await self.template_service.new_start_template(
    #         session, "Could not parse the role. Try again.", is_admin
    #     )
    #
    # async def _update_role(self, session: SessionDB, user : UserDB, intent: dict, is_admin: bool):
    #     # # role can be set only once
    #     if user.role:
    #         return await self.template_service.new_start_template(
    #             session, "Role is already selected 👍", is_admin
    #         )
    #
    #     role = intent.get("role")
    #     if not role:
    #         return await self.template_service.new_start_template(
    #             session, "Could not parse the role. Try again.", is_admin
    #         )
    #
    #     _, err = await self.sql_db_service.update_user(
    #         str(session.user_id), {"role": role}
    #     )
    #     if err:
    #         return await self.template_service.new_start_template(session, str(err), is_admin)
    #
    #     return await self.template_service.new_start_template(session, None, is_admin)
    #
    # async def _confirm_role(self, session: SessionDB, user: UserDB, is_admin: bool):
    #
    #
    #
    #
    #     if not user.role:
    #         return await self.template_service.new_start_template(session, "You need to select a role first.", is_admin)
    #
    #     await self.sql_db_service.update_session(session.user_id, RouteTaskEnum.START.value,  StartStepEnum.USER_NAME.value, None, session.data  )
    #
    #     return await self.template_service.user_name_template(session,)



    # -------- USER NAME STEP --------

    async def _handle_user_name(self, session: SessionDB, user: UserDB, message: str, is_admin: bool):
        name = message.strip()

        # Length validation
        if len(name) > 60:
            return await self.template_service.user_name_template(
                session, "Name is too long (maximum 60 characters). Please enter a shorter name."
            )

        if len(name) == 0:
            return await self.template_service.user_name_template(
                session, "Please enter a name."
            )

        # Check for numbers
        if re.search(r'\d', name):
            return await self.template_service.user_name_template(
                session, "Names cannot contain numbers. Please enter a valid name."
            )

        # Check for special symbols (only allow letters, spaces, hyphens, apostrophes)
        allowed_pattern = r'^[A-Za-zÀ-ÿ\s\-\']+$'
        if not re.match(allowed_pattern, name):
            return await self.template_service.user_name_template(
                session, "Names can only contain letters, spaces, hyphens (-), and apostrophes ('). Please enter a valid name."
            )

        # Additional validations
        name_clean = name.strip(" -'")  # Remove surrounding spaces, hyphens, apostrophes
        if len(name_clean) == 0:
            return await self.template_service.user_name_template(
                session, "Please enter a valid name."
            )

        # Check for excessive special characters
        if '--' in name or "''" in name or '- ' in name or ' -' in name:
            return await self.template_service.user_name_template(
                session, "Name contains invalid formatting. Please use proper spacing."
            )

        # Save the validated name
        _, err = await self.sql_db_service.update_user(
            str(session.user_id), {"filled_name": name}
        )
        if err:
            return await self.template_service.user_name_template(
                session, "Could not save the name. Try again."
            )

        session, err = await self.sql_db_service.update_session(session.user_id, RouteTaskEnum.START.value, StartStepEnum.COMPANY_NAME.value, None, session.data)

        return await self.template_service.start_company_name_template(session=session, user = user, note=f"Nice to meet you, {name} 👍\nLet's continue.")

    async def _handle_company_name(
            self,
            session: SessionDB,
            user: UserDB,
            message: str,
            is_admin: bool
    ):
        company = message.strip()
        if self.ai_service.is_validation_positive(company) and user.company_name:
            if not user.phone_number:
                session, err = await self.sql_db_service.update_session(session.user_id, RouteTaskEnum.START.value, StartStepEnum.PHONE_NUMBER.value, None, session.data)
                return await self.template_service.start_phone_number_template(session=session, user=user, note=f"{emoji.HANDSHAKE} Company \"{user.company_name}\" saved.\nYou're all set 👍")
            else:
                 session, err = await self.sql_db_service.update_session(
                    session.user_id,
                    RouteTaskEnum.START.value,
                    StartStepEnum.EMAIL.value,
                    None,
                    session.data
                )

            return await self.template_service.start_user_email_template(session=session, user=user, note=f"{emoji.PHONE} Got it: {user.phone_number}\nLet's continue.")

        # -------- LENGTH --------
        if len(company) > 100:
            return await self.template_service.start_company_name_template(session, user, "Company name is too long (maximum 100 characters).")

        if len(company) == 0:
            return await self.template_service.start_company_name_template(session, user, "Please enter a company name.")

        # -------- VALIDATION --------
        # allow letters, numbers, spaces and common company symbols
        allowed_pattern = r"^[A-Za-zÀ-ÿ0-9\s\-\&\.\,\'\"]+$"
        if not re.match(allowed_pattern, company):
            return await self.template_service.start_company_name_template(session, user, "Company name contains invalid characters.")

        # clean edges
        company_clean = company.strip(" -&.,'\"")
        if len(company_clean) == 0:
            return await self.template_service.start_company_name_template(session, user, "Please enter a valid company name.")

        # bad formatting
        if any(x in company for x in ["--", "  ", "..", ",,", "''", '""']):
            return await self.template_service.start_company_name_template(session, user, "Company name contains invalid formatting." )

        # -------- SAVE --------
        _, err = await self.sql_db_service.update_user(str(session.user_id), {"company_name": company} )
        if err:
            return await self.template_service.start_company_name_template(session, user,"Could not save the company name. Try again.")

        # -------- NEXT STEP --------
        session, err = await self.sql_db_service.update_session(session.user_id, RouteTaskEnum.START.value, StartStepEnum.PHONE_NUMBER.value, None, session.data)
        return await self.template_service.start_phone_number_template(session=session, user=user, note=f"{emoji.HANDSHAKE} Company \"{company}\" saved.\nYou're all set 👍")

    async def _handle_user_phone(
            self,
            session: SessionDB,
            user: UserDB,
            message: str,
            is_admin: bool
    ):
        phone_raw = message.strip()

        if self.ai_service.is_validation_positive(phone_raw) and user.phone_number:
            session, err = await self.sql_db_service.update_session(
                session.user_id,
                RouteTaskEnum.START.value,
                StartStepEnum.EMAIL.value,
                None,
                session.data
            )

            return await self.template_service.start_user_email_template(session=session, user=user, note=f"{emoji.PHONE} Got it: {user.phone_number}\nLet's continue.")


        # -------- EMPTY --------
        if len(phone_raw) == 0:
            return await self.template_service.start_phone_number_template(
                session, user, "Please enter a phone number."
            )

        # -------- NORMALIZE --------
        phone = phone_raw.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")

        # -------- VALIDATION --------
        # allow leading +
        if not re.match(r"^\+?\d{7,15}$", phone):
            return await self.template_service.start_phone_number_template(
                session,
                user,
                "Invalid phone number format. Use digits with optional '+' (7–15 digits)."
            )

        # -------- SAVE --------
        _, err = await self.sql_db_service.update_user(
            str(session.user_id),
            {"phone_number": phone}
        )
        if err:
            return await self.template_service.start_phone_number_template(
                session, user, "Could not save the phone number. Try again."
            )

        # -------- NEXT STEP --------
        session, err = await self.sql_db_service.update_session(
            session.user_id,
            RouteTaskEnum.START.value,
            StartStepEnum.EMAIL.value,
            None,
            session.data
        )

        return await self.template_service.start_user_email_template(session=session, user=user, note=f"{emoji.PHONE} Got it: {phone}\nLet's continue.")


    async def _handle_user_email(self, session: SessionDB, user: UserDB, message: str, is_admin: bool = False) -> ResponsePayloadCollection:
        intent_dict, err = self.ai_service.parse_user_email(message)
        if err:
            return await self.template_service.session_template(session=session, err_msg=err, is_admin=is_admin )

        if intent_dict.get("email", None) is not None:
            intent_dict['action'] = "update"

        intent = intent_dict.get("action")
        if intent == "update":
            return await self._update_user_email(session, user, intent_dict, is_admin=is_admin)
        elif intent == "confirm":
            return await self._confirm_user_email(session, user, intent_dict, is_admin=is_admin)
        else:
            return await self.template_service.session_template(session, "Did not understand what to do. Try again please.")

    async def _update_user_email(self, session: SessionDB, user: UserDB, intent_dict: Dict, is_admin: bool = False) -> ResponsePayloadCollection:
        email = intent_dict.get("email", None)
        if not email:
            return await self.template_service.session_template(session=session, err_msg="Could not save your email.", is_admin=is_admin)

        await self.sql_db_service.create_event(Event.email_entered(
            user_id=session.user_id,
            payload={
                "status": "updated",
                "user_id": str(session.user_id),
                "email": email,
            },
        ))

        updated_user, err = await self.sql_db_service.update_user(str(session.user_id), {"email": email})
        if err or intent_dict.get("action") == "error":
            return await self.template_service.session_template(session=session, err_msg="Could not save your email.", is_admin=is_admin)

        return await self.template_service.session_template(session=session, is_admin=is_admin)

    async def _confirm_user_email(self, session: SessionDB, user: UserDB, intent_dict: Dict, is_admin: bool = False) -> ResponsePayloadCollection:
        err_messages = []

        if not user.email:
            err_messages.append(f"{emoji.CROSS_RED} Please add your email address.")

        if user.email and not utils.is_valid_email(user.email):
            err_messages.append(f"{emoji.CROSS_RED} The email address is invalid. Please try again.")

        if len(err_messages) > 0:
            return await self.template_service.session_template(session, "\n".join(err_messages))

        await self.sql_db_service.create_event(Event.email_entered(
            user_id=session.user_id,
            payload={
                "status": "confirmed",
                "email": user.email,
            },
        ))

        session, err = await self.sql_db_service.update_session(session.user_id, RouteTaskEnum.START.value, StartStepEnum.PROMOCODE.value, session.route_id, session.data)
        return await self.template_service.session_template(session=session, err_msg=str(err) if err else None, is_admin=is_admin)

    async def _handle_user_promocode(
            self,
            session: SessionDB,
            user: UserDB,
            message: str,
            is_admin: bool
    ):
        q = message.strip().lower()

        if q in ("without_promocode", "without code")  or self.ai_service.is_validation_positive(q):
            # Next step
            session, err = await self.to_main_menu(session)

            if err:
                return await self.template_service.user_promocode_template(
                    session,
                    user,
                    "Could not continue."
                )

            return await self.template_service.session_template(
                session,
                f"<b>Okay, there will be a promo code next time. 👍</b>"
            )


        promocode = message.strip().upper()

        # Empty
        if not promocode:
            return await self.template_service.user_promocode_template(
                session,
                user,
                "Please enter a promo code."
            )


        # Length check
        if len(promocode) != 4:
            return await self.template_service.user_promocode_template(
                session,
                user,
                "Promo code must be exactly 4 letters."
            )

        # Only latin letters
        if not PROMO_PATTERN.match(promocode):
            return await self.template_service.user_promocode_template(
                session,
                user,
                "Promo code must contain only Latin letters (A–Z)."
            )

        # Repeated characters edge case (e.g. AAAAA)
        if len(set(promocode)) == 1:
            return await self.template_service.user_promocode_template(
                session,
                user,
                "Promo code looks invalid. Please check and try again."
            )

        # Save
        _, err = await self.sql_db_service.update_user(
            str(session.user_id),
            {"promocode": promocode}
        )

        if err:
            return await self.template_service.user_promocode_template(
                session,
                user,
                "Could not save the promo code. Try again."
            )

        # Next step
        session, err = await self.to_main_menu(session)

        if err:
            return await self.template_service.user_promocode_template(
                session,
                user,
                "Could not continue."
            )

        return await self.template_service.session_template(
            session,
            f"<b>Promo code '{promocode}' applied successfully 👍</b>"
        )

