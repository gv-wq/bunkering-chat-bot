import enum

class QuoteRequestEnum(enum.Enum):
    VESSEL_NAME = "vessel_name"
    VESSEL_IMO = "vessel_imo"
    PORT_SEARCH = "port_search"
    #ETA_FROM = "eta_from"
    #ETA_TO = "eta_to"
    ETA = "eta"
    # FUEL_NAMES = "fuel_names"
    FUEL_QUANTITY = "fuel_quantity"
    REMARK = "remark"
    COMPANY_NAME = "company_name"
    EMAIL = "email"
    ANOTHER_QUOTE_REQUEST = "another_quote_request"


