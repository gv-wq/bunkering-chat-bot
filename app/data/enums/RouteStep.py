from enum import Enum


class RouteStepEnum(Enum):
    MAIN_MENU = "main_menu"
    DEPARTURE_PORT_SUGGESTION = "departure_suggestion"
    #DEPARTURE_PORT_NEARBY = "departure_nearby"
    DESTINATION_PORT_SUGGESTION = "destination_suggestion"
    #DESTINATION_PORT_NEARBY = "destination_nearby"



    #DEPARTURE_PORT = "departure"
    #DESTINATION_PORT = "destination"

    #DEPARTURE_DESTINATION = "departure_destination"
    DEPARTURE_DATE = "departure_date"
    AVERAGE_SPEED = "average_speed"
    FUEL_SELECTION = "fuel_selection"
    #ROUTE_BUILD_REQUEST = "build_request"
    ROUTE_PORT_LIST = "ports_list"
    BUNKERING_QUEUE = "bunkering_queue"
    PDF_REQUEST = "pdf_request"

    VESSEL_NAME = "vessel_name"
    VESSEL_IMO = "vessel_imo"
    USER_EMAIL = "user_email"
    SUPPLIER_PRICES = "supplier_prices"
    COMPANY_NAME = "company_name"
