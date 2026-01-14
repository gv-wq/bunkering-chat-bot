import uuid
from typing import Dict, List, Optional
from datetime import datetime
from app.data.dto.main.User import UserDB
from app.data.dto.main.Session import SessionDB
from app.data.dto.messenger.ResponsePayload import ResponsePayloadCollection, ResponsePayload
from app.data.enums.AdminStepEnum import AdminStepEnum
from app.data.enums.RouteStep import RouteStepEnum
from app.data.enums.RouteTask import RouteTaskEnum
from app.handlers.navigation_handler import NavigationHandler
from app.services.db_service import DbService
from app.services.template.telegram_template_service import TemplateService
from app.services.ai_service import AiService
from app.services.utils import utils


class AdminHandler:
    def __init__(self, db_service: DbService, template_service: TemplateService, ai_service: AiService, navigation_handler: NavigationHandler):
        self.ai_service = ai_service
        self.db_service = db_service
        self.template_service = template_service
        self.navigation_handler = navigation_handler

    async def handle(self, session: SessionDB, message: str) -> ResponsePayloadCollection:
        if session.current_step == AdminStepEnum.UPDATE_TARIFF.value:
            return await self.handle_tariff_update(session, message)
        return await self.handle_general(session, message)

    async def handle_tariff_update(self, session: SessionDB, message: str)-> ResponsePayloadCollection:
        intent, err = await self.ai_service.parse_update_tariff_intent_robust(message)
        if err or intent.get("action") == "err":
            return await self.template_service.update_tariff_template_simple(session, "Could not parse your intention.\nPlease try again.")

        action = intent.get("action")
        if action == "update":
            return await self.update_user_tariff(session, intent)
        elif action == "confirm":
            return await self.confirm_user_tariff(session, intent)

        return ResponsePayloadCollection(responses=[ResponsePayload(text="Try again.")])


    async def update_user_tariff(self, session: SessionDB, intent: dict) -> ResponsePayloadCollection:

        # user_id = intent.get("user_id")
        # if user_id:
        #     session.data.admin_update_tariff.user_id = user_id

        tariff_id = intent.get("tariff_id")
        if tariff_id:
            session.data.admin_update_tariff.target_tariff_id = tariff_id

        session_u, err = await self.db_service.update_session(session.user_id, session.current_task, session.current_step,  session.route_id, session.data)
        if err or not session_u:
            return await self.template_service.update_tariff_template_simple(session, f"Something went wrong: {err}")

        return await self.template_service.update_tariff_template_simple(session,)


    async def confirm_user_tariff(self, session: SessionDB, intent: dict) -> ResponsePayloadCollection:
        errors = []
        if not session.data.admin_update_tariff.user_id:
            errors.append("User to update tariff to was not selected")

        if not session.data.admin_update_tariff.target_tariff_id:
            errors.append("New tariff to update to was not selected")

        if len(errors) > 0:
            return await self.template_service.update_tariff_template_simple(session, "\n".join(errors))

        new_tariff, err = await self.db_service.get_tariff_by_id(session.data.admin_update_tariff.target_tariff_id)
        if not new_tariff or err:
            return await self.template_service.update_tariff_template_simple(session, "There is no such tariff.")

        user_db, err = await self.db_service.get_user_by_id(uuid.UUID(session.data.admin_update_tariff.user_id))
        if not user_db or err:
            return await self.template_service.update_tariff_template_simple(session, "There is no such user =).")

        new_user, err = await self.db_service.update_user(str(user_db.id), {"current_tariff_id": new_tariff.id})
        if not new_user or err:
            return await self.template_service.update_tariff_template_simple(session, "Could not update tariff.")

        session_u, err = await self.db_service.update_session(session.user_id, session.current_task, None,  session.route_id, session.data)

        #return ResponsePayloadCollection(responses=[ResponsePayload(text="The tariff has been updated.")])

        return await self.template_service.update_tariff_template_simple(session, "The tariff has been updated.")




    async def handle_general(self, session: SessionDB, message: str) -> ResponsePayloadCollection:
        # Parse user management intent
        intent_dict, err = await self.ai_service.parse_user_management_intent(session, message)
        if err:
            return ResponsePayloadCollection(responses=[ResponsePayload(err=err)])

        intent = intent_dict["action"]
        user_id = str(session.user_id)
        user_search = session.data.user_search
        # --------------------------------------------------------------
        # NAVIGATION (for user listing)
        # --------------------------------------------------------------
        if intent == "navigation":
            value = intent_dict.get("value")
            total = 999999

            # Count users based on current filters
            total_u, err = await self.db_service.count_users(
                status_filter=user_search.filter_status,
                admin_filter=user_search.filter_admin,
                search_term=user_search.search_term
            )
            if total_u and not err:
                total = total_u

            page_size = 4

            # Compute target offset
            if value == "+":
                user_search.offset += page_size
            elif value == "-":
                user_search.offset = max(0, user_search.offset - page_size)
            elif value == "start":
                user_search.offset = 0
            elif value == "end":
                remainder = total % page_size or page_size
                user_search.offset = max(0, total - remainder)

            user_search.total = total
            user_search.last_update = datetime.now()

            # Query users with filters
            users, err = await self.db_service.get_users_range(
                offset=user_search.offset,
                limit=page_size,
                status_filter=user_search.filter_status,
                admin_filter=user_search.filter_admin,
                search_term=user_search.search_term
            )

            if not err:
                user_search.ids = [str(u.id) for u in users]

            # Update session
            session, err = await self.db_service.update_session(
                session.user_id,
                RouteTaskEnum.ADMIN.value,
                None,
                None,
                session.data
            )

            return await self.template_service.list_users_template(session)

        elif intent == "start_tariff_update":
            user_id = intent_dict.get("user_id")

            session.data.admin_update_tariff.user_id = user_id
            session.current_step = AdminStepEnum.UPDATE_TARIFF.value

            session_u, err = await self.db_service.update_session(
                session.user_id,
                session.current_task,
                session.current_step,
                session.route_id,
                session.data,
            )

            if err or not session_u:
                return ResponsePayloadCollection(
                    responses=[ResponsePayload(text="Failed to start tariff update.")]
                )

            return await self.template_service.update_tariff_template_simple(session)


        # --------------------------------------------------------------
        # SEARCH USER
        # --------------------------------------------------------------
        elif intent == "search":
            search_term = intent_dict.get("search_term", "").strip()
            if not search_term:
                # If no search term provided, show all users
                user_search.search_term = None
                user_search.offset = 0
            else:
                user_search.search_term = search_term
                user_search.offset = 0

            # Reset other filters when searching
            user_search.filter_status = None
            user_search.filter_admin = None

            session, err = await self.db_service.update_session(
                session.user_id,
                session.current_task,
                session.current_step,
                session.route_id,
                session.data
            )

            # Navigate to show results
            intent_dict["value"] = "start"
            return await self.handle_navigation(session, intent_dict)

        # --------------------------------------------------------------
        # FILTER BY STATUS
        # --------------------------------------------------------------
        elif intent == "filter_status":
            status = intent_dict.get("status")
            if status in ["active", "blocked", "all"]:
                user_search.filter_status = status if status != "all" else None
                user_search.offset = 0
                user_search.search_term = None
                user_search.filter_admin = None


                session, err = await self.db_service.update_session(
                    session.user_id,
                    session.current_task,
                    session.current_step,
                    session.route_id,
                    session.data
                )

                # Navigate to show filtered results
                intent_dict["action"] = "navigation"
                intent_dict["value"] = "start"
                return await self.handle_navigation(session, intent_dict)

        # --------------------------------------------------------------
        # FILTER BY ADMIN STATUS
        # --------------------------------------------------------------
        elif intent == "filter_admin":
            is_admin = intent_dict.get("is_admin")
            if is_admin in [True, False]:
                user_search.filter_admin = is_admin
                user_search.offset = 0
                user_search.search_term = None

                session, err = await self.db_service.update_session(
                    session.user_id,
                    session.current_task,
                    session.current_step,
                    session.route_id,
                    session.data
                )

                # Navigate to show filtered results
                intent_dict["action"] = "navigation"
                intent_dict["value"] = "start"
                return await self.handle_navigation(session, intent_dict)

        # --------------------------------------------------------------
        # RESET FILTERS
        # --------------------------------------------------------------
        elif intent == "reset_filters":
            user_search.filter_status = None
            user_search.filter_admin = None
            user_search.search_term = None
            user_search.offset = 0

            session, err = await self.db_service.update_session(
                session.user_id,
                session.current_task,
                session.current_step,
                session.route_id,
                session.data
            )

            # Navigate to show all users
            intent_dict["action"] = "navigation"
            intent_dict["value"] = "start"
            return await self.handle_navigation(session, intent_dict)

        # --------------------------------------------------------------
        # BLOCK/UNBLOCK USER
        # --------------------------------------------------------------
        elif intent == "toggle_block":
            target_user_id = intent_dict["user_id"]
            if not target_user_id:
                return await self.template_service.list_users_template(session, "Could not parse user id.")

            # Get current user status
            target_user, err = await self.db_service.get_user_by_id(target_user_id)
            if err or not target_user:
                return await self.template_service.list_users_template(session, err or "User not found")

            # Toggle is_active status
            new_status = not target_user.is_active
            _, err = await self.db_service.update_user_status(target_user_id, new_status)

            action = "blocked" if not new_status else "unblocked"
            msg = err or f"User {action} successfully"

            # Refresh the current view
            return await self.template_service.list_users_template(session, msg)

        # --------------------------------------------------------------
        # SHOW USER STATS
        # --------------------------------------------------------------
        elif intent == "show_stats":
            target_user_id = intent_dict["user_id"]
            if not target_user_id:
                return await self.template_service.list_users_template(session, "Could not parse user id.")

            user, err = await self.db_service.get_user_by_id(target_user_id)
            if err or not user:
                return await self.template_service.list_users_template(session, err or "User not found")

            # Get user route statistics
            route_stats, err = await self.db_service.get_user_route_stats(target_user_id)
            if err:
                return await self.template_service.list_users_template(session, err)

            return await self.template_service.show_user_stats_template(user, route_stats)

        # --------------------------------------------------------------
        # UNKNOWN INTENT
        # --------------------------------------------------------------
        else:
            # Reset offset for non-navigation intents
            user_search.offset = 0
            session, err = await self.db_service.update_session(
                session.user_id,
                session.current_task,
                session.current_step,
                session.route_id,
                session.data
            )

        return ResponsePayloadCollection(
            responses=[ResponsePayload(text="Sorry, I didn't understand that command. Please try again.")]
        )

    async def handle_navigation(self, session: SessionDB, intent_dict: Dict) -> ResponsePayloadCollection:
        """Helper method to handle navigation"""
        user_search = session.data.user_search
        value = intent_dict.get("value")
        page_size = 4

        # Get total count with current filters
        total_u, err = await self.db_service.count_users(
            status_filter=user_search.filter_status,
            admin_filter=user_search.filter_admin,
            search_term=user_search.search_term
        )
        total = total_u if total_u is not None and not err else 999999

        # Compute target offset
        if value == "+":
            user_search.offset += page_size
        elif value == "-":
            user_search.offset = max(0, user_search.offset - page_size)
        elif value == "start":
            user_search.offset = 0
        elif value == "end":
            remainder = total % page_size or page_size
            user_search.offset = max(0, total - remainder)

        user_search.total = total

        # Query users
        users, err = await self.db_service.get_users_range(
            offset=user_search.offset,
            limit=page_size,
            status_filter=user_search.filter_status,
            admin_filter=user_search.filter_admin,
            search_term=user_search.search_term
        )

        if not err:
            user_search.ids = [str(u.id) for u in users]

        # Update session
        session, err = await self.db_service.update_session(
            session.user_id,
            RouteTaskEnum.ADMIN.value,
            None,
            None,
            session.data
        )

        return await self.template_service.list_users_template(session)