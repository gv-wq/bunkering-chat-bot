# enums.py
from enum import Enum

class StartStepEnum(str, Enum):
    ROLE = "role"
    USER_NAME = "user_name"
    COMPANY_NAME = "company_name"
    PHONE_NUMBER = "phone_number"
    EMAIL = "email"
    PROMOCODE = "promocode"
    DONE = "done"
