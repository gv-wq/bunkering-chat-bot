import asyncio
import uuid
from datetime import datetime, date
from typing import Dict, Optional, List

from app.data import emoji
from app.data.dto.main.Event import Event
from app.data.dto.main.FuelData import FuelData
from app.data.dto.main.MabuxPortFuelPrice import MabuxPortFuelPriceDB
from app.data.dto.main.QuoteRequestDB import QuoteRequestDB
from app.data.dto.main.Session import SessionDB
from app.data.dto.messenger.ResponsePayload import (
    ResponsePayload,
    ResponsePayloadCollection,
)

from app.data.dto.searoute.SearoutePort import SearoutePort
from app.data.enums.QuoteRequestEnum import QuoteRequestEnum
from app.data.enums.RouteTask import RouteTaskEnum
from app.data.enums.SupplierRequestSearchEnum import SupplierRequestSearchEnum

from app.services.ai_service import AiService
from app.services.db_service import DbService
from app.services.email_sender import EmailSender
from app.services.external_api.request_limiter import RequestLimiter
from app.services.external_api.searoute_api import SearouteApi
from app.services.fuel_price_service import FuelPriceService
from app.services.template.telegram_template_service import TemplateService

from app.handlers.navigation_handler import NavigationHandler
from app.services.utils import utils

class SupplierQuoteRequestHandler:
    def __init__(
            self,
            ai_service: AiService,
            sql_db_service: DbService,
            template_service: TemplateService,
            navigation_handler: NavigationHandler,
            searoute_api: SearouteApi,
            port_fuel_price_service: FuelPriceService,

    ):
        self.ai_service = ai_service
        self.sql_db_service = sql_db_service
        self.template_service = template_service
        self.navigation_handler = navigation_handler
        self.searoute_api = searoute_api
        self.searoute_limiter = RequestLimiter(1, 0.6)
        self.email_sender = EmailSender()
        self.port_fuel_price_service : FuelPriceService = port_fuel_price_service

    async def handle(self, session: SessionDB, message: str) -> ResponsePayloadCollection:
        quote_r, err = await self.sql_db_service.get_or_create_quote_request(session)
        if err:
            return ResponsePayloadCollection(responses=[ResponsePayload(err=err)])

        if session.current_step == QuoteRequestEnum.VESSEL_NAME.value:
            return await self._handle_vessel_name(session, quote_r, message)

        elif session.current_step == QuoteRequestEnum.VESSEL_IMO.value:
            return await self._handle_vessel_imo(session, quote_r, message)

        if session.current_step == QuoteRequestEnum.PORT_SEARCH.value:
            return  await self._handle_port_search(session, quote_r, message)

        if session.current_step == QuoteRequestEnum.ETA.value:
            return await self._handle_eta(session, quote_r, message)

        # elif session.current_step == QuoteRequestEnum.ETA_FROM.value:
        #     return await self._handle_eta_from(session, quote_r, message)
        #
        # elif session.current_step == QuoteRequestEnum.ETA_TO.value:
        #     return await self._handle_eta_to(session, quote_r, message)

        elif session.current_step == QuoteRequestEnum.FUEL_QUANTITY.value:
            return await self._handle_fuel_quantity(session, quote_r, message)

        elif session.current_step == QuoteRequestEnum.REMARK.value:
            return await self._handle_remarks(session, quote_r, message)

        elif session.current_step == QuoteRequestEnum.COMPANY_NAME.value:
            return await self._handle_company_name(session, quote_r, message)

        elif session.current_step == QuoteRequestEnum.EMAIL.value:
            return await self._handle_user_email(session, quote_r, message)

        elif session.current_step == QuoteRequestEnum.ANOTHER_QUOTE_REQUEST.value:
            return await self._handle_again(session, quote_r, message)

        else:
            return await self.template_service.main_menu_template(session)


    async def _handle_vessel_name(self, session: SessionDB, quote_r: QuoteRequestDB, message: str) -> ResponsePayloadCollection:
        intent, err = self.ai_service.parse_name(message)
        if not intent or err:
            return await self.template_service.session_template(session, err)

        name = intent.get("name", None)

        if not name:
            return await self.template_service.session_template(session, "Enter the name please")

        await self.sql_db_service.create_event(Event.vessel_name_entered(
            user_id=session.user_id,
            payload={
                "status": "updated",
                "data": name if name else "undefined",
                "quote_r": quote_r.id,
            },
        ))

        quote_r.vessel_name = name
        n_quote, err = await self.sql_db_service.update_quote_request(quote_r)
        if err:
            return await self.template_service.session_template(session, "Could not continue. Administrator already noticed.")

        session, err = await self.navigation_handler.to_next_step(session)
        return await self.template_service.session_template(session, err_msg= err if err else None)

    async def _handle_vessel_imo(self, session: SessionDB, quote_r: QuoteRequestDB, message: str) -> ResponsePayloadCollection:
        intent, err = self.ai_service.parse_vessel_imo(message)
        if not intent or err:
            return await self.template_service.session_template(session, err)

        imo = intent.get("imo_number", None)
        if not imo and not quote_r.vessel_imo:
            return await self.template_service.session_template(session, "Enter the imo please")

        await self.sql_db_service.create_event(Event.vessel_imo_entered(
            user_id=session.user_id,
            payload={
                "status": "updated",
                "data": imo if imo else "undefined",
                "quote_r": quote_r.id,
            },
        ))

        quote_r.vessel_imo = str(imo)
        n_quote, err = await self.sql_db_service.update_quote_request(quote_r)
        if err:
            return await self.template_service.session_template(session, "Could not continue. Administrator already noticed.")

        session, err = await self.navigation_handler.to_next_step(session)
        return await self.template_service.session_template(session, err_msg=err if err else None)

    async def _handle_port_search(self, session: SessionDB, quote_r: QuoteRequestDB, message: str) -> ResponsePayloadCollection:
        intent, err = self.ai_service.parse_port_user_input(message)

        action = intent['action']
        if action == "update":
            return await self.update_port_suggestion(session, quote_r, intent)
        elif action == "confirm":
            return await self.confirm_port_suggestion(session, quote_r, intent)
        else:
            return await self._handle_unknown_intent(session, quote_r, intent)

    async def update_port_suggestion(self, session: SessionDB, quote_r: QuoteRequestDB, intent: dict) -> ResponsePayloadCollection:
        search_query = quote_r.data.port_search.query or ""
        port = quote_r.data.port_search.port or None
        ports = quote_r.data.port_search.ports or []

        if intent['type'] == 'name':
            search_query = intent['query']
            port, ports, err = self.sql_db_service.search_port_with_suggestions(intent['query'])
            t, err_t = await self.sql_db_service.create_event(Event.port_searched(
                user_id=session.user_id,
                payload={
                    "query": intent['query'],
                    "locode_found": port.locode if ports else "not found",
                    "route_id": str(quote_r.id),
                },
            ))

        elif intent['type'] == 'index':
            search_query = intent['index']
            new_candidate = utils.resolve_port_by_index(ports, intent['index'])
            if new_candidate:
                port = new_candidate
                candidate_found, suggestions, err = self.sql_db_service.search_port_with_suggestions(new_candidate.locode)
                ports = [candidate_found] + suggestions

        if port:
            nearby_bd, _ = await self.sql_db_service.search_ports_nearby(port.latitude, port.longitude, 10, 5000,)
            nearby_bd = nearby_bd or []

            all_ports = utils.merge_ports(
                [port],
                ports,
                nearby_bd,
            )

            missing_sizes = {
                p.locode for p in all_ports if p and p.port_size is None
            }
            if not port.port_size:
                missing_sizes.add(port.locode)

            if missing_sizes:
                searoute_ports = await self.fetch_ports_info(missing_sizes)
                updatable = [
                    p for p in searoute_ports.values() if p.size
                ]
                if updatable:
                    updated = await self.sql_db_service.bulk_upsert_ports(updatable)
                    utils.apply_sizes(all_ports + [port], updated)


            if port and all_ports:
                ports = [p for p in all_ports if p.locode != port.locode]

        ports = ports[:5]


        port_size_priority = {"large": 0, "small": 1, "tiny": 2, None: 3}
        ports.sort(key=lambda p: port_size_priority.get(p.port_size, 3))

        if port and len(ports) > 0:
            ports = [p for p in ports if p.locode != port.locode]

        quote_r.data.port_search.query = search_query
        quote_r.data.port_search.port = port
        quote_r.data.port_search.ports = ports

        quote_r, err = await self.sql_db_service.update_quote_request(quote_r)
        if err:
            return ResponsePayloadCollection(responses=[ResponsePayload(err=str(err))])

        return await self.template_service.single_port_suggestion_template(session, quote_r)

    async def confirm_port_suggestion(self, session: SessionDB, quote_r: QuoteRequestDB, intent: dict) -> ResponsePayloadCollection:

        port = quote_r.data.port_search.port or None
        ports = quote_r.data.port_search.ports or []

        if not port:
            return await self.template_service.single_port_suggestion_template(session, quote_r, "Find the port first")

        quote_r.port_id = port.id
        quote_r, err = await self.sql_db_service.update_quote_request(quote_r)
        if not port:
            return await self.template_service.single_port_suggestion_template(session, quote_r, "Could not save the quote")

        session, err = await self.navigation_handler.to_next_step(session)
        if not port:
            return await self.template_service.single_port_suggestion_template(session, quote_r, "Could not go to the next step")

        return await self.template_service.quote_eta(session, quote_r)


    async def _handle_eta(
            self,
            session,
            quote_r,
            message: str
    ):
        message = message.strip().lower()

        #if message in {"yes", "y"}:
        if self.ai_service.is_validation_positive(message):

            if not quote_r.eta_from or not quote_r.eta_to:
                return await self.template_service.quote_eta(
                    session,
                    quote_r,
                    "❌ ETA range not set."
                )

            session, err = await self.navigation_handler.to_next_step(session)

            if err:
                return await self.template_service.session_template(
                    session,
                    "❌ Could not continue."
                )

            fuels = []

            vls_fo, err = await self.sql_db_service.get_fuel_by_name("VLS FO")
            if not err and vls_fo:
                fuels.append(vls_fo)

            ls_mgo, err = await self.sql_db_service.get_fuel_by_name("MGO LS")
            if not err and ls_mgo:
                fuels.append(ls_mgo)

            port, err = await self.sql_db_service.get_port_by_id(quote_r.port_id)

            if err or not port:
                return await self.template_service.session_template(
                    session,
                    "<b>Port not found.</b>"
                )

            quote_r.fuels = await self.build_priced_port(
                port=port,
                fuels=fuels,
                price_date=datetime.today().date()
            )

            quote_r, _ = await self.sql_db_service.update_quote_request(quote_r)

            return await self.template_service.session_template(session)

        eta_from, eta_to, err = utils.parse_eta_range(message)

        if err:
            return await self.template_service.session_template(session=session, err_msg=err)

        if not eta_from or not eta_to:
            return await self.template_service.quote_eta(
                session,
                quote_r,
                "❌ Invalid ETA format. Use: Jan 15 - Jan 20"
            )

        today = datetime.today().date()

        if eta_from.date() < today:
            return await self.template_service.quote_eta(
                session,
                quote_r,
                "❌ ETA must be in the future."
            )

        quote_r.eta_from = eta_from
        quote_r.eta_to = eta_to

        quote_r, err = await self.sql_db_service.update_quote_request(quote_r)

        if err:
            return await self.template_service.quote_eta(
                session,
                quote_r,
                "❌ Could not save ETA."
            )

        return await self.template_service.quote_eta(session, quote_r)


    async def _handle_fuel_names(self, session: SessionDB, quote_r: QuoteRequestDB, message: str) -> ResponsePayloadCollection:

        fuels = []
        vls_fo, err = await self.sql_db_service.get_fuel_by_name("VLS FO")
        if not err and vls_fo:
            fuels.append(vls_fo)

        ls_mgo, err = await self.sql_db_service.get_fuel_by_name("MGO LS")
        if not err and ls_mgo:
            fuels.append(ls_mgo)


        intent, err = await self.ai_service.parse_fuel_selection_intent(message, fuels)
        if err or intent.get("status") == "failed":
            return await self.template_service.quote_fuels(session, quote_r, "Could not parse fuels. Please try again.")

        status = intent.get("status")
        if status == "update":
            return await self._update_fuels(session, quote_r, intent)
        elif status == "confirm":
            return await self._confirm_fuels(session, quote_r, intent)
        return await self._handle_unknown_intent(session, quote_r, intent)



    async def _update_fuels(self, session: SessionDB, quote_r: QuoteRequestDB, intent: Dict) -> ResponsePayloadCollection:
        fuels = []
        m = {}
        vls_fo, err = await self.sql_db_service.get_fuel_by_name("VLS FO")
        if not err and vls_fo:
            fuels.append(vls_fo)
            m[vls_fo.id] = vls_fo

        ls_mgo, err = await self.sql_db_service.get_fuel_by_name("MGO LS")
        if not err and ls_mgo:
            fuels.append(ls_mgo)
            m[ls_mgo.id] = ls_mgo

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

        t = []
        for id in list(uniq_fuel_id):
            f = m.get(id, None)
            if f:
                t.append(f)

        quote_r.fuels = [FuelData(fuel_name=f.name, quantity=0, price=0) for f in t]
        quote_r, err = await self.sql_db_service.update_quote_request(quote_r)
        return await self.template_service.session_template(session)


    async def _confirm_fuels(self, session:  SessionDB, quote_r: QuoteRequestDB, intent: Dict) -> ResponsePayloadCollection:
        if not quote_r.fuels:
            return await self.template_service.session_template(session, " <b> Please, select at least one fuel type. </b> ")

        port, err = await self.sql_db_service.get_port_by_id(quote_r.port_id)
        if not err and port:
            return await self.template_service.session_template(session, " <b> There is not ports somewhy. </b> ")

        p = await self.build_priced_port(port=port, fuels=quote_r.fuels, price_date=date.today())

        quote_r.fuels = p

        session, errr = await self.navigation_handler.to_next_step(session)

        return await self.template_service.session_template(session)



    async def _handle_fuel_quantity(self, session:  SessionDB, quote_r: QuoteRequestDB, message: str) -> ResponsePayloadCollection:

        intent, err = await self.ai_service.parse_fuel_quantity(message, quote_r.fuels)

        if err or intent.get("action") == "failed":
            return await self.template_service.quote_eta(session, quote_r, "tttt")

        action = intent.get("action")

        if action == "update":
            return await self._update_fuel_quantity(session, quote_r, intent)
        elif action == "confirm":
            return await self._confirm_fuel_quantity(session, quote_r, intent)
        else:
            return await self._handle_unknown_intent(session, quote_r, intent)


    async def _update_fuel_quantity(self,  session:  SessionDB, quote_r: QuoteRequestDB, intent: Dict) -> ResponsePayloadCollection:
        #source = {f.fuel_name : f for f in  intent.get("fuels", {})}
        # target = {f.fuel_name : f for f in quote_r.fuels}
        #
        #
        # for k, v in target.keys():
        #     f = source.get(k, None)
        #     if not f:
        #         continue
        #     v.quantity = f.quantity

        quote_r, err = await self.sql_db_service.update_quote_request(quote_r)
        return await self.template_service.session_template(session, err_msg=str(err) if err else None)


    async def _confirm_fuel_quantity(self, session:  SessionDB, quote_r: QuoteRequestDB, intent: Dict) -> ResponsePayloadCollection:
        for f in quote_r.fuels:
            if not f.quantity:
                return await self.template_service.session_template(session, err_msg="Please fill at least one fuel quantity!")

        session, err = await self.navigation_handler.to_next_step(session)
        return await self.template_service.session_template(session, err_msg=str(err) if err else None)


    async def _handle_remarks(self, session:  SessionDB, quote_r: QuoteRequestDB, message: str) -> ResponsePayloadCollection:
        intent, err = await self.ai_service.quote_remark(message)

        if err or intent.get("status") == "failed":
            return await self.template_service.session_template(session, "❌ Could not parse the date. Please try again.")


        if intent.get("action") == "update":
            return await self._update_remark(session, quote_r, intent)

        elif intent.get("action") == "confirm":
            return await self._confirm_remark(session, quote_r, intent)
        else:
            return await self._handle_unknown_intent(session, quote_r, intent)


    async def _update_remark(self,  session:  SessionDB, quote_r: QuoteRequestDB, intent: Dict) -> ResponsePayloadCollection:
        remark = intent.get("remark")

        if not remark:
            return await self.template_service.session_template(session, err_msg="I do not see any remark.")

        quote_r.remark = remark
        quote_r, err = await self.sql_db_service.update_quote_request(quote_r)
        return await self.template_service.session_template(session, err_msg=str(err) if err else None)


    async def _confirm_remark(self,  session:  SessionDB, quote_r: QuoteRequestDB, intent: Dict) -> ResponsePayloadCollection:
        session, err = await self.navigation_handler.to_next_step(session)
        return await self.template_service.session_template(session, err_msg=str(err) if err else None)

    async def _handle_company_name(self, session: SessionDB, quote_r: QuoteRequestDB, message: str) -> ResponsePayloadCollection:
        intent_dict, err = self.ai_service.parse_name(message)
        if err:
            return await self.template_service.session_template(session, err)

        if intent_dict.get("name", None) is not None:
            intent_dict['action'] = "update"

        intent = intent_dict.get("action")
        r = None
        if intent == "update":
            return await self._update_company_name(session, quote_r, intent_dict)
        elif intent == "confirm":
            return await self._confirm_company_name(session, quote_r, intent_dict)
        return await self.template_service.session_template(session, "Did not get what to do. Please try again.")

    async def _update_company_name(self, session: SessionDB, quote: QuoteRequestDB, intent_dict: Dict) -> ResponsePayloadCollection:
        name = intent_dict.get("name")
        if name:
            quote.company_name = name
        else:
            return await self.template_service.session_template(session, err_msg="I do not see any company name.")

        await self.sql_db_service.create_event(Event.company_name_entered(
            user_id=session.user_id,
            payload={
                "status": "updated",
                "route_id": str(quote.id),
                "data": name,
            },
        ))

        quote, err = await self.sql_db_service.update_quote_request(quote)
        if err or intent_dict.get("action") == "error":
            return await self.template_service.session_template(session, str(err))
        return await self.template_service.session_template(session)

    async def _confirm_company_name(self, session: SessionDB,  quote: QuoteRequestDB, intent_dict: Dict) -> ResponsePayloadCollection:
        err_messages = []

        if not quote.company_name:
            err_messages.append(f"{emoji.CROSS_RED} Add the company name please!")

        if len(err_messages) > 0:
            return await self.template_service.session_template(session, "\n".join(err_messages))

        session, err = await self.navigation_handler.to_next_step(session)
        return await self.template_service.session_template(session, )

    async def _handle_user_email(self, session: SessionDB, quote_r: QuoteRequestDB, message: str) -> ResponsePayloadCollection:
        intent_dict, err = self.ai_service.parse_user_email(message)
        if err:
            return await self.template_service.session_template(session, err)

        if intent_dict.get("email", None) is not None:
            intent_dict['action'] = "update"

        intent = intent_dict.get("action")
        if intent == "update":
            return await self._update_user_email(session, quote_r, intent_dict)
        elif intent == "confirm":
            return await self._confirm_user_email(session, quote_r, intent_dict)
        else:
            return await self.template_service.session_template(session, "Did not understand what to do. Try again please.")

    async def _update_user_email(self, session: SessionDB, quote_r: QuoteRequestDB, intent_dict: Dict) -> ResponsePayloadCollection:
        email = intent_dict.get("email", None)
        if not email:
            return await self.template_service.session_template(session, "Could not save your email.")

        await self.sql_db_service.create_event(Event.email_entered(
            user_id=session.user_id,
            payload={
                "status": "updated",
                "quote_id": str(quote_r.id),
                "email": email,
            },
        ))

        updated_user, err = await self.sql_db_service.update_user(str(session.user_id), {"email": email})
        if err or intent_dict.get("action") == "error":
            return await self.template_service.session_template(session, "Could not save your email.")

        return await self.template_service.session_template(session, )

    async def _confirm_user_email(self, session: SessionDB, quote_r: QuoteRequestDB, intent_dict: Dict) -> ResponsePayloadCollection:
        err_messages = []

        user, err = await self.sql_db_service.get_user_by_id(session.user_id)
        if err:
            err_messages.append(f"{emoji.CROSS_RED} Could not find your user record.")

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
                "quote_id": str(quote_r.id),
                "email": user.email,
            },
        ))

        fuels, err = await self.sql_db_service.get_available_fuels()
        if err:
            return await self.template_service.get_port_fuel_price_template(session, "❌ Could not fetch fuel types")

        port, err = await self.sql_db_service.get_port_by_id(quote_r.port_id)
        if err:
            return await self.template_service.get_port_fuel_price_template(session, "❌ Could not fetch port info.")

        prices = await self.port_fuel_price_service.get_port_fuel_prices(
            port,
            fuels,
            quote_r.eta_to.date(),
        )

        file_to_attach = await self.render_bukering_request_in_pdf(session, quote_r, prices)

        p1 = await self.template_service.quote_user_email(session, quote_r, True)
        if file_to_attach:
            p1.responses[-1].files.append(file_to_attach)

        await self.sql_db_service.create_event(Event.pdf_generated(
            user_id=session.user_id,
            payload={
                "quote_id": str(quote_r.id)
            },
        ))

        session, err = await self.navigation_handler.to_next_step(session)
        p2 = await self.template_service.session_template(session)

        p1.responses += p2.responses

        return p1

    async def render_bukering_request_in_pdf(self, session: SessionDB, quote: QuoteRequestDB, prices: List[MabuxPortFuelPriceDB]):
        user_db, err = await self.sql_db_service.get_user_by_id(session.user_id)
        if err:
            return

        html_content, html_content_bytes, file_obj, subject, images, image_data = await self.template_service.render_supplier_request(user_db, quote, prices)
        if user_db.email and utils.is_valid_email(user_db.email):
            ok, err = await self.email_sender.route_report(
                subject=subject,
                text=html_content,
                images=[image_data],
                pdf_bytes=html_content_bytes,
                to=user_db.email
            )

        return file_obj


    async def _handle_again(self,  session: SessionDB, quote: QuoteRequestDB, message: str):
        intent, err = self.ai_service.parse_yes_or_no(message)

        if not intent and err:
            return await self.template_service.session_template(session, str(err) if err else None)

        t1 = RouteTaskEnum.MAIN_MENU.value
        t2 = None

        if intent.get("action") == "confirm":
            t1 = RouteTaskEnum.SUPPLIER_REQUEST_CREATE.value
            t2 =  QuoteRequestEnum.VESSEL_NAME.value

        session, err = await self.sql_db_service.update_session(
            session.user_id,
            t1,
            t2,
            None,
            session.data
        )
        return await self.template_service.session_template(session, str(err) if err else None)

    # common methods to put in future in sharable module
    async def build_priced_port(
            self,
            port,
            fuels: list,
            price_date: datetime.date
    ) -> Optional[List[FuelData]]:
        async with asyncio.Semaphore(10):
            tasks = {
                fuel.name: self.find_fuel_price(
                    port,
                    fuel.name,
                    price_date,
                )
                for fuel in fuels
            }

            prices = await asyncio.gather(*tasks.values())

            fuels = []
            for fuel_name, price in zip(tasks.keys(), prices):
                fuels.append(
                    FuelData(fuel_name=fuel_name, price=price, quantity=0)
                )

            return fuels


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

    async def get_port_info_limited(self, locode: str):
        await self.searoute_limiter.acquire()
        try:
            return await self.searoute_api.get_port_info(locode)
        finally:
            self.searoute_limiter.release()


    async def _handle_unknown_intent(self, *args, **kwargs) -> ResponsePayloadCollection:
        return ResponsePayloadCollection(
            responses=[
                ResponsePayload(
                    text="Sorry, I didn't understand that. Please try again."
                )
            ]
        )



    # ========================================================== LIST HANDLING

