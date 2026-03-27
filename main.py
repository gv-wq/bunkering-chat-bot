import os
import asyncio
import logging

from app.handlers.admin_handler import AdminHandler
from config.settings import ENV, require

from app.handlers.navigation_handler import NavigationHandler
from app.services.ai_service import AiService
from app.services.core_service import CoreService
from app.services.db_service import DbService
from app.services.external_api.searoute_api import SearouteApi
from app.services.internal_api.map_builder_api import MapBuilderApi
from app.services.telegram_service import TelegramService
from app.services.template.telegram_template_service import TemplateService
from app.services.whatsapp_service import WhatsApp360DialogService
from app.services.fuel_price_service import FuelPriceService

from app.services.utils.island_projection import IslandProjection
from app.services.utils.near_country_search import RouteCountryFinder
import geopandas as gpd

import uvicorn
from health.server import app as health_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def run_health_server():
    config = uvicorn.Config(
        health_app,
        host="0.0.0.0",
        port=os.getenv("BOT_HEALTH_CHECK_PORT", 8003),
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    await server.serve()

async def run_telegram(service: TelegramService):
    await service.run()


async def run_whatsapp(service: WhatsApp360DialogService):
    config = uvicorn.Config(
        service.app,
        host="0.0.0.0",
        port=int(require("WAWEBHOOK_SERVER_PORT")),
        log_level="info"
    )
    server = uvicorn.Server(config)
    await server.serve()

async def main():
    logger.info("Starting app in %s mode", ENV)

    sql_db_service = DbService()
    await sql_db_service.init_pool()

    searoute_api = SearouteApi(
        require("SEAROUTE_BASE_URL"),
        require("SEAROUTE_TOKEN"),
    )

    # bubble_api = BubbleApi(
    #     require("BUBBLE_BASE_URL"),
    #     require("BUBBLE_TOKEN"),
    # )



    map_builder_api = MapBuilderApi(
        base_url=require("MAP_BUILDER_BASE_URL"),
        public_url=require("MAP_BUILDER_PUBLIC_URL")
    )

    navigation_handler = NavigationHandler(sql_db_service)

    ai_service = AiService(
        navigation_handler=navigation_handler,
        sql_db_service=sql_db_service,
    )

    template_service = TemplateService(
        sql_db=sql_db_service,
        navigation_handler=navigation_handler,
        map_image_api=map_builder_api,
    )

    admin_handler = AdminHandler(
        db_service=sql_db_service,
        template_service=template_service,
        ai_service=ai_service,
        navigation_handler=navigation_handler,
    )


    land_gdf = gpd.read_file("./data/ne_10m_land.shp")

    projector = IslandProjection(land_gdf, sql_db_service)

    country_finder = RouteCountryFinder("./data/ne_10m_admin_0_countries.shp", sql_db_service)

    core_service = CoreService(
        ai_service,
        template_service,
        sql_db_service,
        searoute_api,
        #bubble_api,
        navigation_handler,
        map_builder_api,
        admin_handler,
        projector,
        country_finder,
    )

    telegram_service = TelegramService(
        token=require("TELEGRAM_BOT_TOKEN"),
        ai_service=ai_service,
        core_service=core_service,
        sql_db=sql_db_service
    )

    core_service.set_bot(telegram_service.get_bot())

    whatsapp_service = WhatsApp360DialogService(
        core_service=core_service,
        api_key=require("_360_DIALOG_API_KEY"),
        v_token=require("_360_DIALOG_API_TOKEN"),
        sql_db=sql_db_service
    )

    await asyncio.gather(
       run_telegram(telegram_service),
       run_whatsapp(whatsapp_service)
    )


# os.environ["ALL_PROXY"] = "socks5h://127.0.0.1:1082"
# os.environ["HTTP_PROXY"] = "socks5h://127.0.0.1:1082"
# os.environ["HTTPS_PROXY"] = "socks5h://127.0.0.1:1082"

if __name__ == "__main__":
    asyncio.run(main())

# if __name__ == "__main__":
#     async def main():
#         health_task = asyncio.create_task(run_health_server())
#         bot_task = asyncio.create_task(start_bot())
#         await asyncio.gather(health_task, bot_task)
#
#     try:
#         asyncio.run(main())
#     except KeyboardInterrupt:
#         logger.info("Bot stopped by user")
#     except Exception:
#         logger.exception("Bot crashed")
#         sys.exit(1)