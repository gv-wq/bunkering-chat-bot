from app.data.dto.main.Session import SessionDB
from app.data.dto.messenger.ResponsePayload import ResponsePayloadCollection, ResponsePayload
from app.data.enums.QuoteRequestEnum import QuoteRequestEnum
from app.data.enums.RouteTask import RouteTaskEnum
from app.handlers.search_route_handler import SearchRouteHandler

from app.services.ai_service import AiService
from app.services.db_service import DbService
from app.services.template.telegram_template_service import TemplateService

class SupplierResearchHandler:
    def __init__(
            self,
            ai_service: AiService,
            sql_db_service: DbService,
            template_service: TemplateService,

    ):
        self.ai_service = ai_service
        self.sql_db_service = sql_db_service
        self.template_service = template_service

    async def handle(self, session: SessionDB, message: str):
        intent, err = await self.ai_service.parse_quote_research_intent(message)
        if err:
            return await self.template_service.route_research_template(session=session, note=err)
        if not intent:
            return await self.template_service.route_research_template(session=session, note="Now success was reached to get the intent.")

        if intent == RouteTaskEnum.SUPPLIER_REQUEST_CREATE.value:
            session, err = await self.sql_db_service.update_session(session.user_id, RouteTaskEnum.SUPPLIER_REQUEST_CREATE.value, QuoteRequestEnum.VESSEL_NAME.value, None, session.data)
            return await self.template_service.session_template(session)

        elif intent == RouteTaskEnum.SUPPLIER_REQUEST_LIST.value:
            session.data.quote_search.offset = 0
            session.data.quote_search.limit = 10
            q_arr, err = await self.sql_db_service.get_quotes(session.user_id,  session.data.quote_search.offset, session.data.quote_search.limit)
            if not err:
                session.data.quote_search.ids = [q.id for q in q_arr]
                session.data.quote_search.total = len(q_arr)


            updated_session, err = await self.sql_db_service.update_session(
                session.user_id,
                RouteTaskEnum.SUPPLIER_REQUEST_LIST.value,
                None,
                None,
                session.data,
            )
            if err:
                return ResponsePayloadCollection(responses=[ResponsePayload(err=f"Session update error: {err}")])
            return await self.template_service.session_template(updated_session)
        return await self.template_service.route_research_template(session=session, note="Please try again.")


