from app.data import emogye
from app.data.dto.main.User import UserDB
from app.data.dto.messenger.ResponsePayload import ResponsePayloadCollection, ResponsePayload
from app.data.enums.RouteTask import RouteTaskEnum

from app.data.dto.main.Session import SessionDB
from app.handlers.navigation_handler import NavigationHandler
from app.services.ai_service import AiService
from app.services.db_service import DbService
from app.services.email_sender import EmailSender
from app.services.template.telegram_template_service import TemplateService
from app.services.utils import utils


class UpdateTariffHandler:
    def __init__(
            self,
            ai_service: AiService,
            sql_db_service: DbService,
            template_service: TemplateService,
            navigation_handler: NavigationHandler,
    ):
        self.ai_service = ai_service
        self.sql_db_service = sql_db_service
        self.template_service = template_service
        self.navigation_handler = navigation_handler
        self.email_sender = EmailSender()

    async def handle(self, session: SessionDB, message: str):
        intent_dict, err = await self.ai_service.parse_update_tariff_intent(message)
        if err:
            return ResponsePayloadCollection(responses=[ResponsePayload(err=err)])

        info = [
            intent_dict.get("name", None) is not None,
            intent_dict.get("mobile_phone_number", None) is not None,
            intent_dict.get("email", None) is not None,
            intent_dict.get("company_name", None) is not None,
            intent_dict.get("user_message", None) is not None,
            intent_dict.get("chosen_tariff", None) is not None
        ]

        if any(info):
            intent_dict['action'] = "update"

        user_db, err = await self.sql_db_service.get_user_by_id(session.user_id)

        intent = intent_dict.get("action")
        if intent == "update":
            return await self._update_info(session, user_db, intent_dict)
        elif intent == "confirm":
            return await self._confirm_info(session, )
        else:
            return await self.template_service.update_tariff_template(session, user_db, "Sorry, I didn't understand your intent. Please try again.")

    async def _update_info(self, session: SessionDB, user_db: UserDB, intent_dict: dict):

        update = {}

        filled_name = intent_dict.get("name", None)
        if filled_name:
            update['filled_name'] = filled_name

        mobile_phone_number = intent_dict.get("mobile_phone_number", None)
        if mobile_phone_number:
            update['phone_number'] = mobile_phone_number

        email = intent_dict.get("email", None)
        if utils.is_valid_email(email):
            update['email'] = email

        company_name = intent_dict.get("company_name", None)
        if company_name:
            update['company_name'] = company_name

        user_message = intent_dict.get("user_message", None)
        if user_message:
            session.data.tariff_selection.user_message = user_message

        chosen_tariff = intent_dict.get("chosen_tariff", None)
        if chosen_tariff:
            session.data.tariff_selection.chosen_tariff = chosen_tariff

        session, err = await self.sql_db_service.update_session(
            session.user_id,
            session.current_task,
            session.current_step,
            None,
            session.data
        )

        updated_user, err = await self.sql_db_service.update_user(str(user_db.id), update)
        if err:
            return await self.template_service.update_tariff_template(session, user_db, str(err))
        return await self.template_service.update_tariff_template(session, user_db)


    async def _confirm_info(self, session: SessionDB):
        user_db, err = await self.sql_db_service.get_user_by_id(session.user_id)
        if err:
            return await self.template_service.update_tariff_template(session, user_db, str(err))

        err_messages = []

        if not user_db.filled_name:
            err_messages.append(f"{emogye.CROSS_RED} Your name")

        if not user_db.company_name:
            err_messages.append(f"{emogye.CROSS_RED} company name")

        if not user_db.email:
            err_messages.append(f"{emogye.CROSS_RED} email")

        if not user_db.phone_number:
            err_messages.append(f"{emogye.CROSS_RED} phone number")

        if not session.data.tariff_selection.chosen_tariff:
            err_messages.append(f"{emogye.CROSS_RED} chosen tariff")

        if len(err_messages) > 0:
            return await self.template_service.update_tariff_template(session, user_db, "Please fill: " + ", ".join(err_messages))

        text_content, subject, images = await self.template_service.format_tariff_update_email(user_db.id, session.data.tariff_selection.chosen_tariff, session.data.tariff_selection.user_message)
        email_status, err = await self.email_sender.route_report(subject, text_content, images)

        session, err = await self.sql_db_service.update_session(
            user_db.id,
            RouteTaskEnum.MAIN_MENU.value,
            None,
            None,
            session.data,
        )

        if err:
            return ResponsePayloadCollection(responses=[ResponsePayload(err=err)])

        return ResponsePayloadCollection(
            responses=[
                ResponsePayload(
                    text=f'{emogye.MEMO} Your request was sent. We will contact you as soon as possible!'
                )
            ]
        )






