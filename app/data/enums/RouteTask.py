from enum import Enum


class RouteTaskEnum(Enum):
    MAIN_MENU = "main_menu"
    ROUTE_RESEARCH = "route_research"
    GET_PORT_PRICE = "get_port_price"

    SUPPLIER_RESEARCH = "supplier_research"
    SUPPLIER_REQUEST_CREATE = "supplier_request_create"
    SUPPLIER_REQUEST_LIST = "supplier_request_list"

    #SUPPLIER_ORDER = "supplier_order"

    CREATE_ROUTE = "create_route"
    #UPDATE_ROUTE = "update_route"
    SEARCH_ROUTE = "search_route"

    UPDATE_TARIFF = "update_tariff"
    ADMIN = "admin"
    START = "start"
