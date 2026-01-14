# enums.py
from enum import Enum

class StartStepEnum(str, Enum):
    ROLE = "role"
    USER_NAME = "user_name"
    DONE = "done"
