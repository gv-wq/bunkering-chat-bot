from typing import Dict, Tuple, Optional

from telegram import Update
from telegram.ext import ContextTypes
from telegram import Update, InputMediaPhoto
from app.data import emogye
from app.data.dto.main.SessionData import SessionData, RouteSearch
from app.data.dto.main.TariffSelection import TariffSelection
from app.data.dto.main.User import UserDB
from app.data.enums.RouteStep import RouteStepEnum
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


class CoreService:
    def __init__(
        self,
        ai_service: AiService,
        template_service: TemplateService,
        sql_db_service: DbService,
        searoute_api: SearouteApi,
        bubble_api: BubbleApi,
        navigation_handler: NavigationHandler,
        map_image_api: MapBuilderApi,
        admin_handler: AdminHandler,


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
            bubble_api=bubble_api,
            map_image_api=map_image_api,
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

    async def get_or_create_user(
            self,
            context:ContextTypes.DEFAULT_TYPE,
            telegram_user_id: int,
            telegram_effective_chat_id: int,
            user_data: dict = None
    ) -> Tuple[Optional[UserDB], Optional[str]]:
        user, err = await self.sql_db_service.get_user_by_telegram_id(telegram_user_id)
        if err:
            return None, err
        if user:
            return user, None

            # Create new user with new fields
        telegram_user_name = user_data.get("telegram_user_name") if user_data else None
        phone_number = user_data.get("phone_number") if user_data else None
        first_name = user_data.get("first_name") if user_data else None
        last_name = user_data.get("last_name") if user_data else None
        email = user_data.get("email") if user_data else None

        new_user, err = await self.sql_db_service.create_user(
            telegram_id=telegram_user_id,
            telegram_user_name=telegram_user_name,
            phone_number=phone_number,
            first_name=first_name,
            last_name=last_name,
            email=email,
            telegram_effective_chat_id=telegram_effective_chat_id
        )

        super_admin, err = await self.sql_db_service.get_user_by_telegram_name("gee_vo")
        if err:
            return new_user, None

        if not super_admin:
            return new_user, None

        fields = {
            "Telegram user name": f"@{telegram_user_name}" if telegram_user_name else None,
            "Phone number": phone_number,
            "First name": first_name,
            "Last name": last_name,
            "Email": email,
        }

        l = ["You have new user!"] + [
            f"{label}: {value}" for label, value in fields.items() if value
        ]
        message = "\n".join(l)
        try:
            r = await context.bot.send_message(chat_id=super_admin.telegram_effective_chat_id, text=message)
        except Exception as e:
            pass

        return new_user, None





    async def handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            f'{emogye.HI} Hi!\n'
            'I help ship owners, operators & managers\n'
            'plan a vessel route, view bunker prices\n'
            'along the route, and estimate fuel costs — in under 2 minutes.\n\n'
            f'Powered by AI-assisted route & bunker analysis.\n'
            f'No spam.',
            parse_mode="HTML"
        )

        try:
            response_collection: ResponsePayloadCollection = await self.handle_message(update, context, True)

            for response_payload in response_collection.responses:

                # Handle error
                if response_payload.err:
                    await update.message.reply_text(f"❌ Error: {response_payload.err}")
                    continue

                # Handle multiple images → send album
                if response_payload.has_images():
                    media_group = []

                    for idx, img_bytes in enumerate(response_payload.images):
                        media_group.append(
                            InputMediaPhoto(
                                media=img_bytes,
                                caption=response_payload.text if idx == 0 else "",
                                parse_mode="HTML"
                            )
                        )

                    await update.message.reply_media_group(media=media_group)
                    continue

                # Handle text-only message
                if response_payload.has_text():
                    await update.message.reply_text(
                        response_payload.text,
                        parse_mode="HTML"
                    )
                    continue

                # Nothing at all
                await update.message.reply_text("No response generated", parse_mode="HTML")

        except Exception as e:
            await update.message.reply_text(
                f"❌ Unexpected error: {str(e)}",
                parse_mode="HTML"
            )
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE, is_start : bool = False) -> ResponsePayloadCollection:

        if not utils.is_valid_message(update.message.text):
            return ResponsePayloadCollection(responses=[ResponsePayload(text=f"{emogye.BRITAIN_FLAG}/{emogye.USA_FLAG} language please. Chars and digits.")])

        user_data = {
            "first_name": update.effective_user.first_name,
            "last_name": update.effective_user.last_name,
            "telegram_user_name": update.effective_user.username,
        }
        user_db, err = await self.get_or_create_user(context=context, telegram_user_id=update.effective_user.id,telegram_effective_chat_id=update.effective_chat.id, user_data=user_data )
        #user_db, err = await self.sql_db_service.get_or_create_user(update.effective_user.id, user_data)
        if err:
            return ResponsePayloadCollection(responses=[ResponsePayload(err=err)])

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

        intent, err = await self.ai_service.parse_navigation_intent(update.message.text, user_db.is_admin is True)
        if err:
            return ResponsePayloadCollection(
                responses=[ResponsePayload(err=f"Intent parsing error: {err}")]
            )

        if user_tariff.exceeded(user_db.route_count, user_db.message_count) and not user_db.is_admin is True:
            intent["update_tariff"] = True

        if is_start:
            intent["is_start"] = True

        if user_db.role is None:
            intent["is_start"] = True

        response = await self._handle_session_flow(user_db, session, intent, update.message.text)

        message_count = user_db.message_count + 1
        user_db, err = await self.sql_db_service.update_user(str(user_db.id), {"message_count": message_count})

        return response

    async def _handle_session_flow(self, user: UserDB, session: SessionDB, intent: Dict, message: str) -> ResponsePayloadCollection:
        if intent.get("update_tariff", None):
            session, err = await self.sql_db_service.update_session(session.user_id, RouteTaskEnum.UPDATE_TARIFF.value,None,None, session.data)

        if intent.get("is_start", None):
            session, err = await self.sql_db_service.update_session(session.user_id, RouteTaskEnum.START.value,None, None, session.data)

        if intent["main_menu"]:
            session, err = await self.main_menu_handler.to_main_menu(session)

        elif intent["prev_step"]:
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

        # elif session.current_task == RouteTaskEnum.ADMIN.value:
        #     return await self.admin_handler.handle(session=session, message=message)
        else:
            return ResponsePayloadCollection(
                responses=[
                    ResponsePayload(
                        text="Seems like I dont know what to do =)."
                    )
                ]
            )
