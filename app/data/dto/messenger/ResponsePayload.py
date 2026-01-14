import re
from typing import List, Optional
from pydantic import BaseModel, Field, PrivateAttr

class FileObj(BaseModel):
    name: str = Field(description="File name")
    content: bytes = Field(description="File content")

class ResponsePayload(BaseModel):
    text: Optional[str] = Field(default=None, description="Message text")
    images: List[bytes] = Field(default_factory=list, description="List of image bytes")
    files: List[FileObj] = Field(default_factory=list, description="Files to attach")
    err: Optional[str] = Field(default=None, description="Error text")

    # private attribute to store original text
    #_original_text: Optional[str] = PrivateAttr(default=None)
    #
    # def __init__(self, **data):
    #     super().__init__(**data)
    #     # store the raw text internally
    #     self._original_text = data.get("text", None)

    def escape_markdown_v2(self, text: str, keep_asterisk_for_format: bool = True) -> str:
        if keep_asterisk_for_format:
            # Escape all except * (so bold works)
            return re.sub(r'(?<!\\)([_\[\]()~`>#+\-=|{}.!])', r'\\\1', text)
        else:
            # Escape everything
            return re.sub(r'([_*\[\]()~`>#+\-=|{}.!])', r'\\\1', text)

    @property
    def escaped_text(self) -> str:
        """Return MarkdownV2 escaped text"""
        #if self._original_text:
        return self.escape_markdown_v2(self.text)
        #return ""

    def has_images(self) -> bool:
        return bool(self.images)

    def has_text(self) -> bool:
        return bool(self.text and self.text.strip())

    def has_files(self) -> bool:
        return bool(self.files)


class ResponsePayloadCollection(BaseModel):
    responses: List[ResponsePayload] = Field(default_factory=list)
