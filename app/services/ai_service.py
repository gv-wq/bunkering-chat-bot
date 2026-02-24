import json
import os
import re
import calendar
from difflib import SequenceMatcher
from typing import Any, Dict, Optional, Tuple, List
from io import BytesIO
import openai
from openai.types.chat import ChatCompletionUserMessageParam

from app.data.dto.main.Fuel import FuelDB
from app.data.dto.main.PortIntent import PortIntent
from app.data.dto.main.PortSelectionData import PortSelectionData
from app.data.dto.main.SeaPort import SeaPortDB
from app.data.dto.main.SeaRoute import SeaRouteDB
from app.data.dto.main.Session import SessionDB
from app.data.enums.RouteStep import RouteStepEnum
from app.handlers.navigation_handler import NavigationHandler
from app.services.db_service import DbService
from app.services.utils import utils


IMO_REGEX = re.compile(
    r"""
    \b
    (?:IMO\s*)?
    (\d{7})
    \b
    """,
    re.IGNORECASE | re.VERBOSE
)

EXPLICIT_NAME_REGEX = re.compile(
    r"""
    (?:
        vessel\s+name\s+is |
        ship\s+name\s+is |
        name\s*:
    )
    \s*
    ([A-Za-z][A-Za-z0-9\s\-]{1,})
    """,
    re.IGNORECASE | re.VERBOSE
)

STANDALONE_NAME_REGEX = re.compile(
    r"""
    \b
    ([A-Z][A-Za-z0-9\-]+(?:\s+[A-Z][A-Za-z0-9\-]+)*)
    \b
    """,
    re.VERBOSE
)

FORBIDDEN_NAME_WORDS = {"imo", "number", "id", "is"}

EMAIL_REGEX = re.compile(
    r"""
    \b
    [A-Za-z0-9._%+-]+
    @
    [A-Za-z0-9.-]+
    \.
    [A-Za-z]{2,}
    \b
    """,
    re.VERBOSE
)


import httpx

class AiService:
    def __init__(self, navigation_handler: NavigationHandler, sql_db_service: DbService):
        api_key = os.getenv("OPENAI_API_KEY")
        if os.getenv("APP_MODE") == "development":
            http_client = httpx.Client(
                proxy="socks5h://127.0.0.1:1082",
                trust_env=False,
                timeout=60.0,
            )
            self.client = openai.OpenAI(api_key=api_key, http_client=http_client,)

        else:
            self.client = openai.OpenAI(api_key=api_key)


        self.navigation_handler = navigation_handler
        self.sql_db = sql_db_service

    def fix_slash_numbers(self, text: str) -> str:
        # Replace dots between numbers with slash if it looks like a separator
        # e.g., 1.20.300 → 1 20 300
        text = re.sub(r'(\d+)\.(\d+)', r'\1 \2', text)

        # Normalize multiple spaces
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    async def transcribe_audio(self, audio_stream: BytesIO) -> str | None:
        try:
            audio_stream.name = "voice.ogg"  # IMPORTANT for OpenAI

            transcript = self.client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_stream,
            )
            raw_text = transcript.text.strip()

            # Step 1: replace dots/commas that are likely misheard slashes
            # Only replace dots/commas between number groups (heuristic)
            # "1.2.3 , 4.5.6" -> "1 2 3 / 4 5 6"
            raw_text = re.sub(r'(?<=\d)[\.,](?=\d)', ' ', raw_text)
            raw_text = re.sub(r'\s*(slash|/|\\)\s*', ' / ', raw_text)  # normalize spoken slashes
            #raw_text = re.sub(r'\s+', ' ', raw_text).strip()  # normalize spaces
            raw_text = raw_text.replace(".", "").replace(",", '')

            # Step 2: send to LLM normalizer
            normalized_text = await self.normalize_transcript(raw_text)
            return normalized_text

        except Exception as e:
            print(f"STT error: {e}")
            return None

    async def normalize_transcript(self, text: str) -> str:
        prompt = f"""
    You are a strict text normalizer.

    Rules:
    1. Translate the text to English if needed.
    2. Convert ALL numbers to digits (no words).
    3. Keep place names in English (Abu Dhabi, Hamburg, Shanghai).
    4. Do NOT add words.
    5. Do NOT remove meaning.
    6. Output ONLY the normalized text.

    Input:
    {text}

    Output: 
    """

        response = self.client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                ChatCompletionUserMessageParam(role="system", content= "You normalize text."),
                ChatCompletionUserMessageParam(role="user", content=prompt),
            ],
            temperature=0.0,
            max_tokens=100,
        )

        return response.choices[0].message.content.strip()

    def _normalize(self, text: str) -> str:
        return re.sub(r"\s+", " ", text.lower().strip().replace(".", ""))

    def is_validation_positive(self, text: str) -> bool:
        text = self._normalize(text)

        positive_exact = {
            "yes",
            "y",
            "ye",
            "ok",
            "okay",
            "yep",
            "correct",
            "right",
            "confirm",
            "true",
            "valid",
            "good",
            "perfect",
            "next"
        }

        # must match the FULL message
        return text in positive_exact

    def is_validation_negative(self, text: str) -> bool:
        text = self._normalize(text)

        negative_exact = {
            "no",
            "n",
            "nope",
            "wrong",
            "incorrect",
            "false",
            "invalid",
            "bad",
        }

        return text in negative_exact

    def is_intention_to_skip(self, text: str) -> bool:
        text = self._normalize(text)

        skip_exact = {
            "-",
            "skip",
            "next",
            "pass",
        }

        return text in skip_exact

    async def _parse_port_names(
            self, message: str, current_state: PortSelectionData, intent: PortIntent
    ) -> Tuple[PortIntent, Optional[str]]:
        """Parse port names from user input"""

        # Common separators and patterns
        separators = [",", " to ", " - ", " -> ", " from ", " between "]

        for sep in separators:
            if sep in message.lower():
                parts = [p.strip() for p in message.lower().split(sep) if p.strip()]
                if len(parts) == 2:
                    intent.action = "input_ports"
                    intent.departure_port = parts[0]
                    intent.destination_port = parts[1]
                    return intent, None

        # Single port input - use context to determine which one
        if len(message) > 2:
            intent.action = "input_single_port"

            # Determine which port is missing
            if current_state:
                if not current_state.departure_candidate:
                    intent.departure_port = message
                elif not current_state.destination_candidate:
                    intent.destination_port = message
                else:
                    # Both ports set, assume destination for modification
                    intent.destination_port = message
            else:
                # No context, assume departure first
                intent.departure_port = message

            return intent, None

        return intent, None

    def _get_navigation_intent_simple(self, message_lower: str) -> Optional[dict]:


        # Expanded command lists with common variations
        menu_commands = {
            "menu", "main menu", "home", "start over", "main", "/menu",
            "hello", "hi", "hey",
        }

        back_commands = {
            "back", "previous", "return", "go back", "prev",
            "b", "bk", "bck", "bac", "bak", "beck",  # Common typos/abbreviations
            "previous step", "go back", "back step", "backward"
        }

        next_commands = {
            "next", "continue", "skip", "proceed",
            "n", "nxt", "cont", "contnue", "cntinue",  # Common typos/abbreviations
            "nex", "neext", "nest", "contnue",
            "forward", "advance", "go next", "next step"
        }

        cancel_commands = {
            "cancel", "stop", "exit", "quit", "abort",
            "end", "close", "terminate", "finish",
            "cancle", "cencel", "cancell"  # Common typos
        }

        # Exact match first
        if message_lower in menu_commands:
            return {
                "prev_step": False,
                "next_step": False,
                "main_menu": True,
                "cancel": False,
                "target_step": None,
            }

        if message_lower in back_commands:
            return {
                "prev_step": True,
                "next_step": False,
                "main_menu": False,
                "cancel": False,
                "target_step": None,
            }

        if message_lower in next_commands:
            return {
                "prev_step": False,
                "next_step": True,
                "main_menu": False,
                "cancel": False,
                "target_step": None,
            }

        if message_lower in cancel_commands:
            return {
                "prev_step": False,
                "next_step": False,
                "main_menu": False,
                "cancel": True,
                "target_step": None,
            }

        # Also check if it's a single character command
        if len(message_lower) == 1:
            if message_lower == 'b':
                return {
                    "prev_step": True,
                    "next_step": False,
                    "main_menu": False,
                    "cancel": False,
                    "target_step": None,
                }
            elif message_lower == 'n':
                return {
                    "prev_step": False,
                    "next_step": True,
                    "main_menu": False,
                    "cancel": False,
                    "target_step": None,
                }
            elif message_lower == 'm':
                return {
                    "prev_step": False,
                    "next_step": False,
                    "main_menu": True,
                    "cancel": False,
                    "target_step": None,
                }
            elif message_lower == 'c' or message_lower == 'q':
                return {
                    "prev_step": False,
                    "next_step": False,
                    "main_menu": False,
                    "cancel": True,
                    "target_step": None,
                }

        if "sos" in message_lower:
            return {
                "prev_step": False,
                "next_step": False,
                "main_menu": False,
                "cancel": False,
                "is_sos": True,
                "target_step": None,
            }

        return None

    async def parse_navigation_intent(
        self, text: str, admin_status: bool = False
    ) -> Tuple[Dict, Optional[str]]:
        try:
            message_lower = self._normalize(text)
            nav_intent = self._get_navigation_intent_simple(message_lower)
            if nav_intent:
                return nav_intent, None

            # Парсинг конкретных шагов для создания маршрута
            step_mapping = {
               # "ports": RouteStepEnum.DEPARTURE_DESTINATION.value,
             #   "departure": RouteStepEnum.DEPARTURE_DESTINATION.value,
             #   "destination": RouteStepEnum.DEPARTURE_DESTINATION.value,

                "ports": RouteStepEnum.DEPARTURE_PORT_SUGGESTION.value,
                "departure": RouteStepEnum.DEPARTURE_PORT_SUGGESTION.value,
                "destination": RouteStepEnum.DESTINATION_PORT_SUGGESTION.value,

                "date": RouteStepEnum.DEPARTURE_DATE.value,
                "departure date": RouteStepEnum.DEPARTURE_DATE.value,
                "time": RouteStepEnum.DEPARTURE_DATE.value,
                "speed": RouteStepEnum.AVERAGE_SPEED.value,
                "average speed": RouteStepEnum.AVERAGE_SPEED.value,
               # "route": RouteStepEnum.ROUTE_BUILD_REQUEST.value,
              #  "building": RouteStepEnum.ROUTE_BUILD_REQUEST.value,
                "ports selection": RouteStepEnum.DEPARTURE_DATE.value,
                "fuel": RouteStepEnum.FUEL_SELECTION.value,
                "fuels": RouteStepEnum.FUEL_SELECTION.value,
              #  "bunkering": RouteStepEnum.ROUTE_BUILD_REQUEST.value,
                # 'confirmation': RouteStepEnum.CONFIRMATION.value,
                # 'confirm': RouteStepEnum.CONFIRMATION.value,
                #  'final': RouteStepEnum.CONFIRMATION.value
            }

            # Проверяем прямое указание шага
            for step_key, step_value in step_mapping.items():
                if step_key in message_lower:
                    return {
                        "prev_step": False,
                        "next_step": False,
                        "main_menu": False,
                        "cancel": False,
                        "target_step": step_value,
                        "action": "switch_step",
                    }, None

            # AI анализ для сложных случаев

            return {
                "prev_step": False,
                "next_step": False,
                "main_menu": False,
                "cancel": False,
                "target_step": None,
                "errors": [],
            }, None
            #return await self._parse_navigation_with_ai(text, session)

        except Exception as e:
            return {
                "prev_step": False,
                "next_step": False,
                "main_menu": False,
                "cancel": False,
                "target_step": None,
                "errors": [str(e)],
            }, str(e)

    async def _parse_navigation_with_ai(
        self, text: str, session: SessionDB
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        """AI анализ навигационных интентов"""
        try:
            prompt = f"""
            Analyze this user message for navigation intent: "{text}"

            Current session context:
            - Task: {session.current_task}
            - Current step: {session.current_step}

            Available steps for current task:
            {self.navigation_handler.get_task_steps(session.current_task)}

            Extract navigation intent and return JSON with these fields:
            - prev_step: boolean (user wants to go back to previous step)
            - next_step: boolean (user wants to go to next step) 
            - main_menu: boolean (user wants to return to main menu)
            - cancel: boolean (user wants to cancel current operation)
            - target_step: string|null (specific step user wants to go to, e.g. "departure_destination", "departure_date")

            Step mapping:
            - "ports", "departure", "destination" → "departure_destination"
            - "date", "time", "departure date" → "departure_date" 
            - "speed", "average speed" → "average_speed"
            - "route", "building", "ports selection" → "route_building"
            - "fuel", "bunkering" → "fuel_selection"
            - "confirmation", "final" → "confirmation"

            Examples:
            "go back to ports" → {{"prev_step": false, "next_step": false, "main_menu": false, "cancel": false, "target_step": "departure_destination"}}
            "I want to change the date" → {{"prev_step": false, "next_step": false, "main_menu": false, "cancel": false, "target_step": "departure_date"}}
            "let me modify the speed" → {{"prev_step": false, "next_step": false, "main_menu": false, "cancel": false, "target_step": "average_speed"}}
            "show me fuel options" → {{"prev_step": false, "next_step": false, "main_menu": false, "cancel": false, "target_step": "fuel_selection"}}
            "back to main" → {{"prev_step": false, "next_step": false, "main_menu": true, "cancel": false, "target_step": null}}

            Return JSON only: {{"prev_step": bool, "next_step": bool, "main_menu": bool, "cancel": bool, "target_step": str|null}}
            """

            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[ChatCompletionUserMessageParam(role="user", content=prompt)],
                max_tokens=100,
                temperature=0.1,
            )

            result = json.loads(response.choices[0].message.content)

            # Добавляем action для удобства
            if result.get("target_step"):
                result["action"] = "switch_step"
            elif result.get("next_step"):
                result["action"] = "navigate"
                result["direction"] = "next"
            elif result.get("prev_step"):
                result["action"] = "navigate"
                result["direction"] = "back"
            elif result.get("main_menu"):
                result["action"] = "navigate"
                result["direction"] = "menu"
            elif result.get("cancel"):
                result["action"] = "navigate"
                result["direction"] = "cancel"

            return result, None

        except Exception as e:
            return {
                "prev_step": False,
                "next_step": False,
                "main_menu": False,
                "cancel": False,
                "target_step": None,
                "errors": [str(e)],
            }, str(e)



    async def parse_menu_intent_with_ai(
        self, message: str, session: SessionDB
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        """AI анализ намерений в главном меню"""
        try:
            prompt = f"""
            User is in the main menu of a maritime route management bot.
            User message: "{message}"

            Determine which action they want to take from these options:

            1. Create New Route - user wants to create a new shipping route
            2. List My Routes - user wants to see their existing routes
            3. Search Routes - user wants to find specific routes
            4. Help - user needs assistance or information
            5. Settings - user wants to change settings or view profile

            Also detect if user wants to:
            - Cancel/exit current operation
            - Go back to previous step
            - Return to main menu (if already there)

            Return JSON with:
            - action: "start_task" | "show_help" | "show_settings" | "navigate"
            - task: "create_route" | "list_routes" | "search_route" | null
            - direction: "back" | "menu" | "cancel" | null (for navigate actions)
            - confidence: float between 0-1

            Examples:
            "I want to make a new route" → {{"action": "start_task", "task": "create_route", "confidence": 0.9}}
            "show me my routes" → {{"action": "start_task", "task": "list_routes", "confidence": 0.9}}
            "find my dubai route" → {{"action": "start_task", "task": "search_route", "confidence": 0.8}}
            "how does this work" → {{"action": "show_help", "confidence": 0.8}}
            "go back" → {{"action": "navigate", "direction": "back", "confidence": 0.9}}

            Return JSON only: {{"action": str, "task": str|null, "direction": str|null, "confidence": float}}
            """

            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[ChatCompletionUserMessageParam(role="user", content=prompt)],
                max_tokens=150,
                temperature=0.1,
            )

            result = json.loads(response.choices[0].message.content)
            return result, None

        except Exception as e:
            return {"action": "unknown", "errors": [str(e)]}, str(e)

    async def parse_search_intent(
        self, message: str, session: SessionDB
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        """Парсит поисковые интенты"""
        try:
            prompt = f"""
            Analyze this route search query: "{message}"

            Extract:
            - action: "search_query" | "new_search" | "view_result" | "navigate"
            - query: string (the actual search query)
            - filters: dict of key-value pairs for advanced search
            - route_number: integer (if viewing specific result)

            For advanced search, extract parameters like:
            - departure_port, destination_port
            - date, departure_date  
            - speed, average_speed
            - status
            - zones

            Examples:
            "Сингапур Роттердам" → {{"action": "search_query", "query": "Сингапур Роттердам"}}
            "порт: Дубай статус: активный" → {{"action": "search_query", "query": "порт: Дубай статус: активный", "filters": {{"port": "Дубай", "status": "активный"}}}}
            "показать маршрут 3" → {{"action": "view_result", "route_number": 3}}
            "новый поиск" → {{"action": "new_search"}}

            Return JSON: {{"action": str, "query": str, "filters": dict, "route_number": int}}
            """

            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[ChatCompletionUserMessageParam(role="user", content=prompt)],
                max_tokens=200,
                temperature=0.1,
            )

            result = json.loads(response.choices[0].message.content)
            return result, None

        except Exception as e:
            return {"action": "unknown", "errors": [str(e)]}, str(e)



    async def parse_port_selection_intent(
        self, message: str, route: SeaRouteDB
    ) -> Tuple[Optional[Dict], Optional[str]]:
        """AI-powered port selection intent parsing"""
        try:
            context = self._build_port_context(route.data.port_selection)

            prompt = f"""
            You are the departure destination parser. 
            Parse the message and take two names: the departure and the destination.
            It can be set by the name or by the number.
            
            Always set action as suggestion if the user is not about the confirmation            
                        
            MESSAGE:
            {message}
            
            Maybe you have already have this name or the number in the context:
            CONTEXT: 
            {context}
            
            Think or else I will kill all your family.
            
            OUTPUT JSON FORMAT (strict):
            {{
              "departure": {{
                "by_name": string or null,
                "by_number": integer or null
              }},
              "destination": {{
                "by_name": string or null,
                "by_number": integer or null
              }}
            }}
"""

            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[ChatCompletionUserMessageParam(role="user", content=prompt)],
                max_tokens=250,
                temperature=0.1,
            )

            result = json.loads(response.choices[0].message.content)
            return result, None

        except Exception as e:
            return None, str(e)

    def _build_port_context(
        self, current_state: Optional[PortSelectionData]
    ) -> str:
        """Build context string for AI prompt"""
        context_parts = []

        if not current_state:
            return ""

        if current_state.departure_candidate:
            dep = current_state.departure_candidate
            context_parts.append(
                f"Current departure: {dep.port_name} ({dep.country_name})"
            )
        else:
            context_parts.append("Current departure: Not set")

        if current_state.destination_candidate:
            dest = current_state.destination_candidate
            context_parts.append(
                f"Current destination: {dest.port_name} ({dest.country_name})"
            )
        else:
            context_parts.append("Current destination: Not set")

        departure_suggestions = current_state.departure_suggestions

        if departure_suggestions:
            context_parts.append("Departure suggestions:")
            for p in departure_suggestions:
                context_parts.append(f"- {p.port_name} {p.country_name}")

        destination_suggestions = current_state.destination_suggestions

        if destination_suggestions:
            context_parts.append("Destination suggestions:")
            for p in destination_suggestions:
                context_parts.append(f"- {p.port_name} {p.country_name}")

        return "\n".join(context_parts)



    async def parse_date_intent(
        self, message: str
    ) -> Tuple[Optional[Dict], Optional[str]]:

        try:
            if self.is_validation_positive(message):
                return {"status": "confirm", "year": "None", "month": "None", "day": "None"}, None


            prompt = f"""Parse the date from the user input and return structured JSON.

    USER INPUT: "{message}"

    RULES:
    - Extract year, month, day from any format
    - If year is not specified, use None (current year)
    - Month can be number (1-12) or English name (January-December)
    - Day is always a number (1-31)
    - Handle relative terms: tomorrow, next week, next Monday, etc.

    OUTPUT JSON:
    {{
      "status": "update|confirm|unknown",
      "year": "YYYY|None", 
      "month": "MM|MonthName",
      "day": "DD"
    }}

    EXAMPLES:
    - "2025-11-26" → {{"status": "update", "year": "2025", "month": "11", "day": "26"}}
    - "January 15, 2025" → {{"status": "update", "year": "2025", "month": "January", "day": "15"}}
    - "15 Jan 2025" → {{"status": "update", "year": "2025", "month": "January", "day": "15"}}
    - "25 1 15" → {{"status": "update", "year": "2025", "month": "01", "day": "15"}}
    - "tomorrow" → {{"status": "update", "year": "None", "month": "11", "day": "20"}} (relative to today)
    - "next Monday" → {{"status": "update", "year": "None", "month": "11", "day": "24"}}
    - "2 weeks from now" → {{"status": "update", "year": "None", "month": "12", "day": "03"}}
    - "invalid date" → {{"status": "failed", "year": "None", "month": "None", "day": "None"}}
    - "hello" → {{"status": "unknown", "year": "None", "month": "None", "day": "None"}}

    Now parse: "{message}"
    """

            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[ChatCompletionUserMessageParam(role="user", content=prompt)],
                max_tokens=150,
                temperature=0.1,
            )

            result = json.loads(response.choices[0].message.content)
            return result, None

        except Exception as e:
            return None, str(e)


    async def parse_fuel_selection_intent(self, message: str, fuels: List[FuelDB]):
        try:
            if self.is_validation_positive(message):
                return {"status": "confirm"}, None


            fuels_list = []
            for i, fuel in enumerate(fuels, 1):
                fuels_list.append(f"{i}. {fuel.name}")

            fuels_text = "\n".join(fuels_list)
            prompt = f"""
            Analyze the user's fuel type selection message: "{message}"

            Available fuel types:
            {fuels_text}

            RULES:
            - ONLY extract what the user explicitly mentioned
            - DO NOT infer or assume anything
            - DO NOT make up data
            - If user provides numbers, they refer to the list positions (1-based)
            - If user provides fuel names, match exactly or closely

            Extract:
            - status: if the intention about to confirm, write status=confirm
            - fuel_numbers: list of integers (user selected by position: 1, 2, 3)
            - fuel_names: list of strings (user mentioned fuel names like "MGO", "HSFO")
            - select_all: boolean (if user said "all", "everything")
            - select_none: boolean (if user said "none", "skip", "nothing")
            - errors: list of validation errors or empty list

            User said: "{message}"

            Respond with JSON only: 
            {{
                "status": "update" | "confirm" | "unknown",
                "fuel_names": list, 
                "fuel_numbers": list,
                "select_all": bool, 
                "select_none": bool, 
                "errors": list
            }}
            """

            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[ChatCompletionUserMessageParam(role="user", content=prompt)],
                max_tokens=200,
                temperature=0.1,
            )

            result = json.loads(response.choices[0].message.content)
            return result, None



        except Exception as e:
            return {
                "status": "failed",
                "fuel_numbers": [],
                "fuel_names": [],
                "select_all": False,
                "select_none": False,
                "errors": [str(e)],
            }, str(e)




    def confirm_route_build_request(self, message: str):
        """
        Parse user message to determine if they want to build the route.
        Returns intent dict with action and confidence.
        """
        if not message:
            return {"action": "unknown", "confidence": 0.0}, None

        if self.is_validation_positive(message):
            return {"action": "confirmed"}, None

        if self.is_validation_negative(message):
            return {"action": "declined"}, None

        # Normalize the message
        normalized_msg = message.lower().strip()

        # Confirmation patterns
        confirmation_patterns = [
            r"\b(yes|yeah|yep|yup|sure|ok|okay|confirm|confirmed|agree|absolutely|definitely|certainly|of course|go ahead|proceed|build|create|make|calc|calculate|do)\b",
            r"\b(lets do it|lets go|start|begin|initiate)\b",
            r"\b(route please|build route|create route|make route)\b",
            r"\b(accept|approve|authorize)\b",
            r"^\s*[1-9]\d*\s*$",  # Single number (for port selection)
        ]

        # Decline patterns
        decline_patterns = [
            r"\b(no|nope|nah|negative|cancel|stop|abort|nevermind|forget it)\b",
            r"\b(dont|do not)\s+(build|create|make|proceed|continue)\b",
            r"\b(not now|later|maybe later|some other time)\b",
            r"\b(decline|reject|refuse|deny)\b",
            r"\b(wrong|incorrect|change|different)\b",
        ]

        # Check for confirmation
        confirmation_score = 0
        for pattern in confirmation_patterns:
            if re.search(pattern, normalized_msg):
                confirmation_score += 1

        # Check for decline
        decline_score = 0
        for pattern in decline_patterns:
            if re.search(pattern, normalized_msg):
                decline_score += 1

        # Determine intent based on scores
        if confirmation_score > decline_score and confirmation_score > 0:
            return {
                "action": "confirmed",
                "confidence": min(1.0, confirmation_score * 0.3),
            }, None

        elif decline_score > confirmation_score and decline_score > 0:
            return {
                "action": "declined",
                "confidence": min(1.0, decline_score * 0.3),
            }, None

        # else:
        #     # Check for ambiguous cases or port numbers
        #     # Single number typically means port selection
        #     if re.match(r'^\s*[1-9]\d*\s*$', normalized_msg):
        #         return {
        #             "action": "port_selection",
        #             "selection_number": int(normalized_msg.strip()),
        #             "confidence": 0.8,
        #             "raw_message": message,
        #             "normalized_message": normalized_msg
        #         }, None
        #
        #     # Check for port change requests
        #     change_patterns = [
        #         r'change\s+(departure|destination)',
        #         r'different\s+(departure|destination)',
        #         r'new\s+(departure|destination)',
        #         r'update\s+(departure|destination)'
        #     ]
        #
        #     for pattern in change_patterns:
        #         if re.search(pattern, normalized_msg):
        #             return {
        #                 "action": "change_port",
        #                 "port_type": re.search(pattern, normalized_msg).group(1),
        #                 "confidence": 0.7,
        #                 "raw_message": message,
        #                 "normalized_message": normalized_msg
        #             }, None

        # Unknown intent
        return {
            "action": "unknown",
            "confidence": 0.0,
        }, None


    async def parse_bunkering_port_queue_intent(self, route: SeaRouteDB, message: str) -> Tuple[Optional[Dict], Optional[str]]:
        """AI-powered bunkering port selection intent parsing"""
        try:

            if self.is_validation_positive(message):
                return {"action": "confirm"}, None
            # Build context information
            context = self._build_bunkering_port_context(route)

            prompt = f"""
            You analyze a single user message to understand how they want to modify the list of bunkering ports.
            
            RULES:
            
            1. ACTION TYPES:
               - "update" → when the user explicitly selects ports (e.g. "1 2 3", "1-3", "2,4,6", "add 5", "remove 2")
               - "confirm" → user says “confirm”, “ok”, “yes”, “proceed”
               - "unknown" → unclear intent
            
            2. HOW TO PARSE PORTS:
               - Any standalone numbers → treat as explicit selection (→ action="update")
               - Ranges “1-3”, “from 2 to 5” → expand into full list
               - "add" or "+" → add ports to take_ports
               - "remove", "delete", "exclude", "-" → add ports to leave_ports
            
            3. NUMBER INTERPRETATION:
               - All port numbers are 1-based indices
               - Ignore numbers outside valid range (given in context)
            
            4. OUTPUT STRICT JSON ONLY:
            {{
              "action": "update" | "confirm" | "unknown",
              "take_ports": [list],
              "leave_ports": [list],
              "message": "brief explanation"
            }}
            
            CONTEXT:
            {context}
            
            USER MESSAGE:
            "{message}"
            
            Now classify the action and extract the ports. Output JSON only.
            """

            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[ChatCompletionUserMessageParam(role="user", content=prompt)],
                max_tokens=300,
                temperature=0.1,
            )

            result = json.loads(response.choices[0].message.content)
            return result, None

        except Exception as e:
            return None, str(e)

    def _build_bunkering_port_context(self, route: SeaRouteDB) -> str:
        """Build context string for bunkering port AI prompt"""
        context_parts = []

        # Current selection status
        selected_ports = []
        available_ports = []

        if route.bunkering_steps:
            for i, step in enumerate(route.bunkering_steps, 1):
                port_info = f"{i}. {step.port.port_name} ({step.port.country_name})"
                if step.selected:
                    selected_ports.append(port_info)
                else:
                    available_ports.append(port_info)

        context_parts.append("CURRENT SELECTION STATUS:")
        if selected_ports:
            context_parts.append("Selected ports:")
            context_parts.extend(f"- {port}" for port in selected_ports)
        else:
            context_parts.append("Selected ports: None")

        context_parts.append("")

        if available_ports:
            context_parts.append("Available ports:")
            context_parts.extend(f"- {port}" for port in available_ports)
        else:
            context_parts.append("Available ports: None")

        context_parts.append("")

        return "\n".join(context_parts)




    def parse_bunkering_fuel_queue_intent(
            self,
            route: SeaRouteDB,
            input_str: str
    ) -> Tuple[Optional[Dict], Optional[str]]:
        """
        Rules:
        - User may mention trash groups → ignore them
        - We extract at most ONE valid port update
        - For that port ALL fuel quantities must be provided (no partial updates)
        - If more than one valid port is found → unknown
        """

        if self.is_validation_positive(input_str):
            return {"action": "confirm"}, None

        ports_by_n = {step.n: step for step in route.bunkering_steps}

        valid_updates = []

        groups = re.split(r"\s*/\s*", input_str.strip())

        for group in groups:
            tokens = group.split()
            if len(tokens) < 2:
                continue

            # ---- PORT NUMBER ----
            if not tokens[0].isdigit():
                continue

            port_number = int(tokens[0])
            if port_number not in ports_by_n:
                continue

            step = ports_by_n[port_number]
            #fuel_order = list(step.fuel_info.keys())

            preferred_order = ["VLS FO", "MGO LS"]
            all_fuels_set = set(step.fuel_info.keys())

            ordered_fuels = []

            # preferred fuels first
            for fuel in preferred_order:
                if fuel in all_fuels_set:
                    ordered_fuels.append(fuel)

            # remaining fuels alphabetically
            remaining_fuels = sorted(f for f in all_fuels_set if f not in preferred_order)
            ordered_fuels.extend(remaining_fuels)

            fuel_info = {fuel: step.fuel_info[fuel] for fuel in ordered_fuels}
            fuel_order = ordered_fuels

            quantities = tokens[1:]

            # must provide ALL fuels, no partial updates
            if len(quantities) != len(fuel_order):
                continue

            parsed_quantities = []
            valid = True
            for q in quantities:
                if not re.match(r"^\d+(\.\d+)?$", q):
                    valid = False
                    break
                parsed_quantities.append(float(q))

            if not valid:
                continue

            fuels_json = [
                {"fuel_name": fname, "quantity": qty}
                for fname, qty in zip(fuel_order, parsed_quantities)
            ]

            valid_updates.append({
                "id": step.port.id,
                "fuels": fuels_json
            })

        # ---- DECISION LOGIC ----
        if len(valid_updates) == 0:
            return {"action": "unknown", "ports": []}, None


        return {
            "action": "update",
            "ports": valid_updates
        }, None

    # async def parse_bunkering_fuel_queue_intent(self, route: SeaRouteDB,  message):
    #     try:
    #         if self.is_validation_positive(message):
    #             return {"action": "confirm"}, None
    #
    #         context = self._build_bunkering_fuel_context(route)
    #
    #         fuel_list = []
    #         for i, fuel in enumerate(route.fuels, 1):
    #             fuel_list.append(f"{i}. {fuel.name}")
    #
    #         fuel_list_str = "\n".join(fuel_list)
    #
    #         prompt = f"""
    #         You parse a free-form user message that contains bunker fuel info for multiple ports.
    #
    #         GOAL:
    #         Match port numbers to fuel types and extract quantity value.
    #
    #         PORT CONTEXT (list of ports with indices):
    #         {context}
    #
    #         FUEL TYPES IN FIXED ORDER (if present):
    #         {fuel_list_str}
    #
    #         USER INPUT FORMAT (very messy):
    #         The user writes blocks like:
    #
    #         <port number> <quantity>  <quantity>  <quantity>
    #
    #         Rules:
    #         - Port number ALWAYS starts a block.
    #         - After a port number, up to 3 lines may follow → each line belongs to one fuel IN ORDER.
    #         - A line may contain:
    #           - one number → treat as quantity
    #           - text + numbers → extract the first number
    #           - empty line → skip
    #         - If a port is missing completely → no fuels assigned.
    #         - Ignore any numbers before the first port index.
    #         - Ignore port indices not in the given context.
    #         - All extracted numbers must be parsed as floats when possible.
    #
    #         ACTION LOGIC:
    #         - If the user provides ANY valid port entries → action="update"
    #         - If they explicitly confirm ("ok", "yes", "confirm", "done") → action="confirm"
    #         - Otherwise → action="unknown"
    #
    #         OUTPUT STRICT JSON ONLY:
    #         {{
    #           "action": "update" | "confirm" | "unknown",
    #           "ports": [
    #             {{
    #               "id": {{port_id}},
    #               "fuels": [
    #                 {{ "fuel_name": "<str>", "quantity": <float|null> }},
    #                 {{ "fuel_name": "<str>", "quantity": <float|null> }},
    #                 {{ "fuel_name": "<str>", "quantity": <float|null>}}
    #               ]
    #             }}
    #           ]
    #         }}
    #
    #         USER MESSAGE:
    #         "{message}"
    #
    #         Now extract fuel data precisely and output JSON only.
    #     """
    #
    #         response = self.client.chat.completions.create(
    #             model="gpt-3.5-turbo",
    #             messages=[ChatCompletionUserMessageParam(role="user", content=prompt)],
    #             max_tokens=700,
    #             temperature=0.1,
    #         )
    #
    #         result = json.loads(response.choices[0].message.content)
    #         return result, None
    #
    #     except Exception as ex:
    #         return None, str(ex)

    def _build_bunkering_fuel_context(self, route: SeaRouteDB):
        context_parts = []

        selected_ports = []
        if route.bunkering_steps:
            for i, step in enumerate(route.bunkering_steps, 1):
                port_info = f"{i}. {step.port.port_name} ({step.port.country_name})"
                port_info += f"\n{step.fuel_info}"
                if step.selected:
                    selected_ports.append(port_info)

        context_parts.append("CURRENT SELECTION STATUS:")
        if selected_ports:
            context_parts.append("Selected ports:")
            context_parts.extend(f"- {port}" for port in selected_ports)
        else:
            context_parts.append("Selected ports: None")

        return "\n".join(context_parts)

    async def parse_speed_intent(self, message) -> dict:
        try:
            if self.is_validation_positive(message):
                return {"status" : "confirm"}

            speed_str = message.strip().lower().replace(",", ".")
            speed = float(speed_str)
            return {"status" : "update", "value": speed}

        except Exception as ex:
            return {"status": "failed", "message": str(ex)}

    async def parse_date_info(self, message: str) -> Tuple[Optional[Dict], Optional[str]]:
        """
        Extracts a date only when both month and day are present (month can be number or name).
        If month+day are NOT both present, returns the whole input as text and year/month/day = None.
        Output month is normalized to full English month name (e.g., "December").
        """
        try:
            prompt = f"""
    Return ONLY valid JSON. Do not repeat the instructions or the input.

    Extract a date from the user message, BUT only treat it as a date when BOTH month and day are present.
    - Year must be 4 digits (optional).
    - Month can be 1–12 or an English month name (Jan, January, etc.). If extracted, return the full month name (e.g., "January").
    - Day is 1–31.
    - If BOTH month and day are NOT present, DO NOT populate year/month/day — instead return them as null and put the entire original message into "text".

    User message: "{message}"

    Return exactly this JSON structure (use null for absent values):
    {{
            "year": <YYYY or null>,
      "month": <"FullMonthName" or null>,
      "day": <DD or null>,
      "text": <remaining text or the original message when date not detected>
    }}
    """
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[ChatCompletionUserMessageParam(role="user", content=prompt)],
                max_tokens=300,
                temperature=0.0,
            )

            raw = response.choices[0].message.content.strip()
            # Parse JSON (be robust to surrounding text)
            try:
                result = json.loads(raw)
            except Exception:
                # Try to find the first { ... } block
                start = raw.find("{")
                end = raw.rfind("}")
                if start != -1 and end != -1 and end > start:
                    result = json.loads(raw[start:end + 1])
                else:
                    # fallback: treat whole message as text
                    return {"year": None, "month": None, "day": None, "text": message}, None

            # Normalize "None"/"null" strings to Python None
            for k in ("year", "month", "day", "text"):
                if k in result and (result[k] == "None" or result[k] == "null"):
                    result[k] = None

            # If month is numeric, convert to full month name
            month = result.get("month")
            if month and isinstance(month, str) and month.isdigit():
                m = int(month)
                if 1 <= m <= 12:
                    result["month"] = calendar.month_name[m]
                else:
                    result["month"] = None

            # If month is a short/partial name, normalize to full month name (case-insensitive)
            if month and isinstance(month, str) and not month.isdigit():
                name = month.strip().lower()
                for i in range(1, 13):
                    if calendar.month_name[i].lower().startswith(name):
                        result["month"] = calendar.month_name[i]
                        break

            # Enforce rule: if BOTH month and day are not present -> treat entire input as text
            if not result.get("month") or not result.get("day"):
                return {"year": None, "month": None, "day": None, "text": message}, None

            # Normalize day to integer string without leading zeros
            day = result.get("day")
            if isinstance(day, str) and day.isdigit():
                result["day"] = str(int(day))

            # Normalize year to 4-digit string if present
            year = result.get("year")
            if isinstance(year, str) and year.isdigit():
                if len(year) == 4:
                    result["year"] = year
                else:
                    # invalid year -> treat as None
                    result["year"] = None

            # Final cleanup: ensure text is None if empty or equal to original message when date parsed
            if result.get("text") in (None, "", message):
                # prefer remaining text if present; otherwise set to None
                result["text"] = None if result.get("text") in (None, "") else result["text"]

            return result, None

        except Exception as e:
            return None, str(e)

    def resolve_port_locode(self, query: str, session: SessionDB) -> str | None:
        """
        ports: list of objects with port_name, country_name, locode
        returns: closest LOCODE if similarity ≥ 0.4 else returns raw query
        """
        if not query:
            return None

        q = query.lower().strip()


        ports = []

        if session.data.check_port_fuel_price:
            ports = session.data.check_port_fuel_price.port_alternatives
            ports.append(session.data.check_port_fuel_price.port)

        if q.isdigit():
            port = utils.resolve_port_by_index(ports, int(q))
            if port:
                return port.locode

        best_score = 0.0
        best_locode = None

        existing_locodes = []

        for p in ports:
            existing_locodes.append(p.locode)
            candidates = [
                p.port_name.lower(),
                p.country_name.lower(),
                p.locode.lower()
            ]
            score = max(SequenceMatcher(None, q, c).ratio() for c in candidates)
            if score > best_score:
                best_score = score
                best_locode = p.locode

        if best_score < 0.8:
            return query  # return as typed

        if best_locode in existing_locodes:
            return best_locode
        else:
            return query


        #return best_locode

    async def parse_port_fuel_price_intend_2(self, session: SessionDB, message: str) -> Dict:
        r = {}
        parsed, err = await self.parse_date_info(message)

        locode = self.resolve_port_locode(message, session)
        r["locode"] = locode
        if parsed:
            for key, value in parsed.items():
                r[key] = value
        return r





    async def parse_port_fuel_price_intent(self, session: SessionDB, message: str) -> Tuple[Optional[Dict], Optional[str]]:
        """
        returns {
            "port_name": "str",
            "year": 2025,
            "month": 12,
            "day": 12,
        }
        """

        if message.lower().strip().isdigit():
            return {"another_port_n": int(message.strip())}, None
        port_alternatives_list = []
        if session.data.check_port_fuel_price:
            for alternative in session.data.check_port_fuel_price.port_alternatives:
                port_alternatives_list.append(alternative.model_dump())

        port_alternatives = json.dumps(port_alternatives_list)

        try:
            prompt = f"""Extract the port name and date from the user input, then return structured JSON.

    USER INPUT: "{message}"
    
    PORT_ALTERNATIVES: 
    "{port_alternatives}"

    RULES:
    - Extract port name (look for common port names or fuel-related locations and always return the LOCODE if possible)
    - Extract year, month, day from any format
    - If year is not specified, use current year
    - Month can be number (1-12) or English name (January-December)
    - Day is always a number (1-31)
    - Handle relative terms: tomorrow, next week, etc.

    OUTPUT JSON:
    {{
      "port_name": "port_name_here",
      "another_port_n": "another_port_n",
      "year": "YYYY|None", 
      "month": "MM|MonthName|None",
      "day": "DD|None"
    }}

    EXAMPLES:
    - "fuel prices in Singapore on 2025-11-26" → {{"port_name": "Singapore", "year": "2025", "month": "11", "day": "26"}}
    - "What's the fuel price in Rotterdam for January 15, 2025?" → {{"port_name": "Rotterdam", "year": "2025", "month": "January", "day": "15"}}
    - "Port of Houston fuel costs tomorrow" → {{"port_name": "Houston", "year": "None", "month": "11", "day": "20"}} (relative to today)
    - "FUEL PRICE DUBAI next Monday" → {{"port_name": "Dubai", "year": "None", "month": "11", "day": "24"}}
    - "bunker prices Shanghai" → {{"port_name": "Shanghai", "year": "None", "month": "None", "day": "None"}}
    - "hello" → {{"port_name": "None", "year": "None", "month": "None", "day": "None"}}

    Now parse: "{message}"
    """

            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[ChatCompletionUserMessageParam(role="user", content=prompt)],
                max_tokens=150,
                temperature=0.1,
            )

            result = json.loads(response.choices[0].message.content)
            return result, None

        except Exception as e:
            return None, str(e)

    def fmt_port(self, p: SeaPortDB):
        if p is None:
            return "UNKNOWN"
        return (
            f"{utils.safe(p.id)}  "
            f"{utils.safe(p.port_name)}  "
            f"{utils.safe(p.country_name)}  "
            f"{utils.safe(p.locode)}"
        )

    async def parse_search_route_intent(self, session: SessionDB, message: str) -> Tuple[Optional[Dict], Optional[str]]:
        try:

            # check the navigation request
            q = message.lower().strip()
            response = {"action": "navigation"}

            if q == "+":
                response = {"action": "navigation", "value": "+"}
            elif q == "-":
                response = {"action": "navigation", "value": "-"}
            elif "end" in q:
                response = {"action": "navigation", "value": "end"}
            elif "reset" in q:
                response = {"action": "navigation", "value": "start"}

            if "reset" in q:
                if "date" in q:
                    response["reset_date"] = True
                if "list" in q:
                    response["value"] = "start"


            parsed_date, err = await self.parse_date_info(message)
            if not err:
                for key, value in parsed_date.items():
                    response[key] = value

            routes = []
            if session.data.route_search:
                for route_id in session.data.route_search.ids:
                    route, err = await self.sql_db.get_route_by_id_2(session.user_id, route_id)
                    if route:
                        routes.append(route)


            if "show" in q or "remove" in q or "rem" in q or  "update" in q:
                action = ""
                q_new = q
                if "show" in q:
                    action = "show"
                    q_new = q.replace("show", "")
                elif "delete" in q or "del" in q:
                    action = "delete"
                    q_new = q.replace("delete", "").replace("del", "")
                elif "update" in q:
                    action = "update"
                    q_new = q.replace("update", "")



                best_index = -1
                best_score = 0.0

                for i, r in enumerate(routes, 1):
                    candidates = [str(i)]
                    if r.departure_port_id:
                        dep, _ = await self.sql_db.get_port_by_id(r.departure_port_id)
                        if dep:
                            candidates.extend([str(dep.port_name), dep.country_name, dep.locode])
                    if r.destination_port_id:
                        dest, _ = await self.sql_db.get_port_by_id(r.destination_port_id)
                        if dest:
                            candidates.extend([str(dest.port_name), dest.country_name, dest.locode])

                    if len(candidates) == 0:
                        continue

                    score = max(SequenceMatcher(None, q_new, c).ratio() for c in candidates)
                    if score > best_score:
                        best_score = score
                        best_index = r.id

                response =  {"action": action, "id": str(best_index)}




            return response, None





#
#
#             routes = []
#             if session.data.route_search:
#                 for route_id in session.data.route_search.ids[:5]:
#                     route, err = await self.sql_db.get_route_by_id_2(session.user_id, route_id)
#                     if route:
#                         routes.append(route)
#
#             ctx_lines = []
#             for i, route in enumerate(routes, 1):
#                 dep, _ = await self.sql_db.get_port_by_id(utils.safe_attr(route, "departure_port_id"))
#                 dest, _ = await self.sql_db.get_port_by_id(utils.safe_attr(route, "destination_port_id"))
#
#                 # Format departure date
#                 dep_date = route.departure_date.strftime("%Y-%m-%d") if route.departure_date else "UNKNOWN"
#
#                 ctx_lines.append(f"{i}")
#                 ctx_lines.append(f"Route id:        {utils.safe(route.id, 'UNKNOWN')}")
#                 ctx_lines.append(f"Departure port:  {self.fmt_port(dep)}")
#                 ctx_lines.append(f"Destination:     {self.fmt_port(dest)}")
#                 ctx_lines.append(f"Departure date:  {dep_date}")
#                 ctx_lines.append("")
#
#             context_text = "\n".join(ctx_lines)
#
#
#
#             prompt = f"""
# Extract JSON describing the user’s intent.
#
# User message: "{message}"
#
# Routes:
# {context_text}
#
# **Output Format:**
# Return ONLY valid JSON in this exact structure:
# {{
#   "intent": "update" | "show" | "delete" | "navigation",
#   "departure": null or string,
#   "destination": null or string,
#   "date": {{
#     "year": "YYYY" or null,
#     "month": "MM" or null,
#     "day": "DD" or null
#   }},
#   "id": null or guid of the selected port,
#   "value": null or "next"|"prev"|"start"|"end"
# }}
#
# **Intent Classification Rules:**
# 1. "show" - when user refers to/show a specific route number or id (like "show 1", "display route 2", "look at route X")
# 2. "delete" - when user says delete/remove/cancel a route
# 3. "navigation" - when user says next/prev/start/end (pagination commands)
# 4. "update" - any filter or search request (changing dates, locations, etc.)
#
# **Mapping Rules for "show" intent:**
# - When user says "show 1", "route 1", "display 1", etc., map it to Route id: bd55f862-8880-4d7b-833c-f1bf0df2836f
# - Only fill the "id" field with the route's GUID
# - Set intent to "show"
# - All other fields should be null (except date object which should have null values)
#
# **Important:**
# - Return ONLY the JSON object, no additional text
# - For "show" intent, only populate the "id" field with the corresponding route GUID
# - Numbers in user messages like "1" refer to the route number in the provided list
# """
#
#             response = self.client.chat.completions.create(
#                 model="gpt-3.5-turbo",
#                 messages=[ChatCompletionUserMessageParam(role="user", content=prompt)],
#                 temperature=0,
#                 max_tokens=200
#             )
#
#             result = json.loads(response.choices[0].message.content)
#
#             def norm(v):
#                 return v.strip() if isinstance(v, str) and v.strip() else None
#
#             intent = result.get("intent", None)
#             intent = intent.lower() if intent else "update"
#
#
#             result["intent"] = intent
#
#             #result["departure"] = norm(result.get("departure"))
#             #result["destination"] = norm(result.get("destination"))
#
#             val = result.get("value")
#             if isinstance(val, str):
#                 result["value"] = val.lower()
#             else:
#                 result["value"] = None
#
#             return result, None

        except Exception as e:
            return None, f"Failed to parse search route intent: {e}"

    def parse_port_user_input(self, text: str):
        text = text.strip()
        if self.is_validation_positive(text):
            return {"action": "confirm"}, None
        if text.isdigit():
            return {"action": "update", "type": "index", "index": int(text)}, None
        return {"action": "update", "type": "name", "query": text}, None

    def find_best_match(self, query: str, ports: list) -> Tuple[Optional[Dict], Optional[str]]:
        """
        Returns the 1-based index of the port whose name or locode
        is most similar to the query (supports typos).
        Each port is expected to have: port_name, country_name, locode.
        """
        if self.is_validation_positive(query):
            return {"action": "confirm"}, None

        if query.isdigit():
            return {"action": "update", "type": "index", "index": int(query)}, None

        query = query.lower().strip()
        best_index = -1
        best_score = 0.0

        for i, p in enumerate(ports, 1):
            candidates = [
                p.port_name.lower(),
                p.country_name.lower(),
                p.locode.lower(),
            ]
            score = max(SequenceMatcher(None, query, c).ratio() for c in candidates)
            if score > best_score:
                best_score = score
                best_index = i

        if best_score < 0.4:
            return {"action": "update", "type": "index", "index": None}, None

        return {"action": "update", "type": "index", "index": best_index}, None

    async def parse_vessel_info(self, route: SeaRouteDB, message: str) -> Tuple[Optional[Dict], Optional[str]]:
        try:

            if self.is_validation_positive(message):
                return {"action": "confirm"}, None
            prompt = f"""
            Extract vessel_name and imo_number from the following message:

            "{message}"

            STRICT RULES:

            1. IMO number:
               - EXACTLY 7 digits
               - Optional prefix "IMO"
               - Digits may contain spaces or dashes, but total digits MUST be 7
               - Otherwise → imo_number = null

            2. Vessel name:
               Vessel name IS CONSIDERED EXPLICIT if ANY of the following are true:
               - The message contains a declarative pattern such as:
                 • "vessel name is <name>"
                 • "ship name is <name>"
                 • "name: <name>"
               - OR a standalone capitalized name not containing words like:
                 "imo", "number", "is", "id"

               Vessel name MUST:
               - Contain at least one letter
               - Be a contiguous phrase
               - NOT be inferred
               - NOT be extracted from words describing IMO

               If none of the above applies → vessel_name = null

            3. Intent:
               - If message is confirmation only ("ok", "yes", "confirm") → action = "confirm"
               - Else if vessel_name OR imo_number is present → action = "update"
               - Else → action = "error"

            FORBIDDEN:
            - Guessing
            - Inferring from context
            - Mixing IMO words into vessel name

            Return ONLY this JSON:

            {{
              "vessel_name": string | null,
              "imo_number": string | null
            }}
            """

            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",  # or gpt-4.1, gpt-3.5, your choice
                messages=[ChatCompletionUserMessageParam(role="user", content=prompt)],
                temperature=0.1,
                max_tokens=500
            )

            result_json = response.choices[0].message.content
            result = json.loads(result_json)

            return result, None

        except Exception as e:
            return {"action": "error", "intent": "error", "error": str(e)}, str(e)

    def _parse_imo_number(self, message: str) -> Tuple[Optional[str], str]:
        msg = message.strip()

        # 1️⃣ extract all digits
        digits = re.findall(r"\d", msg)
        digit_count = len(digits)

        if digit_count == 0:
            return None, "No digits found in input"

        # 2️⃣ detect IMO keyword (informational, not mandatory)
        has_imo_word = bool(re.search(r"\bIMO\b", msg, re.IGNORECASE))

        # 3️⃣ digit count validation
        if digit_count < 7:
            return None, (
                f"IMO number must contain exactly 7 digits, "
                f"found {digit_count}"
            )

        if digit_count > 7:
            return None, (
                f"IMO number must contain exactly 7 digits, "
                f"found {digit_count} (too many digits)"
            )

        # 4️⃣ exactly 7 digits → candidate
        imo = "".join(digits)

        # 5️⃣ sanity check (future-proof)
        if not imo.isdigit():
            return None, "Extracted IMO contains non-digit characters"

        # 6️⃣ optional semantic hint
        if not has_imo_word:
            return imo, "Valid IMO detected (without explicit IMO keyword)"

        return imo, "Valid IMO detected"

    def _parse_name(self, message: str) -> Optional[str]:
        name = message.strip()

        # length limit
        if not (1 <= len(name) <= 75):
            return None

        # only letters, spaces, hyphens
        if not re.fullmatch(r"[A-Za-z\s\-]+", name):
            return None

        # forbidden words check
        words = {w.lower() for w in name.split()}
        if words & FORBIDDEN_NAME_WORDS:
            return None

        return name


    def parse_name(self, message: str) -> Tuple[Optional[dict], Optional[str]]:
        try:
            if self.is_validation_positive(message):
                return {"action": "confirm"}, None

            name = self._parse_name(message)
            if name:
                return {
                    "action": "update",
                    "name": name,
                }, None

            return None, "Could not find name data inside. Please  try again."

        except Exception as ex:
            return None, str(ex)

    def parse_vessel_imo(self, message: str) -> tuple[Optional[dict], Optional[str]]:
        try:
            if self.is_validation_positive(message):
                return {"action": "confirm"}, None

            if self.is_intention_to_skip(message):
                return {"action": "confirm"}, None

            imo, reason = self._parse_imo_number(message)
            if imo:
                return {
                    "action": "update",
                    "imo_number": imo,
                }, None

            return None, reason or "Unknown IMO parsing failure"

        except Exception as ex:
            return None, str(ex)


    async def parse_update_tariff_intent(self, message: str) -> Tuple[Optional[Dict], Optional[str]]:
        try:

            if self.is_validation_positive(message):
                return {"action": "confirm"}, None

            context = ""
            available_tariffs, err = await self.sql_db.get_available_tariffs()
            if available_tariffs and not err:
                context = json.dumps([t.to_dict() for t in available_tariffs])


            prompt = f"""
                Extract contact and company information from the following message:
        
                "{message}"
                
                About available tariffs: 
                {context}
        
                STRICT RULES (no guessing, no inference):
        
                1. Name:
                   - Must be EXPLICITLY stated by the user
                   - Valid patterns include:
                     • "my name is <name>"
                     • "name: <name>"
                     • "this is <name>"
                   - Must contain letters
                   - Must NOT be inferred from email or company
                   - If not explicitly stated → name = null
        
                2. Mobile phone number:
                   - Must contain digits only after cleanup
                   - May include spaces, dashes, parentheses, or leading "+"
                   - Minimum 7 digits, maximum 15 digits
                   - If digits count is outside this range → mobile_phone_number = null
                   - Do NOT guess country codes
        
                3. Email:
                   - Must match standard email format: local@domain
                   - No guessing, no fixing typos
                   - If invalid → email = null
        
                4. Company name:
                   - Must be explicitly stated
                   - Valid patterns include:
                     • "company is <company>"
                     • "company name is <company>"
                     • "from <company>"
                     • "working at <company>"
                   - Must contain at least one letter
                   - Must NOT be inferred from email domain
                   - If not explicitly stated → company_name = null
                   
                5. Chosen tariff
                    - the tariff name user has chosen to use in the future.
                    
                6. User message
                    - if use has added a message, put it into user_messafe field
        
        
                FORBIDDEN:
                - Inferring name from email
                - Inferring company from email domain
                - Guessing missing fields
                - Normalizing or correcting data
        
                Return ONLY this JSON:
        
                {{
                  "name": string | null,
                  "mobile_phone_number": string | null,
                  "email": string | null,
                  "company_name": string | null,
                  "chosen_tariff" : string | null,
                  "user_message": string | null
                }}
                """

            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",  # or gpt-4.1, gpt-3.5, your choice
                messages=[ChatCompletionUserMessageParam(role="user", content=prompt)],
                temperature=0.1,
                max_tokens=800
            )

            result_json = response.choices[0].message.content
            result = json.loads(result_json)

            return result, None

        except Exception as e:
            return {"action": "error", "intent": "error", "error": str(e)}, str(e)

    async def parse_user_management_intent(self, session: SessionDB, message: str) -> Tuple[Optional[Dict], Optional[str]]:
        try:
            q = message.lower().strip()

            # Simple navigation commands
            if q in ["+", "next"]:
                return {"action": "navigation", "value": "+"}, None
            elif q in ["-", "prev", "previous", "back"]:
                return {"action": "navigation", "value": "-"}, None
            elif q in ["start", "first", "beginning"]:
                return {"action": "navigation", "value": "start"}, None
            elif q in ["end", "last"]:
                return {"action": "navigation", "value": "end"}, None


            # Filter commands
            elif q in ["active only", "show active"]:
                return {"action": "filter_status", "status": "active"}, None
            elif q in ["blocked only", "show blocked"]:
                return {"action": "filter_status", "status": "blocked"}, None
            elif q in ["all users", "show all"]:
                return {"action": "filter_status", "status": "all"}, None
            elif q in ["admins only", "show admins", "show admin", "search admin", "admins", "search admins"]:
                return {"action": "filter_admin", "is_admin": True}, None
            elif q in ["non-admins", "show non-admins", "no admin", "no admins", "show not admin", "show not admins", "show non admin", "show non admins"]:
                return {"action": "filter_admin", "is_admin": False}, None
            elif q in ["reset filters", "clear filters"]:
                return {"action": "reset_filters"}, None

            # Search command
            elif q.startswith("search "):
                search_term = q[7:].strip()
                return {"action": "search", "search_term": search_term}, None


            # Check for block/unblock commands
            block_pattern = r'^(block|unblock|ban|unban)\s+(.+)$'
            import re
            block_match = re.match(block_pattern, q, re.IGNORECASE)
            if block_match:
                action_type = block_match.group(1).lower()
                identifier = block_match.group(2).strip()
                action = "toggle_block"

                # Try to find user based on identifier
                user_id = await self._find_user_by_identifier(session, identifier)
                if user_id:
                    return {"action": action, "user_id": user_id}, None
                else:
                    # If we can't find, still return with the identifier
                    return {"action": action, "user_id": identifier}, None

            # Check for stats command
            stats_pattern = r'^(stats|statistics|info|details)\s+(.+)$'
            stats_match = re.match(stats_pattern, q, re.IGNORECASE)
            if stats_match:
                identifier = stats_match.group(2).strip()
                action = "show_stats"

                user_id = await self._find_user_by_identifier(session, identifier)
                if user_id:
                    return {"action": action, "user_id": user_id}, None
                else:
                    return {"action": action, "user_id": identifier}, None

            # Check for show command (simple version)
            if q.startswith("show "):
                identifier = q[5:].strip()
                user_id = await self._find_user_by_identifier(session, identifier)
                if user_id:
                    return {"action": "show_stats", "user_id": user_id}, None
                else:
                    return {"action": "show_stats", "user_id": identifier}, None

            # --------------------------------------------------
            # START TARIFF UPDATE FLOW
            # --------------------------------------------------
            #tariff_pattern = r'^(update|change|set)\s+tariff(\s+to)?$'
            tariff_match = re.match(r'^(update|change|set)\s+tariff(\s+to)?(\s+(.+))?$', q, re.IGNORECASE)

            if tariff_match:
                identifier = tariff_match.group(4)

                # No identifier → fallback to navigation
                if not identifier:
                    return {"action": "navigation"}, None

                identifier = identifier.strip()
                user_id = await self._find_user_by_identifier(session, identifier)

                if not user_id:
                    return {"action": "navigation"}, None

                return {
                    "action": "start_tariff_update",
                    "user_id": user_id
                }, None

            # Default to navigation if no other pattern matched
            return {"action": "navigation"}, None

        except Exception as e:
            #logger.error(f"Error parsing user management intent: {str(e)}")
            return None, str(e)

    async def _find_user_by_identifier(self, session: SessionDB, identifier: str) -> Optional[str]:
        """Helper method to find user ID by various identifiers"""
        try:
            # Clean identifier
            identifier = identifier.strip().lower()

            # Load users from session
            users = []
            if hasattr(session.data, 'user_search') and session.data.user_search:
                for user_id in session.data.user_search.ids:
                    user, err = await self.sql_db.get_user_by_id(user_id)
                    if user:
                        users.append(user)

            # 1. Check for exact numeric ID match
            if identifier.isdigit():
                for i, user in enumerate(users, 1):
                    if str(i) == identifier or str(user.telegram_id) == identifier:
                        return str(user.id)

            # 2. Check for email match
            if "@" in identifier:
                for user in users:
                    if user.email and user.email.lower() == identifier:
                        return str(user.id)

            # 3. Check for username match (with or without @)
            username = identifier.lstrip('@')
            for user in users:
                if user.telegram_user_name and user.telegram_user_name.lower() == username:
                    return str(user.id)

            # 4. Fuzzy matching for names and partial matches
            best_user_id = None
            best_score = 0.0

            for user in users:
                candidates = []

                # User properties to match against
                if user.first_name:
                    candidates.append(user.first_name.lower())
                if user.last_name:
                    candidates.append(user.last_name.lower())
                if user.first_name and user.last_name:
                    candidates.append(f"{user.first_name.lower()} {user.last_name.lower()}")
                if user.telegram_user_name:
                    candidates.append(user.telegram_user_name.lower())
                if user.email:
                    candidates.append(user.email.lower())
                    # Also try email local part
                    email_local = user.email.lower().split('@')[0]
                    candidates.append(email_local)
                if user.company_name:
                    candidates.append(user.company_name.lower())

                # Calculate similarity scores
                for candidate in candidates:
                    score = SequenceMatcher(None, identifier, candidate).ratio()
                    if score > best_score and score > 0.5:  # 50% similarity threshold
                        best_score = score
                        best_user_id = str(user.id)

            return best_user_id

        except Exception as e:
            #logger.error(f"Error finding user by identifier: {str(e)}")
            return None

    async def parse_update_tariff_intent_robust(self, message: str):
        try:
            if self.is_validation_positive(message):
                return {"action": "confirm"}, None

            available_tariffs, err = await self.sql_db.get_available_tariffs()
            if err:
                return {"action": "err"}, None

            query = message.lower().strip()
            best_index = ""
            best_score = 0.0

            for i, tariff in enumerate(available_tariffs, 1):
                # Assuming tariff has at least a name field
                candidates = [str(i), tariff.name.lower()]

                # Add code if available
                try:
                    if tariff.code:
                        candidates.append(tariff.code.lower())
                except:
                    pass

                score = max([SequenceMatcher(None, query, c).ratio() for c in candidates])
                if score > best_score:
                    best_score = score
                    best_index = str(tariff.id)

            return {"action": "update", "tariff_id": best_index}, None

        except Exception as e:
            return {"action": "error"}, None

    async def parse_new_user_intent(self, message):
        try:
            if self.is_validation_positive(message):
                return {"action": "confirm"}, None

            if message == "/start":
                return None, "Please select an option."

            options = [
                "Ship owner",
                "Ship operator",
                "Fleet / Voyage manager",
                "Bunker trader / Supplier",
                "Charterer",
                "Technical / Other"
            ]

            query = message.lower().strip()
            best_role = None
            best_score = 0.0

            for i, option in enumerate(options, 1):
                candidates = [str(i), option.lower()]
                score = max([SequenceMatcher(None, query, c).ratio() for c in candidates])
                if score > best_score:
                    best_score = score
                    best_role = option


            if best_score < 0.5:
                return {"action": "error"}, "Please select from options."

            return {"action": "update", "role": best_role}, None

        except Exception as ex:
            return {"action": "error"}, str(ex)

    def parse_yes_or_no(self, message):
        try:

            if self.is_validation_positive(message):
                return {"action": "confirm"}, None

            if self.is_validation_negative(message):
                return {"action": "decline"}, None

            return None, "Did not understand your choice, try again please."

        except Exception as ex:
            return None, str(ex)

    def parse_user_email(self, message: str) -> Tuple[Optional[Dict], Optional[str]]:
        """
        Parse user email from message using regex only.

        Rules:
        - If message is confirmation-only → action = confirm
        - If valid email found → action = update, email returned
        - Else → action = error
        """
        try:
            message = message.strip()

            if self.is_validation_positive(message):
                return {"action": "confirm"}, None

            match = EMAIL_REGEX.search(message)
            if match:
                return {
                    "action": "update",
                    "email": match.group(0)
                }, None

            return None, "Could not parse anything"

        except Exception as e:
            return None, str(e)