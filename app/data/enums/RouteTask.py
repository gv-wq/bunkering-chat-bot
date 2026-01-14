from enum import Enum


class RouteTaskEnum(Enum):
    MAIN_MENU = "main_menu"
    CREATE_ROUTE = "create_route"
    UPDATE_ROUTE = "update_route"
    SEARCH_ROUTE = "search_route"
    GET_PORT_PRICE = "get_port_price"
    UPDATE_TARIFF = "update_tariff"
    ADMIN = "admin"
    START = "start"
