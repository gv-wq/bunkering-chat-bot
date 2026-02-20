import math
import json
import os
import uuid
import asyncio
from datetime import datetime, timedelta
from typing import Any, List, Optional, Tuple, Dict
from uuid import UUID

import asyncpg
from psycopg2.pool import SimpleConnectionPool
from psycopg2.extras import RealDictCursor

from app.data.dto.main.Coordinates import Coordinates
from app.data.dto.main.Fuel import FuelDB
from app.data.dto.main.MabuxPortLocodeMap import MabuxPortLocodeMap, MabuxPortLocodeMapDB
from app.data.dto.main.MabuxPortFuelPrice import MabuxPortFuelPrice, MabuxPortFuelPriceDB
from app.data.dto.main.PortFuelPrice import PortFuelPrice, PortFuelPriceDB
from app.data.dto.main.SeaPort import SeaPortDB, SeaPortBubble
from app.data.dto.main.SeaRoute import SeaRouteDB
from app.data.dto.main.Session import SessionDB
from app.data.dto.main.SessionData import SessionData, RouteSearch, UserSearch, AdminUpdateTariff
from app.data.dto.main.TariffSelection import TariffSelection
from app.data.dto.main.User import UserDB
from app.data.dto.main.UserTariff import UserTariffBD
from app.data.dto.searoute.SearoutePort import SearoutePort
from app.services.utils import utils

KM_PER_DEG_LAT = 111.32  # approximate km per degree latitude




class DbService:
    def __init__(self):
        self.connection_pool = None

    async def init_pool(self):
        db_name = os.getenv("DB_NAME", None)
        db_user = os.getenv("DB_USER", None)
        db_password = os.getenv("DB_PASSWORD", None)
        db_host = os.getenv("DB_HOST", None)
        db_port = os.getenv("DB_PORT", None)

        if not all([db_name, db_user, db_password, db_host, db_port]):
            raise Exception("Could not find needed envs for the database")

        dsn = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"

        self.connection_pool = await asyncpg.create_pool(
            database=db_name,
            user=db_user,
            password=db_password,
            host=db_host,
            port=db_port,
            min_size=1,
            max_size=20
        )
        self.simple_pool = SimpleConnectionPool(1, 20, dsn)
        #self.simple_conn = self.simple_pool.getconn()

    # async def create_user(
    #     self,
    #     telegram_id: int,
    #     telegram_user_name: str = None,
    #     phone_number: str = None,
    #     first_name: str = None,
    #     last_name: str = None,
    #     email: str = None,
    #     telegram_effective_chat_id: int = None
    # ) -> Tuple[Optional[UserDB], Optional[str]]:
    #     try:
    #         async with self.connection_pool.acquire() as conn:
    #             # First get the Basic tariff ID
    #             basic_tariff = await conn.fetchrow(
    #                 "SELECT id FROM user_tariffs WHERE name = 'Basic' AND is_active = true"
    #             )
    #
    #             if not basic_tariff:
    #                 return None, "Basic tariff not found"
    #
    #             # Create new user with new fields
    #             row = await conn.fetchrow(
    #                 """
    #                 INSERT INTO users (
    #                     telegram_id, telegram_user_name, phone_number,
    #                     first_name, last_name, email, registration_date,
    #                     current_tariff_id, free_tier_expiry, is_active, telegram_effective_chat_id
    #                 ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
    #                 RETURNING *
    #             """,
    #                 telegram_id,
    #                 telegram_user_name,
    #                 phone_number,
    #                 first_name,
    #                 last_name,
    #                 email,
    #                 datetime.now(),
    #                 basic_tariff["id"],
    #                 datetime.now(),
    #                 True,
    #                 telegram_effective_chat_id
    #             )
    #
    #             return UserDB.from_db_row(row), None
    #     except Exception as e:
    #         return None, f"Error creating user: {str(e)}"

    async def create_user(
            self,
            data: dict
    ) -> Tuple[Optional[UserDB], Optional[str]]:
        try:
            async with self.connection_pool.acquire() as conn:
                # Get Basic tariff
                basic_tariff = await conn.fetchrow(
                    "SELECT id FROM user_tariffs WHERE name = 'Basic' AND is_active = true"
                )

                if not basic_tariff:
                    return None, "Basic tariff not found"

                now = datetime.now()
                phone_number = utils.clean_phone_number(data.get("phone_number"))

                row = await conn.fetchrow(
                    """
                    INSERT INTO users (
                        telegram_id,
                        telegram_user_name,
                        telegram_effective_chat_id,

                        whatsapp_phone,
                        whatsapp_effective_chat,
                        whatsapp_business_id,
                        whatsapp_name,
                        whatsapp_profile_pic_url,

                        phone_number,
                        first_name,
                        last_name,
                        email,

                        registration_date,
                        current_tariff_id,
                        free_tier_expiry,
                        is_active,
                        message_count,
                        route_count
                    )
                    VALUES (
                        $1,$2,$3,
                        $4,$5,$6,$7,$8,
                        $9,$10,$11,$12,
                        $13,$14,$15,$16,$17,$18
                    )
                    RETURNING *
                    """,
                    data.get("telegram_id"),
                    data.get("telegram_user_name"),
                    data.get("telegram_effective_chat_id"),

                    data.get("whatsapp_phone"),
                    data.get("whatsapp_effective_chat"),
                    data.get("whatsapp_business_id"),
                    data.get("whatsapp_name"),
                    data.get("whatsapp_profile_pic_url"),

                    phone_number,
                    data.get("first_name"),
                    data.get("last_name"),
                    data.get("email"),

                    now,
                    basic_tariff["id"],
                    now,
                    True,
                    0,
                    0
                )

                return UserDB.from_db_row(row), None

        except Exception as e:
            return None, f"Error creating user: {str(e)}"

    async def get_user_by_telegram_id(
        self, telegram_id: int
    ) -> Tuple[Optional[UserDB], Optional[str]]:
        try:
            async with self.connection_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM users WHERE telegram_id = $1", telegram_id
                )
                if not row:
                    return None, None
                return UserDB.from_db_row(row), None
        except Exception as e:
            return None, str(e)


    async def get_user_by_telegram_name(self, tg_user_name: str) -> Tuple[Optional[UserDB], Optional[str]]:
        try:
            async with self.connection_pool.acquire() as conn:
                row = await conn.fetchrow("SELECT * FROM users WHERE telegram_user_name = $1", tg_user_name)
                if not row:
                    return None, None
                return UserDB.from_db_row(row), None
        except Exception as e:
            return None, str(e)

    async def get_user_by_phone_number(
            self, phone: str
    ) -> Tuple[Optional[UserDB], Optional[str]]:
        try:
            normalized_phone = utils.clean_phone_number(phone)

            if not normalized_phone:
                return None, "Could not process your phone number!"

            async with self.connection_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM users WHERE phone_number = $1",
                    normalized_phone
                )

                if not row:
                    return None, None

                return UserDB.from_db_row(row), None

        except Exception as e:
            return None, str(e)


    async def get_or_create_user(
        self, telegram_id: int, user_data: dict = None
    ) -> Tuple[Optional[UserDB], Optional[str]]:
        """Get existing user or create new one with Basic tariff"""
        user, err = await self.get_user_by_telegram_id(telegram_id)
        if err:
            return None, err

        if user:
            return user, None

        # Create new user with new fields
        telegram_user_name = user_data.get("telegram_user_name") if user_data else None
        phone_number = user_data.get("phone_number") if user_data else None
        first_name = user_data.get("first_name") if user_data else None
        last_name = user_data.get("last_name") if user_data else None
        email = user_data.get("email") if user_data else None

        return await self.create_user(
            telegram_id=telegram_id,
            telegram_user_name=telegram_user_name,
            phone_number=phone_number,
            first_name=first_name,
            last_name=last_name,
            email=email,
        )

    async def get_user_by_id(
        self, user_id: UUID
    ) -> Tuple[Optional[UserDB], Optional[str]]:
        """Get user by ID"""
        try:
            async with self.connection_pool.acquire() as conn:
                row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
                if not row:
                    return None, None
                return UserDB.from_db_row(row), None
        except Exception as e:
            return None, f"User fetch error: {str(e)}"

    async def get_tariff(
        self, user: UserDB
    ) -> Tuple[Optional[UserTariffBD], Optional[str]]:
        try:
            async with self.connection_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT ut.* FROM user_tariffs ut 
                    JOIN users u ON u.current_tariff_id = ut.id 
                    WHERE u.id = $1
                """,
                    user.id,
                )
                if not row:
                    return None, None
                return UserTariffBD.from_db_row(row), None
        except Exception as e:
            return None, str(e)

    async def get_tariff_by_id(self, user_id: str) -> Tuple[Optional[UserTariffBD], Optional[str]]:
        try:
            async with self.connection_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT * FROM user_tariffs 
                    WHERE id = $1
                """,
                    user_id,
                )
                if not row:
                    return None, None
                return UserTariffBD.from_db_row(row), None
        except Exception as e:
            return None, str(e)

    async def set_test_tariff(
        self, user: UserDB
    ) -> Tuple[Optional[UserTariffBD], Optional[str]]:
        """Assign Basic tariff to user (for testing/demo)"""
        try:
            async with self.connection_pool.acquire() as conn:
                # Get Basic tariff
                row = await conn.fetchrow(
                    "SELECT * FROM user_tariffs WHERE name = 'Basic' AND is_active = true"
                )
                if not row:
                    return None, "Basic tariff not found"

                # Update user with Basic tariff
                await conn.execute(
                    "UPDATE users SET current_tariff_id = $1 WHERE id = $2",
                    row["id"],
                    user.id,
                )

                return UserTariffBD.from_db_row(row), None

        except Exception as e:
            return None, f"Tariff assignment error: {str(e)}"

    # async def get_session(self, user_id: UUID) -> Tuple[Optional[SessionDB], Optional[str]]:
    #     try:
    #         async with self.connection_pool.acquire() as conn:
    #             row = await conn.fetchrow(
    #                 "SELECT * FROM user_sessions WHERE user_id = $1 ORDER BY last_activity DESC LIMIT 1",
    #                 user_id
    #             )
    #             if not row:
    #                 return None, None
    #             return SessionDB.from_db_row(row), None
    #     except Exception as e:
    #         return None, str(e)

    async def get_or_create_session(
        self, user_id: UUID
    ) -> Tuple[Optional[SessionDB], Optional[str]]:
        try:
            async with self.connection_pool.acquire() as conn:
                # Try to get existing session first
                row = await conn.fetchrow(
                    "SELECT * FROM user_sessions WHERE user_id = $1 ORDER BY last_activity DESC LIMIT 1",
                    user_id,
                )

                if row:
                    return SessionDB.from_db_row(row), None

                # If no session exists, create a new one
                new_session_id = uuid.uuid4()
                current_time = datetime.now()

                row = await conn.fetchrow(
                    """
                    INSERT INTO user_sessions (id, user_id, last_activity)
                    VALUES ($1, $2, $3)
                    RETURNING *
                    """,
                    new_session_id,
                    user_id,
                    current_time,
                )

                return SessionDB.from_db_row(row), None

        except Exception as e:
            return None, str(e)

    async def update_session(
        self,
        user_id: UUID,
        current_task: str = None,
        current_step: str = None,
        route_id: UUID = None,
        session_data: SessionData = None,


    ) -> Tuple[Optional[SessionDB], Optional[str]]:
        try:
            async with self.connection_pool.acquire() as conn:
                existing_session = await conn.fetchrow(
                    "SELECT id FROM user_sessions WHERE user_id = $1", user_id
                )

                _session_data = session_data or SessionData(check_port_fuel_price=None, route_search=RouteSearch.from_dict({}), tariff_selection=TariffSelection(user_message=None, chosen_tariff=None), user_search=UserSearch.from_dict({}), admin_update_tariff=AdminUpdateTariff.from_dict({}))
                _session_data = _session_data.to_dict()
                _session_data = json.dumps(_session_data)

                if existing_session:
                    # Update existing session
                    row = await conn.fetchrow(
                        """
                        UPDATE user_sessions 
                        SET current_task = $2, current_step = $3, route_id = $4, 
                            data = $5,  last_activity = NOW()
                        WHERE user_id = $1
                        RETURNING *
                    """,
                        user_id,
                        current_task,
                        current_step,
                        route_id,
                        _session_data,
                    )
                else:

                    row = await conn.fetchrow(
                        """
                        INSERT INTO user_sessions 
                        (user_id, current_task, current_step, route_id, data, last_activity)
                        VALUES ($1, $2, $3, $4, $5, NOW())
                        RETURNING *
                    """,
                        user_id,
                        current_task,
                        current_step,
                        route_id,
                        _session_data,
                    )

                return SessionDB.from_db_row(row), None

        except Exception as e:
            return None, f"Session update error: {str(e)}"

    async def get_available_ports(
        self, offset: int = 0, limit: int = 20
    ) -> Tuple[List[SeaPortDB], Optional[str]]:
        try:
            async with self.connection_pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM ports WHERE is_active = true ORDER BY name LIMIT $1 OFFSET $2",
                    limit,
                    offset,
                )
                return [SeaPortDB.from_db_row(row) for row in rows], None
        except Exception as e:
            return [], str(e)


    async def get_all_ports(self ) -> Tuple[Optional[List[SeaPortDB]], Optional[str]]:
        try:
            async with self.connection_pool.acquire() as conn:
                query = """
                SELECT 
               id,
               bubble_id, 
               port_name,
               country_name,
               locode,
               search_key,
               latitude,
               longitude,
               mabux_ids,
               port_size,
               mabux_id,
               barge_status,
               truck_status,
               agent_contact_list
               FROM public.ports_vector_new
             """
                rows = await conn.fetch(query)
                if rows:
                    return [SeaPortDB.from_tuple(row) for row in rows], None
                return None, "Could not find port"

        except Exception as e:
            return None, str(e)


    async def get_port_by_id(
        self, port_id: str
    ) -> Tuple[Optional[SeaPortDB], Optional[str]]:
        try:
            async with self.connection_pool.acquire() as conn:
                query = """
                SELECT 
               id,
               bubble_id, 
               port_name,
               country_name,
               locode,
               search_key,
               latitude,
               longitude,
               mabux_ids,
               port_size,
               mabux_id,
               barge_status,
               truck_status,
               agent_contact_list
               FROM public.ports_vector_new
               WHERE id = $1
             """
                row = await conn.fetchrow(query, port_id)
                if row:
                    return SeaPortDB.from_tuple(row), None
                return None, "Could not find port"

        except Exception as e:
            return None, str(e)

    async def get_port_by_locode(
        self, locode: str
    ) -> Tuple[Optional[SeaPortDB], Optional[str]]:
        try:
            async with self.connection_pool.acquire() as conn:
                query = """
                SELECT 
               id,
               bubble_id, 
               port_name,
               country_name,
               locode,
               search_key,
               latitude,
               longitude,
               mabux_ids,
               port_size,
                mabux_id,
               barge_status,
               truck_status,
               agent_contact_list
                FROM public.ports_vector_new
                WHERE LOWER(locode) = $1
                """
                row = await conn.fetchrow(query, locode.lower().strip())
                if row:
                    return SeaPortDB.from_db_row(row), None
                return None, "Could not find port"

        except Exception as e:
            return None, str(e)

    async def get_ports_by_locodes(self, locodes: set[str]) -> Tuple[Optional[dict[str, SeaPortDB]], Optional[str]]:
        if not locodes:
            return {}, None

        try:
            async with self.connection_pool.acquire() as conn:
                query = """
                    SELECT 
                    id,
                    bubble_id, 
                    port_name,
                    country_name,
                    locode,
                    search_key,
                    latitude,
                    longitude,
                    mabux_ids,
                    port_size,
                    mabux_id,
                    barge_status,
                    truck_status,
                    agent_contact_list
                    FROM public.ports_vector_new
                    WHERE locode = ANY($1::text[])
                """
                rows = await conn.fetch(query, list(locodes))
                return {row["locode"]: SeaPortDB.from_db_row(row)for row in rows}, None

        except Exception as e:
            return None, str(e)



    async def get_port_by_country_and_port_names(self, country_name: str, port_name: str) -> Tuple[Optional[SeaPortDB], Optional[str]]:
        try:
            async with self.connection_pool.acquire() as conn:
                query = """
                SELECT 
               id,
               bubble_id, 
               port_name,
               country_name,
               locode,
               search_key,
               latitude,
               longitude,
               mabux_ids,
               port_size,
                mabux_id,
               barge_status,
               truck_status
                FROM public.ports_vector_new
                WHERE LOWER(country_name) = $1 AND LOWER(port_name) = $2
                """
                row = await conn.fetchrow(query, country_name.lower().strip(), port_name.lower().strip())
                if row:
                    return SeaPortDB.from_db_row(row), None
                return None, "Could not find port"

        except Exception as e:
            return None, str(e)


    async def get_port_by_port_names(self, port_name: str) -> Tuple[Optional[SeaPortDB], Optional[str]]:
        try:
            async with self.connection_pool.acquire() as conn:
                query = """
                SELECT 
               id,
               bubble_id, 
               port_name,
               country_name,
               locode,
               search_key,
               latitude,
               longitude,
               mabux_ids,
               port_size,
                mabux_id,
               barge_status,
               truck_status
                FROM public.ports_vector_new
                WHERE LOWER(port_name) = $1
                """
                row = await conn.fetchrow(query, port_name.lower().strip())
                if row:
                    return SeaPortDB.from_db_row(row), None
                return None, "Could not find port"

        except Exception as e:
            return None, str(e)



    async def find_ports_by_similar_name(
        self, name: str
    ) -> Tuple[List[SeaPortDB], Optional[str]]:
        try:
            async with self.connection_pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM ports_vector WHERE name ILIKE $1 LIMIT 10",
                    f"%{name}%",
                )
                return [SeaPortDB.from_db_row(row) for row in rows], None
        except Exception as e:
            return [], str(e)

    async def get_or_create_route(
        self, session: SessionDB
    ) -> Tuple[Optional[Any], Optional[str]]:
        if session.route_id:
            route, err = await self.get_route_by_id(str(session.route_id))
            if err:
                return None, f"Route fetch error: {err}"
            return route, None
        else:
            route_data = {
                "user_id": session.user_id,
                "status": "draft",
                "departure_port_id": None,
                "destination_port_id": None,
                "estimated_departure_time": None,
                "average_speed_kts": None,
                "max_deviation_nm": None,
                "zones_preferences": {},  # Empty dict for JSONB field
                "fuels": [],
                "bunkering_steps": {},
                "map_image_bytes": None,
                "data": {},
                "vessel_name": None,
                "imo_number": None
            }
            route, err = await self.create_route(route_data)
            if err:
                return None, f"Route creation error: {err}"

            # Update session with route ID
            await self.update_session(
                session.user_id,
                session.current_task,
                session.current_step,
                route.id,
                session.data,
            )
            return route, None

    async def get_route_by_id(
        self, route_id: str
    ) -> Tuple[Optional[SeaRouteDB], Optional[str]]:
        """Get route by ID"""
        try:
            async with self.connection_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM routes WHERE id = $1",
                    uuid.UUID(route_id),
                )
                if not row:
                    return None, "Route not found"
                return SeaRouteDB.from_db_row(row), None
        except Exception as e:
            return None, f"Route fetch error: {str(e)}"
    #
    # async def count_routes(
    #         self,
    #         user_id: uuid,
    #         statuses: Optional[Tuple[str, ...]] = None
    # ) -> Tuple[int, Optional[str]]:
    #     """Count total number of routes for user"""
    #
    #     try:
    #         async with self.connection_pool.acquire() as conn:
    #             if statuses:
    #                 rows = await conn.fetchval(
    #                     """
    #                     SELECT COUNT(*)
    #                     FROM routes
    #                     WHERE user_id = $1
    #                       AND status = ANY($2)
    #                     """,
    #                     user_id,
    #                     list(statuses),
    #                 )
    #             else:
    #                 rows = await conn.fetchval(
    #                     """
    #                     SELECT COUNT(*)
    #                     FROM routes
    #                     WHERE user_id = $1
    #                     """,
    #                     user_id,
    #                 )
    #
    #             return rows or 0, None
    #
    #     except Exception as e:
    #         return 0, f"Route count error: {str(e)}"


    async def get_route_by_id_2(self, user_id: UUID, route_id: str) -> Tuple[Optional[SeaRouteDB], Optional[str]]:
        try:
            async with self.connection_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM routes WHERE id = $1 and user_id = $2 and status != 'deleted'",
                    route_id,
                    user_id,
                )
                if not row:
                    return None, "Route not found"
                return SeaRouteDB.from_db_row(row), None
        except Exception as e:
            return None, f"Route fetch error: {str(e)}"

    async def get_route_by_id_3(self, route_id: str) -> Tuple[Optional[SeaRouteDB], Optional[str]]:
        try:
            async with self.connection_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM routes WHERE id = $1 and status != 'deleted'",
                    route_id,
                )
                if not row:
                    return None, "Route not found"
                return SeaRouteDB.from_db_row(row), None
        except Exception as e:
            return None, f"Route fetch error: {str(e)}"



    async def count_routes(
            self,
            user_id: str,
            departure_date: Optional[datetime] = None
    ):
        try:
            async with self.connection_pool.acquire() as conn:
                query = """
                    SELECT COUNT(*)
                    FROM routes
                    WHERE user_id = $1
                    AND ( departure_port_id IS NOT NULL OR destination_port_id IS NOT NULL)
                    AND status != 'deleted'
                """
                params = [user_id]
                param_idx = 2

                if departure_date:
                    query += f" AND estimated_departure_time::date = ${param_idx}::date"
                    params.append(departure_date)

                count = await conn.fetchval(query, *params)
                return count, None

        except Exception as e:
            return None, str(e)


    async def count_users(
            self,
            status_filter: Optional[str] = None,
            admin_filter: Optional[bool] = None,
            search_term: Optional[str] = None
    ) -> Tuple[int, Optional[str]]:
        """Count users with optional filters"""
        try:
            async with self.connection_pool.acquire() as conn:
                query = "SELECT COUNT(*) FROM users WHERE 1=1"
                params = []
                param_counter = 1

                if status_filter == "active":
                    query += f" AND is_active = ${param_counter}"
                    params.append(True)
                    param_counter += 1
                elif status_filter == "blocked":
                    query += f" AND is_active = ${param_counter}"
                    params.append(False)
                    param_counter += 1

                if admin_filter is not None:
                    query += f" AND is_admin = ${param_counter}"
                    params.append(admin_filter)
                    param_counter += 1

                if search_term:
                    search_pattern = f"%{search_term}%"
                    query += f""" AND (
                        email ILIKE ${param_counter} OR
                        first_name ILIKE ${param_counter} OR
                        last_name ILIKE ${param_counter} OR
                        telegram_user_name ILIKE ${param_counter} OR
                        CAST(telegram_id AS TEXT) ILIKE ${param_counter} OR
                        company_name ILIKE ${param_counter}
                    )"""
                    params.append(search_pattern)
                    param_counter += 1

                count = await conn.fetchval(query, *params)
                return count, None
        except Exception as e:
            return 0, str(e)

    async def get_users_range(
            self,
            offset: int,
            limit: int = 5,
            status_filter: Optional[str] = None,
            admin_filter: Optional[bool] = None,
            search_term: Optional[str] = None
    ) -> Tuple[List[UserDB], Optional[str]]:
        """Get users with pagination and filters"""
        try:
            async with self.connection_pool.acquire() as conn:
                query = "SELECT * FROM users WHERE 1=1"
                params = []
                param_counter = 1

                if status_filter == "active":
                    query += f" AND is_active = ${param_counter}"
                    params.append(True)
                    param_counter += 1
                elif status_filter == "blocked":
                    query += f" AND is_active = ${param_counter}"
                    params.append(False)
                    param_counter += 1

                if admin_filter is not None:
                    query += f" AND is_admin = ${param_counter}"
                    params.append(admin_filter)
                    param_counter += 1

                if search_term:
                    search_pattern = f"%{search_term}%"
                    query += f""" AND (
                        email ILIKE ${param_counter} OR
                        first_name ILIKE ${param_counter} OR
                        last_name ILIKE ${param_counter} OR
                        telegram_user_name ILIKE ${param_counter} OR
                        CAST(telegram_id AS TEXT) ILIKE ${param_counter} OR
                        company_name ILIKE ${param_counter}
                    )"""
                    params.append(search_pattern)
                    param_counter += 1

                query += f" ORDER BY created_at DESC LIMIT ${param_counter} OFFSET ${param_counter + 1}"
                params.extend([limit, offset])

                rows = await conn.fetch(query, *params)
                users = [UserDB(**dict(row)) for row in rows]
                return users, None
        except Exception as e:
            return [], str(e)

    async def update_user_status(self, user_id: str, is_active: bool) -> Tuple[bool, Optional[str]]:
        """Block or unblock a user"""
        try:
            async with self.connection_pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE users 
                    SET is_active = $1, updated_at = NOW() 
                    WHERE id = $2
                    """,
                    is_active, user_id
                )
                return True, None
        except Exception as e:
            return False, str(e)

    async def get_user_route_stats(self, user_id: str) -> Tuple[Dict, Optional[str]]:
        """Get route statistics for a user"""
        try:
            async with self.connection_pool.acquire() as conn:
                # Count routes by status
                rows = await conn.fetch(
                    """
                    SELECT 
                        COUNT(*) as total,
                        COUNT(CASE WHEN status = 'active' THEN 1 END) as active,
                        COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed,
                        COUNT(CASE WHEN status = 'deleted' THEN 1 END) as deleted,
                        COUNT(CASE WHEN status = 'draft' THEN 1 END) as draft
                    FROM routes 
                    WHERE user_id = $1
                    """,
                    user_id
                )

                if rows:
                    return dict(rows[0]), None
                return {}, None
        except Exception as e:
            return {}, str(e)

    async def search_users(self, search_term: str) -> Tuple[List[UserDB], Optional[str]]:
        """Search users by email, name, or telegram ID"""
        try:
            async with self.connection_pool.acquire() as conn:
                search_pattern = f"%{search_term}%"
                rows = await conn.fetch(
                    """
                    SELECT * FROM users 
                    WHERE 
                        email ILIKE $1 OR
                        first_name ILIKE $1 OR
                        last_name ILIKE $1 OR
                        telegram_user_name ILIKE $1 OR
                        CAST(telegram_id AS TEXT) ILIKE $1 OR
                        company_name ILIKE $1
                    ORDER BY created_at DESC
                    LIMIT 20
                    """,
                    search_pattern
                )
                users = [UserDB(**dict(row)) for row in rows]
                return users, None
        except Exception as e:
            return [], str(e)

    async def count_routes_with_date_filter(
            self,
            user_id: str,
            departure_date: Optional[datetime] = None
    ):
        async with self.connection_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT COUNT(*)
                FROM routes
                WHERE user_id = $1
                AND (departure_port_id IS NOT NULL OR destination_port_id IS NOT NULL)
                AND status != 'deleted'
                AND ($2::date IS NULL OR estimated_departure_time::date = $2::date)
                """,
                user_id,
                departure_date,
            )
            return row["count"], None

    async def get_routes_range_with_date_filter(
            self,
            user_id: str,
            offset: int = 0,
            departure_date: Optional[datetime] = None) -> Tuple[Optional[List[SeaRouteDB]], Optional[str]]:

        try:
            async with self.connection_pool.acquire() as conn:
                # Build query dynamically based on filters
                query_parts = [
                    """
SELECT *
FROM routes
WHERE user_id = $1
AND ( departure_port_id IS NOT NULL OR destination_port_id IS NOT NULL)
AND status != 'deleted'
"""]


                params = [user_id]
                param_idx = 2

                if departure_date:
                    query_parts.append(f"AND estimated_departure_time::date = ${param_idx}::date")
                    params.append(departure_date)
                    param_idx += 1

                # Complete query with pagination
                query_parts.append(f""" 
ORDER BY
((departure_port_id IS NOT NULL)::int +
(destination_port_id IS NOT NULL)::int +
(estimated_departure_time IS NOT NULL)::int +
(average_speed_kts IS NOT NULL)::int) DESC,
created_at DESC
                
                LIMIT 4 OFFSET ${param_idx}""")
                params.append(offset)

                query = " ".join(query_parts)
                rows = await conn.fetch(query, *params)

                if not rows:
                    return [], None

                # Convert rows to SeaRouteDB objects
                routes = []
                for row in rows:
                    try:
                        route = SeaRouteDB.from_db_row(row)
                        routes.append(route)
                    except Exception as e:
                        continue

                return routes, None

        except Exception as e:
            return None, f"Route fetch error: {str(e)}"

    async def create_route(
        self, route_data: dict
    ) -> Tuple[Optional[SeaRouteDB], Optional[str]]:
        try:
            async with self.connection_pool.acquire() as conn:

                zone_preferences = route_data.get("zone_preferences", {})
                if isinstance(zone_preferences, dict):
                    zone_preferences = json.dumps(zone_preferences)

                fuels = route_data.get("fuels", [])
                if isinstance(fuels, list):
                    fuels = json.dumps(fuels)

                values = [
                    route_data.get("user_id"),
                    route_data.get("status", "draft"),
                    route_data.get("departure_port_id"),
                    route_data.get("destination_port_id"),
                    route_data.get("estimated_departure_time"),
                    route_data.get("average_speed_kts"),
                    route_data.get("max_deviation_nm"),
                    zone_preferences,
                    fuels,
                    json.dumps( route_data.get("bunkering_steps", [])),
                    json.dumps( route_data.get("data", {})),
                ]

                row = await conn.fetchrow(
                    """
                    INSERT INTO routes (user_id, status, departure_port_id, destination_port_id,  estimated_departure_time, average_speed_kts, max_deviation_nm, zone_preferences, fuels, bunkering_steps, data)
                    VALUES             ($1,      $2,     $3,                $4,                   $5,                       $6,                $7,               $8,                $9,   $10,             $11)
                    RETURNING *
                """,
                    *values,
                )
                return SeaRouteDB.from_db_row(row), None
        except Exception as e:
            return None, f"Route creation error: {str(e)}"

    # async def update_route(
    #     self, route_id: UUID, update_data: dict
    # ) -> Tuple[Optional[SeaRouteDB], Optional[str]]:
    #     try:
    #         async with self.connection_pool.acquire() as conn:
    #             set_clause = ", ".join(
    #                 [f"{k} = ${i + 2}" for i, k in enumerate(update_data.keys())]
    #             )
    #             values = list(update_data.values())
    #             row = await conn.fetchrow(
    #                 f"""
    #                 UPDATE routes SET {set_clause}, updated_at = NOW()
    #                 WHERE id = $1 RETURNING *
    #             """,
    #                 route_id,
    #                 *values,
    #             )
    #             return SeaRouteDB.from_db_row(row), None
    #     except Exception as e:
    #         return None, str(e)

    async def update_route(
            self, route: SeaRouteDB
    ) -> Tuple[Optional[SeaRouteDB], Optional[str]]:
        try:
            # Custom serialization for complex nested objects
            update_data = {
                "user_id": str(route.user_id),
                "status": route.status,
                "departure_port_id": route.departure_port_id,
                "destination_port_id": route.destination_port_id,
                "estimated_departure_time": route.departure_date if route.departure_date else None,
                "average_speed_kts": float(route.average_speed_kts) if route.average_speed_kts else None,
                "max_deviation_nm": float(route.max_deviation_nm) if route.max_deviation_nm else None,
                "zone_preferences": json.dumps(route.zones_preferences.model_dump()) if route.zones_preferences else json.dumps([]),
                "fuels": json.dumps([fuel.model_dump() for fuel in route.fuels]),
                "bunkering_steps": json.dumps([step.model_dump() for step in route.bunkering_steps]),
                "map_image_bytes": route.map_image_bytes,
                "data": json.dumps(route.data.model_dump()),
                "departure_nearby_image": route.departure_nearby_image,
                "departure_suggestion_image": route.departure_suggestion_image,
                "destination_nearby_image": route.destination_nearby_image,
                "destination_suggestion_image": route.destination_suggestion_image,
                "vessel_name": route.vessel_name,
                "imo_number": route.imo_number,
            }

            # Remove None values if your database columns are nullable
            #update_data = {k: v for k, v in update_data.items() if v is not None}
            update_data = {k: v for k, v in update_data.items()}

            async with self.connection_pool.acquire() as conn:
                set_clause = ", ".join(
                    [f"{k} = ${i + 2}" for i, k in enumerate(update_data.keys())]
                )
                values = list(update_data.values())
                row = await conn.fetchrow(
                    f"""
                    UPDATE routes SET {set_clause}, updated_at = NOW()
                    WHERE id = $1 RETURNING *
                """,
                    route.id,
                    *values,
                )
                return SeaRouteDB.from_db_row(row), None
        except Exception as e:
            return None, str(e)

    async def delete_route(self, route_id: UUID) -> Tuple[bool, Optional[str]]:
        """Delete a route by ID"""
        try:
            async with self.connection_pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM routes WHERE id = $1", route_id
                )
                return True, None
        except Exception as e:
            return False, f"Route deletion error: {str(e)}"

    async def mark_route_deleted(self, route_id: UUID) -> Tuple[Optional[SeaRouteDB], Optional[str]]:
        """Mark a route as deleted by ID and return the updated route"""
        try:
            async with self.connection_pool.acquire() as conn:
                # First update the route
                result = await conn.execute(
                    """
                    UPDATE routes 
                    SET status = 'deleted' 
                    WHERE id = $1 AND status != 'deleted'
                    RETURNING *
                    """,
                    route_id
                )

                # If no rows returned, route not found or already deleted
                if not result:
                    return None, "Route not found or already deleted"

                # Fetch the updated route
                row = await conn.fetchrow(
                    "SELECT * FROM routes WHERE id = $1",
                    route_id
                )

                if not row:
                    return None, "Route not found after update"

                route = SeaRouteDB.from_db_row(row)
                return route, None

        except Exception as e:
            return None, f"Route deletion error: {str(e)}"


    async def increment_user_route_count(
        self, user_id: UUID
    ) -> Tuple[bool, Optional[str]]:
        """Increment user's route count"""
        try:
            async with self.connection_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE users SET route_count = route_count + 1, updated_at = NOW() WHERE id = $1",
                    user_id,
                )
                return True, None
        except Exception as e:
            return False, f"Route count increment error: {str(e)}"

    async def create_route_bunkering_port(
        self, bunkering_data: dict
    ) -> Tuple[Optional[Any], Optional[str]]:
        """Create a route_bunkering_ports entry"""
        try:
            async with self.connection_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO route_bunkering_ports 
                    (route_id, port_id, arrival_date, deviation_nm, bunkering_method, agent_fee, bunkering_fee, order_number)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    RETURNING *
                """,
                    bunkering_data["route_id"],
                    bunkering_data["port_id"],
                    bunkering_data["arrival_date"],
                    bunkering_data["deviation_nm"],
                    bunkering_data["bunkering_method"],
                    bunkering_data.get("agent_fee", 0),
                    bunkering_data.get("bunkering_fee", 0),
                    bunkering_data["order_number"],
                )
                return row, None
        except Exception as e:
            return None, f"Bunkering port creation error: {str(e)}"

    async def get_available_fuels(
        self,
    ) -> Tuple[Optional[List[FuelDB]], Optional[str]]:
        """Get all available fuel types"""
        try:
            async with self.connection_pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT id, name, description FROM fuel_types ORDER BY name"""
                )
                fuels = [FuelDB.from_db_row(row) for row in rows]
                return fuels, None

        except Exception as e:
            return [], f"Fuel types fetch error: {str(e)}"

    async def get_available_tariffs(self,) -> Tuple[Optional[List[UserTariffBD]], Optional[str]]:
        """Get all available fuel types"""
        try:
            async with self.connection_pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT * FROM public.user_tariffs ORDER BY name"""
                )
                fuels = [UserTariffBD.from_db_row(row) for row in rows]
                return fuels, None

        except Exception as e:
            return [], f"Fuel types fetch error: {str(e)}"


    async def list_routes(self, session):
        """Handle listing routes for a user"""
        try:
            async with self.connection_pool.acquire() as conn:
                # Query to get routes for the current user
                rows = await conn.fetch(
                    """SELECT id, user_id, status, departure_port_id, destination_port_id, 
                              estimated_departure_time, average_speed_kts, max_deviation_nm, 
                              zone_preferences, created_at, updated_at, fuels
                       FROM routes 
                       WHERE user_id = $1 
                       ORDER BY created_at DESC 
                       LIMIT 20""",
                    session.user_id,
                )

                routes = [SeaRouteDB.from_db_row(row) for row in rows]
                return routes, None

        except Exception as e:
            return None, e

    async def create_fuel_cost(
        self, fuel_price: PortFuelPrice
    ) -> Tuple[Optional[PortFuelPriceDB], Optional[str]]:
        try:
            async with self.connection_pool.acquire() as conn:
                # Convert date to timestamp for database
                #timestamp = datetime.combine(fuel_price.date, datetime.min.time())

                row = await conn.fetchrow(
                    """INSERT INTO public.fuel_cost (port_id, fuel_id, timestamp, value) 
                    VALUES ($1, $2, $3, $4) 
                    RETURNING id, port_id, fuel_id, timestamp, value""",
                    uuid.UUID(fuel_price.port_id),
                    uuid.UUID(fuel_price.fuel_id),
                    fuel_price.timestamp,
                    fuel_price.value,
                )
                return PortFuelPriceDB.from_db_row(row), None
        except Exception as e:
            return None, str(e)

    async def create_mobux_port_fuel_price(self, price: MabuxPortFuelPrice) -> tuple[Optional[MabuxPortFuelPrice], Optional[str]]:
        try:
            async with self.connection_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO mabux_port_fuel_prices (
                        mabux_id,
                        locode,
                        country_name,
                        iso_alpha_code,
                        port_name,
                        fuel_name,
                        fuel_name_short,
                        price_date,
                        value,
                        unit,
                        indexed,
                        fuel_delivery_method_title,
                        fuel_delivery_method_abbr,
                        has_weekly_price
                    )
                    VALUES (
                        $1, $2, $3, $4, $5,
                        $6, $7, $8, $9, $10,
                        $11, $12, $13, $14
                    )
                    RETURNING *
                    """,
                    price.mabux_id,
                    price.locode,
                    price.countryName,
                    price.isoAlphaCode,
                    price.portName,
                    price.fuelName,
                    price.fuelNameShort,
                    price.date,
                    price.value,
                    price.unit,
                    price.indexed,
                    price.fuelDeliveryMethodATitle,
                    price.fuelDeliveryMethodAbbr,
                    price.hasWeeklyPrice,
                )
                return MabuxPortFuelPriceDB.from_dict(row), None

        except Exception as e:
            return None, str(e)

    async def get_port_fuel_price_by_port_locode(self, locode: str, fuel_name: str, date: datetime.date) -> Tuple[Optional[MabuxPortFuelPriceDB], Optional[str]]:
        try:
            async with self.connection_pool.acquire() as conn:
                #timestamp = datetime.combine(date, datetime.min.time())
                row = await conn.fetchrow(
                    """
                    SELECT *
                    FROM public.mabux_port_fuel_prices
                    WHERE 
                    locode = $1
                    AND fuel_name = $2
                    AND price_date = $3 
                    
                    """,
                    locode,
                    fuel_name,
                    date,
                )
                if not row:
                    return None, "No price"
                return MabuxPortFuelPriceDB.from_dict(row), None
        except Exception as e:
            return None, str(e)

    async def get_port_fuel_price_by_port_mabux_id(self, mabux_id: int, fuel_name: str, date: datetime.date)  -> Tuple[Optional[MabuxPortFuelPriceDB], Optional[str]]:
        try:
            async with self.connection_pool.acquire() as conn:
                # timestamp = datetime.combine(date, datetime.min.time())
                row = await conn.fetchrow(
                    """
                    SELECT *
                    FROM public.mabux_port_fuel_prices
                    WHERE 
                    mabux_id = $1
                    AND fuel_name = $2
                    AND price_date = $3                  
                    """,
                    mabux_id,
                    fuel_name,
                    date,
                )
                if not row:
                    return None, "No price"
                return MabuxPortFuelPriceDB.from_dict(row), None
        except Exception as e:
            return None, str(e)


    async def get_sea_port_locode_by_mabux_id(self, mabux_id: int, ) -> tuple[Optional[str], Optional[str]]:
        try:
            async with self.connection_pool.acquire() as conn:
                row = await conn.fetchrow("""SELECT real_locode FROM public.mabux_port_locode_mapping WHERE mabux_id = $1 """, mabux_id)

                if not row:
                    return None, "No data found for given mobux id"

                return row.get("real_locode").strip(), None

        except Exception as e:
            return None, str(e)

    async def add_sea_port_locode_mabux_id(self, r: MabuxPortLocodeMap) -> Tuple[Optional[MabuxPortLocodeMapDB], Optional[str]]:
        try:
            async with self.connection_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO mabux_port_locode_mapping (
                        mabux_id,
                        port_name,
                        country_name,
                        mabux_locode,
                        real_locode
                    )
                    VALUES (
                        $1, $2, $3, $4, $5
                    )
                    RETURNING *
                    """,
                    r.mabux_id,
                    r.port_name,
                    r.country_name,
                    r.mabux_locode,
                    r.real_locode
                )

                return MabuxPortLocodeMapDB.from_dict(row), None

        except Exception as e:
            return None, str(e)


    async def get_alternative_mabux_ids(self, locode: str) -> Tuple[Optional[List[int]], Optional[str]]:
        try:
            async with self.connection_pool.acquire() as conn:
                rows = await conn.fetch("""SELECT mabux_id FROM public.port_mabux_links WHERE LOWER(locode) = LOWER($1)""", locode)
                return [int(row['mabux_id']) for row in rows], None
        except Exception as e:
            return None, str(e)

    async def get_fuel_cost_by_port_and_fuel(
        self, port_id: str, fuel_id: str, date: datetime.date
    ) -> Tuple[Optional[PortFuelPriceDB], Optional[str]]:
        try:
            async with self.connection_pool.acquire() as conn:
                timestamp = datetime.combine(date, datetime.min.time())
                row = await conn.fetchrow(
                    """SELECT id, port_id, fuel_id, timestamp, value 
                    FROM public.fuel_cost 
                    WHERE port_id = $1 AND fuel_id = $2 and timestamp = $3""",
                    uuid.UUID(port_id),
                    uuid.UUID(fuel_id),
                    timestamp,
                )
                if not row:
                    return None, None
                return PortFuelPriceDB.from_db_row(row), None
        except Exception as e:
            return None, str(e)

    # async def get_fuel_const_by_port_and_fuel_name(self, port_id: str, fuel_name: str, date: datetime.date)-> Tuple[Optional[PortFuelPriceDB], Optional[str]]:
    #     try:
    #         async with self.connection_pool.acquire() as conn:
    #             timestamp = datetime.combine(date, datetime.min.time())
    #             row = await conn.fetchrow(
    #                 """SELECT id, port_id, fuel_id, timestamp, value
    #                 FROM public.fuel_cost
    #                 WHERE port_id = $1 AND name = $2 and timestamp = $3""",
    #                 uuid.UUID(port_id),
    #                 fuel_name,
    #                 timestamp,
    #             )
    #             if not row:
    #                 return None, None
    #             return PortFuelPriceDB.from_db_row(row), None
    #     except Exception as e:
    #         return None, str(e)
    #

    async def get_fuel_by_name(
        self, name: str
    ) -> Tuple[Optional[FuelDB], Optional[str]]:
        try:
            async with self.connection_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id, name, description FROM public.fuel_types WHERE name = $1",
                    name.strip(),
                )
                if not row:
                    return None, None
                return FuelDB.from_db_row(row), None
        except Exception as e:
            return None, str(e)

    # def search_ports_similarity(
    #     self, query: str, country_filter: Optional[str] = None, n_results: int = 10
    # ) -> Tuple[Optional[List[SeaPortDB]], Optional[str]]:
    #     """
    #     Search ports using PostgreSQL similarity functions (trigram)
    #     """
    #
    #     #conn = self.simple_pool.getconn()
    #     cursor = self.simple_conn.cursor()
    #     try:
    #
    #         base_query = """
    #                SELECT
    #                    id,
    #                    bubble_id,
    #                    port_name,
    #                    country_name,
    #                    locode,
    #                    search_key,
    #                    latitude,
    #                    longitude,
    #                    mabux_ids,
    #                    port_size,
    #                    mabux_id,
    #                    barge_status,
    #                    truck_status,
    #                    agent_contact_list,
    #                    GREATEST(
    #                        similarity(port_name, %s),
    #                        similarity(country_name, %s),
    #                        similarity(locode, %s),
    #                        similarity(search_key, %s)
    #                    ) as similarity_score
    #                FROM ports_vector_new
    #                WHERE
    #                    port_name %% %s OR
    #                    country_name %% %s OR
    #                    locode %% %s OR
    #                    search_key %% %s
    #            """
    #
    #         params = [query, query, query, query, query, query, query, query]
    #
    #         # Add country filter if provided
    #         if country_filter:
    #             base_query += " AND country_name ILIKE %s"
    #             country_pattern = f"%{country_filter}%"
    #             params.append(country_pattern)
    #
    #         # Add ordering and limit
    #         base_query += " ORDER BY similarity_score DESC LIMIT %s"
    #         params.append(n_results)
    #
    #         cursor.execute(base_query, params)
    #         rows = cursor.fetchall()
    #
    #         results = [SeaPortDB.from_tuple(row) for row in rows]
    #
    #         # if conn:
    #         #     conn.close()
    #
    #         return results, None
    #
    #     except Exception as e:
    #         return None, str(e)
        # finally:
        #     if conn:
        #         conn.close()

    def search_ports_similarity(
            self, query: str, country_filter: Optional[str] = None, n_results: int = 10
    ) -> Tuple[Optional[List[SeaPortDB]], Optional[str]]:
        """
        Search ports using PostgreSQL similarity functions (trigram)
        and sort by similarity and port_size (large > small > tiny > None)
        """
        try:
            # Acquire connection from pool
            conn = self.simple_pool.getconn()
            try:
                with conn.cursor() as cursor:
                    base_query = """
                        SELECT
                            id,
                            bubble_id, 
                            port_name,
                            country_name,
                            locode,
                            search_key,
                            latitude,
                            longitude,
                            mabux_ids,
                            port_size,
                            mabux_id,
                            barge_status,
                            truck_status,
                            agent_contact_list,
                            manual_input,
                            GREATEST(
                                similarity(port_name, %s),
                                similarity(country_name, %s),
                                similarity(locode, %s),
                                similarity(search_key, %s)
                            ) as similarity_score
                        FROM ports_vector_new
                        WHERE 
                            port_name %% %s OR 
                            country_name %% %s OR 
                            locode %% %s OR
                            search_key %% %s
                    """

                    params = [query] * 8  # 4 for GREATEST, 4 for WHERE %% conditions

                    # Add country filter if provided
                    if country_filter:
                        base_query += " AND country_name ILIKE %s"
                        params.append(f"%{country_filter}%")

                    # Add ordering and limit
                    base_query += """
                        ORDER BY similarity_score DESC,
                            CASE port_size
                                WHEN 'large' THEN 1
                                WHEN 'small' THEN 2
                                WHEN 'tiny' THEN 3
                                ELSE 4
                            END ASC
                        LIMIT %s
                    """
                    params.append(n_results)

                    cursor.execute(base_query, params)
                    rows = cursor.fetchall()

                    results = [SeaPortDB.from_tuple(row) for row in rows]
                    return results, None

            finally:
                # Return connection to pool
                self.simple_pool.putconn(conn)

        except Exception as e:

            return None, str(e)


    def search_users_trgm(
            self, search_query: str, limit_count: int = 10
    ) -> Tuple[Optional[List[UserDB]], Optional[str]]:
        """
        Universal user search:
        - Trigram similarity for normal queries (>=3 chars)
        - ILIKE pattern matching for short queries (<3 chars)
        """
        try:
            conn = self.simple_pool.getconn()
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:

                    # Lower threshold for fuzzy matches (optional)
                    cursor.execute("SET pg_trgm.similarity_threshold = 0.1;")

                    if len(search_query) < 3:
                        # Short queries: use ILIKE pattern matching
                        sql = """
                            SELECT
                                id AS user_id,
                                telegram_id,
                                telegram_user_name,
                                email,
                                first_name,
                                last_name,
                                company_name,
                                filled_name,
                                phone_number,
                                1.0 AS similarity_score
                            FROM public.users
                            WHERE
                                telegram_user_name ILIKE %s OR
                                first_name ILIKE %s OR
                                last_name ILIKE %s OR
                                email ILIKE %s OR
                                company_name ILIKE %s OR
                                filled_name ILIKE %s OR
                                phone_number ILIKE %s
                            LIMIT %s;
                        """
                        pattern = f"%{search_query}%"
                        params = [pattern] * 7 + [limit_count]
                    else:
                        # Normal queries: use trigram similarity
                        sql = """
                            SELECT
                                id AS user_id,
                                telegram_id,
                                telegram_user_name,
                                email,
                                first_name,
                                last_name,
                                company_name,
                                filled_name,
                                phone_number,
                                GREATEST(
                                    similarity(telegram_user_name, %s),
                                    similarity(first_name, %s),
                                    similarity(last_name, %s),
                                    similarity(email, %s),
                                    similarity(company_name, %s),
                                    similarity(filled_name, %s),
                                    similarity(phone_number, %s)
                                ) AS similarity_score
                            FROM public.users
                            WHERE 
                                telegram_user_name %% %s OR
                                first_name %% %s OR
                                last_name %% %s OR
                                email %% %s OR
                                company_name %% %s OR
                                filled_name %% %s OR
                                phone_number %% %s
                            ORDER BY similarity_score DESC
                            LIMIT %s;
                        """
                        # 7 similarities + 7 %% checks + limit
                        params = [search_query] * 14 + [limit_count]

                    cursor.execute(sql, params)
                    rows = cursor.fetchall()
                    results = [UserDB.from_db_row(r) for r in rows]
                    return results, None
            finally:
                self.simple_pool.putconn(conn)
        except Exception as e:
            return None, str(e)

    def search_port_with_suggestions(
            self,
            port_name: str,
    ) -> Tuple[Optional[SeaPortDB], Optional[List[SeaPortDB]], Optional[str]]:

        departure_results, err = self.search_ports_similarity(port_name, n_results=50)
        if not err and departure_results and len(departure_results) > 0:

            # Sort results by port_size priority: large > small > tiny > None
            port_size_priority = {"large": 0, "small": 1, "tiny": 2, None: 3}
            departure_results.sort(key=lambda p: port_size_priority.get(p.port_size, 3))

            port = departure_results[0]
            suggestions = departure_results[1:]
            return port, suggestions, None
        else:
            return None, [], str(err)



    # Example: inside your SQL DB service class
    async def search_ports_nearby(
            self,
            latitude: float,
            longitude: float,
            n: int = 10,
            radius_km: float = 100.0,
    ):
        try:
            async with self.connection_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT *,
                           ST_Distance(
                               geom,
                               ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography
                           ) AS distance_m
                    FROM public.ports_vector_new
                    WHERE ST_DWithin(
                        geom,
                        ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography,
                        $3 * 1000
                    )
                    ORDER BY distance_m
                    LIMIT $4
                    """,
                    longitude,
                    latitude,
                    radius_km,
                    n,
                )

            ports = []
            for r in rows:
                p = SeaPortDB.from_db_row(r)
                setattr(p, "_distance_km", r["distance_m"] / 1000.0)
                ports.append(p)

            return ports, None

        except Exception as e:
            return [], str(e)

    async def get_ports_by_list_of_country_codes(self, country_codes):
        if not country_codes:
            return [], None

        normalized_codes = [c.strip().upper() for c in country_codes]

        try:
            async with self.connection_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT *
                    FROM public.ports_vector_new
                    WHERE 
                        LEFT(locode, 2) = ANY($1::text[])
                        AND port_size = 'large'
                        AND (
                            mabux_id IS NOT NULL
                            OR (mabux_ids IS NOT NULL AND cardinality(mabux_ids) > 0)
                        )
                    """,
                    normalized_codes,
                )

            ports = [SeaPortDB.from_db_row(r) for r in rows]
            return ports, None

        except asyncpg.PostgresError as e:
            #logger.exception("Database error while fetching ports by country codes")
            return None, str(e)

        except Exception as e:
            #logger.exception("Unexpected error in get_ports_by_list_of_country_codes")
            return None, str(e)



    async def search_ports_nearby_with_prices(
            self,
            latitude: float,
            longitude: float,
            n: int = 50,
            radius_km: float = 200.0,
    ):
        async with self.connection_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT *,
                       ST_Distance(
                           geom,
                           ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography
                       ) AS distance_m
                FROM public.ports_vector_new
                WHERE 
                ST_DWithin(
                    geom,
                    ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography,
                    $3 * 1000
                )
                AND (
                    mabux_id IS NOT NULL
                    OR (mabux_ids IS NOT NULL AND cardinality(mabux_ids) > 0)
                )
                AND (port_size = 'large' )
                
                ORDER BY distance_m
                LIMIT $4
                """,
                longitude,
                latitude,
                radius_km,
                n,
            )

        ports = []
        for r in rows:
            p = SeaPortDB.from_db_row(r)
            setattr(p, "_distance_km", r["distance_m"] / 1000.0)
            ports.append(p)

        return ports, None

    async def search_ports_within_polygon(self, polygon_wkt: str, n: int = 200):
        try:
            async with self.connection_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT *,
                           ST_Distance(
                               geom::geography,
                               ST_Centroid(ST_GeomFromText($1, 4326))::geography
                           ) AS distance_m
                    FROM public.ports_vector_new
                    WHERE ST_Within(geom, ST_GeomFromText($1, 4326))
                      AND (mabux_id IS NOT NULL OR (mabux_ids IS NOT NULL AND cardinality(mabux_ids) > 0))
                      AND port_size = 'large'
                    ORDER BY distance_m
                    LIMIT $2
                    """,
                    polygon_wkt,
                    n,
                )

            ports = []
            for r in rows:
                p = SeaPortDB.from_db_row(r)
                setattr(p, "_distance_km", r["distance_m"] / 1000.0)
                ports.append(p)
            return ports, None
        except Exception as e:
            return None, str(e)

    async def search_ports_along_route_inland(
            self,
            sea_route_coords: List[Coordinates],  # [(lon, lat), ...]
            route_width_km: float = 20.0,
            inland_km: float = 10.0,
            limit: int = 200,
    ):
        async with self.connection_pool.acquire() as conn:
            flat_coords = []
            for c in sea_route_coords:
                flat_coords.extend([c.longitude, c.latitude])

            query = """
            WITH input_points AS (
                SELECT ST_SetSRID(
                           ST_MakePoint(coords[i], coords[i+1]),
                           4326
                       ) AS geom
                FROM generate_subscripts($1::float8[], 1) g(i),
                     (SELECT $1::float8[] AS coords) s
                WHERE i % 2 = 1
            ),
            route AS (
                SELECT ST_MakeLine(geom) AS geom
                FROM input_points
            ),
            route_buffer AS (
                SELECT ST_Buffer(geom, $2 * 1000) AS geom
                FROM route
            ),
            coastal_land AS (
                SELECT ST_Intersection(l.geom, rb.geom) AS geom
                FROM gis.land_polygons l
                JOIN route_buffer rb ON l.geom && rb.geom
            ),
            inland_area AS (
                SELECT ST_Buffer(geom, $3 * 1000) AS geom
                FROM coastal_land
            ),
            merged_area AS (
                SELECT ST_Union(geom) AS geom
                FROM inland_area
            )
            SELECT p.*,
                   ST_Distance(p.geom::geography, (SELECT ST_Centroid(geom)::geography FROM merged_area)) AS distance_m
            FROM public.ports_vector_new p
            WHERE p.geom && (SELECT geom FROM merged_area)
              AND ST_Within(p.geom::geometry, (SELECT geom FROM merged_area))
              AND (p.mabux_id IS NOT NULL OR (p.mabux_ids IS NOT NULL AND cardinality(p.mabux_ids) > 0))
              AND p.port_size = 'large'
            ORDER BY distance_m
            LIMIT $4;
            """

            rows = await conn.fetch(
                query,
                flat_coords,  # $1
                route_width_km,  # $2
                inland_km,  # $3
                limit  # $4
            )

        ports = []
        for r in rows:
            p = SeaPortDB.from_db_row(r)
            setattr(p, "_distance_km", r["distance_m"] / 1000.0)
            ports.append(p)

        return ports, None

    async def get_fuel_price_for_port_and_date(self, port_id: str, fuel_id: str, target_date: Optional[datetime.date] = None) -> Tuple[Optional[PortFuelPrice], Optional[str]]:
        try:

            if target_date:
                fuel_price, err = await self.get_fuel_cost_by_port_and_fuel(port_id, fuel_id, target_date)
                if fuel_price:
                    return fuel_price, None
                    # return PortFuelPrice(
                    #     port_id=fuel_price.port_id,
                    #     fuel_id=fuel_price.fuel_id,
                    #     date=fuel_price.date,
                    #     value=fuel_price.value
                    # ), None

            async with self.connection_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """SELECT id, port_id, fuel_id, timestamp, value 
                    FROM public.fuel_cost 
                    WHERE port_id = $1 AND fuel_id = $2 
                    ORDER BY timestamp DESC 
                    LIMIT 1""",
                    uuid.UUID(port_id),
                    uuid.UUID(fuel_id),

                )

                if row:
                    db_price = PortFuelPriceDB.from_db_row(row)
                    return db_price, None
                    # return PortFuelPrice(
                    #     port_id=db_price.port_id,
                    #     fuel_id=db_price.fuel_id,
                    #     date=db_price.date,
                    #     value=db_price.value
                    # ), None

                return None, None

        except Exception as e:
            return None, str(e)

    async def get_port_fuel_cost_timeseria(
            self,
            port_id: str,
            fuel_id: str,
            dt_from: Optional[datetime.date] = None,
            dt_to: Optional[datetime.date] = None,
    ) -> Tuple[Optional[List[PortFuelPriceDB]], Optional[str]]:

        try:
            today = datetime.now().date()

            if dt_to is None:
                dt_to = today

            if dt_from is None:
                dt_from = today - timedelta(days=30)

            if dt_from > dt_to:
                return None, f"Bad bounds, {dt_from} > {dt_to}"

            async with self.connection_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, port_id, fuel_id, timestamp, value
                    FROM public.fuel_cost
                    WHERE port_id = $1
                      AND fuel_id = $2
                      AND timestamp::date >= $3
                      AND timestamp::date <= $4
                    ORDER BY timestamp ASC
                    """,
                    uuid.UUID(port_id),
                    uuid.UUID(fuel_id),
                    dt_from,
                    dt_to,
                )

                if not rows:
                    return None, None

                return [PortFuelPriceDB.from_db_row(r) for r in rows], None

        except Exception as e:
            return None, str(e)

    async def get_port_fuel_cost_timeseria2(
            self,
            port_locode: str,
            fuel_name: str,
            dt_from: Optional[datetime.date] = None,
            dt_to: Optional[datetime.date] = None
    ) -> Tuple[Optional[List[MabuxPortFuelPriceDB]], Optional[str]]:

        try:
            today = datetime.now().date()

            if dt_to is None:
                dt_to = today

            if dt_from is None:
                dt_from = today - timedelta(days=30)

            if dt_from > dt_to:
                return None, f"Bad bounds, {dt_from} > {dt_to}"

            async with self.connection_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT DISTINCT ON (price_date)
                       *
                    FROM public.mabux_port_fuel_prices
                    WHERE LOWER(locode) = LOWER($1)
                      AND LOWER(fuel_name) = LOWER($2)
                      AND price_date::date >= $3
                      AND price_date::date <= $4
                    ORDER BY price_date, created_at DESC
                    """,
                    port_locode.strip(),
                    fuel_name.strip(),
                    dt_from,
                    dt_to,
                )

                if not rows:
                    return None, None

                return [MabuxPortFuelPriceDB.from_dict(r) for r in rows], None

        except Exception as e:
            return None, str(e)


    async def create_port_from_bubble(self, port: SeaPortBubble) -> Tuple[Optional[SeaPortDB], Optional[str]]:
        try:
            async with self.connection_pool.acquire() as conn:
                # Insert new port with size info
                insert_query = """
                      INSERT INTO public.ports_vector_new (
                          bubble_id,
                          locode,
                          port_name,
                          country_name,
                          latitude,
                          longitude,
                          mabux_ids,
                          search_key,
                          created_at

                      ) VALUES (
                          $1,
                          $2,
                          $3,
                          $4,
                          $5,
                          $6,
                          $7,
                          $8,
                          CURRENT_TIMESTAMP
                      )
                      RETURNING 
                          id,
                          bubble_id, 
                          port_name,
                          country_name,
                          locode,
                          search_key,
                          latitude,
                          longitude,
                          mabux_ids,
        
                      """

                row = await conn.fetchrow(
                    insert_query,
                    port.bubble_id,
                    port.locode,
                    port.port_name,
                    port.country_name,
                    port.latitude,
                    port.longitude,
                    json.dumps(port.mabux_ids),
                    port.search_key,

                )

            if row:
                return SeaPortDB.from_db_row(row), None
            else:
                return None, "Failed to update or insert port"

        except Exception as e:
            return None, f"Database error: {str(e)}"

    async def upsert_port_size_from_searoute(
            self, searoute_port: SearoutePort
    ) -> Tuple[Optional[SeaPortDB], Optional[str]]:
        """
        Update port size if port exists, otherwise insert new port with size info.
        """
        try:
            async with self.connection_pool.acquire() as conn:
                # First, check if port exists
                check_query = """
                SELECT id FROM public.ports_vector_new 
                WHERE LOWER(locode) = $1
                """

                locode_lower = searoute_port.locode.lower().strip()
                existing_row = await conn.fetchrow(check_query, locode_lower)

                if existing_row:
                    # Update existing port with size
                    update_query = """
                    UPDATE public.ports_vector_new 
                    SET port_size = $1
                    WHERE LOWER(locode) = $2
                    RETURNING 
                        id,
                        bubble_id, 
                        port_name,
                        country_name,
                        locode,
                        search_key,
                        latitude,
                        longitude,
                        mabux_ids,
                        port_size
                    """

                    row = await conn.fetchrow(
                        update_query,
                        searoute_port.size,
                        locode_lower
                    )
                else:
                    # Insert new port with size info
                    insert_query = """
                    INSERT INTO public.ports_vector_new (
                        locode,
                        port_name,
                        country_name,
                        latitude,
                        longitude,
                        port_size,
                        search_key,
                        created_at
       
                    ) VALUES (
                        $1::text, $2::text, $3::text, $4, $5, $6::text,
                        LOWER($1 || ' ' || COALESCE($2, ''))::text,
                        CURRENT_TIMESTAMP
                    )
                    RETURNING 
                        id,
                        bubble_id, 
                        port_name,
                        country_name,
                        locode,
                        search_key,
                        latitude,
                        longitude,
                        mabux_ids,
                        port_size
                    """

                    row = await conn.fetchrow(
                        insert_query,
                        searoute_port.locode,
                        searoute_port.name,
                        searoute_port.countryName,
                        searoute_port.latitude,
                        searoute_port.longitude,
                        searoute_port.size
                    )

                if row:
                    return SeaPortDB.from_db_row(row), None
                else:
                    return None, "Failed to update or insert port"

        except Exception as e:
            return None, f"Database error: {str(e)}"

    async def bulk_upsert_ports(
            self,
            ports: List["SearoutePort"]
    ) -> Tuple[Optional[dict[str, "SeaPortDB"]], Optional[str]]:

        if not ports:
            return {}, None

        # 1. Build the dynamic VALUES part
        values_sql = []
        values_args = []
        for i, p in enumerate(ports):
            # $1, $2, ... placeholders
            start_index = i * 6 + 1
            values_sql.append(
                f"(${start_index}, ${start_index + 1}, ${start_index + 2}, ${start_index + 3}::double precision, ${start_index + 4}::double precision, ${start_index + 5})"
            )
            values_args.extend([
                p.locode,
                p.name,
                p.countryName,
                p.latitude,
                p.longitude,
                p.size
            ])

        values_clause = ",\n".join(values_sql)

        # 2. Full SQL with CTEs
        SQL = f"""
           WITH incoming (locode, port_name, country_name, latitude, longitude, port_size) AS (
    VALUES
    {values_clause}
),
updated AS (
    UPDATE public.ports_vector_new p
    SET
        port_name   = incoming.port_name,
        country_name = incoming.country_name,
        latitude    = incoming.latitude,
        longitude   = incoming.longitude,
        port_size   = incoming.port_size
    FROM incoming
    WHERE p.locode = incoming.locode
    RETURNING p.*
),
inserted AS (
    INSERT INTO public.ports_vector_new (
        locode,
        port_name,
        country_name,
        latitude,
        longitude,
        port_size,
        search_key,
        created_at
    )
    SELECT
        incoming.locode,
        incoming.port_name,
        incoming.country_name,
        incoming.latitude,
        incoming.longitude,
        incoming.port_size,
        LOWER(incoming.locode || ' ' || COALESCE(incoming.port_name, '')),
        CURRENT_TIMESTAMP
    FROM incoming
    WHERE NOT EXISTS (
        SELECT 1
        FROM public.ports_vector_new p
        WHERE p.locode = incoming.locode
    )
    RETURNING *
)
SELECT * FROM updated
UNION ALL
SELECT * FROM inserted;

           """

        try:
            async with self.connection_pool.acquire() as conn:
                rows = await conn.fetch(SQL, *values_args)
                return {
                    row["locode"]: SeaPortDB.from_db_row(row)
                    for row in rows
                }, None

        except Exception as e:
            return None, f"Database error: {str(e)}"

    async def fetch_ports_missing_size(
            self,
            limit: int = 100,
            offset: int = 0
    ) -> tuple[list[SeaPortDB], str | None]:
        SQL = """
            SELECT *
            FROM public.ports_vector_new
            WHERE port_size IS NULL
            ORDER BY id
            LIMIT $1 OFFSET $2;
        """
        try:
            async with self.connection_pool.acquire() as conn:
                rows = await conn.fetch(SQL, limit, offset)
                ports = [SeaPortDB.from_db_row(row) for row in rows]
                return ports, None
        except Exception as e:
            return [], f"Database error: {str(e)}"


    async def upsert_mabux_id_barge_truc(self, port_id: str, mabux_id: int, barge_status: Optional[bool] = None, truck_status: Optional[bool] = None) -> Tuple[Optional[SeaPortDB], Optional[str]]:
        try:
            async with self.connection_pool.acquire() as conn:
                update_query = """
                    UPDATE public.ports_vector_new 
                    SET mabux_id = $2, barge_status = $3, truck_status = $4
                    WHERE id = $1
                    RETURNING *
                    """

                row = await conn.fetchrow(
                    update_query,
                    port_id,
                    mabux_id,
                    barge_status,
                    truck_status
                )
                if row:
                    return SeaPortDB.from_db_row(row), None
                else:
                    return None, "Failed to update or insert port"

        except Exception as e:
            return None, f"Database error: {str(e)}"

    async def upsert_mabux_fields(
            self,
            port_id: str,
            fields: Dict[str, Any]
    ) -> Tuple[Optional[SeaPortDB], Optional[str]]:

        try:
            if not fields:
                return None, "No fields to update"

            # build SET clause
            set_clauses = []
            values = [port_id]
            idx = 2

            for col, val in fields.items():
                set_clauses.append(f"{col} = ${idx}")
                values.append(val)
                idx += 1

            query = f"""
                UPDATE public.ports_vector_new
                SET {", ".join(set_clauses)}
                WHERE id = $1
                RETURNING *
            """

            async with self.connection_pool.acquire() as conn:
                row = await conn.fetchrow(query, *values)

            if row:
                return SeaPortDB.from_db_row(row), None

            return None, "Port not found"

        except Exception as e:
            return None, f"Database error: {e}"

    async def update_port(self, locode: str, fields: dict) -> Tuple[Optional[SeaPortDB], Optional[str]]:

        try:
            if not fields:
                return None, "No fields to update"

            # build SET clause
            set_clauses = []
            values = [locode]
            idx = 2

            for col, val in fields.items():
                set_clauses.append(f"{col} = ${idx}")
                values.append(val)
                idx += 1

            query = f"""
                UPDATE public.ports_vector_new
                SET {", ".join(set_clauses)}
                WHERE locode = $1
                RETURNING *
            """

            async with self.connection_pool.acquire() as conn:
                row = await conn.fetchrow(query, *values)

            if row:
                return SeaPortDB.from_db_row(row), None

            return None, "Port not found"

        except Exception as e:
            return None, f"Database error: {e}"



    async def update_user(self, user_id: str, update_data: dict) -> Tuple[Optional[UserDB], Optional[str]]:
        try:
            async with self.connection_pool.acquire() as conn:
                if update_data:
                    set_clause = ", ".join(
                        [f"{k} = ${i + 2}" for i, k in enumerate(update_data.keys())]
                    )
                    values = list(update_data.values())
                    sql = f"""
                        UPDATE users SET {set_clause}, updated_at = NOW()
                        WHERE id = $1 RETURNING *
                    """
                    row = await conn.fetchrow(sql, user_id, *values)
                else:
                    # only update updated_at
                    row = await conn.fetchrow(
                        """
                        UPDATE users SET updated_at = NOW()
                        WHERE id = $1 RETURNING *
                        """,
                        user_id,
                    )
                return UserDB.from_db_row(row), None
        except Exception as e:
            return None, str(e)

