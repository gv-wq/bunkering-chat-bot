import asyncio
import traceback
import sys
from typing import List
import re
import httpx
from telegram import Update, InputMediaPhoto, InputFile
from io import BytesIO
from typing import Dict, Optional
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    CallbackQueryHandler
)

from app.data import emogye
from app.domain.message import IncomingMessage

# Create a custom HTTP client with better settings
timeout = httpx.Timeout(timeout=30.0, connect=10.0)
http_client = httpx.AsyncClient(timeout=timeout)

from app.data.dto.messenger.ResponsePayload import ResponsePayloadCollection, ResponsePayload
from app.services.core_service import CoreService
from app.services.ai_service import AiService

class TelegramService:
    def __init__(self, core_service: CoreService, ai_service: AiService, token: str):
        self.core_service = core_service
        self.ai_service = ai_service
        self.application = None
        self.application = (
            Application.builder()
            .token(token)
            .read_timeout(60)
            .write_timeout(60)
            .connect_timeout(60)
            .pool_timeout(60)
            .build()
        )

        # Add handlers
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("menu", self.menu))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        self.application.add_handler(CallbackQueryHandler(self.handle_button))
        self.application.add_handler(MessageHandler(filters.VOICE, self.handle_voice))

    def get_bot(self):
        return self.application

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):

        await update.message.reply_text(
            f'{emogye.HI} Hi!\n'
            'I help ship owners, operators & managers\n'
            'plan a vessel route, view bunker prices\n'
            'along the route, and estimate fuel costs — in under 2 minutes.\n\n'
            f'Powered by AI-assisted route & bunker analysis.\n'
            f'No spam.',
            parse_mode="HTML"
        )

        msg = self.from_update(update)
        responses = await self.core_service.handle(msg, start_status=True)
        await self.send(responses, update)



    async def menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        response: ResponsePayloadCollection = await self.core_service.new_route_handler.template_service.main_menu_template()
        await update.message.reply_text(response[0].text, parse_mode="Markdown")

    @staticmethod
    def from_update(update: Update, override_text: Optional[str] = None ) -> Optional[IncomingMessage]:

        message = update.message or (update.callback_query.message if update.callback_query else None)

        if message is None:
            return None

        text = override_text or (update.message.text if update.message else update.callback_query.data)

        return IncomingMessage(
            source="telegram",
            user_id=str(update.effective_user.id),
            chat_id=str(update.effective_chat.id),
            text=text,
            raw=update,
            meta={
                "username": update.effective_user.username,
                "first_name": update.effective_user.first_name,
                "last_name": update.effective_user.last_name,
            },
        )

    async def handle_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        await self.handle_message(update=update, context=context, override_text=query.data)

    async def handle_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        voice = update.message.voice

        file = await context.bot.get_file(voice.file_id)
        voice_bytes = BytesIO()
        await file.download_to_memory(voice_bytes)
        voice_bytes.seek(0)

        text = await self.ai_service.transcribe_audio(voice_bytes)

        if not text:
            await update.message.reply_text("❌ Could not recognize speech")
            return

        await update.message.reply_text(f"🎤 I heard:\n\n <b> {text} </b> ", parse_mode="HTML")

        await self.handle_message(update=update, context=context, override_text=text)

    async def handle_message(self, update, context, override_text : str = None):
        msg = self.from_update(update, override_text)
        responses = await self.core_service.handle(msg)
        await self.send(responses, update)

    async def send(self, responses: ResponsePayloadCollection, update: Update):
        message = update.message or (update.callback_query.message if update.callback_query else None)

        if message is None:
            return

        try:
            for response_payload in responses.responses:

                # Error
                if response_payload.err:
                    await message.reply_text(
                        f"❌ Error: {response_payload.err}"
                    )
                    continue

                # Images
                if response_payload.has_images():
                    media_group = [
                        InputMediaPhoto(
                            media=img.content,
                            caption=response_payload.text if i == 0 else "",
                            parse_mode="HTML"
                        )
                        for i, img in enumerate(response_payload.images)
                    ]

                    await message.reply_media_group(media_group)

                    if response_payload.keyboard:
                        await message.reply_text(
                            "Navigation Commands:",
                            reply_markup=response_payload.keyboard,
                            parse_mode="HTML"
                        )

                    continue

                # Files
                if response_payload.has_files():
                    for i, file_obj in enumerate(response_payload.files):
                        file_stream = BytesIO(file_obj.content)
                        file_stream.name = f"{file_obj.name}.pdf"

                        await message.reply_document(
                            document=InputFile(file_stream),
                            caption=response_payload.text if i == 0 else None,
                            reply_markup=response_payload.keyboard,
                            parse_mode="HTML"
                        )
                    continue

                # Text
                if response_payload.has_text():
                    await message.reply_text(
                        response_payload.text,
                        reply_markup=response_payload.keyboard,
                        parse_mode="HTML"
                    )
                    continue

                await message.reply_text("No response generated")

        except Exception as e:
            exc_type, exc_value, exc_tb = sys.exc_info()
            tb = traceback.extract_tb(exc_tb)[-1]
            filename = tb.filename
            line_no = tb.lineno

            await message.reply_text(
                f"❌ Error in  <b> {filename} </b>  at line  <b> {line_no} </b> : {e}",
                parse_mode="HTML"
            )

    async def run(self):
        """Run polling in async mode (for PyCharm debugger)"""
        print("🔧 Starting bot in async polling mode...")
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()

        print("✅ Bot is now polling for messages...")

        while True:
            await asyncio.sleep(1)