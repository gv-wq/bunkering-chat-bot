import re
from typing import List, Optional, Any
from pydantic import BaseModel, Field, PrivateAttr
from telegram import InlineKeyboardMarkup

class MediaImage(BaseModel):
    content: Optional[bytes] = Field(default=None, description="Raw image bytes")
    url: Optional[str] = Field(default=None, description="Public URL of image")
    filename: Optional[str] = Field(default=None, description="Image filename")


class MediaFile(BaseModel):
    content: Optional[bytes] = Field(default=None, description="Raw file bytes")
    url: Optional[str] = Field(default=None, description="Public URL of file")
    filename: Optional[str] = Field(description="File name with extension")


class ResponsePayload(BaseModel):
    text: Optional[str] = None
    images: List[MediaImage] = []
    files: List[MediaFile] = []
    err: Optional[str] = None
    keyboard: Optional[Any] = None  # WhatsApp uses interactive templates

    def has_text(self):
        return bool(self.text)

    def has_images(self):
        return bool(self.images)

    def has_files(self):
        return bool(self.files)

    def has_buttons(self):
        return bool(self.keyboard)


class ResponsePayloadCollection(BaseModel):
    responses: List[ResponsePayload] = Field(default_factory=list)
