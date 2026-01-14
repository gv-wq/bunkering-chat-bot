import asyncio
import traceback
import sys
from typing import List
import re
import httpx
from telegram import Update, InputMediaPhoto, InputFile
from io import BytesIO

from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.data import emogye

# Create a custom HTTP client with better settings
timeout = httpx.Timeout(timeout=30.0, connect=10.0)
http_client = httpx.AsyncClient(timeout=timeout)

from app.data.dto.messenger.ResponsePayload import ResponsePayloadCollection, ResponsePayload
from app.services.core_service import CoreService


class TelegramService:
    def __init__(self, core_service: CoreService, token: str):
        self.core_service = core_service
        self.application = None
        self.application = (
            Application.builder()
            .token(token)
            # .request(self.request)
            .read_timeout(60)
            .write_timeout(60)
            .connect_timeout(60)
            .pool_timeout(60)
            # .proxy("socks5://127.0.0.1:1081")
            .build()
        )

        # Add handlers
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("menu", self.menu))
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message)
        )

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.core_service.handle_start(update, context)

    async def menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        response: ResponsePayloadCollection = await self.core_service.new_route_handler.template_service.main_menu_template()
        await update.message.reply_text(response[0].text, parse_mode="Markdown")

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            response_collection: ResponsePayloadCollection = await self.core_service.handle_message(update, context)

            for response_payload in response_collection.responses:
                #print(response_payload.text)
               # continue

                # Handle error
                if response_payload.err:
                    await update.message.reply_text(f"❌ Error: {response_payload.err}")
                    continue

                # Handle multiple images → send album
                if response_payload.has_images():
                    media_group = []

                    for idx, img_bytes in enumerate(response_payload.images):
                        media_group.append(
                            InputMediaPhoto(
                                media=img_bytes,
                                caption=response_payload.text if idx == 0 else "",
                                parse_mode="HTML"
                            )
                        )

                    await update.message.reply_media_group(media=media_group)
                    continue

                # Handle files (PDF, etc.)
                if response_payload.has_files():
                    for idx, file_obj in enumerate(response_payload.files):
                        file_stream = BytesIO(file_obj.content)
                        file_stream.name = f"{file_obj.name}.pdf"  # Telegram needs filename

                        await update.message.reply_document(
                            document=InputFile(file_stream),
                            caption=response_payload.text if idx == 0 else None,
                            parse_mode="HTML"
                        )
                    continue


                # Handle text-only message
                if response_payload.has_text():
                    await update.message.reply_text(
                        response_payload.text,
                        parse_mode="HTML"
                    )
                    continue


                # Nothing at all
                await update.message.reply_text("No response generated", parse_mode="MarkdownV2")

        except Exception as e:
            exc_type, exc_value, exc_tb = sys.exc_info()
            tb = traceback.extract_tb(exc_tb)[-1]  # last frame where error occurred
            filename = tb.filename
            line_no = tb.lineno
            await update.message.reply_text(
                f"❌ Error in <b>{filename}</b> at line <b>{line_no}</b>: {e}",
                parse_mode="HTML"
            )

    async def run_polling_blocking(self):
        """Run polling in blocking mode (for normal execution)"""
        print("🔧 Starting bot in blocking mode...")
        if self.application:
            await self.application.initialize()
            asyncio.run( self.application.run_polling())
            asyncio.run(self.application.shutdown())
        else:
            raise Exception("Nothing to start!")

    async def run_polling(self):
        """Run polling in async mode (for PyCharm debugger)"""
        print("🔧 Starting bot in async polling mode...")
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()

        print("✅ Bot is now polling for messages...")

        # Keep the bot running
        while True:
            await asyncio.sleep(1)