from app.data.dto.main.Session import SessionDB
from app.data.dto.messenger.ResponsePayload import ResponsePayloadCollection, ResponsePayload
from app.data.enums.RouteStep import RouteStepEnum
from app.data.enums.RouteTask import RouteTaskEnum
from app.handlers.new_route_handler import NewRouteHandler
from app.handlers.search_route_handler import SearchRouteHandler

from app.services.ai_service import AiService
from app.services.db_service import DbService
from app.services.template.telegram_template_service import TemplateService

class RouteResearchHandler:
    def __init__(
        self,
        ai_service: AiService,
        sql_db_service: DbService,
        template_service: TemplateService,
        new_route_handler: NewRouteHandler,
        search_route_handler: SearchRouteHandler
    ):
        self.ai_service = ai_service
        self.sql_db_service = sql_db_service
        self.template_service = template_service
        self.new_route_handler = new_route_handler
        self.search_route_handler = search_route_handler

    async def handle(self, session: SessionDB, message: str):
        intent, err = await self.ai_service.parse_route_research_intent(message)
        if err:
            return await self.template_service.route_research_template(session=session, note=err)
        if not intent:
            return await self.template_service.route_research_template(session=session, note="Now success was reached to get the intent.")

        if intent == RouteTaskEnum.CREATE_ROUTE.value:
            session, err = await self.sql_db_service.update_session(session.user_id, RouteTaskEnum.CREATE_ROUTE.value, RouteStepEnum.DEPARTURE_PORT_SUGGESTION.value, None, session.data)
            return await self.new_route_handler.handle_create_route_flow(session, message)

        elif intent == RouteTaskEnum.SEARCH_ROUTE.value:
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


            #session, err = await self.sql_db_service.update_session(session.user_id, RouteTaskEnum.SEARCH_ROUTE.value, None, None, session.data)
            #return await self.search_route_handler.handle(session, message)

        return await self.template_service.route_research_template(session=session, note="Please try again.")




