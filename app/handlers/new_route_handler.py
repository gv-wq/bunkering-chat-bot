import re
from collections import defaultdict, deque
from uuid import UUID

import math
import asyncio
import datetime
from typing import List, Dict, Optional

from app.data import emoji
from app.data.dto.main.BunkeringStep import BunkeringStep
from app.data.dto.main.Event import Event


from app.data.dto.main.SeaPort import SeaPortDB
from app.data.dto.main.SeaRoute import SeaRouteDB
from app.data.dto.main.SeaRouteData import SeaRouteData
from app.data.dto.main.Session import SessionDB
from app.data.dto.messenger.ResponsePayload import (
    ResponsePayload,
    ResponsePayloadCollection,
)
from app.data.dto.searoute.SearoutePort import SearoutePort
from app.data.enums.RouteStep import RouteStepEnum
from app.data.enums.RouteTask import RouteTaskEnum
from app.handlers.navigation_handler import NavigationHandler
from app.services.ai_service import AiService
from app.services.db_service import DbService
from app.services.email_sender import EmailSender
from app.services.external_api.request_limiter import RequestLimiter

from app.services.external_api.searoute_api import SearouteApi
from app.services.fuel_price_service import FuelPriceService
from app.services.internal_api.map_builder_api import MapBuilderApi
from app.services.template.telegram_template_service import TemplateService
from app.services.utils import searoute_utils, email_sender, utils
from app.services.utils.island_projection import IslandProjection
from app.services.utils.near_country_search import RouteCountryFinder



class NewRouteHandler:
    def __init__(
        self,
        ai_service: AiService,
        sql_db_service: DbService,
        template_service: TemplateService,
        navigation_handler: NavigationHandler,
        searoute_api: SearouteApi,
        #bubble_api: BubbleApi,
        map_image_api: MapBuilderApi,
        projector: IslandProjection,
        country_finder: RouteCountryFinder,
        port_fuel_price_service: FuelPriceService,
    ):
        self.ai_service = ai_service
        self.sql_db_service = sql_db_service
        self.template_service = template_service
        self.navigation_handler = navigation_handler
        self.searoute_api = searoute_api
        #self.bubble_api = bubble_api
        self.map_image_api = map_image_api
        self.email_sender = EmailSender()

        self.searoute_limiter = RequestLimiter(1, 0.6)
        self.proj = projector
        self.country_finder = country_finder
        self.port_fuel_price_service=port_fuel_price_service

    async def handle_create_route_flow(self, session: SessionDB, message: str) -> ResponsePayloadCollection:
        """Flow создания маршрута"""
        route, err = await self.sql_db_service.get_or_create_route(session)
        if err:
            return ResponsePayloadCollection(responses=[ResponsePayload(err=err)])

        if session.current_step in [RouteStepEnum.DEPARTURE_PORT_SUGGESTION.value, RouteStepEnum.DESTINATION_PORT_SUGGESTION.value]:
            return  await self._handle_port_suggestion(session, route, message)

        elif session.current_step == RouteStepEnum.DEPARTURE_DATE.value:
            return await self._handle_departure_date(session, route, message)

        elif session.current_step == RouteStepEnum.AVERAGE_SPEED.value:
            return await self._handle_average_speed(session, route, message)

        elif session.current_step == RouteStepEnum.FUEL_SELECTION.value:
            return await self._handle_fuel_selection(session, route, message)

        elif session.current_step == RouteStepEnum.ROUTE_PORT_LIST.value:
            return await self._handle_bunkering_port_sequence(session, route, message)

        elif session.current_step == RouteStepEnum.BUNKERING_QUEUE.value:
            return await self._handle_fuel_bunkering_sequence(session, route, message)

        elif session.current_step == RouteStepEnum.PDF_REQUEST.value:
            return await self._handle_pdf_request(session, route, message)

        elif session.current_step == RouteStepEnum.VESSEL_NAME.value:
            return await self._handle_vessel_name(session, route, message)

        elif session.current_step == RouteStepEnum.VESSEL_IMO.value:
            return await self._handle_vessel_imo(session, route, message)

        elif session.current_step == RouteStepEnum.USER_EMAIL.value:
            return await self._handle_user_email(session, route, message)

        elif session.current_step == RouteStepEnum.SUPPLIER_PRICES.value:
            return await self._handle_supplier_prices(session, route, message)

        elif session.current_step == RouteStepEnum.COMPANY_NAME.value:
            return await self._handle_company_name(session, route, message)

        else:
            return await self.template_service.main_menu_template(session)

    async def _handle_company_name(self, session: SessionDB, route: SeaRouteDB, message: str) -> ResponsePayloadCollection:
        intent_dict, err = self.ai_service.parse_name(message)
        if err:
           return await self.template_service.session_template(session, err)

        if intent_dict.get("name", None) is not None:
            intent_dict['action'] = "update"

        intent = intent_dict.get("action")
        r = None
        if intent == "update":
            return await self._update_company_name(session, route, intent_dict)
        elif intent == "confirm":
            return await self._confirm_company_name(session, route, intent_dict)
        else:
            return await self._handle_unknown_intent(session, route, intent)

    async def finish_route(self, session: SessionDB, route: SeaRouteDB):

        await self.send_bunekring_request_with_quote(session, route)

        route.status = "finished"
        route_new, err = await self.sql_db_service.update_route(route)
        if err:
            return ResponsePayloadCollection(responses=[ResponsePayload(err=err)])

        user_db, err = await self.sql_db_service.get_user_by_id(session.user_id)
        if user_db:
            user_db.route_count += 1
            user_db, err = await self.sql_db_service.update_user(str(user_db.id), {"route_count": user_db.route_count})

        session.route_id = None
        session.current_task = None
        session.current_step = None
        session, err = await self._update_session(session, route.user_id)

        if err:
            return ResponsePayloadCollection(responses=[ResponsePayload(err=err)])

        finish_rc =  self.template_service.new_route_finish(route)
        session, err = await self.navigation_handler.return_to_main_menu(session)
        if not err:
            menu_rc = await self.template_service.main_menu_template(session)
            finish_rc.responses.extend(menu_rc.responses)

        await self.sql_db_service.create_event(Event.route_finished(
            user_id=session.user_id,
            payload={
                "route_id": str(route.id),
            },
        ))

        return finish_rc

    async def _update_company_name(self, session: SessionDB, route: SeaRouteDB, intent_dict: Dict) -> ResponsePayloadCollection:
        user, err = await self.sql_db_service.get_user_by_id(session.user_id)
        if err:
            return await self.template_service.session_template(session, err)

        name = intent_dict.get("name", user.company_name)
        if name:
            user.company_name = name

        await self.sql_db_service.create_event(Event.company_name_entered(
            user_id=session.user_id,
            payload={
                "status": "updated",
                "route_id": str(route.id),
                "data": name,
            },
        ))

        new_route, err = await self.sql_db_service.update_user(str(session.user_id), {"company_name": name})
        if err or intent_dict.get("action") == "error":
            return await self.template_service.session_template(session, str(err))
        return await self.template_service.session_template(session)

    async def _confirm_company_name(self, session: SessionDB, route: SeaRouteDB, intent_dict: Dict) -> ResponsePayloadCollection:
        err_messages = []

        user, err = await self.sql_db_service.get_user_by_id(session.user_id)
        if err:
            return await self.template_service.session_template(session, err)

        name = intent_dict.get("name", user.company_name)

        if not name:
            err_messages.append(f"{emoji.CROSS_RED} Add the company name please!")

        if len(err_messages) > 0:
            return await self.template_service.session_template(session, "\n".join(err_messages))

        session, err = await self.navigation_handler.return_to_main_menu(session)
        return await self.finish_route(session, route)

    async def _handle_supplier_prices(self, session: SessionDB, route: SeaRouteDB, message: str) -> ResponsePayloadCollection:
        intent_dict, err = self.ai_service.parse_yes_or_no(message)
        if err:
            return await self.template_service.session_template(session, err)

        intent = intent_dict.get("action")
        if intent == "decline":
            return await self._decline_supplier_request(session, route, intent_dict)
        elif intent == "confirm":
            return await self._confirm_supplier_request(session, route, intent_dict)
        else:
            return await self._handle_unknown_intent(session, route, intent)

    async def _decline_supplier_request(self, session: SessionDB, route: SeaRouteDB, message: str) -> ResponsePayloadCollection:

        route.data.quote_requested = False
        route, err = await self.sql_db_service.update_route(route)
        if err:
            return ResponsePayloadCollection(responses=[ResponsePayload(err="Failed to update the route.")])

        await self.sql_db_service.create_event(Event.supplier_price_declined(
            user_id=session.user_id,
            payload={
                "status": "declined",
                "route_id": str(route.id),
            },
        ))

        supplier_req_t = self.template_service.get_supplier_request(session, route)

        session, err = await self.navigation_handler.to_next_step(session)
        if err:
            return await self.template_service.session_template(session, err)

        m_r =  await self.template_service.session_template(session)

        supplier_req_t.responses.extend(m_r.responses)

        await self.send_bunekring_request_with_quote(session, route)

        return supplier_req_t

    async def _confirm_supplier_request(self, session: SessionDB, route: SeaRouteDB, message: str) -> ResponsePayloadCollection:

        route.data.quote_requested = True
        route, err = await self.sql_db_service.update_route(route)
        if err:
            return ResponsePayloadCollection(responses=[ResponsePayload(err="Failed to update the route.")])

        await self.sql_db_service.create_event(Event.supplier_price_requested(
            user_id=session.user_id,
            payload={
                "status": "accepted",
                "route_id": str(route.id),
            },
        ))

        #c1 = await self.template_service.supplier_prices_template(session, route, status=True)

        session, err = await self.navigation_handler.to_next_step(session)
        if err:
            return await self.template_service.session_template(session, err)

        user_db, err = await self.sql_db_service.get_user_by_id(session.user_id)

        supplier_req_t = self.template_service.get_supplier_request(session, route)

        c2 = None
        c2 = await self.template_service.session_template(session)

        if c2:
            supplier_req_t.responses.extend(c2.responses)

        await self.send_bunekring_request_with_quote(session, route)


        return supplier_req_t

    async def _handle_user_email(self, session: SessionDB, route: SeaRouteDB, message: str) -> ResponsePayloadCollection:
        intent_dict, err = self.ai_service.parse_user_email(message)
        if err:
            return await self.template_service.session_template(session, err)

        if intent_dict.get("email", None) is not None:
            intent_dict['action'] = "update"

        intent = intent_dict.get("action")
        if intent == "update":
            return await self._update_user_email(session, route, intent_dict)
        elif intent == "confirm":
            return await self._confirm_user_email(session, route, intent_dict)
        else:
            return await self.template_service.session_template(session, "Did not understand what to do. Try again please.")

    async def _update_user_email(self, session: SessionDB, route: SeaRouteDB, intent_dict: Dict) -> ResponsePayloadCollection:
        email = intent_dict.get("email", None)
        if not email:
            return await self.template_service.session_template(session, "Could not save your email.")

        await self.sql_db_service.create_event(Event.email_entered(
            user_id=session.user_id,
            payload={
                "status": "updated",
                "route_id": str(route.id),
                "email": email,
            },
        ))

        updated_user, err = await self.sql_db_service.update_user(str(session.user_id), {"email": email})
        if err or intent_dict.get("action") == "error":
            return await self.template_service.session_template(session, "Could not save your email.")

        return await self.template_service.session_template(session,)

    async def _confirm_user_email(self, session: SessionDB, route: SeaRouteDB, intent_dict: Dict) -> ResponsePayloadCollection:
        err_messages = []

        user, err = await self.sql_db_service.get_user_by_id(session.user_id)
        if err:
            err_messages.append(f"{emoji.CROSS_RED} Could not find your user record.")

        if not user.email:
            err_messages.append(f"{emoji.CROSS_RED} Please add your email address.")

        if user.email and not utils.is_valid_email(user.email):
            err_messages.append(f"{emoji.CROSS_RED} The email address is invalid. Please try again.")

        if len(err_messages) > 0:
            return await self.template_service.session_template(session,"\n".join(err_messages))

        await self.sql_db_service.create_event(Event.email_entered(
            user_id=session.user_id,
            payload={
                "status": "confirmed",
                "route_id": str(route.id),
                "email": user.email,
            },
        ))

        file_to_attach = await self.render_bukering_request_in_pdf(session, route)

        p1 = await self.template_service.user_email_template(session, route, True)
        if file_to_attach:
            p1.responses[-1].files.append(file_to_attach)

        await self.sql_db_service.create_event(Event.pdf_generated(
            user_id=session.user_id,
            payload={
                "route_id": str(route.id)
            },
        ))

        session, err = await self.navigation_handler.to_next_step(session)
        p2 = await self.template_service.session_template(session)

        p1.responses += p2.responses

        return p1


    async def _handle_pdf_request(self, session: SessionDB, route: SeaRouteDB, message: str) -> ResponsePayloadCollection:
        intent_dict, err = self.ai_service.parse_yes_or_no(message)
        if err:
            return await self.template_service.session_template(session, err)

        intent = intent_dict.get("action")
        if intent == "decline":
            return await self._decline_pdf(session, route, intent_dict)
        elif intent == "confirm":
            return await self._confirm_pdf(session, route, intent_dict)
        else:
            return await self._handle_unknown_intent(session, route, intent)

    async def _decline_pdf(self, session: SessionDB, route: SeaRouteDB, message: str) -> ResponsePayloadCollection:

        route.data.pdf_requested = False
        route, err = await self.sql_db_service.update_route(route)
        if err:
            return ResponsePayloadCollection(responses=[ResponsePayload(err="Failed to update the route.")])

        await self.sql_db_service.create_event(Event.pdf_declined(
            user_id=session.user_id,
            payload={
                "route_id": str(route.id)
            },
        ))

        session.current_step = RouteStepEnum.COMPANY_NAME.value
        session, err = await self.sql_db_service.update_session(session.user_id, session.current_task, session.current_step, session.route_id, session.data)
        if err:
            return await self.template_service.session_template(session, err)

        return await self.template_service.session_template(session, err)

    async def _confirm_pdf(self, session: SessionDB, route: SeaRouteDB, message: str) -> ResponsePayloadCollection:

        route.data.pdf_requested = True
        route, err = await self.sql_db_service.update_route(route)
        if err:
            return ResponsePayloadCollection(responses=[ResponsePayload(err="Failed to update the route.")])

        await self.sql_db_service.create_event(Event.pdf_requested(
            user_id=session.user_id,
            payload={
                "route_id": str(route.id)
            },
        ))


        session, err = await self.navigation_handler.to_next_step(session)
        if err:
            return await self.template_service.session_template(session, err)

        return await self.template_service.session_template(session, err)


    async def _handle_vessel_name(self, session: SessionDB, route: SeaRouteDB, message: str) -> ResponsePayloadCollection:

        intent_dict, err = self.ai_service.parse_name(message)
        if err :
           return await self.template_service.session_template(session, err)

        if intent_dict.get("name", None) is not None:
            intent_dict['action'] = "update"

        intent = intent_dict.get("action")
        if intent == "update":
            return await self._update_vessel_name(session, route, intent_dict)
        elif intent == "confirm":
            return await self._confirm_vessel_name(session, route, intent_dict)
        else:
            return await self._handle_unknown_intent(session, route, intent)

    async def _update_vessel_name(self, session: SessionDB, route: SeaRouteDB, intent_dict: Dict) -> ResponsePayloadCollection:
        vessel_name = intent_dict.get("name", route.vessel_name)
        if vessel_name:
            route.vessel_name = vessel_name

        await self.sql_db_service.create_event(Event.vessel_name_entered(
            user_id=session.user_id,
            payload={
                "status": "updated",
                "data": vessel_name if vessel_name else "undefined",
                "route_id": route.id,
            },
        ))

        new_route, err = await self.sql_db_service.update_route(route)
        if err or intent_dict.get("action") == "error":
            return await self.template_service.vessel_name_template(session, route, str(err))
        return await self.template_service.vessel_name_template(session, route)

    async def _confirm_vessel_name(self, session: SessionDB, route: SeaRouteDB, intent_dict: Dict) -> ResponsePayloadCollection:
        err_messages = []
        if not route.vessel_name:
            err_messages.append(f"{emoji.CROSS_RED} Add the vessel name please!")

        if len(err_messages) > 0:
            return await self.template_service.vessel_name_template(session, route, "\n".join(err_messages))

        await self.sql_db_service.create_event(Event.vessel_name_entered(
            user_id=session.user_id,
            payload={
                "status": "confirmed",
                "data": route.vessel_name if route.vessel_name else "undefined",
                "route_id": route.id,
            },
        ))

        session, err = await self.navigation_handler.to_next_step(session, )
        return await self.template_service.session_template(session)

    async def _handle_vessel_imo(self, session: SessionDB, route: SeaRouteDB, message: str) -> ResponsePayloadCollection:
        intent_dict, err = self.ai_service.parse_vessel_imo(message)
        if err :
            return await self.template_service.session_template(session, err)

        if intent_dict.get("vessel_imo", None) is not None:
            intent_dict['action'] = "update"

        intent = intent_dict.get("action")
        if intent == "update":
            return await self._update_vessel_imo(session, route, intent_dict)
        elif intent == "confirm":
            return await self._confirm_vessel_imo(session, route, intent_dict)
        else:
            return await self._handle_unknown_intent(session, route, intent)

    async def _update_vessel_imo(self, session: SessionDB, route: SeaRouteDB, intent_dict: Dict) -> ResponsePayloadCollection:
        imo_number = intent_dict.get("imo_number", route.imo_number)
        if imo_number:
            route.imo_number = imo_number

        await self.sql_db_service.create_event(Event.vessel_imo_entered(
            user_id=session.user_id,
            payload={
                "status": "update",
                "data": route.imo_number if route.imo_number else "undefined",
                "route_id": route.id,
            },
        ))

        new_route, err = await self.sql_db_service.update_route(route)
        if err or intent_dict.get("action") == "error":
            return await self.template_service.vessel_imo_template(session, route, str(err))
        return await self.template_service.vessel_imo_template(session, route)

    async def _confirm_vessel_imo(self, session: SessionDB, route: SeaRouteDB, intent_dict: Dict) -> ResponsePayloadCollection:
        err_messages = []

        # if not route.imo_number:
        #     err_messages.append(f"{emoji.CROSS_RED} Add the imo number please!")

        def is_valid_imo(imo: str) -> bool:
            return bool(re.fullmatch(r"\d{7}", imo))

        if route.imo_number:
            if not is_valid_imo(route.imo_number):
                err_messages.append(f"{emoji.CROSS_RED}  Imo number is 7 digits value!")

        if len(err_messages) > 0:
            return await self.template_service.vessel_imo_template(session, route, "\n".join(err_messages))

        await self.sql_db_service.create_event(Event.vessel_imo_entered(
            user_id=session.user_id,
            payload={
                "status": "confirmed",
                "data": route.imo_number if route.imo_number else "undefined",
                "route_id": route.id,
            },
        ))

        session, err = await self.navigation_handler.to_next_step(session )
        return await self.template_service.session_template(session, str(err) if err else None)

    async def _handle_port_suggestion(self, session: SessionDB, route: SeaRouteDB, message: str) -> ResponsePayloadCollection:
        intent, err = self.ai_service.parse_port_user_input(message)

        action = intent['action']
        if action == "update":
            return await self.update_port_suggestion(session, route, intent)
        elif action == "confirm":
            return await self.confirm_port_suggestion(session, route, intent)
        else:
            return await self._handle_unknown_intent(session, route, intent)


    async def get_port_info_limited(self, locode: str):
        await self.searoute_limiter.acquire()
        try:
            return await self.searoute_api.get_port_info(locode)
        finally:
            self.searoute_limiter.release()

    async def fetch_ports_info(self, locodes: set[str]) -> dict[str, SearoutePort]:
        tasks = {
            locode: asyncio.create_task(self.get_port_info_limited(locode))
            for locode in locodes
        }

        results = {}
        for locode, task in tasks.items():
            port, err = await task
            if port and not err:
                results[locode] = port

        return results

    def apply_sizes(self, ports, updated_map):
        for i, p in enumerate(ports):
            if p.locode in updated_map:
                ports[i] = updated_map[p.locode]

    def merge_ports(self, *lists):
        out = {}
        for lst in lists:
            for p in lst:
                out[p.locode] = p
        return list(out.values())

    async def update_port_suggestion(self, session: SessionDB, route: SeaRouteDB, intent: Dict):
        candidate = None
        suggestions: List[SeaPortDB] = []
        #image = None

        if session.current_step == RouteStepEnum.DEPARTURE_PORT_SUGGESTION.value:
            candidate = route.data.port_selection.departure_candidate
            suggestions = route.data.port_selection.departure_suggestions or []
        elif session.current_step == RouteStepEnum.DESTINATION_PORT_SUGGESTION.value:
            candidate = route.data.port_selection.destination_candidate
            suggestions = route.data.port_selection.destination_suggestions or []


        if intent['type'] == 'name':
            candidate = None
            suggestions = []
            candidate, suggestions, err = self.sql_db_service.search_port_with_suggestions(intent['query'])
            t, err_t = await self.sql_db_service.create_event(Event.port_searched(
                user_id=session.user_id,
                payload={
                    "query": intent['query'],
                    "locode_found": candidate.locode if candidate else "not found",
                    "route_id": str(route.id),
                },
            ))
            # if all([not err, new_candidate, new_suggestions]):
            #     candidate = new_candidate
            #     suggestions = new_suggestions


        elif intent['type'] == 'index':
            new_candidate = self._resolve_port_by_index(suggestions, intent['index'])
            if new_candidate:
                candidate = new_candidate
                candidate_found, suggestions, err = self.sql_db_service.search_port_with_suggestions(new_candidate.locode)
                suggestions = [candidate_found] + suggestions


        if candidate:
            # 1. SeaRoute nearby
            searoute_nearby, searoute_err = await self.searoute_api.get_nearest_port_to_coordinates(candidate.latitude, candidate.longitude, {"limit": 25}, )
            searoute_nearby = searoute_nearby or []

            t, err_t = await self.sql_db_service.create_event(Event.searoute_nearest(
                user_id=session.user_id,
                payload={
                    "port_locode": candidate.locode if candidate else "not found",
                    "route_id": str(route.id),
                },
            ))

            if searoute_err:
                await self.sql_db_service.create_event(Event.searoute_error(
                    user_id=session.user_id,
                    payload={
                        "locode": candidate.locode,
                        "latitude": candidate.latitude,
                        "longitude": candidate.longitude,
                        "route_id": str(route.id),
                        "error": searoute_err
                    },
                ))

            # 2. Bulk DB fetch
            db_ports, _ = await self.sql_db_service.get_ports_by_locodes({p.locode for p in searoute_nearby if p.locode})
            db_ports = db_ports or {}

            # 3. Insert missing ports
            missing = [p for p in searoute_nearby if p.locode not in db_ports]
            inserted = {}
            if missing:
                inserted, err = await self.sql_db_service.bulk_upsert_ports(missing)
                inserted = inserted or {}

            # 4. Merge nearby
            nearby_ports = [
                db_ports.get(p.locode) or inserted.get(p.locode)
                for p in searoute_nearby
            ]

            # 5. Local DB nearby
            nearby_bd, _ = await self.sql_db_service.search_ports_nearby(
                candidate.latitude,
                candidate.longitude,
                10,
                5000,
            )
            nearby_bd = nearby_bd or []

            # 6. Single enrichment pass
            all_ports = self.merge_ports(
                [candidate],
                suggestions,
                nearby_ports,
                nearby_bd,
            )

            missing_sizes = {
                p.locode for p in all_ports if p and p.port_size is None
            }
            if not candidate.port_size:
                missing_sizes.add(candidate.locode)

            if missing_sizes:
                searoute_ports = await self.fetch_ports_info(missing_sizes)
                updatable = [
                    p for p in searoute_ports.values() if p.size
                ]
                if updatable:
                    updated = await self.sql_db_service.bulk_upsert_ports(updatable)
                    self.apply_sizes(all_ports + [candidate], updated)

            # # 7. Final selection
            # large_ports = [
            #     p for p in all_ports
            #     if p.port_size == "large" and p.locode != candidate.locode
            # ]
            #
            # # Ensure candidate is large if possible
            # if intent['type'] != 'index':
            #     if not candidate.port_size or candidate.port_size != "large":
            #         if large_ports:
            #             # Swap candidate with the first large port
            #             new_candidate = large_ports.pop(0)
            #             suggestions = [candidate] + suggestions  # put old candidate back into suggestions
            #             candidate = new_candidate

            # Remove candidate from suggestions to avoid duplication
            if candidate and all_ports:
                suggestions = [p for p in all_ports if p.locode != candidate.locode]

        suggestions = suggestions[:5]


        port_size_priority = {"large": 0, "small": 1, "tiny": 2, None: 3}
        suggestions.sort(key=lambda p: port_size_priority.get(p.port_size, 3))


        if candidate and len(suggestions) > 0:
            suggestions = [p for p in suggestions if p.locode != candidate.locode]

        if session.current_step == RouteStepEnum.DEPARTURE_PORT_SUGGESTION.value:
            route.data.port_selection.departure_candidate = candidate
            route.data.port_selection.departure_suggestions = suggestions

        elif session.current_step == RouteStepEnum.DESTINATION_PORT_SUGGESTION.value:
            route.data.port_selection.destination_candidate = candidate
            route.data.port_selection.destination_suggestions = suggestions

        route, err = await self.sql_db_service.update_route(route)
        if err:
            return ResponsePayloadCollection(responses=[ResponsePayload(err=str(err))])

        return await self.template_service.port_suggestions_template(session, route)


    def _resolve_port_by_index(self, suggestions: List[SeaPortDB], index: int) -> Optional[SeaPortDB]:
        if not suggestions or index is None:
            return None
        adjusted_index = int(index) - 1
        if 0 <= adjusted_index < len(suggestions):
            return suggestions[adjusted_index]
        return None

    async def confirm_port_suggestion(self, session: SessionDB, route: SeaRouteDB, intent: Dict):

        candidate = None
        port_id = None
        nearby = []
        port_type_name = ""

        if session.current_step == RouteStepEnum.DEPARTURE_PORT_SUGGESTION.value:
            candidate = route.data.port_selection.departure_candidate
            nearby = route.data.port_selection.departure_suggestions
            port_type_name = "departure"
            port_id = route.departure_port_id
        elif session.current_step == RouteStepEnum.DESTINATION_PORT_SUGGESTION.value:
            candidate = route.data.port_selection.destination_candidate
            nearby = route.data.port_selection.destination_suggestions
            port_type_name = "destination"
            port_id = route.destination_port_id

        if candidate is None and port_id is None:
            return await self.template_service.port_suggestions_template(session, route, f"{emoji.CROSS_GRAY} Firstly select {port_type_name} port.")

        if session.current_step == RouteStepEnum.DEPARTURE_PORT_SUGGESTION.value:
            route.departure_port_id = candidate.id if candidate else None
            route.data.port_selection.departure_candidate = candidate
            route.data.port_selection.departure_suggestions = nearby

        elif session.current_step == RouteStepEnum.DESTINATION_PORT_SUGGESTION.value:
            route.destination_port_id = candidate.id if candidate else None
            route.data.port_selection.destination_candidate = candidate
            route.data.port_selection.destination_suggestions = nearby

        updated_route, err = await self.sql_db_service.update_route(route)
        if err:
            return ResponsePayloadCollection(
                responses=[ResponsePayload(err="Failed to save route ports")]
            )
        session, err = await self.navigation_handler.to_next_step(session)
        if err:
            return ResponsePayloadCollection(responses=[ResponsePayload(err=f"Failed to save user session: {err}")])

        if session.current_step == RouteStepEnum.DEPARTURE_DATE.value:
            return await self.template_service.departure_date_template(session, route)

        if session.current_step in [RouteStepEnum.DESTINATION_PORT_SUGGESTION.value, RouteStepEnum.DEPARTURE_PORT_SUGGESTION.value]:
            return await self.template_service.port_suggestions_template(session, route)

        return await self._handle_unknown_intent(session, route, "Could not parse the intent")

    async def _update_session(self, session: SessionDB, user_id: UUID):
        """Helper to update session"""
        return await self.sql_db_service.update_session(
            user_id,
            session.current_task,
            session.current_step,
            session.route_id,
            session.data,
        )

    async def _handle_departure_date(
        self, session: SessionDB, route: SeaRouteDB, message: str
    ):
        """AI-enhanced date selection handler"""

        intent, err = await self.ai_service.parse_date_intent(message)

        if err or intent.get("status") == "failed":
            return await self.template_service.departure_date_template(
                session, route, "❌ Could not parse the date. Please try again."
            )

        status = intent.get("status")

        if status == "update":
            return await self._handle_departure_date_update(session, route, intent)
        elif status == "confirm":
            session, err = await self.navigation_handler.to_next_step(session)
            return await self.template_service.session_template(session, err if err else None)
        else:
            return await self._handle_ai_date_unknown(session, route, intent)

    async def _handle_departure_date_update(
        self, session: SessionDB, route: SeaRouteDB, intent: Dict
    ) -> ResponsePayloadCollection:
        try:
            year = intent.get("year")
            month = intent.get("month")
            day = intent.get("day")

            year_str = year if year != "None" else str(datetime.datetime.now().year)

            month_map = {
                "January": "01",
                "February": "02",
                "March": "03",
                "April": "04",
                "May": "05",
                "June": "06",
                "July": "07",
                "August": "08",
                "September": "09",
                "October": "10",
                "November": "11",
                "December": "12",
            }
            month_str = month_map.get(month, month.zfill(2))

            # Create date string
            date_str = f"{year_str}-{month_str}-{day.zfill(2)}"
            departure_date = datetime.datetime.strptime(date_str, "%Y-%m-%d")


            # Validate date is not in the past
            if departure_date < datetime.datetime.now():
                return await self.template_service.departure_date_template(
                    session, route, "❌ You need to plan the future.\n"
                )
            route.departure_date = departure_date
            updated_route, err = await self.sql_db_service.update_route(route)
            if err:
                return await self.template_service.departure_date_template(
                    session, route, "❌ Could not save the departure date."
                )
            return await self.template_service.departure_date_template(session, updated_route)

        except ValueError:
            return await self.template_service.departure_date_template(
                session, route, "❌ Could not parse the date"
            )

    async def _handle_ai_date_unknown(
        self, session: SessionDB, route: SeaRouteDB, intent: Optional[Dict] = None
    ):
        return await self.template_service.departure_date_template(
            session, route, "❌ Please, follow examples.\n"
        )


    async def _handle_average_speed(self, session: SessionDB, route: SeaRouteDB, message: str):

        intent = await self.ai_service.parse_speed_intent(message)

        if intent.get("status") == "failed":
            return await self.template_service.average_speed_template(
                session, route, "❌ Could not parse the speed. Please try again."
            )

        status = intent.get("status")

        if status == "update":
            speed = intent.get("value")
            if not (0.1 <= speed <= 30):
                return await self.template_service.average_speed_template(session, route, "Vessel speed bounds: 0.1 .. 30")

            route.average_speed_kts = speed
            route, err = await self.sql_db_service.update_route(route)
            if err:
                return await self.template_service.average_speed_template(session, route, err)
            return await self.template_service.average_speed_template(session, route, )

        elif status == "confirm":
            if not route.average_speed_kts:
                return await self.template_service.average_speed_template(session, route, "Enter value before confirmation")

            session, err = await self.navigation_handler.to_next_step(session)
            return await self.template_service.fuel_selection_template(session, route)
        else:
            return await self._handle_unknown_intent(session, route, intent)

    async def _handle_fuel_selection(self, session: SessionDB, route: SeaRouteDB, message: str):
        fuels = []

        vls_fo, err = await self.sql_db_service.get_fuel_by_name("VLS FO")
        if not err and vls_fo:
            fuels.append(vls_fo)


        ls_mgo, err = await self.sql_db_service.get_fuel_by_name("MGO LS")
        if not err and ls_mgo:
            fuels.append(ls_mgo)


        intent, err = await self.ai_service.parse_fuel_selection_intent(message, fuels)
        if err or intent.get("status") == "failed":
            return await self.template_service.average_speed_template(
                session, route, "Could not parse fuels. Please try again."
            )

        status = intent.get("status")
        if status == "update":
            return await self._handle_fuel_selection_update(session, route, intent)
        elif status == "confirm":
            return await self._build_the_bunkering_plan(session, route, intent)
            #session, err = await self.navigation_handler.to_next_step(session)
            #return await self.template_service.route_build_confirmation_request_template(session, route)

        return await self._handle_unknown_intent(session, route, intent)

    async def _handle_fuel_selection_update(self, session: SessionDB, route: SeaRouteDB, intent: Dict):
        route.fuels = []

        fuels = []
        vls_fo, err = await self.sql_db_service.get_fuel_by_name("VLS FO")
        if not err and vls_fo:
            fuels.append(vls_fo)

        ls_mgo, err = await self.sql_db_service.get_fuel_by_name("MGO LS")
        if not err and ls_mgo:
            fuels.append(ls_mgo)

        fuels_list = []

        for name in intent.get("by_name", []):
            f, err = await self.sql_db_service.get_fuel_by_name(name.strip())
            if not err and f:
                fuels_list.append(f)


        for n in intent.get("fuel_numbers", []):
            if 0 <= n - 1 < len(fuels):
                fuels_list.append(fuels[n - 1])

        if intent.get("select_all", False):
            fuels_list.extend(fuels)

        uniq_fuel_id = set()
        for fuel in fuels_list:
            if not fuel.id in uniq_fuel_id:
                uniq_fuel_id.add(fuel.id)

        route.fuels = [f for f in fuels if f.id in uniq_fuel_id]
        route, err = await self.sql_db_service.update_route(route)
        return await self.template_service.fuel_selection_template(session, route)


    async def _handle_route_build_request(
        self, session: SessionDB, route: SeaRouteDB, message: str
    ) -> ResponsePayloadCollection:
        intent, err = self.ai_service.confirm_route_build_request(message)
        if err or intent.get("action") == "error":
            return ResponsePayloadCollection(
                responses=[
                    ResponsePayload(
                        err="Sorry, I didn't understand that. Please try again."
                    )
                ]
            )
        action = intent.get("action")

        if action == "confirmed":
            return await self._build_the_bunkering_plan(session, route, intent)
        elif action == "declined":
            return await self._decline_route_building(session, route, intent)
        elif action == "unknown":
            return await self._handle_unknown_intent(session, route, intent)
        else:
            return await self._handle_unknown_intent(session, route, intent)


    # -------------------- fuel prices --------------------

    async def find_fuel_price(
            self,
            port,
            fuel_name: str,
            date: datetime.date,
    ) -> Optional[float]:
        date = utils.adjust_from_weekend(date)

        price_db, _ = await self.sql_db_service.get_port_fuel_price_by_port_locode(
            port.locode, fuel_name, date
        )
        if price_db:
            if price_db.value > 0:
                return price_db.value

        alt_ids, err = await self.sql_db_service.get_alternative_mabux_ids(port.locode.strip())
        if err or not alt_ids:
            return None

        for mabux_id in alt_ids:
            price_db, _ = await self.sql_db_service.get_port_fuel_price_by_port_mabux_id(
                mabux_id, fuel_name, date
            )
            if price_db:
                if price_db.value > 0:
                    return price_db.value

        return None

    # -------------------- port pricing --------------------

    async def build_priced_port(
            self,
            port,
            fuels: list,
            price_date: datetime.date,
            take_anyway: List[str],
            semaphore: asyncio.Semaphore,
    ) -> Optional[Dict]:
        async with semaphore:
            tasks = {
                fuel.name: self.find_fuel_price(
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

            if prices_count == 0 and not port.locode in take_anyway:
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

    def find_nearest_waypoint(self, step, waypoints):
        nearest_wp = None
        min_dist = float("inf")

        for wp in waypoints:
            d = self.haversine_km(
                step.get("port").latitude,
                step.get("port").longitude,
                wp.latitude,
                wp.longitude,
            )
            if d < min_dist:
                min_dist = d
                nearest_wp = wp

        return nearest_wp

    def haversine_km(self, lat1, lon1, lat2, lon2) -> float:
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
            self,
            searoute,
            radius_km: float = 500.0,
            limit: int = 50,
            step: int = 50,
            chunk_size: int = 20,
            max_parallel_chunks: int = 4,
    ):
        seen = {}

        semaphore = asyncio.Semaphore(max_parallel_chunks)

        async def process_chunk(chunk):
            async with semaphore:
                for c in chunk:
                    ports, err = await self.sql_db_service.search_ports_nearby_with_prices(
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


        # coords = [[Coordinates(
        #     latitude=wp.latitude,
        #     longitude=wp.longitude,
        # ) for wp in sea_route.waypoints]]
        # tasks = [process_chunk(c) for c in coords]

        tasks = [ process_chunk(chunk) for chunk in utils.chunk_coords(searoute.seaRouteCoordinates, step, chunk_size)]

        await asyncio.gather(*tasks)

        ports = list(seen.values())
        ports.sort(key=lambda p: getattr(p, "_distance_km", float("inf")))
        ports = utils.unique_ports(ports)


        # fetch ports in the groups
        group_ports = await self.get_ports_via_group(ports)
        ports.extend(group_ports)
        ports = utils.unique_ports(ports)
        return ports, [port.locode for port in group_ports]


    async def get_ports_via_group(self, ports: List[SeaPortDB]):
        group_ids = set()
        for p in ports:
            port_groups, err = await self.sql_db_service.get_port_groups(p.locode)
            if port_groups and not err:
                [group_ids.add(p.group_id) for p in port_groups]

        group_ports = []
        for group_id in list(group_ids):
            r, err = await self.sql_db_service.get_group_ports(group_id)
            if r and not err:
                group_ports.extend(r)

        ports = []
        for g in group_ports:
            port, err = await self.sql_db_service.get_port_by_locode(g.port_locode)
            if port and not err:
                ports.append(port)

        return ports

    def find_nearest_coord_index(self, step, coordinates) -> int:
        min_dist = float("inf")
        min_idx = 0

        for i, c in enumerate(coordinates):
            d = self.haversine_km(
                step.get("port").latitude,
                step.get("port").longitude,
                c.latitude,
                c.longitude,
            )
            if d < min_dist:
                min_dist = d
                min_idx = i

        return min_idx

    def distance_from_start_to_index(self, coordinates, idx: int) -> float:
        total = 0.0

        for i in range(1, idx + 1):
            prev = coordinates[i - 1]
            curr = coordinates[i]
            total += self.haversine_km(
                prev.latitude,
                prev.longitude,
                curr.latitude,
                curr.longitude,
            )

        return total

    def precompute_route_distances(self, coordinates):
        cumulative = [0.0]
        total = 0.0

        for i in range(1, len(coordinates)):
            prev = coordinates[i - 1]
            curr = coordinates[i]
            total += self.haversine_km(
                prev.latitude,
                prev.longitude,
                curr.latitude,
                curr.longitude,
            )
            cumulative.append(total)

        return cumulative

    def build_coord_index(self, coordinates):
        return [
            (c.latitude, c.longitude, idx)
            for idx, c in enumerate(coordinates)
        ]

    def index_waypoints(self, waypoints):
        return [
            (wp.latitude, wp.longitude, wp)
            for wp in waypoints
        ]

    def nearest_coord_index_fast(self, lat, lon, coord_index):
        min_dist = float("inf")
        min_idx = 0

        for clat, clon, idx in coord_index:
            d = self.haversine_km(lat, lon, clat, clon)
            if d < min_dist:
                min_dist = d
                min_idx = idx

        return min_idx

    def nearest_waypoint_fast(self, lat, lon, wp_index):
        min_dist = float("inf")
        nearest = None

        for wlat, wlon, wp in wp_index:
            d = self.haversine_km(lat, lon, wlat, wlon)
            if d < min_dist:
                min_dist = d
                nearest = wp

        return nearest

    async def enrich_ports_with_eta_and_distance_fast(
            self,
            steps: List[dict],
            sea_route,
    ):
        coordinates = sea_route.seaRouteCoordinates
        waypoints = sea_route.waypoints

        # --- PRECOMPUTE ONCE ---
        cumulative_distances = self.precompute_route_distances(coordinates)
        coord_index = self.build_coord_index(coordinates)
        wp_index = self.index_waypoints(waypoints)

        for step in steps:
            port = step["port"]
            lat = port.latitude
            lon = port.longitude

            # nearest waypoint → ETA
            wp = self.nearest_waypoint_fast(lat, lon, wp_index)
            step["eta_datetime"] = wp.eta_datetime if wp else None

            # nearest coordinate → distance along route
            idx = self.nearest_coord_index_fast(lat, lon, coord_index)
            step["distance"] = cumulative_distances[idx]


    # -------------------- bunkering steps --------------------

    async def build_bunkering_steps(
            self,
            ports: List,
            fuels: list,
            price_date: datetime.date,
            take_anyway : List[str],
            max_concurrency: int = 40,
            steps_limit: int = 20,

    ) -> List[Dict]:
        semaphore = asyncio.Semaphore(max_concurrency)

        tasks = [
            self.build_priced_port(
                port=p,
                fuels=fuels,
                price_date=price_date,
                take_anyway=take_anyway,
                semaphore=semaphore,
            )
            for p in ports
        ]

        results = await asyncio.gather(*tasks)
        steps = [r for r in results if r is not None]

        # sort: (a) prices_count desc, (b) prices_sum asc
        steps.sort(key=lambda s: (-s["prices_count"], s["prices_sum"]))

        return steps

    # def select_ports_zigzag(
    #         self,
    #         steps_dicts: list,
    #         max_ports: int = 20,
    #         max_per_country: int = 2,
    #         top_n_marked: int = 3,
    # ):
    #     """
    #     Two-phase selection of ports:
    #     1. Take cheapest ports (by prices_sum) with max 2 per country until 12 ports.
    #     2. Fill remaining ports using zig-zag along distance (start ↔ end) starting after last selected.
    #     """
    #     # Phase 1: cheapest ports selection
    #     steps_by_price = sorted(steps_dicts, key=lambda s: s["prices_sum"])
    #     country_counts = {}
    #     selected = []
    #
    #     for step in steps_by_price:
    #         country = step["port"].country_name or "unknown"
    #         country_counts.setdefault(country, 0)
    #
    #         if country_counts[country] < max_per_country:
    #             selected.append(step)
    #             country_counts[country] += 1
    #
    #         if len(selected) >= 12:
    #             break
    #
    #     # Phase 2: zig-zag selection along distance for remaining ports
    #     if len(selected) < max_ports:
    #         # Sort remaining ports by distance
    #         remaining_steps = [s for s in steps_dicts if s not in selected]
    #         remaining_steps.sort(key=lambda s: s["distance"])
    #
    #         left = 0
    #         right = len(remaining_steps) - 1
    #         toggle = True
    #
    #         while len(selected) < max_ports and left <= right:
    #             idx = left if toggle else right
    #             step = remaining_steps[idx]
    #             country = step["port"].country_name or "unknown"
    #             country_counts.setdefault(country, 0)
    #
    #             if country_counts[country] < max_per_country:
    #                 selected.append(step)
    #                 country_counts[country] += 1
    #
    #             if toggle:
    #                 left += 1
    #             else:
    #                 right -= 1
    #
    #             toggle = not toggle
    #
    #         # If still less than max_ports, fill remaining ignoring country
    #         if len(selected) < max_ports:
    #             for step in remaining_steps:
    #                 if step not in selected:
    #                     selected.append(step)
    #                 if len(selected) >= max_ports:
    #                     break
    #
    #     # Mark top_n_marked cheapest ports
    #     selected.sort(key=lambda s: s["prices_sum"])
    #     for s in selected[:top_n_marked]:
    #         s["marked"] = True
    #
    #     # Final sort by distance along route
    #     selected.sort(key=lambda s: s["distance"])
    #
    #     return selected

    def select_ports_zigzag(
            self,
            steps_dicts: list,
            max_ports: int = 20,
            max_per_country: int = 2,
            top_n_marked: int = 3,
    ):
        """
        Three-phase selection of ports:
        1. Take cheapest ports with max_per_country per country until 12 ports.
        2. Zig-zag along distance for remaining ports (respecting country limits).
        3. If still < max_ports:
           - iterate countries one by one
           - take next cheapest unused port per country
           - after each full pass, apply zig-zag again
        Goal: touch as many countries as possible while preserving zig-zag logic.
        """

        # ---------- helpers ----------
        def country_of(step):
            return step["port"].country_name or "unknown"

        # ---------- Phase 1: cheapest per country ----------
        steps_by_price = sorted(steps_dicts, key=lambda s: s["prices_sum"])
        country_counts = {}
        selected = []

        for step in steps_by_price:
            country = country_of(step)
            country_counts.setdefault(country, 0)

            if country_counts[country] < max_per_country:
                selected.append(step)
                country_counts[country] += 1

            if len(selected) >= min(12, max_ports):
                break

        # ---------- Phase 2: zig-zag by distance ----------
        def zigzag_fill(selected, country_counts):
            remaining = [s for s in steps_dicts if s not in selected]
            remaining.sort(key=lambda s: s["distance"])

            left, right = 0, len(remaining) - 1
            toggle = True

            while len(selected) < max_ports and left <= right:
                idx = left if toggle else right
                step = remaining[idx]
                country = country_of(step)
                country_counts.setdefault(country, 0)

                if country_counts[country] < max_per_country:
                    selected.append(step)
                    country_counts[country] += 1

                if toggle:
                    left += 1
                else:
                    right -= 1

                toggle = not toggle

        zigzag_fill(selected, country_counts)

        # ---------- Phase 3: expand countries, then zig-zag again ----------
        if len(selected) < max_ports:
            # group remaining ports by country, cheapest first
            from collections import defaultdict

            by_country = defaultdict(list)
            for step in steps_by_price:
                if step not in selected:
                    by_country[country_of(step)].append(step)

            # round-robin by country
            added = True
            while len(selected) < max_ports and added:
                added = False
                for country, steps in by_country.items():
                    if len(selected) >= max_ports:
                        break

                    country_counts.setdefault(country, 0)
                    if country_counts[country] >= max_per_country:
                        continue

                    if steps:
                        step = steps.pop(0)
                        selected.append(step)
                        country_counts[country] += 1
                        added = True

                # after each country sweep → zig-zag again
                zigzag_fill(selected, country_counts)

        # ---------- Mark cheapest ----------
        selected.sort(key=lambda s: s["prices_sum"])
        for s in selected[:top_n_marked]:
            s["marked"] = True

        # ---------- Final sort by distance ----------
        selected.sort(key=lambda s: s["distance"])

        return selected



    # def select_ports_zigzag2(
    #         self,
    #         steps_dicts: list,
    #         departure_port,
    #         destination_port,
    #         max_ports: int = 20,
    #         max_per_country: int = 2,
    #         top_n_marked: int = 3,
    # ):
    #     """
    #     Efficient three-phase selection with center-out zigzag, guaranteed departure/destination,
    #     and marking top_n_marked cheapest per port.
    #     """
    #
    #     # ---------- helpers ----------
    #     def country_of(step):
    #         return step["port"].country_name or "unknown"
    #
    #     # Initialize selected list and country counts
    #     selected = []
    #     country_counts = defaultdict(int)
    #
    #     # Map port_id -> list of steps for marking later
    #     port_to_steps = defaultdict(list)
    #     for step in steps_dicts:
    #         port_to_steps[step["port"].id].append(step)
    #
    #     # ---------- Include departure and destination ----------
    #     dep_dest_ids = {departure_port.id, destination_port.id}
    #     for step in steps_dicts:
    #         if step["port"].id in dep_dest_ids:
    #             selected.append(step)
    #             country_counts[country_of(step)] += 1
    #
    #     # ---------- Phase 1: cheapest per country ----------
    #     steps_by_price = sorted(
    #         [s for s in steps_dicts if s["port"].id not in dep_dest_ids],
    #         key=lambda s: s["prices_sum"]
    #     )
    #
    #     for step in steps_by_price:
    #         country = country_of(step)
    #         if country_counts[country] < max_per_country:
    #             selected.append(step)
    #             country_counts[country] += 1
    #         if len(selected) >= min(12, max_ports):
    #             break
    #
    #     # ---------- Phase 2: center-out zig-zag ----------
    #     remaining = [s for s in steps_dicts if s not in selected]
    #     remaining.sort(key=lambda s: s["distance"])
    #     remaining_deque = deque(remaining)
    #
    #     toggle = True
    #     while remaining_deque and len(selected) < max_ports:
    #         step = remaining_deque.popleft() if toggle else remaining_deque.pop()
    #         country = country_of(step)
    #         if country_counts[country] < max_per_country:
    #             selected.append(step)
    #             country_counts[country] += 1
    #         toggle = not toggle
    #
    #     # ---------- Phase 3: round-robin per country & zigzag again ----------
    #     if len(selected) < max_ports:
    #         # Pre-sort steps per country by price once
    #         by_country = {
    #             country: sorted(
    #                 [s for s in steps_dicts if s not in selected and country_of(s) == country],
    #                 key=lambda s: s["prices_sum"]
    #             )
    #             for country in set(country_of(s) for s in steps_dicts)
    #         }
    #
    #         added = True
    #         while len(selected) < max_ports and added:
    #             added = False
    #             for country, steps_list in by_country.items():
    #                 if len(selected) >= max_ports:
    #                     break
    #                 if country_counts[country] >= max_per_country or not steps_list:
    #                     continue
    #                 step = steps_list.pop(0)  # already sorted by price
    #                 selected.append(step)
    #                 country_counts[country] += 1
    #                 added = True
    #
    #             # zigzag on remaining globally
    #             remaining_zig = [s for s in steps_dicts if s not in selected]
    #             remaining_zig.sort(key=lambda s: s["distance"])
    #             remaining_zig_deque = deque(remaining_zig)
    #             toggle = True
    #             while remaining_zig_deque and len(selected) < max_ports:
    #                 step = remaining_zig_deque.popleft() if toggle else remaining_zig_deque.pop()
    #                 country = country_of(step)
    #                 if country_counts[country] < max_per_country:
    #                     selected.append(step)
    #                     country_counts[country] += 1
    #                 toggle = not toggle
    #
    #     # ---------- Mark ports with 3 cheapest prices ----------
    #     all_prices = [(s["prices_sum"], s["port"]) for s in steps_dicts if s.get("prices_sum") is not None]
    #     all_prices.sort(key=lambda x: x[0])
    #     cheapest_three_prices = {p for p, _ in all_prices[:3]}  # take 3 lowest prices
    #
    #     # mark ports that appear in the top 3 prices
    #     for s in steps_dicts:
    #         if s.get("prices_sum") in cheapest_three_prices:
    #             s['marked'] = True
    #
    #     # ---------- Final sort by distance ----------
    #     selected.sort(key=lambda s: s["distance"])
    #
    #     return selected

    def select_ports_zigzag2(
            self,
            steps_dicts: list,
            departure_port,
            destination_port,
            take_anyway,
            max_ports: int = 20,
            max_per_country: int = 2,
            top_n_marked: int = 3,
    ):
        from collections import defaultdict, deque

        def country_of(step):
            return step["port"].country_name or "unknown"

        def distance_of(step):
            return step.get("distance") or step.get("_distance_km") or float("inf")

        selected = []
        selected_ids = set()
        country_counts = defaultdict(int)

        take_anyway_set = set(take_anyway)

        # ---------------------------------------------------
        # 1️⃣ Add ALL manual_input ports and take_anyway ports
        # ---------------------------------------------------
        for step in steps_dicts:
            port = step["port"]
            port_id = port.id
            if getattr(port, "manual_input", False) or getattr(port, "locode", "") in take_anyway_set:
                if port_id not in selected_ids:
                    selected.append(step)
                    selected_ids.add(port_id)
                    # Do not count towards country limits

        # ---------------------------------------------------
        # 2️⃣ Ensure departure & destination are included
        # ---------------------------------------------------
        for special_port in [departure_port, destination_port]:
            if special_port.id not in selected_ids:
                # Try to find corresponding step
                step = next((s for s in steps_dicts if s["port"].id == special_port.id), None)
                if step:
                    selected.append(step)
                    selected_ids.add(special_port.id)
                    # Count country if not manual/take_anyway
                    if not getattr(step["port"], "manual_input", False) and step["port"].locode not in take_anyway_set:
                        country_counts[country_of(step)] += 1

        # ---------------------------------------------------
        # 3️⃣ Select remaining ports with zigzag and limits
        # ---------------------------------------------------
        remaining = [
            s for s in steps_dicts
            if s["port"].id not in selected_ids and not getattr(s["port"], "manual_input", False)
        ]

        # Zigzag: sort by distance first
        remaining.sort(key=distance_of)
        dq = deque(remaining)
        toggle = True

        while dq:
            non_manual_count = len([s for s in selected if not getattr(s["port"], "manual_input", False)])
            if non_manual_count >= max_ports:
                break

            step = dq.popleft() if toggle else dq.pop()
            country = country_of(step)
            if country_counts[country] < max_per_country:
                selected.append(step)
                selected_ids.add(step["port"].id)
                country_counts[country] += 1

            toggle = not toggle

        # ---------------------------------------------------
        # 4️⃣ Mark cheapest ports globally
        # ---------------------------------------------------
        valid_prices = [s.get("prices_sum") for s in steps_dicts if s.get("prices_sum") is not None]
        cheapest_prices = set(sorted(valid_prices)[:top_n_marked])
        for s in steps_dicts:
            if s.get("prices_sum") in cheapest_prices:
                s["marked"] = True

        # ---------------------------------------------------
        # 5️⃣ Final sort: departure first, destination last, others by distance
        # ---------------------------------------------------
        dep_step = next(s for s in selected if s["port"].id == departure_port.id)
        dest_step = next(s for s in selected if s["port"].id == destination_port.id)
        middle_steps = [s for s in selected if s["port"].id not in {departure_port.id, destination_port.id}]
        middle_steps.sort(key=distance_of)

        return [dep_step, *middle_steps, dest_step]

    # -------------------- full pipeline --------------------

    def tttt(
            self,
            steps_dicts: list,
            departure_port,
            destination_port,
            top_n_marked: int = 3,
    ):

        def country_of(step):
            return step["port"].country_name or "unknown"

        def distance_of(step):
            return step.get("distance") or step.get("_distance_km") or float("inf")


        country_counts = defaultdict(int)


        steps_dicts.sort(key=lambda s: s.get("prices_sum") or float("inf"))


        valid_prices = [
            s.get("prices_sum")
            for s in steps_dicts
            if s.get("prices_sum") is not None
        ]

        cheapest_prices = set(sorted(valid_prices)[:top_n_marked])

        for s in steps_dicts:
            if s.get("prices_sum") in cheapest_prices:
                s["marked"] = True
        # ---------------------------------------------------
        # 5️⃣ Final sort (still allowed, but not used for picking)
        # ---------------------------------------------------
        steps_dicts.sort(key=distance_of)
        return steps_dicts


    async def build_bunkering_plan_fast(
            self,
            user_id,
            departure_port,
            destination_port,
            fuels,
            speed_kts: float = 10.0,
            departure_dt: datetime.datetime = datetime.datetime.now(),
            is_plan: bool = False,
    ):
        sea_route = None

        route, err = await self.sql_db_service.get_route_by_ports_id(departure_port.id, destination_port.id)
        if route and not err:
            sea_route = route.data.full_response


        if sea_route is not None:
            await self.sql_db_service.create_event(Event.searoute_data_reuse(
                user_id,
                {
                    "departure_locode": departure_port.locode,
                    "destination_locode": destination_port.locode,
                    "route_id": str(route.id),
                }))

        if sea_route is None:
            sea_route, err = await self.searoute_api.build_sea_route(
                departure_port.latitude,
                departure_port.longitude,
                destination_port.latitude,
                destination_port.longitude,
                speed_in_knots=speed_kts,
                is_plan=is_plan,
                departure_dt=departure_dt,
            )

            if err:
                await self.sql_db_service.create_event(Event.searoute_plan_error(
                    user_id,
                    {
                        "departure_locode": departure_port.locode,
                        "destination_locode": destination_port.locode,
                        "route_id": str(route.id),
                        "error": str(err)
                    }))

                return None, None, str(err)

            await self.sql_db_service.create_event(Event.searoute_plan(
                user_id,
                {
                    "departure_locode": departure_port.locode,
                    "destination_locode": destination_port.locode,
                    "route_id": str(route.id),
                }))


        if sea_route is None:
            return None, None, "Could not build a path for this route."

        ports, locodes = await self.collect_ports_parallel(searoute=sea_route)
        #ports_per_country, err = await self.country_finder.do_job(sea_route.seaRouteCoordinates)



        # projection
        #projected_ports, err = await self.proj.do_job(coordinates=sea_route.seaRouteCoordinates)

        ports = [departure_port, *ports, destination_port]

        #if ports_per_country and not err:
        #    ports.extend(ports_per_country)

        ports = utils.unique_ports(ports)
        take_anyway = [departure_port.locode, destination_port.locode, *locodes]

        steps_dicts = await self.build_bunkering_steps(
            ports=ports,
            fuels=fuels,
            price_date=datetime.date.today(), #TODO
            take_anyway=take_anyway,
        )

        await self.enrich_ports_with_eta_and_distance_fast(steps_dicts, sea_route)

        zigzag_steps = self.select_ports_zigzag2(steps_dicts, departure_port, destination_port, take_anyway =take_anyway,  max_ports=50, max_per_country=2, top_n_marked = 3)

        #zigzag_steps =  self.tttt(steps_dicts, departure_port, destination_port)

        # Convert dicts to BunkeringStep objects
        bunkering_steps: List[BunkeringStep] = []
        for idx, step in enumerate(zigzag_steps, start=1):
            bunkering_step = BunkeringStep(
                n=idx,
                port=step["port"],
                eta_datetime=step.get("eta_datetime"),
                distance=step.get("distance"),
                fuel_info=step["fuel_info"],
                agent_required=False,  # can adjust later if needed
                selected=False,
                to_show=True,
                marked=step.get("marked", False)
            )
            bunkering_steps.append(bunkering_step)

        return bunkering_steps, sea_route, None

    async def _build_the_bunkering_plan(self, session: SessionDB, route: SeaRouteDB, intent: Dict) -> ResponsePayloadCollection:
        departure_port, err = await self.sql_db_service.get_port_by_id(route.departure_port_id)
        if err:
            return ResponsePayloadCollection(responses=[ResponsePayload(err="Sorry, I didn't find departure port.")])

        destination_port, err = await self.sql_db_service.get_port_by_id(route.destination_port_id)
        if err:
            return ResponsePayloadCollection(responses=[ResponsePayload(err="Sorry, I didn't find destination port.")])

        if not route.fuels:
            return await self.template_service.session_template(session, " <b> Please, select at least one fuel type. </b> ")

        bunkering_steps, searoute, err = await self.build_bunkering_plan_fast(
            user_id=session.user_id,
            departure_port=departure_port,
            destination_port=destination_port,
            fuels=route.fuels,
            speed_kts=float(route.average_speed_kts),
            departure_dt=route.departure_date,
            is_plan=True
        )
        if err:
            return ResponsePayloadCollection(responses=[ResponsePayload(err=err)])

        route.bunkering_steps = bunkering_steps
        route.data.full_response = searoute
        route.data.departure_to_destination_coordinates = searoute.seaRouteCoordinates
        route.data.is_updating = False

        route_new, err = await self.sql_db_service.update_route(route)
        if err:
            return ResponsePayloadCollection(responses=[ResponsePayload(err=err)])

        await self.sql_db_service.create_event(Event.route_built(
            session.user_id,
            {
                "departure_locode": departure_port.locode,
                "destination_locode": destination_port.locode,
            }))

        session, err = await self.navigation_handler.to_next_step(session)
        return await self.template_service.build_universal_bunkering_template(session, route)
    #
    # async def _build_the_bunkering_plan(self, session: SessionDB, route: SeaRouteDB, intent: Dict) -> ResponsePayloadCollection:
    #     departure_port, err = await self.sql_db_service.get_port_by_id(route.departure_port_id)
    #     if err:
    #         return ResponsePayloadCollection(responses=[ResponsePayload(err="Sorry, I didn't find departure port.")])
    #
    #     destination_port, err = await self.sql_db_service.get_port_by_id(route.destination_port_id)
    #     if err:
    #         return ResponsePayloadCollection(responses=[ResponsePayload(err="Sorry, I didn't find destination port.")])
    #
    #     sea_route, err = await self.searoute_api.build_sea_route(departure_port.latitude, departure_port.longitude, destination_port.latitude, destination_port.longitude, speed_in_knots=route.average_speed_kts, is_plan=True, departure_dt=route.departure_date)
    #     if err:
    #         return ResponsePayloadCollection(responses=[ResponsePayload(err=err)])
    #
    #     route.data.departure_to_destination_coordinates = sea_route.seaRouteCoordinates
    #
    #     waypoint_ports: list[SearoutePort] = []
    #
    #     for waypoint in sea_route.waypoints:
    #         time.sleep(random.uniform(0.3, 0.5))
    #         near_ports, err = await self.searoute_api.get_nearest_port_to_coordinates(
    #             waypoint.latitude,
    #             waypoint.longitude,
    #             {"limit": 50},
    #         )
    #         if err or not near_ports:
    #             continue
    #
    #         # persist / update reference data (ETL: load)
    #         await asyncio.gather(
    #             *[
    #                 self.sql_db_service.upsert_port_size_from_searoute(port)
    #                 for port in near_ports
    #             ]
    #         )
    #
    #         # enrich ports with route-specific attributes (ETL: transform)
    #         for port in near_ports:
    #             port.eta_datetime = waypoint.eta_datetime
    #             port.distance = waypoint.distance
    #
    #         waypoint_ports.extend(near_ports)
    #
    #         # async-friendly throttling
    #         await asyncio.sleep(random.uniform(0.4, 0.5))
    #
    #     # deduplicate & sort
    #     large_ports = [p for p in waypoint_ports if p.size == 'large']
    #     unique_ports = searoute_utils.get_unique_ports(large_ports)
    #     unique_ports.sort(key=lambda p: p.distance, reverse=False)
    #
    #
    #     route.bunkering_steps =  await self.build_bunkering_steps_optimized(
    #         waypoint_ports = unique_ports,
    #         fuels=route.fuels,
    #         price_date=datetime.date.today()
    #     )
    #     route.data.is_updating = False
    #
    #     route_new, err = await self.sql_db_service.update_route(route)
    #     if err:
    #         return ResponsePayloadCollection(responses=[ResponsePayload(err=err)])
    #
    #     session, err = await self.navigation_handler.to_next_step(session)
    #     return await self.template_service.build_universal_bunkering_template(session, route)



        #
        # # BUILD THE SEQUENCE OF PORTS
        # closest_ports = []
        # for route_area in sea_route.routeAreas:
        #     time.sleep(0.3)
        #     near_ports, err = await self.searoute_api.get_nearest_port_to_coordinates(route_area.latitude, route_area.longitude, {"limit": 5})
        #     if err:
        #         pass
        #     else:
        #         for n_port in near_ports:
        #             updated_port, err = await self.sql_db_service.upsert_port_size_from_searoute(n_port)
        #
        #         only_large_ports = [p for p in near_ports ]#if p.size == "large"]
        #         closest_ports.extend(only_large_ports)
        #         #closest_ports.extend(near_ports)
        #
        # unique_ports = searoute_utils.get_unique_ports(closest_ports)
        # unique_ports.sort(key=lambda p: p.distance)
        #
        # ports_in_db = [] #[departure_port, destination_port]
        # for port in unique_ports:
        #     port_db, err = await self.sql_db_service.get_port_by_locode(port.locode)
        #     if not err:
        #         ports_in_db.append(port_db)
        #
        # # for coordinate in sea_route.seaRouteCoordinates[::30]:
        # #     nearby_db, err = await self.sql_db_service.search_ports_nearby(coordinate.latitude, coordinate.longitude, 7, 1000)
        # #     if not nearby_db and err:
        # #         continue
        # #     ports_in_db.extend(nearby_db)
        #
        # filtered_ports = utils.unique_ports(ports_in_db)
        #
        # ports_in_db = [departure_port, *filtered_ports, destination_port]
        #
        # bunkering_steps = await self.build_bunkering_steps_optimized(ports_in_db=ports_in_db, fuels=route.fuels, date=datetime.date.today())
        #
        #
        # for i, step in enumerate(bunkering_steps, 1):
        #     step.n = i
        #
        # route.bunkering_steps = bunkering_steps
        #
        # route, err = await self.sql_db_service.update_route(route)
        #
        # if err:
        #     return ResponsePayloadCollection(responses=[ResponsePayload(err=err)])
        #
        # route, err = await self.sql_db_service.update_route(route)
        # if err:
        #     return ResponsePayloadCollection(responses=[ResponsePayload(err=err)])
        #
        #
        # session, err = await self.navigation_handler.to_next_step(session)
        # return await self.template_service.build_universal_bunkering_template(session, route)

    # def _adjust_from_weekend(self, date: datetime.date) -> datetime.date:
    #     # 5 = Saturday, 6 = Sunday
    #     while date.weekday() >= 5:
    #         date -= datetime.timedelta(days=1)
    #     return date
    #
    # async def _find_fuel_price(
    #         self,
    #         port: SeaPortDB,
    #         fuel_name: str,
    #         date: datetime.datetime.date,
    # ) -> Optional[float]:
    #     """
    #     Tries to find fuel price by:
    #     1) port locode
    #     2) alternative mabux ids
    #     Stops immediately when a price is found.
    #     """
    #     date = self._adjust_from_weekend(date)
    #
    #     price_db, err = await self.sql_db_service.get_port_fuel_price_by_port_locode(
    #         port.locode, fuel_name, date
    #     )
    #     if price_db:
    #         return price_db.value
    #
    #     alt_ids, err = await self.sql_db_service.get_alternative_mabux_ids(port.locode.strip())
    #     if err or not alt_ids:
    #         return None
    #
    #     for mabux_id in alt_ids:
    #         price_db, err = await self.sql_db_service.get_port_fuel_price_by_port_mabux_id(
    #             mabux_id, fuel_name, date
    #         )
    #         if price_db:
    #             return price_db.value
    #
    #     return None
    #
    # async def _build_port_step(
    #         self,
    #         idx: int,
    #         searoute_port: SearoutePort,
    #         fuels: list,
    #         price_date: datetime.date,
    #         semaphore: asyncio.Semaphore,
    # ) -> Optional[Tuple[BunkeringStep, int, float]]:
    #     async with semaphore:
    #         port_db, err = await self.sql_db_service.get_port_by_locode(
    #             searoute_port.locode
    #         )
    #         if err or not port_db:
    #             return None
    #
    #         # fetch prices concurrently (ETL: extract)
    #         price_tasks = {
    #             fuel.name: self._find_fuel_price(
    #                 port=port_db,
    #                 fuel_name=fuel.name,
    #                 date=price_date,
    #             )
    #             for fuel in fuels
    #         }
    #
    #         prices = await asyncio.gather(*price_tasks.values())
    #
    #         fuel_info = {}
    #         prices_count = 0
    #         prices_sum = 0.0
    #
    #         for fuel_name, price in zip(price_tasks.keys(), prices):
    #             if price is not None:
    #                 prices_count += 1
    #                 prices_sum += price
    #
    #             fuel_info[fuel_name] = {
    #                 "mobux_price_status": price is not None,
    #                 "fuel_name": fuel_name,
    #                 "fuel_price": price,
    #                 "quantity": None,
    #             }
    #
    #         if prices_count == 0:
    #             return None
    #
    #         preferred_order = ["VLS FO", "MGO LS"]
    #         all_fuels_set = set(fuel_info.keys())
    #
    #         ordered_fuels = []
    #
    #         # preferred fuels first
    #         for fuel in preferred_order:
    #             if fuel in all_fuels_set:
    #                 ordered_fuels.append(fuel)
    #
    #         # remaining fuels alphabetically
    #         remaining_fuels = sorted(f for f in all_fuels_set if f not in preferred_order)
    #         ordered_fuels.extend(remaining_fuels)
    #
    #         fuel_info = {fuel: fuel_info[fuel] for fuel in ordered_fuels}
    #
    #
    #         bunkering_step = BunkeringStep(
    #             n=idx,
    #             port=port_db,
    #             eta_datetime=searoute_port.eta_datetime,
    #             distance=searoute_port.distance,
    #             fuel_info=fuel_info,
    #             agent_required=False,
    #             selected=False,
    #             to_show=True,
    #             marked=False
    #         )
    #
    #         return bunkering_step, prices_count, prices_sum
    #
    # async def build_bunkering_steps_optimized(
    #         self,
    #         waypoint_ports: List[SearoutePort],
    #         fuels: list,
    #         price_date: datetime.date,
    #         max_concurrency: int = 10,
    # ) -> List[BunkeringStep]:
    #     semaphore = asyncio.Semaphore(max_concurrency)
    #
    #     tasks = [
    #         self._build_port_step(
    #             idx=i,
    #             searoute_port=port,
    #             fuels=fuels,
    #             price_date=price_date,
    #             semaphore=semaphore,
    #         )
    #         for i, port in enumerate(waypoint_ports, start=1)
    #     ]
    #
    #     results: list[Optional[Tuple[BunkeringStep, int, float]]] = await asyncio.gather(*tasks)
    #
    #     # filter invalid / empty results
    #     valid_results = [
    #         r for r in results
    #         if r is not None
    #            and r[1] > 0
    #            and r[0].port.port_size == "large"
    #     ]
    #
    #     # business sorting rule
    #     valid_results.sort(key=lambda r: r[0].distance, reverse=False)
    #
    #     steps = [step for step, _, _ in valid_results]
    #
    #     # normalize step numbering
    #     for i, step in enumerate(steps, start=1):
    #         step.n = i
    #
    #     self.mark_cheapest_steps(steps)
    #     return steps
    #
    # def mark_cheapest_steps(self, steps: list[BunkeringStep], top_n: int = 3) -> None:
    #     priced_steps = []
    #
    #     for step in steps:
    #         prices = [
    #             info["fuel_price"]
    #             for info in step.fuel_info.values()
    #             if info["fuel_price"] is not None
    #         ]
    #         if not prices:
    #             step.marked = False
    #             continue
    #
    #         avg_price = sum(prices) #/ len(prices)
    #         priced_steps.append((step, avg_price))
    #
    #     # sort by cheapest average price
    #     priced_steps.sort(key=lambda x: x[1])
    #
    #     cheapest_steps = {step.n for step, _ in priced_steps[:top_n]}
    #
    #     for step in steps:
    #         step.marked = step.n in cheapest_steps


    async def _decline_route_building(
        self, session: SessionDB, route: SeaRouteDB, intent: Dict
    ) -> ResponsePayloadCollection:
        session.current_task = RouteTaskEnum.MAIN_MENU.value
        session.current_step = None
        route.data = SeaRouteData(full_response=None)
        session.route_id = None
        session, err = await self._update_session(session, route.user_id)
        return ResponsePayloadCollection(
            responses=[
                ResponsePayload(
                    text="New route creating was cancelled but saved.\nYou may continue later."
                )
            ]
        )

    async def _handle_bunkering_port_sequence(self, session: SessionDB, route: SeaRouteDB, message: str) -> ResponsePayloadCollection:
        intent, err = await self.ai_service.parse_bunkering_port_queue_intent(route, message)

        if err or intent.get("action", "error") == "error":
            return ResponsePayloadCollection(responses=[ResponsePayload(err="Sorry, I didn't understand that. Please try again.")])

        if intent.get("take_ports", None) or intent.get("leave_ports", None):
            intent["action"] = "suggestions"


        action = intent.get("action")

        if action == "suggestions":
            return await self._apply_bunkering_port_sequence_suggestions(session, route, intent)
        elif action == "confirm":
            return await self._bunkering_port_sequence_confirmed(session, route, intent)
        else:
            return ResponsePayloadCollection(
                responses=[ResponsePayload(text="Sorry, I didn't understand that. Please try again.")]
            )

    async def _apply_bunkering_port_sequence_suggestions(
        self, session: SessionDB, route: SeaRouteDB, intent: Dict
    ):
        if not route.bunkering_steps:
            return ResponsePayload(err="There were no bunkering ports to configure.")

        # Get the ports to take and leave from intent
        take_ports = intent.get("take_ports", [])
        leave_ports = intent.get("leave_ports", [])

        # Simple logic: go through all ports and set selection status
        for i, port in enumerate(route.bunkering_steps, 1):
            if i in take_ports:
                port.selected = True
            elif i in leave_ports:
                port.selected = False
            # If not mentioned in either array, keep current selection


        route, err = await self.sql_db_service.update_route(route)

        session, err = await self._update_session(session, route.user_id)
        if err:
            return ResponsePayload(err=err)

        return await self.template_service.build_universal_bunkering_template(session, route)

    async def _bunkering_port_sequence_confirmed(self, session: SessionDB, route: SeaRouteDB, intent: dict):

        if not [s for s in route.bunkering_steps if s.selected]:
            return await self.template_service.build_universal_bunkering_template(session, route, " <b> Select at least one port. </b> ")

        session, err = await self.navigation_handler.to_next_step(session)
        if err:
            return ResponsePayload(err="Could not go to the fuel quantity selection")

        return await self.template_service.build_universal_bunkering_template(session, route)


    async def _handle_fuel_bunkering_sequence(self, session: SessionDB, route: SeaRouteDB, message):
        intent, err = self.ai_service.parse_bunkering_fuel_queue_intent(route, message)

        if err or intent.get("action", "error") == "error":
            return ResponsePayloadCollection(responses=[ResponsePayload(err="Sorry, I didn't understand that. Please try again.")])

        action = intent.get("action")

        if action == "update":
            return await self._apply_fuel_bunkering_suggestions(session, route, intent)
        elif action == "confirm":
            return await self._confirm_fuel_bunkering(session, route, intent)
        else:
            return await self._handle_unknown_intent(session, route, intent)

    async def _handle_unknown_intent(
        self, *args, **kwargs
    ) -> ResponsePayloadCollection:
        return ResponsePayloadCollection(
            responses=[
                ResponsePayload(
                    text="Sorry, I didn't understand that. Please try again."
                )
            ]
        )

    async def _apply_fuel_bunkering_suggestions(
        self, session: SessionDB, route: SeaRouteDB, intent: Dict
    ) -> ResponsePayloadCollection:
        ports_payload = intent.get("ports", [])
        port_updates = {str(p["id"]): p["fuels"] for p in ports_payload if "id" in p}

        for i, step in enumerate(route.bunkering_steps, 1):
            fuels_update = port_updates.get(str(step.port.id), None)
            if fuels_update is None:
                continue

            for fuel_entry in fuels_update:
                fname = fuel_entry["fuel_name"]
                qty = fuel_entry.get("quantity")
                price = fuel_entry.get("price")

                if fname in step.fuel_info:
                    step.fuel_info[fname]["quantity"] = qty if qty is not None else ""
                    step.fuel_info[fname]["price_on_request"] = price in (
                        None,
                        "",
                    )
                    # #if not step.fuel_info[fname]["mobux_price_status"]:
                    # step.fuel_info[fname]["fuel_price"] = (
                    #         price if price is not None else ""
                    #     )

        route, err = await self.sql_db_service.update_route(route)
        session, err = await self._update_session(session, session.user_id)
        return await self.template_service.build_universal_bunkering_template(session, route)

    async def _confirm_fuel_bunkering(self, session: SessionDB, route: SeaRouteDB, intent: Dict) -> ResponsePayloadCollection:

        route, err = await self.sql_db_service.update_route(route)
        if err:
            return ResponsePayloadCollection(responses=[ResponsePayload(err=err)])

        session, err = await self.navigation_handler.to_next_step(session)
        if err:
            return ResponsePayloadCollection(responses=[ResponsePayload(err=f"Could not go to the next step: {err}")])

        return await self.template_service.session_template(session)

    async def render_bukering_request_in_pdf(self, session: SessionDB, route: SeaRouteDB):
        user_db, err = await self.sql_db_service.get_user_by_id(session.user_id)
        if err:
            return

        html_content, html_content_bytes, file_obj, subject, images, image_data = await self.template_service.format_option2_email2_jinja(user_db, route)
        if user_db.email and utils.is_valid_email(user_db.email):
            ok, err = await self.email_sender.route_report(
                subject=subject,
                text=html_content,
                images=[image_data],
                pdf_bytes=html_content_bytes,
                to=user_db.email
            )

        return file_obj


    async def send_bunekring_request_with_quote(self, session: SessionDB, route: SeaRouteDB):
        user_db, err = await self.sql_db_service.get_user_by_id(session.user_id)
        if err:
            return

        html_content, html_content_bytes, file_obj, subject, images, image_data = await self.template_service.format_option2_email2_jinja(user_db, route)

        ok, err = await self.email_sender.route_report(
            subject=subject,
            text=html_content,
            images=[image_data],
            pdf_bytes=html_content_bytes,
        )


