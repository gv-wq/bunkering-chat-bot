from io import BytesIO
from typing import Dict, Tuple, Optional

from telegram import Update, InputFile
from telegram.ext import ContextTypes
from telegram import Update, InputMediaPhoto
from app.data import emogye
from app.data.dto.main.SessionData import SessionData, RouteSearch
from app.data.dto.main.TariffSelection import TariffSelection
from app.data.dto.main.User import UserDB
from app.data.enums.RouteStep import RouteStepEnum
from app.data.enums.StartStepEnum import StartStepEnum
from app.domain.message import IncomingMessage
from app.domain.response import OutgoingResponse
from app.handlers.admin_handler import AdminHandler
from app.handlers.update_tariff_handler import UpdateTariffHandler
from app.services.external_api.bubble_api import BubbleApi
from app.services.external_api.searoute_api import SearouteApi
from app.services.internal_api.map_builder_api import MapBuilderApi

from app.data.dto.main.Session import SessionDB
from app.data.dto.messenger.ResponsePayload import (
    ResponsePayload,
    ResponsePayloadCollection,
)
from app.data.enums.RouteTask import RouteTaskEnum

from app.handlers.main_menu_handler import MainMenuHandler
from app.handlers.navigation_handler import NavigationHandler
from app.handlers.new_route_handler import NewRouteHandler
from app.handlers.search_route_handler import SearchRouteHandler
from app.handlers.seaport_handler import SeaportHandler
from app.services.ai_service import AiService
from app.services.db_service import DbService
from app.services.template.telegram_template_service import TemplateService
from app.services.utils import utils
from app.services.utils.island_projection import IslandProjection
from app.services.utils.near_country_search import RouteCountryFinder


class CoreService:
    def __init__(
        self,
        ai_service: AiService,
        template_service: TemplateService,
        sql_db_service: DbService,
        searoute_api: SearouteApi,
        #bubble_api: BubbleApi,
        navigation_handler: NavigationHandler,
        map_image_api: MapBuilderApi,
        admin_handler: AdminHandler,
        projector: IslandProjection,
        country_finder: RouteCountryFinder

    ):
        self.admin_handler = admin_handler
        self.sql_db_service = sql_db_service
        self.ai_service = ai_service
        self.template_service = template_service

        self.navigation_handler = navigation_handler
        self.main_menu_handler = MainMenuHandler(
            ai_service, sql_db_service, template_service
        )
        self.new_route_handler = NewRouteHandler(
            ai_service=ai_service,
            sql_db_service=sql_db_service,
            template_service=template_service,
            navigation_handler=navigation_handler,
            searoute_api=searoute_api,
          #  bubble_api=bubble_api,
            map_image_api=map_image_api,
            projector=projector,
            country_finder=country_finder
        )

        self.search_route_handler = SearchRouteHandler(
            ai_service=ai_service,
            db_service=sql_db_service,
            template_service=template_service,
            navigation_handler=navigation_handler
        )

        self.seaport_handler = SeaportHandler(
            ai_service=ai_service,
            sql_db_service=sql_db_service,
            template_service=template_service,
            navigation_handler=navigation_handler,
            searoute_api=searoute_api
        )
        self.update_tariff_handler = UpdateTariffHandler(
            ai_service=ai_service,
            sql_db_service=sql_db_service,
            template_service=template_service,
            navigation_handler=navigation_handler,)

        self.tg_bot = None

    def set_bot(self, tg_bot):
        self.tg_bot = tg_bot

    async def get_or_create_user(self, msg: IncomingMessage) -> Tuple[Optional[UserDB], Optional[str]]:
        """
        Get or create user for either Telegram or WhatsApp
        channel: 'telegram' or 'whatsapp'
        """

        user = None

        if msg.source == "telegram" and msg.user_id:
            user, err = await self.sql_db_service.get_user_by_telegram_id(int(msg.user_id))
            if err:
                return None, err

        elif msg.source == "whatsapp" and msg.user_id:
            user, err = await self.sql_db_service.get_user_by_phone_number(msg.user_id)
            if err:
                return None, err


        if user:
            # Update channel-specific info if needed
            update_fields = {}

            if msg.source == "whatsapp":
                if msg.source and not user.whatsapp_phone:
                    update_fields["whatsapp_phone"] = msg.source
                if msg.chat_id and not user.whatsapp_effective_chat:
                    update_fields["whatsapp_effective_chat"] = msg.chat_id

                if msg.meta.get("whatsapp_name", False) and not user.whatsapp_name:
                    update_fields["whatsapp_name"] = msg.meta.get("whatsapp_name")

                # If this is a WhatsApp user but phone matches telegram user's phone
                if msg.user_id and msg.user_id.replace("+", "") == user.phone_number.replace("+", "") and not user.whatsapp_phone:
                    update_fields["whatsapp_phone"] = msg.user_id

            if update_fields:
                user, err = await self.sql_db_service.update_user(str(user.id), update_fields)
                if err:
                    #logger.error(f"Failed to update user: {err}")
                    pass

            return user, None

        # Create new user
        if msg.source == "telegram":
            d = {
                "telegram_id": msg.user_id,
                "telegram_effective_chat_id": msg.chat_id,
                "telegram_user_name": msg.meta.get("telegram_user_name"),
                "phone_number": msg.meta.get("phone_number"),
                "first_name": msg.meta.get("first_name"),
                "last_name": msg.meta.get("last_name"),
            }
            new_user, err = await self.sql_db_service.create_user(d)
            await self._notify_admin_new_user(new_user,"Telegram")

        elif msg.source == "whatsapp":
            d = {
                "phone_number": msg.user_id,
                "whatsapp_effective_chat": msg.chat_id,
                "first_name": msg.meta.get("whatsapp_name"),
            }
            new_user, err = await self.sql_db_service.create_user(d)
            if not new_user or err:
                return None, "Could not create user"

            await self._notify_admin_new_user(new_user, "WhatsApp")

        else:
            return None, f"Unsupported channel: {msg.source}"

        return new_user, None

    async def _notify_admin_new_user(self, user: UserDB, platform: str):
        """Notify admin about new user registration"""
        try:
            super_admin, err = await self.sql_db_service.get_user_by_telegram_name("gee_vo")
            if err or not super_admin or not super_admin.telegram_effective_chat_id:
                return

            fields = [f"Platform: {platform}"]

            if platform == "Telegram":
                if user.telegram_user_name:
                    fields.append(f"Username: @{user.telegram_user_name}")
                if user.first_name:
                    fields.append(f"First: {user.first_name}")
                if user.last_name:
                    fields.append(f"Last: {user.last_name}")
                if user.phone_number:
                    fields.append(f"Phone: {user.phone_number}")
                if user.email:
                    fields.append(f"Email: {user.email}")

            elif platform == "WhatsApp":
                if user.phone_number:
                    fields.append(f"Phone: {user.phone_number}")
                if user.whatsapp_name:
                    fields.append(f"Name: {user.whatsapp_name}")
                if user.phone_number:
                    fields.append(f"Additional phone: {user.phone_number}")
                if user.email:
                    fields.append(f"Email: {user.email}")

            message = "📱 New user registered!\n\n" + "\n".join(fields)

            if not self.tg_bot:
                return

            await self.tg_bot.send_message(chat_id=super_admin.telegram_effective_chat_id, text=message)

        except Exception:
            pass

    async def handle(self, msg: IncomingMessage, start_status: bool = False) -> ResponsePayloadCollection:
        if not utils.is_valid_message(msg.text):
            return ResponsePayloadCollection(responses=[ResponsePayload(text=f"{emogye.BRITAIN_FLAG}/{emogye.USA_FLAG} language please. Chars and digits.")])

        user_db, err = await self.get_or_create_user(msg)
        if not user_db or err:
            return ResponsePayloadCollection(responses=[ResponsePayload(text="could not register  you, something went wrong")])

        if not user_db.is_active:
            return ResponsePayloadCollection(responses=[ResponsePayload(text="Sorry, yor account was suspended.\n Please contact +971 58 584 6441 to get help.")])

        user_tariff, err = await self.sql_db_service.get_tariff(user_db)
        if err:
            return ResponsePayloadCollection(responses=[ResponsePayload(err=err)])

        session, err = await self.sql_db_service.get_or_create_session(user_db.id)
        if err:
            return ResponsePayloadCollection(responses=[ResponsePayload(err=err)])

        user_routes_count, err = await self.sql_db_service.count_routes(str(user_db.id))
        if user_routes_count and not err:
            user_db.route_count = user_routes_count

        intent, err = await self.ai_service.parse_navigation_intent(msg.text, user_db.is_admin is True)
        if err:
            return ResponsePayloadCollection(responses=[ResponsePayload(err=f"Intent parsing error: {err}")])

        if user_tariff.exceeded(user_db.route_count, user_db.message_count) and not user_db.is_admin is True:
            intent["update_tariff"] = True


        if user_db.message_count == 0:
            intent["is_start"] = True

        if start_status:
            intent["is_start"] = True

        if user_db.role is None:
            intent["is_start"] = True

        response = await self._handle_session_flow(user_db, session, intent, msg.text)

        message_count = user_db.message_count + 1
        user_db, err = await self.sql_db_service.update_user(str(user_db.id), {"message_count": message_count})
        return response


    async def _handle_session_flow(self, user: UserDB, session: SessionDB, intent: Dict, message: str) -> ResponsePayloadCollection:
        if intent.get("update_tariff", None):
            session, err = await self.sql_db_service.update_session(session.user_id, RouteTaskEnum.UPDATE_TARIFF.value,None,None, session.data)

        if intent.get("is_start", None):
            session, err = await self.sql_db_service.update_session(session.user_id, RouteTaskEnum.START.value,None, None, session.data)

        if intent["main_menu"]:
            if session.current_step in (StartStepEnum.ROLE.value, StartStepEnum.USER_NAME.value):
                return await self.main_menu_handler.handle_start(session, message, user.is_admin)

            session, err = await self.main_menu_handler.to_main_menu(session)

        elif intent["prev_step"]:
            if session.current_step in (StartStepEnum.ROLE.value, StartStepEnum.USER_NAME.value):
                return await self.main_menu_handler.handle_start(session, message, user.is_admin)


            session, err = await self.navigation_handler.to_prev_step(session)
            return await self.template_service.session_template(session, err, is_admin=user.is_admin)

        # elif intent["next_step"]:
        #     session, err = await self.navigation_handler.to_next_step(session)
        #     return await self.return_session_template(session, err)

        elif intent["target_step"]:
            session, err = await self.navigation_handler.switch_session_step(
                session, intent["target_step"]
            )

        if session.current_task == RouteTaskEnum.START.value:
            return await self.main_menu_handler.handle_start(session, message, user.is_admin)

        if session.current_task is None:
            session, err = await self.main_menu_handler.to_main_menu(session)
            return await self.main_menu_handler.template_service.main_menu_template(session, is_admin=user.is_admin)

        if session.current_task == RouteTaskEnum.MAIN_MENU.value:
            return await self.main_menu_handler.handle_main_menu(session, message, user.is_admin)

        elif session.current_task == RouteTaskEnum.CREATE_ROUTE.value:
            return await self.new_route_handler.handle_create_route_flow(session=session, message=message)

        elif session.current_task == RouteTaskEnum.GET_PORT_PRICE.value:
            return await self.seaport_handler.handle(session=session, message=message)

        elif session.current_task == RouteTaskEnum.SEARCH_ROUTE.value:
            return await self.search_route_handler.handle(session=session, message=message)

        elif session.current_task == RouteTaskEnum.UPDATE_TARIFF.value:
            return await self.update_tariff_handler.handle(session=session, message=message)

        else:
            return ResponsePayloadCollection(
                responses=[
                    ResponsePayload(
                        text="Seems like I dont know what to do =)."
                    )
                ]
            )
