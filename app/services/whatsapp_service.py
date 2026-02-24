import os
import sys
import io
import re
import math
import asyncio
import traceback
from typing import Optional, List

import httpx
from PIL import Image
from fastapi import FastAPI, Request, HTTPException
from telegram import InlineKeyboardMarkup

from app.data.dto.main.ErrorLog import ErrorLogFactory
from app.data.dto.messenger.ResponsePayload import ResponsePayloadCollection
from app.domain.message import IncomingMessage
from app.services.core_service import CoreService


import logging

from app.services.db_service import DbService

logger = logging.getLogger(__name__)

BOLD_PATTERN = re.compile(r"<b>\s*(.*?)\s*</b>", re.DOTALL)
ALLOWED_PATTERN = re.compile(r"[^A-Za-z0-9 \n\.\,\-\/\+\@\_]")

class WhatsApp360DialogService:

    def __init__(self, core_service: CoreService, api_key: str, v_token: str,  sql_db: DbService):
        self.core_service = core_service
        self.verify_token = v_token #os.getenv("WHATSAPP_VERIFY_TOKEN")
        self.api_key = api_key #os.getenv("WHATSAPP_API_KEY")
        self.sql_db = sql_db

        self.app = FastAPI()
        self._register_routes()

    def telegram_to_whatsapp_buttons(self, keyboard: InlineKeyboardMarkup) -> list[dict]:
        """
        Converts Telegram InlineKeyboardMarkup to WhatsApp 'reply' buttons.
        Only the first 3 buttons are supported (WhatsApp limit).
        """
        wa_buttons = []

        # Flatten rows into single list (Telegram allows multiple rows)
        flat_buttons = [btn for row in keyboard.inline_keyboard for btn in row]

        for btn in flat_buttons[:3]:  # WhatsApp max 3 buttons
            wa_buttons.append({
                "type": "reply",
                "reply": {
                    "id": btn.callback_data or btn.text,  # Use callback_data if exists
                    "title": btn.text[:20]  # WhatsApp max title length 20
                }
            })

        return wa_buttons


    async def send_response(self, phone: str, responses: ResponsePayloadCollection):
        """
        Production-grade WhatsApp sender with:
        - Image grid batching
        - Deterministic ordering
        - Proper caption handling
        - Button separation logic
        """

        # 🔹 Normalize bold once
        for response in responses.responses:
            if response.has_text() and response.text:
                response.text = BOLD_PATTERN.sub(r"*\1*", response.text).strip()

        for response in responses.responses:


            await asyncio.sleep(0.2)

            # ========================
            # 1️⃣ ERROR
            # ========================
            if response.err:
                await self._send_text(phone, f"❌ {response.err}")
                continue

            # ========================
            # 2️⃣ IMAGES (HIGHEST PRIORITY)
            # ========================
            if response.has_images():
                await self._handle_images_response(phone, response)
                continue

            # ========================
            # 3️⃣ FILES
            # ========================
            if response.has_files():
                await self._handle_files_response(phone, response)
                continue

            # ========================
            # 4️⃣ TEXT + BUTTONS
            # ========================
            if response.has_buttons():
                await self._handle_buttons_response(phone, response)
                continue

            # ========================
            # 5️⃣ ONLY TEXT
            # ========================
            if response.has_text():
                await self._send_text(phone, response.text)
                continue

            # ========================
            # 6️⃣ FALLBACK
            # ========================
            await self._send_text(phone, "No response generated.")

    # ============================================================
    # 🖼 IMAGE HANDLER
    # ============================================================

    async def _handle_images_response(self, phone: str, response):

        images = response.images
        text = response.text
        has_buttons = response.has_buttons()

        # 1️⃣ Split into batches of 6
        N = 4
        batches = [images[i:i + N] for i in range(0, len(images), N)]

        for batch_index, batch in enumerate(batches):

            # Merge into grid if more than 1 image
            if len(batch) > 1:
                merged_bytes = await self._merge_images_grid(batch)
                media_id = await self._upload_media(merged_bytes, "image/jpeg")

                payload = {
                    "messaging_product": "whatsapp",
                    "to": phone,
                    "type": "image",
                    "image": {
                        "id": media_id
                    }
                }

            else:
                image = batch[0]
                media_id_or_link = image.url

                if not media_id_or_link and image.content:
                    media_id_or_link = await self._upload_media(
                        image.content,
                        "image/jpeg"
                    )

                payload = {
                    "messaging_product": "whatsapp",
                    "to": phone,
                    "type": "image",
                    "image": {}
                }

                if image.content:
                    payload["image"]["id"] = media_id_or_link
                else:
                    payload["image"]["link"] = media_id_or_link

            # Caption only on FIRST batch
            if batch_index == 0 and text:
                payload["image"]["caption"] = text

            await self._post(payload)

        # 2️⃣ Buttons must be separate message (after images)
        if has_buttons:

            # # If exactly one image → use STANDARD caption
            # if len(images) == 1:
            #     await self._send_buttons_message(
            #         phone,
            #         response,
            #         override_text="Choose an option:"
            #     )
            # else:
                await self._send_buttons_message(phone, response, "Choose an option:")

    # ============================================================
    # 🧠 GRID MERGE (3x2)
    # ============================================================

    async def _merge_images_grid(self, images: List):

        pil_images = []

        for img in images:
            if img.content:
                pil = Image.open(io.BytesIO(img.content)).convert("RGB")
            else:
                # If only URL available, you must fetch externally
                raise ValueError("Grid requires raw image bytes.")
            pil_images.append(pil)

        cols = 2
        rows = math.ceil(len(pil_images) / cols)

        widths = [img.width for img in pil_images]
        heights = [img.height for img in pil_images]

        max_w = max(widths)
        max_h = max(heights)

        grid = Image.new(
            "RGB",
            (cols * max_w, rows * max_h),
            color=(255, 255, 255)
        )

        for idx, img in enumerate(pil_images):
            row = idx // cols
            col = idx % cols
            grid.paste(img.resize((max_w, max_h)), (col * max_w, row * max_h))

        output = io.BytesIO()
        grid.save(output, format="PNG", quality=100)
        output.seek(0)

        return output.read()

    # ============================================================
    # 📄 FILE HANDLER
    # ============================================================

    async def _handle_files_response(self, phone: str, response):

        for idx, file in enumerate(response.files):

            media_id_or_link = file.url

            if not media_id_or_link and file.content:
                media_id_or_link = await self._upload_media(
                    file.content,
                    "application/pdf"
                )

            payload = {
                "messaging_product": "whatsapp",
                "to": phone,
                "type": "document",
                "document": {
                    "filename": file.filename
                }
            }

            if file.content:
                payload["document"]["id"] = media_id_or_link
            else:
                payload["document"]["link"] = media_id_or_link

            if idx == 0 and response.text:
                payload["document"]["caption"] = response.text

            await self._post(payload)

    # ============================================================
    # 🔘 BUTTON HANDLER
    # ============================================================

    async def _handle_buttons_response(self, phone: str, response):
        await self._send_buttons_message(phone, response)

    async def _send_role_list_message(self, phone: str, response):

        payload = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {
                    "text": response.text or "Please select your role:"
                },
                "action": {
                    "button": "View Options",
                    "sections": [
                        {
                            "title": "Available Roles",
                            "rows": [
                                {
                                    "id": "1",
                                    "title": "Ship owner",
                                    "description": "Owns vessels"
                                },
                                {
                                    "id": "2",
                                    "title": "Ship operator",
                                    "description": "Operates vessels"
                                },
                                {
                                    "id": "3",
                                    "title": "Fleet / Voyage manager",
                                    "description": "Manages fleet operations"
                                },
                                {
                                    "id": "4",
                                    "title": "Bunker trader / Supplier",
                                    "description": "Fuel trading & supply"
                                },
                                {
                                    "id": "5",
                                    "title": "Charterer",
                                    "description": "Charters vessels"
                                },
                                {
                                    "id": "6",
                                    "title": "Technical / Other",
                                    "description": "Technical or other role"
                                }
                            ]
                        }
                    ]
                }
            }
        }

        await self._post(payload)

    async def _send_buttons_message(self, phone: str, response, override_text: str = None):

        if not response.keyboard:
            return

        # Flatten ALL telegram buttons first (no slicing)
        flat_buttons = [
            btn
            for row in response.keyboard.inline_keyboard
            for btn in row
        ]

        button_ids = {
            btn.callback_data or btn.text
            for btn in flat_buttons
        }

        # ✅ Special case: role selection (6 fixed options)
        if button_ids == {"1", "2", "3", "4", "5", "6"}:
            await self._send_role_list_message(phone, response)
            return

        # ✅ Default behavior (normal WhatsApp buttons)
        buttons = self.telegram_to_whatsapp_buttons(response.keyboard)

        payload = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {
                    "text": override_text or response.text or "Choose an option:"
                },
                "action": {
                    "buttons": buttons
                }
            }
        }

        await self._post(payload)

    async def _send_text(self, phone: str, text: str):

        payload = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "text",
            "text": {
                "body": text
            }
        }

        await self._post(payload)

    async def _upload_media(self, content: bytes, mime_type: str):

        url = "https://waba-v2.360dialog.io/media"

        headers = {
            "D360-API-KEY": self.api_key
        }

        data = {
            "messaging_product": "whatsapp"
        }

        files = {
            "file": ("file", content, mime_type)
        }

        async with httpx.AsyncClient() as client:
            r = await client.post(
                url,
                headers=headers,
                data=data,
                files=files
            )

            r.raise_for_status()
            response_data = r.json()

            return response_data["id"]

    async def _post(self, payload: dict):

        url = "https://waba-v2.360dialog.io/messages"

        headers = {
            "D360-API-KEY": self.api_key,
            "Content-Type": "application/json"
        }

        # Ensure required field exists
        payload["messaging_product"] = "whatsapp"

        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    url,
                    json=payload,
                    headers=headers
                )

                r.raise_for_status()
                return r.json()

        except httpx.HTTPStatusError as e:
            print("WhatsApp API error:", e.response.text)
            raise

        except Exception as e:
            print("Request failed:", str(e))
            raise

    def sanitize_message(self, msg: str) -> str:
        # 1. Remove disallowed characters
        cleaned = ALLOWED_PATTERN.sub("", msg)

        # 2. Trim to max length (optional)
        return cleaned[:300].strip()

    def extract_whatsapp_event(self, payload: dict) -> Optional[dict]:
        if not payload:
            return None

        if payload.get("object") != "whatsapp_business_account":
            return None

        entry = payload.get("entry") or []
        if not entry:
            return None

        changes = entry[0].get("changes") or []
        if not changes:
            return None

        value = changes[0].get("value") or {}

        messages = value.get("messages") or []
        if not messages:
            return None

        message = messages[0]
        contacts = value.get("contacts") or []

        text = None

        if message.get("type") == "text":
            text = message.get("text", {}).get("body")

        elif message.get("type") == "interactive":
            interactive = message.get("interactive", {})
            if interactive.get("type") == "button_reply":
                text = interactive.get("button_reply", {}).get("title")
                text = self.sanitize_message(text)
                #logger.info(text)

            elif interactive.get("type") == "list_reply":
                text = interactive.get("list_reply", {}).get("title")
                text = self.sanitize_message(text)


        logger.info(text)


        return {
            "wa_id": message.get("from"),
            "chat_id": message.get("from"),
            "name": contacts[0]["profile"]["name"] if contacts else None,
            "message_type": message.get("type"),
            "text": text,
            "raw": message
        }

    async def send_progress_whatsapp(self, phone: str):
        try:
            messages = [
                "👀 Give me a second, I’m on it",
                "Still working on it — checking details",
                "Almost there. This may take a bit longer"
            ]

            for msg in messages:
                await asyncio.sleep(15)
                await self._send_text(phone, msg)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Progress message failed: {e}")

    async def process_message(self, event, body):

        progress_task = asyncio.create_task(
            self.send_progress_whatsapp(event["chat_id"])
        )

        try:
            msg = IncomingMessage(
                source="whatsapp",
                user_id=event["wa_id"],
                chat_id=event["chat_id"],
                text=event["text"],
                raw=body,
                meta={
                    "whatsapp_name": event["name"],
                    "message_type": event["message_type"]
                }
            )

            responses = await self.core_service.handle(msg)
            await self.send_response(msg.user_id, responses)

        except Exception as ex:
            error = ErrorLogFactory.from_exception(ex=ex, position="whatsapp_handler")
            await self.sql_db.log_error(error)
            await self._send_text(event["wa_id"], "The error just happened. Admins are already noticed, dont worry.")
        finally:
                progress_task.cancel()


    def _register_routes(self):

        @self.app.get("/webhook")
        async def verify(mode: str, token: str, challenge: str):
            if mode == "subscribe" and token == self.verify_token:
                return int(challenge)
            raise HTTPException(status_code=403)

        @self.app.post("/webhook")
        async def receive_message(request: Request):

            body = await request.json()

            event = None
            try:
                event = self.extract_whatsapp_event(body)

            except Exception:
                return {"status": "error"}

            if not event:
                return {"status": "ignored"}

            # RETURN FAST
            asyncio.create_task(self.process_message(event, body))

            return {"status": "ok"}



            t = """ 
{
    "object": "whatsapp_business_account",
    "entry": [
        {
            "id": "901137005734105",
            "changes": [
                {
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "display_phone_number": "971585647500",
                            "phone_number_id": "970231476172491"
                        },
                        "contacts": [
                            {
                                "profile": {
                                    "name": "Semyon"
                                },
                                "wa_id": "79275212987"
                            }
                        ],
                        "messages": [
                            {
                                "from": "79275212987",
                                "id": "wamid.HBgLNzkyNzUyMTI5ODcVAgASGCBBQzU1MzQwMTkzQTBGRkNDNkY5MkNFMEYyQ0Q0NEVFQQA=",
                                "timestamp": "1770726503",
                                "text": {   
                                    "body": "Test"
                                },
                                "type": "text"
                            }
                        ]
                    },
                    "field": "messages"
                }
            ]
        }
    ]
}   

button
{
    "object": "whatsapp_business_account",
    "entry": [
        {
            "id": "901137005734105",
            "changes": [
                {
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "display_phone_number": "971585647500",
                            "phone_number_id": "970231476172491"
                        },
                        "contacts": [
                            {
                                "profile": {
                                    "name": "Semyon"
                                },
                                "wa_id": "79275212987"
                            }
                        ],
                        "messages": [
                            {
                                "context": {
                                    "from": "971585647500",
                                    "id": "wamid.HBgLNzkyNzUyMTI5ODcVAgARGBJDRTNDNTYxNkVEQUMxRjI1OTYA"
                                },
                                "from": "79275212987",
                                "id": "wamid.HBgLNzkyNzUyMTI5ODcVAgASGCBBQzFBMkFCMENDRENDNDNEMDhBODJDREUxNkU4RUVDOAA=",
                                "timestamp": "1770759091",
                                "type": "interactive",
                                "interactive": {
                                    "type": "button_reply",
                                    "button_reply": {
                                        "id": "3",
                                        "title": "📈 Port prices"
                                    }
                                }
                            }
                        ]
                    },
                    "field": "messages"
                }
            ]
        }
    ]
}  


{
  "object": "whatsapp_business_account",
  "entry": [
    {
      "id": "901137005734105",
      "changes": [
        {
          "value": {
            "messaging_product": "whatsapp",
            "metadata": {
              "display_phone_number": "971585647500",
              "phone_number_id": "970231476172491"
            },
            "contacts": [
              {
                "profile": {
                  "name": "Semyon"
                },
                "wa_id": "79275212987"
              }
            ],
            "messages": [
              {
                "context": {
                  "from": "971585647500",
                  "id": "wamid.HBgLNzkyNzUyMTI5ODcVAgARGBJEMDY1OTQ5MkNCNzNFNUUwREUA"
                },
                "from": "79275212987",
                "id": "wamid.HBgLNzkyNzUyMTI5ODcVAgASGBYzRUIwRTI5OTczQzJFMDFFMzdBQTc1AA==",
                "timestamp": "1770896195",
                "type": "interactive",
                "interactive": {
                  "type": "button_reply",
                  "button_reply": {
                    "id": "2",
                    "title": "🗓️ My routes"
                  }
                }
              }
            ]
          },
          "field": "messages"
        }
      ]
    }
  ]
}










"""


