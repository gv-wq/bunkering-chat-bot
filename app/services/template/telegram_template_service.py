import base64
import io
import os

import uuid
from datetime import datetime, timedelta
from typing import Optional, List, Tuple, Dict

from html import escape
import pandas as pd
import matplotlib.pyplot as plt
from requests import session

from app.data import emogye
from app.data.dto.main.BunkeringStep import BunkeringStep
from app.data.dto.main.DepartureToDestinationCoordinatesPath import DepartureToDestinationCoordinatesPath
from app.data.dto.main.SeaPort import SeaPortDB
from app.data.dto.main.SeaRoute import SeaRouteDB
from app.data.dto.main.Session import SessionDB
from app.data.dto.main.User import UserDB
from app.data.dto.main.UserTariff import UserTariffBD
from app.data.dto.messenger.ResponsePayload import (
    ResponsePayload,
    ResponsePayloadCollection, MediaFile, MediaImage,
)
from app.data.enums.RouteStep import RouteStepEnum
from app.data.enums.RouteTask import RouteTaskEnum
from app.data.enums.search_route_enum import SearchRouteStepEnum
from app.handlers.navigation_handler import NavigationHandler
from app.services.db_service import DbService
from app.services.internal_api.map_builder_api import MapBuilderApi
from app.services.utils import utils

UNKNOWN = "—"
MARK = "✔️"
YELLOW_ALERT = "⚠️"
PRICE_ON_REQUEST = "Price on request"
from weasyprint import HTML
from io import BytesIO
from jinja2 import Environment, FileSystemLoader, select_autoescape
env = Environment(
    loader=FileSystemLoader(os.getcwd() + "/app/services/template/templates"),
    autoescape=select_autoescape(["html", "xml"])
)

class TemplateService:
    def __init__(self, sql_db: DbService, navigation_handler: NavigationHandler, map_image_api: MapBuilderApi):
        self.sql_db = sql_db
        self.navigation_handler = navigation_handler
        self.map_image_api = map_image_api
        self.MAX_MSG_LEN = 700  # example, set you

    async def session_template(self, session: SessionDB, err_msg: Optional[str] = None, is_admin: bool = None) -> ResponsePayloadCollection:

        if session.current_task == RouteTaskEnum.MAIN_MENU.value:
            return await self.main_menu_template(session, err_msg, is_admin)
        elif session.current_task == RouteTaskEnum.CREATE_ROUTE.value:
            return await self.get_create_route_template(session=session, err_msg=err_msg)
        elif session.current_task == RouteTaskEnum.GET_PORT_PRICE.value:
            return await self.get_port_fuel_price_template(session=session, message=err_msg)
        elif session.current_task == RouteTaskEnum.SEARCH_ROUTE.value:
            if session.current_step == SearchRouteStepEnum.CONFIRM_DELETE.value:
                return ResponsePayloadCollection(
                responses=[ResponsePayload(
                    text=" <b>Are you sure?\n1. Yes\n0. Cancel\n </b> ",
                    keyboard=self.navigation_handler.get_yes_no_keyboard()
                )]
            )
            return await self.search_route_template(session=session, message=err_msg)

        elif session.current_task == RouteTaskEnum.ADMIN.value:
            return await self.list_users_template(session=session, message=err_msg)

        return ResponsePayloadCollection(
            responses=[
                ResponsePayload(text="Ouch!. Something went wrong.", keyboard=None)
            ]
        )


    async def get_create_route_template(self, session: SessionDB, err_msg: Optional[str] = None):
        route, err = await self.sql_db.get_or_create_route(session)
        if err:
            return ResponsePayload(err=err, keyboard=None)

        current_step = session.current_step

        if current_step in [RouteStepEnum.DEPARTURE_PORT_SUGGESTION.value, RouteStepEnum.DESTINATION_PORT_SUGGESTION.value]:
            return await self.port_suggestions_template(session, route, err_msg)

        # elif current_step in [RouteStepEnum.DEPARTURE_PORT_NEARBY.value, RouteStepEnum.DESTINATION_PORT_NEARBY.value]:
        #     return await self.port_nearby_template(session, route, err_msg)

        elif current_step == RouteStepEnum.DEPARTURE_DATE.value:
            return await self.departure_date_template(session, route, err_msg)

        elif current_step == RouteStepEnum.AVERAGE_SPEED.value:
            return await self.average_speed_template(session, route, err_msg)

        elif current_step == RouteStepEnum.FUEL_SELECTION.value:
            return await self.fuel_selection_template(session, route, err_msg)

        elif current_step == RouteStepEnum.ROUTE_PORT_LIST.value:
            return await self.build_universal_bunkering_template(session, route, err_msg)

        elif current_step ==  RouteStepEnum.BUNKERING_QUEUE.value:
            return await self.build_universal_bunkering_template(session, route, err_msg)

        elif current_step == RouteStepEnum.PDF_REQUEST.value:
            return await self.pdf_request_template(session, route, err_msg)

        elif current_step == RouteStepEnum.VESSEL_NAME.value:
            return await self.vessel_name_template(session, route, err_msg)

        elif current_step == RouteStepEnum.VESSEL_IMO.value:
            return await self.vessel_imo_template(session, route, err_msg)

        elif current_step == RouteStepEnum.USER_EMAIL.value:
            return await self.user_email_template(session=session, route=route, message=err_msg)

        elif current_step == RouteStepEnum.SUPPLIER_PRICES.value:
            return await self.supplier_prices_template(session, route, err_msg)

        elif current_step == RouteStepEnum.COMPANY_NAME.value:
            return await self.company_name_template(session, route, err_msg)
        else:
            return await self._handle_unknown_intent(session, route, err_msg)

    async def _handle_unknown_intent(self, *args, **kwargs) -> ResponsePayloadCollection:
        return ResponsePayloadCollection(responses=[ResponsePayload(text="Sorry, I didn't understand that. Please try again.")])


    async def get_new_route_header(self, session: SessionDB, route: SeaRouteDB, add_lines: List[str] = None, update_status: bool = False):


        title = self.navigation_handler.get_step_title(session.current_step, route.data.is_updating)
        departure_port = None
        destination_port = None
        is_updating = route.data.is_updating

        #if route.data.port_selection.departure_candidate:
        if route.departure_port_id:
            #departure_port = route.data.port_selection.departure_candidate
            departure_port, dep_err =  await self.sql_db.get_port_by_id(route.departure_port_id)

        #if route.data.port_selection.destination_candidate:
        if route.destination_port_id:
            destination_port, dest_err = await self.sql_db.get_port_by_id(route.destination_port_id)
            #destination_port = route.data.port_selection.destination_candidate

        lines = [title, ""]

        if route.vessel_name:
            if is_updating and session.current_step == RouteStepEnum.VESSEL_NAME.value:
                lines.append(f"{emogye.PLAY}  <b>Vessel name (current):</b>  {route.vessel_name}")
            else:
                lines.append(f" <b>Vessel name:</b>  {route.vessel_name}")

        if route.imo_number:
            if is_updating and session.current_step == RouteStepEnum.VESSEL_IMO.value:
                lines.append(f"{emogye.PLAY}  <b>IMO number (current):</b> {route.vessel_name}")
            else:
                lines.append(f" <b>IMO number:</b> {route.imo_number}")

        if add_lines:
            lines.extend(add_lines)

        if departure_port:
            dep_db, err = await self.sql_db.get_port_by_locode(departure_port.locode)
            if dep_db and not err:
                departure_port = dep_db

            if is_updating and session.current_step ==  RouteStepEnum.DEPARTURE_PORT_SUGGESTION.value:
                lines.append("\n" + departure_port.format_port(True, True) + "\n")
            else:
                lines.append("\n" + departure_port.format_port(True))

        if destination_port:
            dest_db, err = await self.sql_db.get_port_by_locode(destination_port.locode)
            if dest_db and not err:
                destination_port = dest_db

            if is_updating and session.current_step == RouteStepEnum.DESTINATION_PORT_SUGGESTION.value:
                lines.append("\n" + destination_port.format_port(False, True) + "\n")
            else:
                lines.append("\n" +  destination_port.format_port(False) + "\n")

        if route.departure_date:
            if is_updating and session.current_step == RouteStepEnum.DEPARTURE_DATE.value:
                lines.append(f"{emogye.PLAY} <b>Departure date (current):</b> {route.departure_date.strftime('%B %d, %Y')}")
            else:
                lines.append(f" <b>Departure date:</b> {route.departure_date.strftime('%B %d, %Y')}")

        if route.average_speed_kts:
            if is_updating and session.current_step == RouteStepEnum.AVERAGE_SPEED.value:
                lines.append(f"{emogye.PLAY}  <b>Avg.speed (current):</b> {route.average_speed_kts} knots")
            else:
                lines.append(f" <b>Avg. speed:</b> {route.average_speed_kts} knots")

        lines.append(" ")
        return "\n".join(lines)

    async def get_show_route_header(self, route: SeaRouteDB, add_lines: List[str] = None):

        departure_port = None
        destination_port = None

        # if route.data.port_selection.departure_candidate:
        if route.departure_port_id:
            # departure_port = route.data.port_selection.departure_candidate
            departure_port, dep_err = await self.sql_db.get_port_by_id(route.departure_port_id)

        # if route.data.port_selection.destination_candidate:
        if route.destination_port_id:
            destination_port, dest_err = await self.sql_db.get_port_by_id(route.destination_port_id)
            # destination_port = route.data.port_selection.destination_candidate

        lines = [f"{emogye.ANCHOR} New route - From {departure_port.locode if departure_port else ''} to {destination_port.locode if destination_port else ''}"]

        if add_lines:
            lines.extend(add_lines)

        if departure_port:
            dep_db, err = await self.sql_db.get_port_by_locode(departure_port.locode)
            if dep_db and not err:
                departure_port = dep_db

            lines.append("\n" + departure_port.format_port(True))

        if destination_port:
            dest_db, err = await self.sql_db.get_port_by_locode(destination_port.locode)
            if dest_db and not err:
                destination_port = dest_db

            lines.append("\n" + destination_port.format_port(False) + "\n")

        if route.departure_date:
            lines.append(f"Departure date: {route.departure_date.strftime('%B %d, %Y')}")

        if route.average_speed_kts:
            lines.append(f"Avg. speed: {route.average_speed_kts} knots")

        if route.vessel_name:
            lines.append(f"Vessel name: {route.vessel_name}")

        if route.imo_number:
            lines.append(f"IMO number: {route.imo_number}")

        lines.append(" ")
        return "\n".join(lines)

    async def main_menu_template(
        self, session: SessionDB, message: str = None, is_admin: bool = False, new_user: bool = False
    ) -> ResponsePayloadCollection:

        text = self.navigation_handler.get_main_menu(is_admin, new_user)

        if message:
            text = f"{message}\n\n{text}"

        return ResponsePayloadCollection(responses=[ResponsePayload(text=text, keyboard=self.navigation_handler.get_main_menu_keyboard(session))])

    #
    #
    # async def port_nearby_template(self, session: SessionDB, route: SeaRouteDB, message: Optional[str] = None):
    #     candidate = None
    #     is_departure = True
    #     is_suggestion = False
    #     if session.current_step == RouteStepEnum.DEPARTURE_PORT_NEARBY.value:
    #         prompt = "Enter departure port name."
    #         candidate = route.data.port_selection.departure_candidate
    #         nearby = route.data.port_selection.departure_nearby or []
    #         port_arrow = emogye.ARROW_UP
    #         port_color = "blue"
    #         is_departure = True
    #         #nearby_image = route.departure_nearby_image
    #     else:
    #         prompt = "Enter destination port name."
    #         candidate = route.data.port_selection.destination_candidate
    #         nearby = route.data.port_selection.destination_nearby or []
    #         port_arrow = emogye.ARROW_DOWN
    #         port_color = "red"
    #         is_departure = False
    #
    #
    #         #nearby_image = route.destination_nearby_image
    #
    #     images = []
    #
    #     nav = self.navigation_handler.get_navigation_text(session)
    #     map_link = self.map_image_api.get_search_port_map_link(str(session.route_id), is_departure, is_suggestion)
    #     header = await self.get_new_route_header(session, route)
    #     # Build base top lines
    #     top = [header]
    #
    #     if route.data.is_updating:
    #         top.append("Waiting for update...")
    #
    #     add_lines = []
    #     if candidate:
    #         top.append(candidate.format_port(is_departure))
    #         top.append(f"\nWrite yes(y), confirm when port is correct")
    #         top.append(f"Or enter new name")
    #         top.append(f"Or choose from list (e.g. 1, 2, 3).")
    #     else:
    #         top.append(prompt)
    #
    #
    #     if message:
    #         top.append("")
    #         top.append(message)
    #     #if len(nearby) > 0:
    #         #top.append("")
    #         #top.append("Options:")
    #     top.append("")
    #
    #
    #
    #     # --------------------- BUILD IMAGE -----------------------------
    #     indexed = []
    #     if candidate:
    #         indexed.append(candidate.to_indexed2(port_arrow, port_color, "medium", True))
    #
    #     for i, port in enumerate(nearby, 1):
    #         indexed.append(port.to_indexed2(str(i), "orange", "medium", False))
    #
    #     images_generated = await self.map_image_api.render_map_images([], indexed, True)
    #     images.extend(images_generated)
    #
    #     responses = []
    #
    #     def chunks(lst, size):
    #         for i in range(0, len(lst), size):
    #             yield lst[i:i + size]
    #
    #     counter = 1
    #     if nearby:
    #         nearby_chunks = list(chunks(nearby, 7))
    #
    #
    #         if len(nearby_chunks) > 0:
    #             first_lines = top + ["Nearby ports:"]
    #             for i, p in enumerate(nearby_chunks[0], 1):
    #                 first_lines.append(p.format_indexed(counter))
    #                 #first_lines.append(f"{counter}. {p.port_name} - {p.country_name} - {p.locode} {"(" + p.port_size  + ")"  if p.port_size else  "(unknown size)\n"}")
    #                 counter += 1
    #
    #             if counter == len(nearby) + 1:
    #                 first_lines.append(f"\n\n{emogye.PLANET} On map:\n" + map_link)
    #                 first_lines.append(nav)
    #
    #             #images = [img for img in [nearby_image] if img]
    #             responses.append(
    #                 ResponsePayload(
    #                     text="\n".join(first_lines),
    #                     images=images,
    #                 )
    #             )
    #
    #         for chunk in nearby_chunks[1:]:
    #             lines = [] #["Nearby ports:"]
    #             for p in chunk:
    #                 lines.append(p.format_indexed(counter))
    #                 #lines.append(f"{counter}. {p.port_name} - {p.country_name} - {p.locode} {"(" + p.port_size  + ")" if p.port_size else  "(unknown size)\n"}")
    #                 counter += 1
    #
    #             if counter == len(nearby) + 1:
    #                 lines.append(f"\n\n{emogye.PLANET} On map:\n" + map_link)
    #                 lines.append(nav)
    #
    #             responses.append(ResponsePayload(text="\n".join(lines)))
    #
    #
    #     else:
    #
    #         responses.append(
    #             ResponsePayload(
    #                 text="\n".join(top) +  "\nI couldn’t find any large ports nearby. Please go back and enter a nearby major port if needed. Thanks!\n" +  f"\n{emogye.PLANET} On map:\n" + map_link + nav,
    #                 images=images,
    #             )
    #         )
    #
    #
    #     return ResponsePayloadCollection(responses=responses)

    async def departure_date_template(self, session: SessionDB, route: SeaRouteDB, message: Optional[str] = None) -> ResponsePayloadCollection:
        lines = []

        if route.data.is_updating:
            lines.append(f"\n{emogye.THIS} Waiting for new departure date...\n")

        lines.extend([
            f"\n{emogye.THIS}  <b> Confirm or enter new date. </b> \n" if route.departure_date else f"\n{emogye.THIS}  <b> Departure date? </b> \n",
        ])
        if message:
            lines.append(f"Note: {message}")

        #if not route.departure_date:
        lines.extend(
                [
               #     "\n",
            "Like:",
             f"{(datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d')} (YYYY-MM-DD)",
          #  "2025 January 15",
          #  "25 1 15 (YY M D)",
            "15 Jan 2025",
            "15 Jan",
            "Jan 15"
           # "January 15, 2025",
                ]
            )

        text = "\n".join(lines)



        header_text = await self.get_new_route_header(session, route)
        navigation_text = self.navigation_handler.get_navigation_text(session)
        text = header_text + text + navigation_text
        #text = header_text + navigation_text

        return ResponsePayloadCollection(responses=[ResponsePayload(text=text, keyboard=self.navigation_handler.get_navigation_keyboard(session.current_step))])

    async def average_speed_template(self, session: SessionDB, route: SeaRouteDB, message: Optional[str] = None) -> ResponsePayloadCollection:

        lines = []

        #if route.data.is_updating:
        #   lines.append(f"\n Waiting for avg. speed value...\n")

        if route.average_speed_kts:
            lines.append(f"\n{emogye.THIS} <b>Enter new or confirm with yes(y). </b> \n")
        else:
            lines.append(f"\n{emogye.THIS} <b>Enter vessel avg. speed in knots. </b> ")

        if message:
            lines.append(f"Note: {message}")

        header_text = await self.get_new_route_header(session, route)
        navigation_text = self.navigation_handler.get_navigation_text(session)
        text = header_text + "\n".join(lines) + navigation_text

        keyboard = self.navigation_handler.get_navigation_keyboard(session.current_step)


        return ResponsePayloadCollection(responses=[ResponsePayload(text=text, keyboard=keyboard)])


    async def fuel_selection_template(self, session: SessionDB, route: SeaRouteDB, err_msg: Optional[str] = None) -> ResponsePayloadCollection:
        lines = []

        if route.data.is_updating:
            lines.append("\nWaiting for new departure date...\n")

        lines.extend([
            f"\n{emogye.THIS}  <b> Please confirm with yes(y) or choose again (e.g. 1, 2): </b> \n"
        ])

        if err_msg:
            lines.extend([err_msg, '\n'])

        available_fuels = []

        f, err = await self.sql_db.get_fuel_by_name("VLS FO")
        if not err and f:
            available_fuels.append(f)

        f, err = await self.sql_db.get_fuel_by_name("MGO LS")
        if not err and f:
            available_fuels.append(f)

        user_fuel_names = set([f.name for f in route.fuels])

        for i, fuel in enumerate(available_fuels, 1):
            postfix =  emogye.CHECK_GRAY if fuel.name in user_fuel_names else ""
            lines.append(f"{i}. {fuel.name} {postfix}")

        #lines.append("\nWhen done, enter fine, yes(y)\n")

        body_text = "\n".join(lines)
        header_text = await self.get_new_route_header(session, route)
        navigation_text = self.navigation_handler.get_navigation_text(session)

        text = header_text + body_text + navigation_text
        return ResponsePayloadCollection(responses=[ResponsePayload(text=text,keyboard=self.navigation_handler.get_navigation_keyboard())])


    def format_port_block(self, step: BunkeringStep, index):
        """Return a full port block: header + all fuels."""
        p = step.port
        mark = emogye.CHECK_GREEN_BACKGROUND if step.selected else emogye.CROSS_GRAY

        lines = [
            f"{index}. [{mark}] {p.port_name} - {p.country_name} - {p.locode}",
            f"     Agent required: {'Yes' if step.agent_required else 'No'}"
        ]

        for fuel_name, info in step.fuel_info.items():
            qty = info.get("quantity") or "—"
            price = info.get("fuel_price") or PRICE_ON_REQUEST
           # mobux = " (MABUX)" if info.get("mobux_price_status") else ""
            lines.append(f"     {fuel_name}: qty={qty}, price={price}")

        lines.append("")  # separator
        return "\n".join(lines)

    def chunk_by_whole_ports(self, port_blocks, msg_limit):
        """
        Each port block stays atomic.
        Build messages not exceeding msg_limit.
        """
        chunks = []
        current = []

        current_len = 0

        for block in port_blocks:
            block_len = len(block)

            # If a block alone exceeds limit — still put it alone
            if block_len > msg_limit:
                if current:
                    chunks.append("\n".join(current))
                    current = []
                    current_len = 0

                chunks.append(block)
                continue

            # If adding this block exceeds the limit → start new message
            if current and current_len + block_len > msg_limit:
                chunks.append("\n".join(current))
                current = [block]
                current_len = block_len
            else:
                current.append(block)
                current_len += block_len

        if current:
            chunks.append("\n".join(current))

        return chunks

    async def build_universal_bunkering_template(self, session: SessionDB, route: SeaRouteDB, message: Optional[str] = None) -> ResponsePayloadCollection:
        header = await self.get_new_route_header(session, route)
        mode = session.current_step


        steps = []
        images = []

        any_selected = any([s.selected for s in route.bunkering_steps])
        show_remove_status = True if any_selected else False
        no_ports_err = "\nNo ports available."

        # -------- Determine steps --------
        if mode == RouteStepEnum.ROUTE_PORT_LIST.value and not any_selected:
            steps = [s for s in route.bunkering_steps if s.to_show]

        else:
            steps = [s for s in route.bunkering_steps if s.selected]
            no_ports_err = "\n <b> No ports were selected. Go back and select at least one. </b> "



        # --------------------- BUILD IMAGE -----------------------------
        indexed = []
        departure_candidate = route.data.port_selection.departure_candidate
        destination_candidate = route.data.port_selection.destination_candidate

        if departure_candidate:
            indexed.append(departure_candidate.to_indexed2(emogye.ARROW_UP, "blue", "medium", True))

        if destination_candidate:
            indexed.append(destination_candidate.to_indexed2(emogye.ARROW_DOWN, "red", "medium", True))

        for i, step in enumerate(steps, 1):
            color = "gray"

            if step.selected:
                color = "orange"

            if step.marked:
                color = "green"

            indexed.append(step.port.to_indexed2(str(i), color, "medium", False))

        image, image_err = await self.map_image_api.render_map(route.data.departure_to_destination_coordinates, indexed)
        if image and not image_err:
            images.append(MediaImage(content=image))
            # with open("f.png", "wb") as fp:
            #     fp.write(image)

        route_map_link = self.map_image_api.get_route_map_link(str(route.id))

        if not steps:
            return ResponsePayloadCollection(
                responses=[
                    ResponsePayload(
                        text=header + no_ports_err,
                        images=images#[route.map_image_bytes] if route.map_image_bytes  else []
                    )
                ]
            )
        # ports = [s.port for s in steps]
        # coordinates = route.data.departure_to_destination_coordinates
        # map_image_response, map_image_err = await self.map_image_api.build_map_image(coordinates, ports)
        # images = []
        # if not map_image_err:
        #     image_err = map_image_response.get("error", True)
        #     if not image_err:
        #         map_image_bytes = eval(map_image_response.get("image_bytes"))
        #         images.append(map_image_bytes)


        # -------- Format full port blocks (atomic units!) --------
        #port_blocks = [self.format_port_block(step, step.n) for step in steps]
        port_blocks = [s.format_port_block() for s in steps]

        max_len = self.MAX_MSG_LEN - 150 if mode == RouteStepEnum.ROUTE_PORT_LIST.value else self.MAX_MSG_LEN - 150
        # -------- Chunk messages by whole-port blocks --------
        port_chunks = self.chunk_by_whole_ports(port_blocks, max_len)

        responses = []

        # -------- FIRST MESSAGE --------
        first = [header]

        if message:
            first.extend([message, '\n'])

        # Mode instructions
        if mode == RouteStepEnum.ROUTE_PORT_LIST.value:
            first.append(f"{emogye.THIS}  <b> Select ports with 1, 2, 3 - 5\nOr confirm all (yes/y). </b> ")

            if show_remove_status:
                first.append(" <b> To remove ports from the list, use: </b> ")
                first.append(" <b> remove 1, 2, 3 - 5 </b> ")

            first.append(f"\n{emogye.STAR} - cheapest port.")
            first.append(f"{emogye.CHECK_GRAY} - selected port.")

        else:
            first.append(f"{emogye.NOTE_THIS}  <b> Enter quantities per port in this format:")
            first.append("port_number fuel1 fuel2")
            first.append("Separate ports with /")
            first.append("Example: 1 200 100 / 4 500 10 </b> ")
            first.append("")
            #first.append("Enter yes, fine or done when approved")

        if len(port_chunks) > 0:
            first.append("\nBunkering steps:")
            first.append(port_chunks[0])
        else:
            first.append("\nNo bunkering steps to show.")

        responses.append(
            ResponsePayload(
                text="\n".join(first),
                images=images#[route.map_image_bytes ] if route.map_image_bytes  else []
            )
        )

        # -------- MIDDLE CHUNKS (if any) --------
        for chunk in port_chunks[1:-1]:
            responses.append(ResponsePayload(text=chunk))


        # -------- LAST CHUNK — with final ports + cost + navigation --------
        last_parts = []

        if len(port_chunks) > 1:
            last_parts.append(port_chunks[-1])

        # ----- COST SUMMARY -----
        if mode == RouteStepEnum.BUNKERING_QUEUE.value:
            fuel_totals = {}
            total_cost = 0

            for step in steps:
                if not step.selected:
                    continue

                for fuel_name, info in step.fuel_info.items():
                    qty = info.get("quantity") or 0
                    price = info.get("fuel_price") or 0
                    cost = qty * price

                    total_cost += cost

                    if fuel_name not in fuel_totals:
                        fuel_totals[fuel_name] = {"qty": 0, "cost": 0}

                    fuel_totals[fuel_name]["qty"] += qty
                    fuel_totals[fuel_name]["cost"] += cost

            summary = [#"Estimated cost summary:",

                       "", f" <b> Estimated cost: </b>  ${total_cost:,.0f}",]
            preferred_order = ["VLS FO", "MGO LS"]
            all_fuels_set = set(fuel_totals.keys())

            ordered_fuels = []

            # preferred fuels first
            for fuel in preferred_order:
                if fuel in all_fuels_set:
                    ordered_fuels.append(fuel)

            # remaining fuels alphabetically
            remaining_fuels = sorted(f for f in all_fuels_set if f not in preferred_order)
            ordered_fuels.extend(remaining_fuels)

            fuel_info = {fuel: fuel_totals[fuel] for fuel in ordered_fuels}

            for f, t in fuel_info.items():
                if t["cost"]:
                    summary.append(f"{f}: {t['qty']:.2f} mt — ${t['cost']:,.0f}")
                else:
                    summary.append(f"{f}: {t['qty']:.2f} mt — $0 (on request)")

            summary.append("")
            #summary.append("Submit inquiry? Y/N")

            last_parts.append("\n".join(summary))

        # --- Navigation last ---

        last_parts.append(f"\n{emogye.PLANET} On map: \n" + route_map_link)
        last_parts.append( self.navigation_handler.get_navigation_text(session))

        responses.append(ResponsePayload(text="\n".join(last_parts), keyboard=self.navigation_handler.get_navigation_keyboard(session.current_step)))

        return ResponsePayloadCollection(responses=responses)

    def chunk_atomic_blocks(self, blocks, max_len):
        chunks = []
        current = []
        cur_len = 0

        for block in blocks:
            blen = len(block)

            # oversized — send alone
            if blen > max_len:
                if current:
                    chunks.append("".join(current))
                    current = []
                    cur_len = 0

                chunks.append(block)
                continue

            # adding this block exceeds the limit
            if current and cur_len + blen > max_len:
                chunks.append("".join(current))
                current = [block]
                cur_len = blen
            else:
                current.append(block)
                cur_len += blen

        if current:
            chunks.append("".join(current))

        return chunks

    def split_blocks(self, blocks, max_len):
        chunks = []
        current = []
        cur_len = 0

        for block in blocks:
            blen = len(block)

            # single block too large
            if blen > max_len:
                if current:
                    chunks.append("".join(current))
                    current, cur_len = [], 0
                chunks.append(block)
                continue

            if cur_len + blen > max_len:
                chunks.append("".join(current))
                current = [block]
                cur_len = blen
            else:
                current.append(block)
                cur_len += blen

        if current:
            chunks.append("".join(current))

        return chunks


    async def port_suggestions_template(self, session: SessionDB, route: SeaRouteDB, message: Optional[str] = None):
        # ---------------------- STEP SELECTION ----------------------
        is_departure = True
        is_suggestion = True
        if session.current_step == RouteStepEnum.DEPARTURE_PORT_SUGGESTION.value:
            candidate = route.data.port_selection.departure_candidate
            suggestions = route.data.port_selection.departure_suggestions
            prompt = f"\n{emogye.THIS}  <b> Type yes(y) to confirm if port is correct</b>\n       <b>or Enter new name</b>\n       <b>Or Choose from list (e.g. 1, 2, 3). </b> " if candidate else f"{emogye.THIS}  <b>What’s your departure port?</b> "
            port_arrow = emogye.ARROW_UP
            port_color = "purple"

        else:
            candidate = route.data.port_selection.destination_candidate
            suggestions = route.data.port_selection.destination_suggestions
            prompt = f"\n{emogye.THIS}  <b> Type yes(y) to confirm if port is correct</b>\n       <b>or Enter new name</b>\n       <b>Or Choose from list (e.g. 1, 2, 3).</b> " if candidate else f"{emogye.THIS}  <b>What’s your destination port?</b> "

            port_arrow = emogye.ARROW_DOWN
            port_color = "purple"
            is_departure = False


        images = []
        header = await self.get_new_route_header(session, route)
        nav = self.navigation_handler.get_navigation_text(session)
        map_link = self.map_image_api.get_search_port_map_link(str(route.id), is_departure, is_suggestion)

        top = [header,]


        if route.data.is_updating:
            top.append("Waiting for new port name or index...\n")

        if candidate:
            top.append(candidate.format_port(is_departure))
            #top.append(f"\nWrite yes(y), confirm when port is correct")
            #top.append(f"Or Enter new name")
            #top.append(f"Or Choose from list (e.g. 1, 2, 3).")

            #top.append("Enter yes(y), confirm when port is correct.")
        #else:
        top.append(prompt)

        # if suggestions:
        #     top.append("Or select")
        if message:
            top.extend(["", message])


        # ---------------------- NO SUGGESTIONS ----------------------
        if not suggestions:
            return ResponsePayloadCollection(
                responses=[
                    ResponsePayload(
                        text="\n".join(top) + nav,
                        images=images,
                        keyboard=self.navigation_handler.get_navigation_keyboard(session.current_step)
                    )
                ]
            )


        # --------------------- BUILD IMAGE -----------------------------
        indexed = []

        if candidate:
            indexed.append(candidate.to_indexed2(port_arrow, port_color, "medium", True))

        for i, port in enumerate(suggestions, 1):
            indexed.append(port.to_indexed2(str(i), "orange", "medium", False))

        images_generated = await self.map_image_api.render_map_images([], indexed, True)
        images.extend([MediaImage(content=content) for content in images_generated])

        # ---------------------- BUILD ATOMIC BLOCKS ----------------------
        global_counter = 1
        blocks = []

        for p in suggestions:
            blocks.append(p.format_indexed(global_counter))
            global_counter += 1

        # ---------------------- CHUNKING ----------------------

        header = "\n".join(top) + "\n\nSelect from:\n" if len(suggestions) > 0 else "I couldn’t find this port.\n Please try again or enter a nearby major port."
        first_limit = self.MAX_MSG_LEN - len(header)

        responses = []

        # ---------- FIRST MESSAGE ----------
        first_blocks = self.split_blocks(blocks, first_limit)

        responses.append(
            ResponsePayload(
                text=header + first_blocks[0],
                images=images,
                keyboard=None
            )
        )

        # ---------- MIDDLE ----------
        for chunk in first_blocks[1:]:
            responses.append(ResponsePayload(text=chunk))

        # ---------- LAST ----------
        # responses.append(
        #     ResponsePayload(
        #         text=first_blocks[-1] + "\nOn map:\n" + map_link + nav
        #     )
        # )

        responses[-1].text +=  "\nOn map:\n" + map_link + nav
        responses[-1].keyboard = self.navigation_handler.get_navigation_keyboard(session.current_step)

        return ResponsePayloadCollection(responses=responses)

    def split_text_chunks(self, lines: list[str], footer: str = "") -> list[str]:
        chunks = []
        current = []

        def cur_len():
            return len("\n".join(current)) + (len(footer) if footer else 0)

        for line in lines:
            if cur_len() + len(line) + 1 > self.MAX_MSG_LEN:
                chunks.append("\n".join(current))
                current = [line]
            else:
                current.append(line)

        if current:
            chunks.append("\n".join(current))

        if footer and chunks:
            chunks[-1] += "\n" + footer

        return chunks

    def format_route_block(self, index: int, route, dep_port, dest_port) -> str:
        if dep_port and dest_port:
            f_p = dep_port.format_port()
            t_p = dest_port.format_port()
            title = f"{index})\n{f_p} →\n{t_p}"
        else:
            title = f"{index}) Route"

        return "\n".join([
            "━━━━━━━━━━━━━━",
            title,
            f"Departure date: {route.departure_date.strftime('%Y-%m-%d') if route.departure_date else UNKNOWN}",
            f"Speed: {route.average_speed_kts or UNKNOWN} kn",
            "",
            f"{emogye.PLANET} Map:",
            self.map_image_api.get_route_map_link(str(route.id)),
            "",
        ])

    def split_route_blocks(self, blocks: list[str], max_per_msg: int, max_len: int):
        chunks = []
        current = []
        current_len = 0

        for block in blocks:
            if (
                    len(current) >= max_per_msg
                    or current_len + len(block) > max_len
            ):
                chunks.append("\n".join(current))
                current = []
                current_len = 0

            current.append(block)
            current_len += len(block)

        if current:
            chunks.append("\n".join(current))

        return chunks

    async def search_route_template(
            self,
            session: SessionDB,
            message: Optional[str] = None
    ) -> ResponsePayloadCollection:

        search = session.data.route_search
        page_size = 5

        total, err = await self.sql_db.count_routes(str(session.user_id))
        search.total = total if total and not err else 0

        total = search.total or 0
        current_page = max(1, search.offset + 1) if search.offset else 1
        total_pages = max(1, (total + page_size) // page_size)

        # ---------------------- HEADER ----------------------
        header_lines = [
            f"{emogye.PIN} My routes",
         #   f"Departure date filter: {search.date.strftime('%B %d, %Y') if search.date else UNKNOWN}",
            "",
            f"{emogye.THIS}  <b> Choose from list (e.g. 1, 2, 3). </b> ",
        #    "To add the departure date filter, enter the date please.",
        ]

        if message:
            header_lines.extend(["", message])

        header = "\n".join(header_lines) + "\n\n"

        # ---------------------- BUILD ATOMIC ROUTE BLOCKS ----------------------
        route_blocks = []
        all_images = []
        global_counter = 1

        for route_id in search.ids:
            route, err = await self.sql_db.get_route_by_id(route_id)
            if err or not route:
                continue

            dep_port, _ = await self.sql_db.get_port_by_id(route.departure_port_id)
            dest_port, _ = await self.sql_db.get_port_by_id(route.destination_port_id)

            # ---- map markers ----
            indexed = []
            if dep_port:
                indexed.append(dep_port.to_indexed2(emogye.ARROW_UP, "green", "medium", True))
            if dest_port:
                indexed.append(dest_port.to_indexed2(emogye.ARROW_DOWN, "red", "medium", True))

            for step in route.bunkering_steps:
                if not step.selected:
                    continue
                color = "green" if step.marked else "blue"
                indexed.append(step.port.to_indexed2(str(step.n), color, "medium", False))

            images = await self.map_image_api.render_map_images(
                route.data.departure_to_destination_coordinates or [],
                indexed,
            )

            for i in images:
                all_images.append(MediaImage(content=i))

            route_blocks.append(
                self.format_route_block(global_counter, route, dep_port, dest_port)
            )
            global_counter += 1

        if not route_blocks:
            route_blocks.append(f"{YELLOW_ALERT} No routes found.\n")

        # ---------------------- CHUNKING ----------------------
        first_limit = self.MAX_MSG_LEN - len(header)

        chunks = self.split_route_blocks(
            route_blocks,
            max_per_msg=3,
            max_len=first_limit,
        )

        responses: list[ResponsePayload] = []

        # ---------- FIRST MESSAGE ----------
        responses.append(
            ResponsePayload(
                text=header + chunks[0],
                images=all_images,
                keyboard=None
            )
        )

        # ---------- MIDDLE ----------
        for chunk in chunks[1:]:
            responses.append(ResponsePayload(text=chunk, keyboard=None))

        # ---------------------- FOOTER ----------------------
        footer = "\n".join([
            "",
            f"Page {current_page} / {total_pages} • Total routes: {total}",
            "",
            "Navigation Commands:",
            '+ — Show more routes',
            '— — Show previous routes',
            'number — Open a route',
            'remove number — Remove a route from the list',
         #   '• "reset"  reset date filter',
            #'- "back"  to prev step',
            'menu — Main menu',
            " ",
            "Examples:",
            "3 — open route #3",
            "remove 2 — remove route #2"

        ])

        responses.append(ResponsePayload(text=footer, keyboard = self.navigation_handler.get_show_route_navigation_keyboard(session)))

        return ResponsePayloadCollection(responses=responses)


    async def show_route_template(
            self,
            route: SeaRouteDB,
            message: Optional[str] = None
    ) -> ResponsePayloadCollection:

        # -------- SELECTED STEPS --------
        steps = [s for s in route.bunkering_steps if s.selected]

        images: list = []

        # -------- MAP INDEXING --------
        indexed = []
        departure_candidate = route.data.port_selection.departure_candidate
        destination_candidate = route.data.port_selection.destination_candidate

        if departure_candidate:
            indexed.append(
                departure_candidate.to_indexed2(emogye.ARROW_UP, "blue", "medium", True)
            )

        if destination_candidate:
            indexed.append(
                destination_candidate.to_indexed2(emogye.ARROW_DOWN, "red", "medium", True)
            )

        for i, step in enumerate(steps, 1):
            if step.marked:
                color = "green"
            elif step.selected:
                color = "orange"
            else:
                color = "gray"

            indexed.append(
                step.port.to_indexed2(str(i), color, "medium", False)
            )

        image, image_err = await self.map_image_api.render_map(
            route.data.departure_to_destination_coordinates,
            indexed
        )
        if image and not image_err:
            images.append(MediaImage(content=image))

        route_map_link = self.map_image_api.get_route_map_link(str(route.id))

        # if not steps:
        #     return ResponsePayloadCollection(
        #         responses=[
        #             ResponsePayload(
        #                 text="Nothing to show for this route.",
        #                 images=images
        #             )
        #         ]
        #     )

        # -------- HEADER --------
        header_lines = [
            "📍 Route details",
            "",
            f"{departure_candidate.format_port()} → "
            f"{destination_candidate.format_port()}"
            if departure_candidate and destination_candidate else "Route",
            "",

        ]

        header_lines.extend([
            f"{emogye.THIS}  <b> Do you want to update the route?:</b>",
            ' <b>Enter yes(y) to do it,</b>',
            '',
            ' <b>Or enter "remove" to remove it.</b> '
            #'• "2 or remove (r)"  remove route',
            #'• "0 or back (b)"  back to list',
            "\n",
        ])

        if message:
            header_lines.append(message)
            header_lines.append("")

        # -------- PORT BLOCKS --------
        port_blocks = [s.format_port_block() for s in steps]

        max_len = self.MAX_MSG_LEN - 200
        port_chunks = self.chunk_by_whole_ports(port_blocks, max_len)

        responses: list[ResponsePayload] = []

        # -------- FIRST MESSAGE --------
        first_parts = header_lines.copy()

        if port_chunks:
            first_parts.append("Bunkering steps:")
            first_parts.append("")
            first_parts.append(port_chunks[0])
        else:
            first_parts.append("No bunkering steps.")

        responses.append(
            ResponsePayload(
                text="\n".join(first_parts),
                images=images,
                keyboard=None
            )
        )

        # -------- MIDDLE CHUNKS --------
        for chunk in port_chunks[1:-1]:
            responses.append(ResponsePayload(text=chunk))

        # -------- LAST MESSAGE --------
        last_parts: list[str] = []

        if len(port_chunks) > 1:
            last_parts.append(port_chunks[-1])
            last_parts.append("")

        # -------- COST SUMMARY --------
        fuel_totals: dict = {}
        total_cost = 0.0

        for step in steps:
            for fuel_name, info in step.fuel_info.items():
                qty = info.get("quantity") or 0
                price = info.get("fuel_price") or 0
                cost = qty * price

                total_cost += cost

                if fuel_name not in fuel_totals:
                    fuel_totals[fuel_name] = {"qty": 0.0, "cost": 0.0}

                fuel_totals[fuel_name]["qty"] += qty
                fuel_totals[fuel_name]["cost"] += cost

        summary = [
          #  "Estimated cost summary:",
            "",
            f"Total estimated cost: ${total_cost:,.0f}",
            "",
        ]

        preferred_order = ["VLS FO", "MGO LS"]
        ordered_fuels = []

        for fuel in preferred_order:
            if fuel in fuel_totals:
                ordered_fuels.append(fuel)

        ordered_fuels.extend(
            sorted(f for f in fuel_totals if f not in preferred_order)
        )

        for fuel in ordered_fuels:
            t = fuel_totals[fuel]
            if t["cost"]:
                summary.append(f"{fuel}: {t['qty']:.2f} mt — ${t['cost']:,.0f}")
            else:
                summary.append(f"{fuel}: {t['qty']:.2f} mt — price on request")

        last_parts.append("\n".join(summary))

        # -------- ROUTE ACTION NAVIGATION --------
        last_parts.extend([
            "",
            f"{emogye.PLANET} Map:",
            route_map_link,
            "",

            "Navigation:",
            " - yes(y) - Update the route",
            " - back(b) - Back to list",
            " - menu - Main menu"
        ])

        responses.append(
            ResponsePayload(
                text="\n".join(last_parts),
                keyboard = self.navigation_handler.get_show_route_navigation_keyboard2("asda")
            )
        )

        return ResponsePayloadCollection(responses=responses)

    def render_delivery_basis(self, port: SeaPortDB):
        icons = []

        if port.barge_status:
            icons.append("🚢")  # barge
        if port.truck_status:
            icons.append("🚚")  # truck
        if getattr(port, "pipe_status", False):
            icons.append("🛢️")  # pipeline

        return " ".join(icons) if icons else "—"

    async def format_option2_email(self, route):
        departure = route.data.port_selection.departure_candidate
        destination = route.data.port_selection.destination_candidate
        steps = [s for s in route.bunkering_steps if s.selected]
        subject = ""
        images = []

        user_db, err = await self.sql_db.get_user_by_id(route.user_id)

        if user_db:
            subject += f"{user_db.first_name or ''} {user_db.last_name or ''} {user_db.telegram_user_name or ''}"

        # ============================================================
        # 1) Build Overview HTML
        # ============================================================
        overview_html = f"""
        <div style="font-family: Arial, sans-serif; margin-bottom: 20px;">
            <h2 style="color: #1a365d; border-bottom: 2px solid #e2e8f0; padding-bottom: 10px;">
                Route & Bunkering Report — Official Summary
            </h2>

            <h3 style="color: #2d3748; margin-top: 25px; margin-bottom: 15px;">Voyage Overview</h3>
            <div style="background: #f7fafc; padding: 15px; border-radius: 5px; border-left: 4px solid #4299e1;">
        """

        if departure:
            overview_html += f"""
            <p style="margin: 8px 0;">
                <strong style="color: #2d3748; min-width: 150px; display: inline-block;">Departure:</strong>
                <span>{departure.port_name} ({departure.locode}), {departure.country_name}</span>
            </p>
            """

        if destination:
            overview_html += f"""
            <p style="margin: 8px 0;">
                <strong style="color: #2d3748; min-width: 150px; display: inline-block;">Destination:</strong>
                <span>{destination.port_name} ({destination.locode}), {destination.country_name}</span>
            </p>
            """

        if route.departure_date:
            overview_html += f"""
            <p style="margin: 8px 0;">
                <strong style="color: #2d3748; min-width: 150px; display: inline-block;">Departure Date:</strong>
                <span>{route.departure_date.strftime('%d %B %Y')}</span>
            </p>
            """

        if route.average_speed_kts:
            overview_html += f"""
            <p style="margin: 8px 0;">
                <strong style="color: #2d3748; min-width: 150px; display: inline-block;">Average Speed:</strong>
                <span>{route.average_speed_kts} knots</span>
            </p>
            """

        if route.vessel_name:
            overview_html += f"""
            <p style="margin: 8px 0;">
                <strong style="color: #2d3748; min-width: 150px; display: inline-block;">Vessel:</strong>
                <span>{route.vessel_name}</span>
            </p>
            """

        if route.imo_number:
            overview_html += f"""
            <p style="margin: 8px 0;">
                <strong style="color: #2d3748; min-width: 150px; display: inline-block;">IMO Number:</strong>
                <span>{route.imo_number}</span>
            </p>
            """

        overview_html += """
            </div>
        </div>
        """

        # ============================================================
        # 2) Build dynamic pandas table: Any number of fuels per port
        # ============================================================
        rows = []
        all_fuels = set()

        for step in steps:
            for fuel_name in step.fuel_info.keys():
                all_fuels.add(fuel_name)

        all_fuels = sorted(list(all_fuels))

        # Build rows for DataFrame
        for step in steps:
            p = step.port
            row = {
                "Port": f"{p.port_name}, {p.country_name}",
                "UNLOCODE": p.locode,
                "Agent": "Yes" if step.agent_required else "No"
            }

            # For each fuel, insert proper value
            for fuel in all_fuels:
                info = step.fuel_info.get(fuel, {})
                qty = info.get("quantity") or 0
                price = info.get("fuel_price")
                if price:
                    cell = f"{qty} mt — ${price}"
                else:
                    cell = f"{qty} mt — Price on request"
                row[fuel] = cell

            rows.append(row)

        df = pd.DataFrame(rows)

        # ============================================================
        # 3) Convert pandas DataFrame → HTML table with styling
        # ============================================================
        def df_to_html_table(df):
            table_style = (
                "width: 100%; "
                "border-collapse: collapse; "
                "font-family: Arial, sans-serif; "
                "font-size: 14px; "
                "margin: 20px 0; "
                "box-shadow: 0 1px 3px rgba(0,0,0,0.1);"
            )
            th_style = (
                "border: 1px solid #cbd5e0; "
                "padding: 12px 15px; "
                "background: #2d3748; "
                "color: white; "
                "text-align: left; "
                "font-weight: 600;"
            )
            td_style = (
                "border: 1px solid #cbd5e0; "
                "padding: 10px 15px; "
                "vertical-align: top;"
            )
            tr_even_style = "background: #f7fafc;"
            tr_hover_style = "background: #ebf8ff;"

            html = [f'<table style="{table_style}">']

            # Header row
            html.append("<thead>")
            html.append("<tr>")
            for col in df.columns:
                html.append(f'<th style="{th_style}">{escape(str(col))}</th>')
            html.append("</tr>")
            html.append("</thead>")

            # Body rows
            html.append("<tbody>")
            for idx, (_, row) in enumerate(df.iterrows()):
                row_style = tr_even_style if idx % 2 == 0 else ""
                html.append(f'<tr style="{row_style}" onmouseover="this.style.background=\'#ebf8ff\'" onmouseout="this.style.background=\'{row_style if row_style else "inherit"}\'">')
                for col in df.columns:
                    html.append(f'<td style="{td_style}">{escape(str(row[col]))}</td>')
                html.append("</tr>")
            html.append("</tbody>")

            html.append("</table>")
            return "\n".join(html)

        html_table = df_to_html_table(df)

        # ============================================================
        # 4) Calculate cost summary
        # ============================================================
        fuel_totals = {}
        total_cost = 0

        for step in steps:
            for fuel_name, info in step.fuel_info.items():
                qty = info.get("quantity") or 0
                price = info.get("fuel_price") or 0
                cost = qty * price
                total_cost += cost

                if fuel_name not in fuel_totals:
                    fuel_totals[fuel_name] = {"qty": 0, "cost": 0}

                fuel_totals[fuel_name]["qty"] += qty
                fuel_totals[fuel_name]["cost"] += cost

        # Build cost summary HTML
        cost_summary_html = f"""
        <div style="font-family: Arial, sans-serif; margin-top: 30px; margin-bottom: 20px;">
            <h3 style="color: #2d3748; margin-bottom: 15px;">Cost Summary</h3>
            <div style="background: #f0fff4; padding: 20px; border-radius: 5px; border-left: 4px solid #38a169;">
                <div style="font-size: 18px; font-weight: bold; color: #2f855a; margin-bottom: 15px;">
                    Total Estimated Cost: <span style="color: #276749;">${total_cost:,.0f}</span>
                </div>
        """

        for fuel, t in fuel_totals.items():
            if t["cost"]:
                cost_summary_html += f"""
                <p style="margin: 10px 0; padding: 8px 12px; background: white; border-radius: 4px; border-left: 3px solid #4299e1;">
                    <strong style="color: #2d3748;">{fuel}:</strong> 
                    <span style="color: #4a5568;">{t['qty']:.2f} mt</span> — 
                    <span style="color: #38a169; font-weight: 600;">${t['cost']:,.0f}</span>
                </p>
                """
            else:
                cost_summary_html += f"""
                <p style="margin: 10px 0; padding: 8px 12px; background: white; border-radius: 4px; border-left: 3px solid #a0aec0;">
                    <strong style="color: #2d3748;">{fuel}:</strong> 
                    <span style="color: #4a5568;">{t['qty']:.2f} mt</span> — 
                    <span style="color: #a0aec0; font-style: italic;">$0 (on request)</span>
                </p>
                """

        cost_summary_html += """
            </div>
        </div>
        """

        # ============================================================
        # 5) Combine all HTML sections
        # ============================================================
        final_email_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Bunkering Report</title>
        </head>
        <body style="margin: 0; padding: 0; background: #edf2f7;">
            <div style="max-width: 800px; margin: 20px auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">

                <!-- Header -->
                <div style="text-align: center; margin-bottom: 30px; padding-bottom: 20px; border-bottom: 1px solid #e2e8f0;">
                    <h1 style="color: #1a365d; margin: 0; font-size: 24px;">
                        ⚓ Route & Bunkering Report
                    </h1>
                    <p style="color: #718096; margin-top: 5px; font-size: 14px;">
                        Official Summary | Generated on {datetime.now().strftime('%d %B %Y')}
                    </p>
                </div>

                <!-- Voyage Overview -->
                {overview_html}

                <!-- Port Bunkering Schedule -->
                <div style="font-family: Arial, sans-serif; margin: 30px 0;">
                    <h3 style="color: #2d3748; margin-bottom: 15px; padding-bottom: 10px; border-bottom: 2px solid #e2e8f0;">
                        Port Bunkering Schedule
                    </h3>
                    {html_table}
                    <p style="font-size: 12px; color: #718096; margin-top: 10px; font-style: italic;">
                        Note: All quantities are in metric tons (mt)
                    </p>
                </div>

                <!-- Cost Summary -->
                {cost_summary_html}

                <!-- Footer -->
                <div style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #e2e8f0; text-align: center; font-size: 12px; color: #a0aec0;">
                    <p>This report is generated automatically. For questions, please contact the operations team.</p>
                    <p>© {datetime.now().year} Bunkering Operations. All rights reserved.</p>
                </div>

            </div>
        </body>
        </html>
        """

        # ============================================================
        # 6) Generate map image
        # ============================================================
        indexed = []
        if departure:
            indexed.append(departure.to_indexed2(emogye.ARROW_UP, "green", "medium", True))
        if destination:
            indexed.append(destination.to_indexed2(emogye.ARROW_DOWN, "red", "medium", True))

        for step in steps:
            indexed.append(step.port.to_indexed2(str(step.n), "blue", "medium", False))

        image, image_err = await self.map_image_api.render_map(route.data.departure_to_destination_coordinates, indexed)
        if image and not image_err:
            images.append(MediaImage(content=image))

        return final_email_html, subject, images

    def render_images_html(self, images: list[str]) -> str:
        if not images:
            return ""

        blocks = []
        for img_b64 in images:
            blocks.append(f"""
            <div style="margin: 20px 0; text-align: center;">
                <img
                    src="data:image/png;base64,{img_b64}"
                    style="max-width: 100%; border-radius: 6px; box-shadow: 0 2px 6px rgba(0,0,0,0.15);"
                />
            </div>
            """)

        return "\n".join(blocks)

    async def format_option2_email2(self, route):
        departure = route.data.port_selection.departure_candidate
        destination = route.data.port_selection.destination_candidate
        steps = [s for s in route.bunkering_steps if s.selected]
        subject = ""
        images = []

        user_db, err = await self.sql_db.get_user_by_id(route.user_id)

        if user_db:
            subject += f"{user_db.first_name or ''} {user_db.last_name or ''} {user_db.telegram_user_name or ''}"

        # ============================================================
        # 1) Generate map image FIRST (to embed in HTML)
        # ============================================================
        indexed = []
        if departure:
            indexed.append(departure.to_indexed2(emogye.ARROW_UP, "green", "medium", True))
        if destination:
            indexed.append(departure.to_indexed2(emogye.ARROW_DOWN, "red", "medium", True))

        for step in steps:
            if not step.selected:
                continue

            indexed.append(step.port.to_indexed2(str(step.n), "blue", "medium", False))

        image, image_err = await self.map_image_api.render_map(route.data.departure_to_destination_coordinates, indexed)

        # Base64 encode the image for embedding in HTML
        if image and not image_err:
            images.append(MediaImage(content=image))

        images_html = self.render_images_html(images)


        # ============================================================
        # 2) Build Overview HTML
        # ============================================================
        overview_html = f"""
        <div style="font-family: Arial, sans-serif; margin-bottom: 20px;">
            <h2 style="color: #1a365d; border-bottom: 2px solid #e2e8f0; padding-bottom: 10px;">
                Route & Bunkering Report — Official Summary
            </h2>

            <h3 style="color: #2d3748; margin-top: 25px; margin-bottom: 15px;">Voyage Overview</h3>
            <div style="background: #f7fafc; padding: 15px; border-radius: 5px; border-left: 4px solid #4299e1;">
        """

        if departure:
            overview_html += f"""
            <p style="margin: 8px 0;">
                <strong style="color: #2d3748; min-width: 150px; display: inline-block;">Departure:</strong>
                <span>{departure.port_name} ({departure.locode}), {departure.country_name}</span>
            </p>
            """

        if destination:
            overview_html += f"""
            <p style="margin: 8px 0;">
                <strong style="color: #2d3748; min-width: 150px; display: inline-block;">Destination:</strong>
                <span>{destination.port_name} ({destination.locode}), {destination.country_name}</span>
            </p>
            """

        if route.departure_date:
            overview_html += f"""
            <p style="margin: 8px 0;">
                <strong style="color: #2d3748; min-width: 150px; display: inline-block;">Departure Date:</strong>
                <span>{route.departure_date.strftime('%d %B %Y')}</span>
            </p>
            """

        if route.average_speed_kts:
            overview_html += f"""
            <p style="margin: 8px 0;">
                <strong style="color: #2d3748; min-width: 150px; display: inline-block;">Average Speed:</strong>
                <span>{route.average_speed_kts} knots</span>
            </p>
            """

        if route.vessel_name:
            overview_html += f"""
            <p style="margin: 8px 0;">
                <strong style="color: #2d3748; min-width: 150px; display: inline-block;">Vessel:</strong>
                <span>{route.vessel_name}</span>
            </p>
            """

        if route.imo_number:
            overview_html += f"""
            <p style="margin: 8px 0;">
                <strong style="color: #2d3748; min-width: 150px; display: inline-block;">IMO Number:</strong>
                <span>{route.imo_number}</span>
            </p>
            """

        overview_html += """
            </div>
        </div>
        """

        # ============================================================
        # 3) Build dynamic pandas table: Any number of fuels per port
        # ============================================================
        rows = []
        all_fuels = set()

        for step in steps:
            for fuel_name in step.fuel_info.keys():
                all_fuels.add(fuel_name)

        all_fuels = sorted(list(all_fuels))

        preferred_order = ["VLS FO", "MGO LS"]
        all_fuels_set = set(all_fuels)

        ordered_fuels = []
        # preferred fuels first
        for fuel in preferred_order:
            if fuel in all_fuels_set:
                ordered_fuels.append(fuel)

        # remaining fuels alphabetically
        remaining_fuels = sorted(f for f in all_fuels_set if f not in preferred_order)
        ordered_fuels.extend(remaining_fuels)

        # Build rows for DataFrame
        for step in steps:
            p = step.port
            row = {
                "Port": p.format_port().replace("\n", ""),
                #"UNLOCODE": p.locode,
                "Arrival date": step.eta_datetime.strftime("%B %d, %Y") if step.eta_datetime else emogye.LINE,
                "Port info": p.agent_contact_list if p.agent_contact_list else emogye.LINE,
                "Fuel delivery method": self.render_delivery_basis(p),
            }

            # For each fuel, insert proper value
            for fuel in ordered_fuels:
                info = step.fuel_info.get(fuel, {})
                qty = info.get("quantity") or 0
                price = info.get("fuel_price")
                if price:
                    cell = f"{qty} mt — ${price}"
                else:
                    cell = f"{qty} mt — Price on request"
                row[fuel] = cell

            rows.append(row)

        df = pd.DataFrame(rows)

        # ============================================================
        # 4) Convert pandas DataFrame → HTML table with styling
        # ============================================================
        def df_to_html_table(df):
            table_style = (
                "width: 100%; "
                "border-collapse: collapse; "
                "font-family: Arial, sans-serif; "
                "font-size: 14px; "
                "margin: 20px 0; "
                "box-shadow: 0 1px 3px rgba(0,0,0,0.1);"
            )
            th_style = (
                "border: 1px solid #cbd5e0; "
                "padding: 12px 15px; "
                "background: #2d3748; "
                "color: white; "
                "text-align: left; "
                "font-weight: 600;"
            )
            td_style = (
                "border: 1px solid #cbd5e0; "
                "padding: 10px 15px; "
                "vertical-align: top;"
            )
            tr_even_style = "background: #f7fafc;"
            tr_hover_style = "background: #ebf8ff;"

            html = [f'<table style="{table_style}">']

            # Header row
            html.append("<thead>")
            html.append("<tr>")
            for col in df.columns:
                html.append(f'<th style="{th_style}">{escape(str(col))}</th>')
            html.append("</tr>")
            html.append("</thead>")

            # Body rows
            html.append("<tbody>")
            for idx, (_, row) in enumerate(df.iterrows()):
                row_style = tr_even_style if idx % 2 == 0 else ""
                html.append(f'<tr style="{row_style}" onmouseover="this.style.background=\'#ebf8ff\'" onmouseout="this.style.background=\'{row_style if row_style else "inherit"}\'">')
                for col in df.columns:
                    html.append(f'<td style="{td_style}">{escape(str(row[col]))}</td>')
                html.append("</tr>")
            html.append("</tbody>")

            html.append("</table>")
            return "\n".join(html)

        html_table = df_to_html_table(df)

        # ============================================================
        # 5) Calculate cost summary
        # ============================================================
        fuel_totals = {}
        total_cost = 0

        for step in steps:
            for fuel_name, info in step.fuel_info.items():
                qty = info.get("quantity") or 0
                price = info.get("fuel_price") or 0
                cost = qty * price
                total_cost += cost

                if fuel_name not in fuel_totals:
                    fuel_totals[fuel_name] = {"qty": 0, "cost": 0}

                fuel_totals[fuel_name]["qty"] += qty
                fuel_totals[fuel_name]["cost"] += cost

        # Build cost summary HTML
        cost_summary_html = f"""
        <div style="font-family: Arial, sans-serif; margin-top: 30px; margin-bottom: 20px;">
            <h3 style="color: #2d3748; margin-bottom: 15px;">Cost Summary</h3>
            <div style="background: #f0fff4; padding: 20px; border-radius: 5px; border-left: 4px solid #38a169;">
                <div style="font-size: 18px; font-weight: bold; color: #2f855a; margin-bottom: 15px;">
                    Total Estimated Cost: <span style="color: #276749;">${total_cost:,.0f}</span>
                </div>
        """

        for fuel, t in fuel_totals.items():
            if t["cost"]:
                cost_summary_html += f"""
                <p style="margin: 10px 0; padding: 8px 12px; background: white; border-radius: 4px; border-left: 3px solid #4299e1;">
                    <strong style="color: #2d3748;">{fuel}:</strong> 
                    <span style="color: #4a5568;">{t['qty']:.2f} mt</span> — 
                    <span style="color: #38a169; font-weight: 600;">${t['cost']:,.0f}</span>
                </p>
                """
            else:
                cost_summary_html += f"""
                <p style="margin: 10px 0; padding: 8px 12px; background: white; border-radius: 4px; border-left: 3px solid #a0aec0;">
                    <strong style="color: #2d3748;">{fuel}:</strong> 
                    <span style="color: #4a5568;">{t['qty']:.2f} mt</span> — 
                    <span style="color: #a0aec0; font-style: italic;">$0 (on request)</span>
                </p>
                """

        cost_summary_html += """
            </div>
        </div>
        """

        # ============================================================
        # 6) Combine all HTML sections WITH MAP AT THE TOP
        # ============================================================
        final_email_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Bunkering Report</title>
            
        </head>
        <body style="margin: 0; padding: 0; background: #edf2f7;">
            <div style="max-width: 800px; margin: 20px auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">

                <!-- Header -->
                <div style="text-align: center; margin-bottom: 30px; padding-bottom: 20px; border-bottom: 1px solid #e2e8f0;">
                    <h1 style="color: #1a365d; margin: 0; font-size: 24px;">
                        ⚓ Route & Bunkering Report
                    </h1>
                    <p style="color: #718096; margin-top: 5px; font-size: 14px;">
                        Official Summary | Generated on {datetime.now().strftime('%d %B %Y')}
                    </p>
                </div>
                
                {images_html}

                <!-- Voyage Overview -->
                {overview_html}

                <!-- Port Bunkering Schedule -->
                <div style="font-family: Arial, sans-serif; margin: 30px 0;">
                    <h3 style="color: #2d3748; margin-bottom: 15px; padding-bottom: 10px; border-bottom: 2px solid #e2e8f0;">
                        Port Bunkering Schedule
                    </h3>
                    {html_table}
                    <p style="font-size: 12px; color: #718096; margin-top: 10px; font-style: italic;">
                        Note: All quantities are in metric tons (mt)
                    </p>
                </div>

                <!-- Cost Summary -->
                {cost_summary_html}

                <!-- Footer -->
                <div style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #e2e8f0; text-align: center; font-size: 12px; color: #a0aec0;">
                    <p>This report is generated automatically. For questions, please contact the operations team.</p>
                    <p>© {datetime.now().year} Bunkering Operations. All rights reserved.</p>
                </div>

            </div>
        </body>
        </html>
        """

        return final_email_html, subject, images


    async def show_route_user_template(self, route: SeaRouteDB) -> Tuple[ResponsePayloadCollection, str, bool]:
        departure_port = None
        destination_port = None
        subject = ""

        user_db, err = await self.sql_db.get_user_by_id(route.user_id)

        if user_db:
            subject += f"{user_db.first_name or ''} {user_db.last_name or ''} {user_db.telegram_user_name or ''}"

        if route.data.port_selection.departure_candidate:
            departure_port = route.data.port_selection.departure_candidate

        if route.data.port_selection.destination_candidate:
            destination_port = route.data.port_selection.destination_candidate

        lines = [f"{emogye.ANCHOR} New route report"]
        if departure_port:
            lines.append(
                f"Departure: {departure_port.port_name} - {departure_port.country_name} - {departure_port.locode}"
            )

        if destination_port:
            lines.append(
                f"Destination: {destination_port.port_name} - {destination_port.country_name} - {destination_port.locode}"
            )

        if route.departure_date:
            lines.append(
                f"Departure date: {route.departure_date.strftime('%B, %d %Y')}"
            )

        if route.average_speed_kts:
            lines.append(f"Average speed: {route.average_speed_kts} knots")

        if route.vessel_name:
            lines.append(f"Vessel name: {route.vessel_name}")
            subject += f" - {route.vessel_name}"

        if route.imo_number:
            lines.append(f"IMO number: {route.imo_number}")
            subject += f" - {route.imo_number}"

        lines.append(" ")

        header = "\n".join(lines)
        steps = [s for s in route.bunkering_steps if s.selected]

        indexed = []
        if departure_port:
            indexed.append(departure_port.to_indexed2(emogye.ARROW_UP, "green", "medium", True))

        if destination_port:
            indexed.append(destination_port.to_indexed2(emogye.ARROW_DOWN, "red", "medium", True))

        for step in steps:
            indexed.append(step.port.to_indexed2(str(step.n), "blue", "medium", False))

        images = []
        image, err = await self.map_image_api.render_map(route.data.departure_to_destination_coordinates, indexed)
        if image and not err:
            images.append(MediaImage(content=image))




        if not steps:
            return ResponsePayloadCollection(
                responses=[
                    ResponsePayload(
                        text=header + "\nNo ports available.",
                        images=images,
                        keyboard=self.navigation_handler.get_navigation_keyboard()
                    )
                ]
            ), subject, False

        port_blocks = [
            #self.format_port_block(step, idx)
            step.format_port_block()
            for idx, step in enumerate(steps, 1)
        ]

        port_chunks = self.chunk_by_whole_ports(port_blocks, self.MAX_MSG_LEN)
        if len(port_chunks) == 0:
            return ResponsePayloadCollection(
                responses=[
                    ResponsePayload(
                        text=header + "\nNo ports available.",
                        images=images,
                        keyboard=None
                    )
                ]
            ), subject, False

        responses = []

        first = [header, ""]

        first.append("Ports:")
        first.append(port_chunks[0])
        responses.append(
            ResponsePayload(
                text="\n".join(first),
                images=images,
                keyboard=None
            )
        )

        for chunk in port_chunks[1:-1]:
            responses.append(ResponsePayload(text=chunk, keyboard=None))

        last_parts = []

        if len(port_chunks) > 1:
            last_parts.append(port_chunks[-1])

        fuel_totals = {}
        total_cost = 0

        for step in steps:
            if not step.selected:
                continue

            for fuel_name, info in step.fuel_info.items():
                qty = info.get("quantity") or 0
                price = info.get("fuel_price") or 0
                cost = qty * price

                total_cost += cost

                if fuel_name not in fuel_totals:
                    fuel_totals[fuel_name] = {"qty": 0, "cost": 0}

                fuel_totals[fuel_name]["qty"] += qty
                fuel_totals[fuel_name]["cost"] += cost

        summary = [#"Estimated cost summary:",
                   f"Estimated cost: ${total_cost:,.0f}", ""]

        for f, t in fuel_totals.items():
            if t["cost"]:
                summary.append(f"{f}: {t['qty']:.2f} mt — ${t['cost']:,.0f}")
            else:
                summary.append(f"{f}: {t['qty']:.2f} mt — $0 (on request)")

        last_parts.append("\n".join(summary))

        responses.append(ResponsePayload(text="\n".join(last_parts)))

        return ResponsePayloadCollection(responses=responses), subject, True

    async def get_port_fuel_price_template(self, session: SessionDB, message: str = None):
        lines = [f"{emogye.STATS_LINE} Check port price"]
        images = []

        # --- If no port search started ---
        if not getattr(session.data, "check_port_fuel_price", None):
            lines.append(f"\n{emogye.THIS}  <b> Enter the port info to search prices. </b> ")
            if message:
                lines.append(f"\nErr: {message}")

            lines.extend([
                "\n",
                "Navigation:",
                "- menu - to main menu",
            ])
            return ResponsePayloadCollection(responses=[ResponsePayload(text=chr(10).join(lines), keyboard=self.navigation_handler.get_menu_keyboard())])

        # --- Extract port and prices safely ---
        port_info = getattr(session.data.check_port_fuel_price, "port", None)
        prices = getattr(session.data.check_port_fuel_price, "prices", [])
        port_alternatives = getattr(session.data.check_port_fuel_price, "port_alternatives", [])

        if not port_info:
            lines.append("\n⚠️ Port information is missing.")
        else:
            lines.append(f"Port: {port_info.format_port() if port_info else  'N/A'}")
                         #f"{getattr(port_info, 'country_name', 'N/A')} - "
                         #f"{getattr(port_info, 'locode', 'N/A')}"
                         #)
            lines.append(f"Info: {port_info.agent_contact_list}")
            today = datetime.now()
            lines.append(f"Date now: {today.strftime('%B %d, %Y')}")
            if today.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
                lines.append("Note: Today is a holiday (Saturday/Sunday).\nMobux updates prices only on working days.")


        # --- Get fuels safely ---
        fuels, err = await self.sql_db.get_available_fuels()
        #fuel_names = {fuel.id: fuel.name for fuel in fuels} if fuels else {}


        # --- Prepare price timeseries safely ---
        prices_timeseries = {}
        if prices:
            for price in prices:
                prices_timeseries.setdefault(price.fuelName, []).append(price)

        # --- Build dataframe safely ---
        # --- Prepare price timeseries safely ---
        prices_timeseries = {}
        if prices:
            for price in prices:
                prices_timeseries.setdefault(price.fuelName, []).append(price)

        # --- Build dataframe safely ---
        df = pd.DataFrame()
        if prices_timeseries:
            try:
                df_list = []
                for fuel, recs in prices_timeseries.items():
                    if recs:
                        df_list.append(pd.DataFrame([{"date": getattr(r, "date", None), fuel: getattr(r, "value", None)} for r in recs]))
                if df_list:
                    # Use merge instead of concat+groupby to get proper wide format
                    df = df_list[0].set_index('date')
                    for temp_df in df_list[1:]:
                        temp_df = temp_df.set_index('date')
                        df = df.merge(temp_df, left_index=True, right_index=True, how='outer')
                    df = df.sort_index()
            except Exception as e:
                lines.append(f"\n⚠️ Failed to build dataframe: {str(e)}")

        # The rest of your plotting code remains the same...

        # --- Plot chart safely ---
        image_bytes = None
        if not df.empty:
            # Store the original index labels for x-axis
            original_index_labels = [i.strftime("%b, %d %Y") for i in df.index]

            # Reset index to numeric but keep it for plotting
            df_numeric = df.reset_index(drop=True)  # This creates 0,1,2,... index

            try:
                fig, ax = plt.subplots(figsize=(14, 7))

                # Plot using numeric index (0, 1, 2, ...)
                for fuel in df_numeric.columns:
                    ax.plot(df_numeric.index, df_numeric[fuel], marker="o", linewidth=2, label=fuel)

                    # Add data labels
                    for x, y in zip(df_numeric.index, df_numeric[fuel]):
                        if pd.notna(y):
                            ax.text(x, y, f"{y:.0f}", fontsize=12, ha="center", va="bottom")

                ax.set_ylabel("Price, $/mton")
                ax.set_title("Fuel Cost Timeseries, $/mton")
                ax.grid(True, linestyle="--", alpha=0.6)
                ax.legend()

                # Set x-axis ticks and labels
                ax.set_xticks(df_numeric.index)  # Set numeric positions
                ax.set_xticklabels(original_index_labels)  # Set original date labels

                # Rotate x-axis labels for better readability
                plt.setp(ax.get_xticklabels(), rotation=45, ha='right')

                plt.tight_layout()

                buf = io.BytesIO()
                fig.savefig(buf, format='png', dpi=300)
                buf.seek(0)
                image_bytes = buf.getvalue()
                images.append(MediaImage(content=image_bytes))
                buf.close()
                plt.close(fig)
            except Exception as e:
                lines.append(f"\n⚠️ Failed to generate plot: {str(e)}")

        # --- Append dataframe markdown ---
        if not df.empty:
            try:
               # df_markdown = df.to_markdown()
               lines.append("\nPrices:")

                #lines.append(self.df_to_preformatted(df))
                #table_image_bytes = self.df_to_image(df)
                #images.append(table_image_bytes)

               df_sorted = df.sort_index()
               latest_date = df_sorted.index.max()
               latest_row = df_sorted.loc[latest_date]

               for fuel in df_sorted.columns:
                   value = latest_row[fuel]
                   if pd.notna(value):
                       lines.append(f"{latest_date.strftime('%b-%d-%Y')}    {fuel}         <b> ${value:.0f} </b> ")
                   else:
                       lines.append(f"{latest_date.strftime('%b-%d-%Y')}    {fuel}         <b> Not available </b> ")


            except Exception as e:
                lines.append(f"\n⚠️ Failed to convert dataframe to markdown: {str(e)}")
        else:
            lines.append("\n⚠️ No price data available.")



        #indexed = []
        global_counter = 1
        blocks = []
        # for p in port_alternatives:
        #     blocks.append(p.format_indexed(global_counter))
        #     indexed.append(p.to_indexed2(str(global_counter), "orange", "medium", False))
        #     global_counter += 1
        #
        # images_new = await self.map_image_api.render_map_images([], indexed, True)
        # images.extend([MediaImage(content=c) for c in images_new])

        header = "\n".join(lines) + f"\n\n{emogye.THIS}  <b> Enter new port name if needed. </b> " + "\n\nName similar:\n"
        first_limit = self.MAX_MSG_LEN - len(header)
        responses = []
        first_blocks = self.split_blocks(blocks, first_limit)

        if len(first_blocks) > 0:
            header += first_blocks[0]

        responses.append(
            ResponsePayload(
                text=header,
                images=images
            )
        )

        for chunk in first_blocks[1:]:
            responses.append(ResponsePayload(text=chunk))

        responses[-1].text += "\nNavigation:\n- menu - Main menu"
        responses[-1].keyboard = self.navigation_handler.get_to_main_menu_keyboard(session)

        return ResponsePayloadCollection(responses=responses)

    def df_to_html_rotated(self, df: pd.DataFrame) -> str:
        html = '<table border="1" style="border-collapse: collapse;">'
        # header row
        html += '<tr>'
        html += f'<th>Date</th>'
        for col in df.columns:
            html += f'<th style="transform: rotate(-45deg); white-space: nowrap; padding: 5px;">{col}</th>'
        html += '</tr>'
        # data rows
        for idx, row in df.iterrows():
            html += '<tr>'
            html += f'<td>{idx.date() if hasattr(idx, "date") else idx}</td>'
            for col in df.columns:
                html += f'<td>{row[col]}</td>'
            html += '</tr>'
        html += '</table>'
        return html

    def vertical_headers(self, df: pd.DataFrame) -> str:
        headers = [list(col) for col in df.columns]
        max_len = max(len(h) for h in headers)
        # pad shorter headers
        for h in headers:
            while len(h) < max_len:
                h.append(" ")
        # transpose letters
        lines = []
        for i in range(max_len):
            line = " | ".join(h[i] for h in headers)
            lines.append(line)
        # add separator
        lines.append("-" * len(lines[0]))
        # add data rows
        for idx, row in df.iterrows():
            row_str = " | ".join(str(row[col]) for col in df.columns)
            lines.append(row_str)
        return "\n".join(lines)

    def df_to_preformatted(self, df: pd.DataFrame) -> str:
        # shorten fuel names to max 10 chars
        df = df.rename(columns=lambda x: x[:10])

        # convert dataframe to string
        df_str = df.to_markdown(tablefmt="plain")

        return f"<pre>{df_str}</pre>"

    def df_to_image(self, df: pd.DataFrame) -> bytes:
        if df.empty:
            return None  # nothing to plot

        # --- Plot table as image ---
        fig, ax = plt.subplots(figsize=(max(8, len(df.columns)), int(max(2, len(df) / 2))))
        ax.axis('off')  # hide axes

        # shorten column names if too long
        df_plot = df.copy()
        df_plot = df_plot.rename(columns=lambda x: x if len(x) <= 12 else x[:12] + "...")

        # render table
        table = ax.table(
            cellText=df_plot.values,
            colLabels=df_plot.columns,
            rowLabels=[str(d.date()) if hasattr(d, "date") else str(d) for d in df_plot.index],
            cellLoc='center',
            loc='center'
        )
        table.auto_set_font_size(False)
        table.set_fontsize(12)
        table.auto_set_column_width(col=list(range(len(df_plot.columns))))

        # adjust header
        for key, cell in table.get_celld().items():
            if key[0] == 0:  # header row
                cell.set_text_props(rotation=0, ha='right', weight='bold')

        # save to bytes
        buf = io.BytesIO()
        plt.tight_layout()
        fig.savefig(buf, format='png', dpi=300)
        buf.seek(0)
        image_bytes = buf.getvalue()
        buf.close()
        plt.close(fig)

        return image_bytes

    async def vessel_info_template(
            self,
            session: SessionDB,
            route: SeaRouteDB,
            message: Optional[str] = None
    ) -> ResponsePayloadCollection:

        if route.vessel_name or route.imo_number:
            lines = ["\nIs this vessel information correct?\nEnter new vessel name/IMO or confirm.\n"]
        else:
            lines = ["\nEnter vessel name and/or IMO number.\n"]


        lines.extend(
            [
                "Examples:",
                "- vessel Maersk Alabama imo 9321483",
                "- IMO 9456123",
                "- vessel name is Aurora",
                "- update vessel to Ever Given and imo 9811000",
                "\n",
            ]
        )

        text = "\n".join(lines)

        if message:
            text += f"Note: {message}\n"

        header_text = await self.get_new_route_header(session, route)
        navigation_text = self.navigation_handler.get_navigation_text(session)
        text = header_text + text + navigation_text

        return ResponsePayloadCollection(
            responses=[ResponsePayload(text=text, keyboard=self.navigation_handler.get_navigation_keyboard(session.current_step))]
        )

    async def user_name_template(self, session: SessionDB, message: str = None):
        lines = [
            f"By the way {emogye.SMILE}",
            "How can I call you here?",
            "",
            "First name is enough",
          #  "You can type '-' to skip."
        ]

        if message:
            lines.extend(["", "Note:", message])

        return ResponsePayloadCollection(responses=[ResponsePayload(text="\n".join(lines))])

    async def vessel_name_template(
            self,
            session: SessionDB,
            route: SeaRouteDB,
            message: Optional[str] = None
    ) -> ResponsePayloadCollection:
        """Template for vessel name input step"""

        lines = []

        if route.data.is_updating:
            lines.append("\nWaiting for new vessel name...\n")

        lines.extend([
            f"\n{emogye.THIS}  <b> Enter vessel name: </b> " if not route.vessel_name else f"\n {emogye.THIS}  <b> Enter new name or confirm current. </b> ",
            "",
           # "Examples:",
            "Like \"Maersk Alabama\"",
         #   "- vessel name is Aurora",
         #   "- update vessel to Ever Given",
         #   "- MSC Oscar",
        #    "",
            #"This is a required field."
        ])

        text = "\n".join(lines)

        if message:
            text += f"\n\nNote: {message}\n"

        header_text = await self.get_new_route_header(session, route)
        navigation_text = self.navigation_handler.get_navigation_text(session)
        text = header_text + text + navigation_text

        return ResponsePayloadCollection(
            responses=[ResponsePayload(text=text, keyboard=self.navigation_handler.get_navigation_keyboard(session.current_step))]
        )


    async def vessel_imo_template(
            self,
            session: SessionDB,
            route: SeaRouteDB,
            message: Optional[str] = None
    ) -> ResponsePayloadCollection:
        """Template for vessel IMO input step (optional)"""
        current_vessel_info = []

        lines = []

        if route.data.is_updating:
            lines.append("\nWaiting for new IMO number...\n")

        lines.extend([
            f"\n{emogye.THIS}  <b>Enter the IMO number</b>\n<b>(example: 9312345)</b>\n<b>or type yes/y to skip this step. </b> " if not route.imo_number else f"\n{emogye.THIS}  <b>Enter new IMO or yes(y) to confirm</b> ",
            ""
        ])

        lines.extend([
            "Examples:",
            "- IMO 9321483",
            "- imo 9456123",
            "- yes(y) or - to continue without IMO",
            "",
            "Note: IMO must be 7 digits"
        ])

        text = "\n".join(lines)

        if message:
            text += f"\n\nNote: {message}\n"

        header_text = await self.get_new_route_header(session, route)
        navigation_text = self.navigation_handler.get_navigation_text(session)
        text = header_text + text + navigation_text

        return ResponsePayloadCollection(
            responses=[ResponsePayload(text=text,keyboard=self.navigation_handler.get_navigation_keyboard(session.current_step))]
        )

    def format_tariffs_lines(self, tariffs: List[UserTariffBD]) -> List[str]:
        lines = ["Available tariffs:", ""]

        def yn(value: bool) -> str:
            return "Yes" if value else "No"

        for tariff in tariffs:
            if not tariff.is_active:
                continue

            price = f"${tariff.monthly_price:.2f}"
            lines.append(f"🔹 {tariff.name} — {price} / month")
            lines.append(f"  • Routes: {tariff.max_routes}")
            lines.append(f"  • Messages: {tariff.max_messages}")

            features = tariff.features

            if hasattr(features, "api_access"):
                lines.append(f"  • API access: {yn(features.api_access)}")

            lines.append(f"  • Custom domains: {yn(features.custom_domains)}")
            lines.append(f"  • Priority support: {yn(features.priority_support)}")
            lines.append(f"  • Advanced analytics: {yn(features.advanced_analytics)}")
            lines.append("")

        lines.append("Type the tariff name exactly as shown above.")
        return lines

    async def update_tariff_template(
            self,
            session: SessionDB,
            user: UserDB,
            msg: str = None
    ) -> ResponsePayloadCollection:
        """
        Builds tariff update messages split so that
        each ResponsePayload.text <= self.MAX_MSG_LEN

        Rules:
        - Header appears only in the first message
        - Navigation appears only in the last message
        """

        tariff_data = session.data.tariff_selection if session.data else None
        chosen_tariff = getattr(tariff_data, "chosen_tariff", None)
        user_message = getattr(tariff_data, "user_message", None)

        # --------------------------------------------------
        # Header (FIRST message only)
        # --------------------------------------------------
        header_blocks = [
            "🔄 Tariff Update",
            "",
        ]

        # --------------------------------------------------
        # Main content blocks (chunkable)
        # --------------------------------------------------
        content_blocks = []

        if chosen_tariff:
            content_blocks.extend([
                f"Current tariff: {chosen_tariff}",
                "",
                "Would you like to keep this tariff or switch to a different one?",
                "- Reply Yes or Y to confirm",
                "- Or enter a new tariff name to change it",
                "",
            ])
        else:
            content_blocks.extend([
                "Please select the tariff you would like to switch to.",
                "",
            ])

        # --------------------------------------------------
        # Tariff list (atomic per tariff line)
        # --------------------------------------------------
        tariffs, err = await self.sql_db.get_available_tariffs()
        if tariffs and not err:
            content_blocks.append("📋 Available tariffs:")
            content_blocks.append("")
            content_blocks.extend(self.format_tariffs_lines(tariffs))
            content_blocks.append("")

        # --------------------------------------------------
        # Optional user comment
        # --------------------------------------------------
        if not user_message:
            content_blocks.extend([
                "💬 Additional information (optional)",
                "You may add a short comment to help us tailor the tariff for you:",
                "- Expected usage or volumes",
                "- Number of vessels",
                "- Any specific company requirements",
                "",
            ])

        # --------------------------------------------------
        # Required details (synced + values)
        # --------------------------------------------------
        required_blocks = ["🧾 Required details"]

        # user name
        if user.filled_name:
            required_blocks.append(
                f"{emogye.CHECK_GREEN_BACKGROUND} Your name: {user.filled_name}"
            )
        else:
            required_blocks.append(
                f"{emogye.CROSS_RED} Your name: _not provided_"
            )

        # Company name
        if user.company_name:
            required_blocks.append(
                f"{emogye.CHECK_GREEN_BACKGROUND} Company name: {user.company_name}"
            )
        else:
            required_blocks.append(
                f"{emogye.CROSS_RED} Company name: _not provided_"
            )

        # Email
        if user.email:
            required_blocks.append(
                f"{emogye.CHECK_GREEN_BACKGROUND} Email: {user.email}"
            )
        else:
            required_blocks.append(
                f"{emogye.CROSS_RED} Email: _not provided_"
            )

        # Phone number
        if user.phone_number:
            required_blocks.append(
                f"{emogye.CHECK_GREEN_BACKGROUND} Mobile phone: {user.phone_number}"
            )
        else:
            required_blocks.append(
                f"{emogye.CROSS_RED} Mobile phone: _not provided_"
            )

        # Chosen tariff
        chosen_tariff = session.data.tariff_selection.chosen_tariff
        if chosen_tariff:
            required_blocks.append(
                f"{emogye.CHECK_GREEN_BACKGROUND} Selected tariff: {chosen_tariff}"
            )
        else:
            required_blocks.append(
                f"{emogye.CROSS_RED} Selected tariff: _not selected_"
            )

        # Optional user message
        user_message = session.data.tariff_selection.user_message
        if user_message:
            required_blocks.append(
                f"{emogye.CHECK_GREEN_BACKGROUND} Message / comment: \n {user_message}"
            )
        else:
            required_blocks.append(
                f"{emogye.INFO} Message / comment: _optional_"
            )

        required_blocks.append("")

        content_blocks.extend(required_blocks)

        # --------------------------------------------------
        # Validation note
        # --------------------------------------------------
        if msg:
            content_blocks.extend([
                f"ℹ️ Note: {msg}",
                "",
            ])

        # --------------------------------------------------
        # Navigation (LAST message only)
        # --------------------------------------------------
        navigation_text = self.navigation_handler.get_navigation_text(session)

        # --------------------------------------------------
        # Chunking logic (safe & deterministic)
        # --------------------------------------------------
        chunks = []
        current = []
        current_len = 0

        def flush():
            nonlocal current, current_len
            if current:
                chunks.append("\n".join(current))
                current = []
                current_len = 0

        for block in content_blocks:
            block_len = len(block) + 1  # + newline

            if block_len > self.MAX_MSG_LEN:
                flush()
                chunks.append(block)
                continue

            if current and current_len + block_len > self.MAX_MSG_LEN:
                flush()

            current.append(block)
            current_len += block_len

        flush()

        # --------------------------------------------------
        # Assemble final payloads
        # --------------------------------------------------
        responses = []

        for i, chunk in enumerate(chunks):
            parts = []

            if i == 0:
                parts.extend(header_blocks)

            parts.append(chunk)

            if i == len(chunks) - 1:
                parts.append(navigation_text)

            responses.append(
                ResponsePayload(text="\n".join(parts))
            )

        return ResponsePayloadCollection(responses=responses)

    async def format_tariff_update_email(
            self,
            user_id: uuid,
            requested_tariff_name: Optional[str] = None,
            user_message: Optional[str] = None
    ) -> Tuple[str, str, List[bytes]]:
        """
        Builds a professional HTML email for a user requesting tariff upgrade/change.
        """

        images = []
        subject = "Tariff Update Request"

        user, err = await self.sql_db.get_user_by_id(user_id)
        if not user or err:
            return "", "", []

        route_count_str = "-"
        route_count, err = await self.sql_db.count_routes(user_id)
        if route_count:
            route_count_str = str(route_count)

        # ------------------------------------------------------------
        # Subject
        # ------------------------------------------------------------
        subject = (
            f"Tariff Update Request — "
            f"{user.company_name or ''} "
            f"{user.first_name or ''} {user.last_name or ''}".strip()
        )

        # ------------------------------------------------------------
        # User header block
        # ------------------------------------------------------------
        user_header_html = f"""
        <div style="font-family: Arial, sans-serif; margin-bottom: 25px;">
            <h2 style="color: #1a365d; border-bottom: 2px solid #e2e8f0; padding-bottom: 10px;">
                Tariff Update Request
            </h2>

            <div style="background: #f7fafc; padding: 15px; border-radius: 6px; border-left: 4px solid #4299e1;">
                <p><strong>User:</strong> {escape(f"{user.first_name or ''} {user.last_name or ''}")}</p>
                <p><strong>Telegram:</strong> @{escape(user.telegram_user_name or "-")}</p>
                <p><strong>Company:</strong> {escape(user.company_name or "-")}</p>
                <p><strong>Email:</strong> {escape(user.email or "-")}</p>
                <p><strong>Phone:</strong> {escape(user.phone_number or "-")}</p>
            </div>
        </div>
        """

        # ------------------------------------------------------------
        # Account details
        # ------------------------------------------------------------
        account_html = f"""
        <div style="font-family: Arial, sans-serif; margin-bottom: 30px;">
            <h3 style="color: #2d3748; margin-bottom: 12px;">Account Overview</h3>

            <table style="width:100%; border-collapse: collapse; font-size:14px;">
                <tr>
                    <td style="padding:8px; border:1px solid #cbd5e0;"><strong>Current Tariff</strong></td>
                    <td style="padding:8px; border:1px solid #cbd5e0;">{escape(str(user.current_tariff_id))}</td>
                </tr>
                <tr style="background:#f7fafc;">
                    <td style="padding:8px; border:1px solid #cbd5e0;"><strong>Messages Used</strong></td>
                    <td style="padding:8px; border:1px solid #cbd5e0;">{user.message_count}</td>
                </tr>
                <tr>
                    <td style="padding:8px; border:1px solid #cbd5e0;"><strong>Routes Built</strong></td>
                    <td style="padding:8px; border:1px solid #cbd5e0;">{route_count_str}</td>
                </tr>
                <tr style="background:#f7fafc;">
                    <td style="padding:8px; border:1px solid #cbd5e0;"><strong>Free Tier Expiry</strong></td>
                    <td style="padding:8px; border:1px solid #cbd5e0;">
                        {user.free_tier_expiry.strftime('%d %B %Y') if user.free_tier_expiry else "—"}
                    </td>
                </tr>
                <tr>
                    <td style="padding:8px; border:1px solid #cbd5e0;"><strong>Account Status</strong></td>
                    <td style="padding:8px; border:1px solid #cbd5e0;">
                        {"Active" if user.is_active else "Inactive"}
                    </td>
                </tr>
            </table>
        </div>
        """

        # ------------------------------------------------------------
        # Requested change
        # ------------------------------------------------------------
        request_html = f"""
        <div style="font-family: Arial, sans-serif; margin-bottom: 30px;">
            <h3 style="color: #2d3748; margin-bottom: 12px;">Requested Change</h3>

            <div style="background:#fffaf0; padding:15px; border-radius:6px; border-left:4px solid #ed8936;">
                <p>
                    <strong>Requested Tariff:</strong>
                    {escape(requested_tariff_name) if requested_tariff_name else "Not specified"}
                </p>
                <p style="margin-top:10px;">
                    <strong>User Comment:</strong><br>
                    <em style="color:#4a5568;">
                        {escape(user_message) if user_message else "—"}
                    </em>
                </p>
            </div>
        </div>
        """

        # ------------------------------------------------------------
        # CTA block
        # ------------------------------------------------------------
        cta_html = f"""
        <div style="font-family: Arial, sans-serif; margin-top: 40px;">
            <div style="background:#f0fff4; padding:20px; border-radius:6px; border-left:4px solid #38a169;">
                <h3 style="margin-top:0; color:#2f855a;">Next Actions</h3>
                <ul style="margin:10px 0 0 18px; color:#2d3748;">
                    <li>Review usage and suitability of requested tariff</li>
                    <li>Contact user for confirmation if needed</li>
                    <li>Apply tariff change in billing system</li>
                    <li>Notify user about activation</li>
                </ul>
            </div>
        </div>
        """

        # ------------------------------------------------------------
        # Final HTML
        # ------------------------------------------------------------
        final_email_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>Tariff Update Request</title>
        </head>
        <body style="margin:0; padding:0; background:#edf2f7;">
            <div style="max-width:800px; margin:20px auto; background:white; padding:30px;
                        border-radius:8px; box-shadow:0 4px 6px rgba(0,0,0,0.1);">

                <div style="text-align:center; margin-bottom:30px; padding-bottom:15px;
                            border-bottom:1px solid #e2e8f0;">
                    <h1 style="margin:0; color:#1a365d;">📄 Tariff Update Request</h1>
                    <p style="color:#718096; font-size:13px;">
                        Generated on {datetime.now().strftime('%d %B %Y')}
                    </p>
                </div>

                {user_header_html}
                {account_html}
                {request_html}
                {cta_html}

                <div style="margin-top:40px; padding-top:15px; border-top:1px solid #e2e8f0;
                            text-align:center; font-size:12px; color:#a0aec0;">
                    <p>This message was generated automatically.</p>
                    <p>© {datetime.now().year} Operations Team</p>
                </div>

            </div>
        </body>
        </html>
        """

        return final_email_html, subject, images

    async def list_users_template(self, session: SessionDB, message: Optional[str] = None) -> ResponsePayloadCollection:
        def fmt_date(dt):
            if not dt:
                return "N/A"
            return dt.strftime('%Y-%m-%d')

        def fmt_bool(b):
            return "✓" if b else "✗"

        user_search = session.data.user_search
        page_size = 5

        # Load users
        users: List[UserDB] = []
        if user_search and user_search.ids:
            for user_id in user_search.ids:
                user, _ = await self.sql_db.get_user_by_id(user_id)
                if user:
                    users.append(user)

        # ---------- PAGE INFO ----------
        total = user_search.total or 0
        current_page = (user_search.offset // page_size) + 1 if total else 1
        total_pages = max(1, (total + page_size - 1) // page_size)

        # ---------- HEADER ----------
        lines = [
            "Task - User Management",
            f"Total users: {total}",
        ]

        if message:
            lines.append(f"\n{message}")

        if not users:
            lines.append(f"\n⚠️ No users found")

        # ---------- USER CARDS ----------
        for i, user in enumerate(users, 1):
            # Get user route statistics
            route_stats, _ = await self.sql_db.get_user_route_stats(str(user.id))
            total_routes = route_stats.get('total', 0) if route_stats else 0
            active_routes = route_stats.get('active', 0) if route_stats else 0
            completed_routes = route_stats.get('completed', 0) if route_stats else 0
            deleted_routes = route_stats.get('deleted', 0) if route_stats else 0
            draft = route_stats.get('draft', 0) if route_stats else 0

            tariff_db, err = await self.sql_db.get_tariff(user)
            tariff_name = tariff_db.name if tariff_db else "Unknown"

            lines.extend([
                "",
                f"{i}. {user.first_name or ''} {user.last_name or ''}",
                f"    ID: {user.id}",
                f"    Tariff: {tariff_name}",
                f"    Telegram: @{user.telegram_user_name or 'N/A'} (ID: {user.telegram_id or 'N/A'})",
                f"    User role: {user.role or 'N/A' }",
                f"    Email: {user.email or 'N/A'}",
                f"    Company: {user.company_name or 'N/A'}",
                f"    Registered: {fmt_date(user.registration_date)}",
                f"    Status: {'Active' if user.is_active else 'Blocked'} {fmt_bool(user.is_active)}",
                f"    Admin: {fmt_bool(user.is_admin)}",
                f"    Messages: {user.message_count or 0}",
                f"    Routes: Total: {total_routes} (Active: {active_routes}, Draft: {draft} Completed: {completed_routes}, Deleted: {deleted_routes})",
                f"    Free tier expires: {fmt_date(user.free_tier_expiry)}",
                f"    Last updated: {fmt_date(user.updated_at)}",
            ])

        lines.append(f"\nPage: {current_page} of {total_pages}")

        # ---------- COMMANDS ----------
        lines.extend([
            "",
            "Commands:",
            ' - "+" - show next page',
            ' - "-" - show previous page',
            ' - block "user_id" - block a user',
            ' - unblock "user_id" - unblock a user',
            ' - stats "user_id" - show user statistics',
            ' - search "term" - search by email/name/telegram',
            ' - show "user_id" - show detailed user info',
            ' - update tariff to - start tariff updating'
        ])

        navigation_text = self.navigation_handler.get_navigation_text(session)
        text = "\n".join(lines) + "\n" + navigation_text
        response = ResponsePayload(text=text)

        return ResponsePayloadCollection(responses=[response])

    async def show_user_stats_template(self, user: UserDB, route_stats: Dict) -> ResponsePayloadCollection:
        def fmt_date(dt):
            if not dt:
                return "N/A"
            return dt.strftime('%Y-%m-%d %H:%M')

        lines = [
            f"📊 User Statistics for {user.first_name or ''} {user.last_name or ''}",
            f"ID: {user.id}",
            f"Email: {user.email or 'N/A'}",
            f"Telegram: @{user.telegram_user_name or 'N/A'}",
            f"Status: {'Active ✓' if user.is_active else 'Blocked ✗'}",
            "",
            "📈 Route Statistics:",
            f"  Total routes: {route_stats.get('total', 0)}",
            f"  Active routes: {route_stats.get('active', 0)}",
            f"  Completed routes: {route_stats.get('completed', 0)}",
            f"  Deleted routes: {route_stats.get('deleted', 0)}",
            f"  Draft routes: {route_stats.get('draft', 0)}",
            "",
            "📊 User Activity:",
            f"  Messages sent: {user.message_count or 0}",
            f"  Registered: {fmt_date(user.registration_date)}",
            f"  Last active: {fmt_date(user.updated_at)}",
            f"  Current tariff: {user.current_tariff_id or 'Free tier'}",
            f"  Free tier expires: {fmt_date(user.free_tier_expiry)}",
        ]

        if user.company_name:
            lines.append(f"  Company: {user.company_name}")

        text = "\n".join(lines)
        return ResponsePayloadCollection(responses=[ResponsePayload(text=text)])

    async def update_tariff_template_simple(self, session: SessionDB, message: str = None):
        l = [
            "Admin - Update user tariff"
        ]

        if session.data.admin_update_tariff.user_id:
            user_db, err = await self.sql_db.get_user_by_id(uuid.UUID(session.data.admin_update_tariff.user_id))

            if user_db:
                l.append(f"Target user: {user_db.first_name} {user_db.last_name} {user_db.telegram_user_name}")

        tariff = None
        if session.data.admin_update_tariff.target_tariff_id:
            tariff, err = await self.sql_db.get_tariff_by_id( session.data.admin_update_tariff.target_tariff_id)

            if tariff:
                l.append(f"Target tariff: {tariff.name}")



        l.extend([
            "\nEnter the new tariff name (number)"
        ])

        if tariff:
            l[-1] += " or confirm selected."


        tariffs, err = await self.sql_db.get_available_tariffs()

        if tariffs:
            for i, t in enumerate(tariffs, 1):
                l.append(f"{i}. {t.name}")

        nav = self.navigation_handler.get_navigation_text(session)
        l.append(nav)
        text = "\n".join(l)

        return ResponsePayloadCollection(responses=[ResponsePayload(text=text)])

    async def new_start_template(self, session: SessionDB, message: str = None, is_admin: bool = False):
        lines = [
            f"{emogye.THIS}  <b> To tailor the results for you, please share your role to https://thebunkering.com/.</b> ",
        ]

        user, err = await self.sql_db.get_user_by_id(session.user_id)
        if err:
            lines.extend([
                "\n",
                " <b> Could not find the user. Try again please. </b> "
            ])
        else:
            lines.extend([
                #"\nCurrently selected role: " + user.role if user.role else "not selected",
                #"After role selected, please text \"fine\" or \"next\""
                f"\n{emogye.THIS}  <b> Please enter a number from the menu (e.g. 1, 2, 3). </b> "
            ])

        # if message:
        #     lines.extend(["\nNote: ", message])


        lines.extend([
            "\nOptions:",
            f"1. Ship owner {emogye.SHIP}",
            f"2. Ship operator {emogye.OPERATOR}",
            f"3. Fleet / Voyage manager {emogye.COMPASS}",
            f"4. Bunker trader / Supplier {emogye.OIL_DUM}",
            f"5. Charterer {emogye.STATS}",
            f"6. Technical / Other {emogye.MECHANICAL_KEY}"
        ])

        return ResponsePayloadCollection(responses=[ResponsePayload(text="\n".join(lines), keyboard=self.navigation_handler.get_role_choice_keyboard())])

    async def pdf_request_template(
            self,
            session: SessionDB,
            route: SeaRouteDB,
            message: Optional[str] = None
    ) -> ResponsePayloadCollection:
        """Template for PDF request confirmation step"""

        lines = [
            f"\nI can send you a PDF with the full breakdown {emogye.SMILE}",
            "",
            "It will include:",
            "- Route details",
            "- Prices",
            "- Bunkering ports",
            "- Totals",
            "",
            f"{emogye.THIS}  <b> Want me to do it? Yes(y)/No(n) </b> ",
        ]

        text = "\n".join(lines)

        if message:
            text += f"\n\nNote: {message}\n"

        header_text = self.navigation_handler.get_step_title(session.current_step)
        navigation_text = self.navigation_handler.get_navigation_text(session)
        text = header_text + text + navigation_text

        return ResponsePayloadCollection(responses=[ResponsePayload(text=text, keyboard=self.navigation_handler.get_yes_no_back_keyboard())])

    async def user_email_template(
            self,
            session: SessionDB,
            route: SeaRouteDB,
            email_received: bool = False,
            pdf_link: Optional[str] = None,
            message: Optional[str] = None
    ) -> ResponsePayloadCollection:
        """
        Template for user email step.
        When email is received, returns TWO messages:
        1) Generating PDF
        2) Done + delivery
        """

        user_email = None
        user_db, err = await self.sql_db.get_user_by_id(route.user_id)
        if not err and user_db:
            user_email = user_db.email

        navigation_text = self.navigation_handler.get_navigation_text(session)

        responses = []

        if not email_received:
            # ASK FOR EMAIL
            lines = [
                "\nGot it 🙂",
                "",
                "What email should I send the PDF to?" if not user_email else f"Your email is: {user_email}. Update if you want.",
                "",
                "Examples:",
                "- john.doe@example.com",
                "- ops@company.com",
                "",
                f"Please make sure the email address is correct.\n{emogye.THIS}  <b> Enter yes(y) to get email.</b> "
            ]

            text = "\n".join(lines)

            if message is not None:
                text += f"\n\nNote: {message}\n"

            text = text + navigation_text
            # responses[-1].keyboard = self.navigation_handler.get_navigation_keyboard(session)
            responses.append(ResponsePayload(text=text, keyboard=self.navigation_handler.get_navigation_keyboard(session.current_step)))

        else:
            # MESSAGE 1 — GENERATING
            text_1 = "\n".join([
                f"\nGreat {emogye.FINE}",
                "",
                "Generating the PDF now…"
            ])
            text_1 = text_1 #+ navigation_text

            responses.append(ResponsePayload(text=text_1))

            # MESSAGE 2 — DONE
            lines_2 = [
                "\nDone 🙂",
                "",
                "The PDF is in your email now."
            ]

            if pdf_link:
                lines_2.extend([
                    "",
                    "Here’s a direct link as well:",
                    f"👉 {pdf_link}"
                ])

            text_2 = "\n".join(lines_2)
            text_2 = text_2 #+ navigation_text

            responses.append(ResponsePayload(text=text_2))

        return ResponsePayloadCollection(responses=responses)

    # async def request_submitted_template(
    #         self,
    #         message: Optional[str] = None
    # ) -> ResponsePayloadCollection:
    #     """Template shown after request is submitted to suppliers"""
    #
    #     lines = [
    #         f"\nThanks {emogye.FINE}",
    #         "",
    #         "I’ve got everything I need for now.",
    #         "I’ll submit the request to suppliers",
    #         "and get back to you as soon as quotes are in.",
    #         "",
    #         "If anything needs to be changed,",
    #         "We can update the details at any time — no problem."
    #     ]
    #
    #     text = "\n".join(lines)
    #
    #     if message:
    #         text += f"\n\nNote: {message}\n"
    #
    #     return ResponsePayloadCollection(responses=[ResponsePayload(text=text)])

    # def render_delivery_basis(self, port: SeaPortDB):
    #     icons = []
    #
    #     if port.barge_status:
    #         icons.append("🚢")
    #     if port.truck_status:
    #         icons.append("🚚")
    #     if getattr(port, "pipe_status", False):
    #         icons.append("🛢️")
    #
    #     return " ".join(icons) if icons else "—"

    def html_to_pdf(self, html: str) -> bytes:
        buffer = BytesIO()
        HTML(string=html).write_pdf(buffer)
        return buffer.getvalue()

    async def format_option2_email2_jinja(self, user, route):
        departure, _ = await self.sql_db.get_port_by_id(route.departure_port_id)
        destination, _ = await self.sql_db.get_port_by_id(route.destination_port_id)
        steps = [s for s in route.bunkering_steps if s.selected]
        images = []

        # User info
        user_db, err = await self.sql_db.get_user_by_id(route.user_id)
        subject = f"BunkeringBot {user_db.first_name or ''} {user_db.last_name or ''} {user_db.telegram_user_name or ''}" if user_db else ""
        if route.data.quote_requested:
            subject += " WITH BUNKER QUOTES REQUEST!"

        # Map image
        indexed = []
        if departure:
            indexed.append(departure.to_indexed2(emogye.ARROW_UP, "green", "medium", True))
        if destination:
            indexed.append(destination.to_indexed2(emogye.ARROW_DOWN, "red", "medium", True))
        for step in steps:
            if not step.selected:
                continue

            indexed.append(step.port.to_indexed2(str(step.n), "blue", "medium", False))

        image_data, image_err = await self.map_image_api.render_map(
            route.data.departure_to_destination_coordinates,
            indexed
        )
        map_link = self.map_image_api.get_route_map_link(str(route.id))

        # CONVERT PNG BYTES TO BASE64
        if image_data and not image_err:
            # Check if it's already base64 string
            if isinstance(image_data, str) and image_data.startswith('data:image'):
                # Already base64
                images.append(image_data.split(',')[1] if ',' in image_data else image_data)
            elif isinstance(image_data, bytes):
                # Convert PNG bytes to base64
                base64_image = base64.b64encode(image_data).decode('utf-8')
                images.append(base64_image)
            else:
                print(f"Unexpected image data type: {type(image_data)}")


    # Voyage overview
        overview = {
            "user": user,
            "departure": departure.format_port().replace("\n", ""),
            "destination": destination.format_port().replace("\n", ""),
            "departure_date": route.departure_date,
            "average_speed": route.average_speed_kts,
            "vessel_name": route.vessel_name,
            "imo_number": route.imo_number,
            "map_link": map_link
        }

        # Build fuel table
        # First, collect all unique fuels from all steps
        all_fuels_set = {fuel for step in steps for fuel in step.fuel_info.keys()}

        # Define preferred order - VLS FO and MGO LS must go first
        preferred_order = ["VLS FO", "MGO LS"]

        # Sort fuels: first preferred ones in order, then others alphabetically
        all_fuels = []
        # Add preferred fuels first (if they exist in the data)
        for fuel in preferred_order:
            if fuel in all_fuels_set:
                all_fuels.append(fuel)

        # Add remaining fuels (excluding the ones already added) in alphabetical order
        remaining_fuels = sorted([f for f in all_fuels_set if f not in preferred_order])
        all_fuels.extend(remaining_fuels)

        table_rows = []
        for step in steps:
            p = step.port
            dm = self.render_delivery_basis(p)
            if not len(dm) > 0 or dm != "":
                dm = emogye.LINE
            row = {
                "Port": p.format_port().replace("\n", ""),
                "ETA": step.eta_datetime.strftime("%B %d, %Y") if step.eta_datetime else emogye.LINE,
                "Port info": p.agent_contact_list or emogye.LINE,
                "Fuel delivery method": dm
            }

            for fuel in all_fuels:
                info = step.fuel_info.get(fuel, {})
                qty = info.get("quantity") or 0
                price = info.get("fuel_price")
                row[fuel] = f"{qty} mt — ${price}" if price else f"{qty} mt — Price on request"
            table_rows.append(row)

        # Cost summary
        fuel_totals = {}
        total_cost = 0
        for step in steps:

            # Sort fuels: first preferred ones in order, then others alphabetically
            all_fuels = []
            # Add preferred fuels first (if they exist in the data)
            for fuel in preferred_order:
                if fuel in all_fuels_set:
                    all_fuels.append(fuel)

            # Add remaining fuels (excluding the ones already added) in alphabetical order
            remaining_fuels = sorted([f for f in all_fuels_set if f not in preferred_order])
            all_fuels.extend(remaining_fuels)

            step_fuels = {fuel: step.fuel_info[fuel] for fuel in all_fuels}


            for fuel_name, info in step_fuels.items():
                qty = info.get("quantity") or 0
                price = info.get("fuel_price") or 0
                cost = qty * price
                total_cost += cost
                if fuel_name not in fuel_totals:
                    fuel_totals[fuel_name] = {"qty": 0, "cost": 0}
                fuel_totals[fuel_name]["qty"] += qty
                fuel_totals[fuel_name]["cost"] += cost

        # Render Jinja2 template
        template = env.get_template("bunkering_report.html")
        html_content = template.render(
            images=images,
            overview=overview,
            table_rows=table_rows,
            table_columns=["Port", "ETA", "Port info", "Fuel delivery method"] + all_fuels,
            fuel_totals=fuel_totals,
            total_cost=total_cost,
            generation_date=datetime.now().strftime("%d %B %Y"),

        )

        file_name = f"{overview['departure']} to {overview['destination']} at {overview['departure_date']}"
        html_content_bytes = self.html_to_pdf(html_content)
        file_obj = MediaFile(filename=file_name, content=html_content_bytes)
        return  html_content, html_content_bytes, file_obj, subject, images, image_data if not image_err else b''

    async def supplier_prices_template(
            self,
            session,
            route,
            message: str = None,
            status : bool = None
    ):

        header_text = self.navigation_handler.get_step_title(session.current_step,)

        text = header_text
        keyboard = None

        if not status:
            text += f"\n\nI can request live supplier prices — free and with no obligation.\n{emogye.THIS}  <b> Want me to do that? (Yes/No). </b> "
            keyboard = self.navigation_handler.get_yes_no_back_keyboard()
        else:
            text += f"\n\nPerfect {emogye.FINE}\nI’ll reach out to suppliers and get back to you with live quotes.\nMight need a couple of quick details along the way."

        if message:
            text += "\n" + message

        return ResponsePayloadCollection(responses=[ResponsePayload(text=text, keyboard=keyboard)])

    def get_supplier_request(self, session: SessionDB, route: SeaRouteDB, message: Optional[str] = None):
        lines = []

        if route.data.quote_requested:
            lines.extend([
                f"{emogye.FINE} The request was sent!",
                "",
                f"{emogye.OIL_STATION}  <b> Supplier requests will help confirm real prices and availability </b> ",
                "for your route."
            ])

        else:
            lines.extend([
                f"{emogye.FINE} No problem — the request was not sent.",
                "",
                f"{emogye.OIL_STATION}  <b> Supplier requests help confirm real prices and availability </b> ",
                "for your route."
            ])

        return ResponsePayloadCollection(responses=[ResponsePayload(text="\n".join(lines))])


    async def company_name_template(self, session, route, message: str = None):
        company_name = None
        user_db, err = await self.sql_db.get_user_by_id(route.user_id)
        if not err and user_db:
            company_name = user_db.company_name

        navigation_text = self.navigation_handler.get_navigation_text(session)

        responses = []

        lines = [
            f"Quick check {emogye.SMILE}",
            "What company name should I use for the supplier request?" if not company_name else f"Is company name \"{company_name}\" correct? \n <b> Enter new to update. </b> "
        ]

        text = "\n".join(lines)

        if message:
            text += f"\n\nNote: {message}\n"

        text = text + navigation_text

        responses.append(ResponsePayload(text=text, keyboard=self.navigation_handler.get_navigation_keyboard(session)))

        return ResponsePayloadCollection(responses=responses)


    def new_route_finish(self, route: SeaRouteDB):
        l = [
            f"Thanks {emogye.FINE}",
            "",
            "I’ve got everything I need for now.",
            "I’ll submit the request to suppliers \nand get back to you as soon as quotes are in.\n" if route.data.pdf_requested else "",
            "If anything needs to be changed, you can always change this later — just go to",
            "Main menu → 2."
        ]

        return ResponsePayloadCollection(
            responses=[
                ResponsePayload(
                    text="\n".join(l)
                )
            ]
        )

    async def sos_template(self, super_admin: Optional["UserDB"]) -> ResponsePayloadCollection:
        """
        Returns a template message to the user notifying that their SOS request
        has been received and the admin will contact them.
        """
        admin_contact = []

        if super_admin:
            if super_admin.telegram_user_name:
                admin_contact.append(f"Telegram: @{super_admin.telegram_user_name}")
            if super_admin.phone_number:
                admin_contact.append(f"Phone: {super_admin.phone_number}")

        contact_info = "\n".join(admin_contact) if admin_contact else "Admin will contact you soon."

        message_lines = [
            "✅ Your SOS request has been received!",
            "Our admin will get back to you shortly.",
            "",
            contact_info
        ]

        return ResponsePayloadCollection(
            responses=[
                ResponsePayload(text="\n".join(message_lines))
            ]
        )


