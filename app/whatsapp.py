"""
WhatsApp Cloud API channel for the invoice agent.
Single-instance bot — credentials come from env vars.
"""

import asyncio
import logging
import mimetypes
import os
from pathlib import Path
from typing import Any, Optional

import httpx

from app.agent import reset_session, run_agent
from app.config import settings

log = logging.getLogger(__name__)

WHATSAPP_API_VERSION = "v25.0"
WHATSAPP_API_BASE_URL = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}"

_ACCEPTED_MIME_TYPES = {
    "audio/aac",
    "audio/mp4",
    "audio/mpeg",
    "audio/amr",
    "audio/ogg",
    "audio/opus",
    "application/vnd.ms-powerpoint",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/pdf",
    "text/plain",
    "application/vnd.ms-excel",
    "image/jpeg",
    "image/png",
    "image/webp",
    "video/mp4",
    "video/3gpp",
}


def _resolve_mime(file_path: Path) -> str:
    ext = file_path.suffix.lower()
    overrides = {
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".csv": "text/plain",
        ".pdf": "application/pdf",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }
    mime = overrides.get(ext) or (mimetypes.guess_type(str(file_path))[0] or "")
    return mime if mime in _ACCEPTED_MIME_TYPES else "text/plain"


class WhatsAppBot:
    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=WHATSAPP_API_BASE_URL,
                headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"},
                timeout=30.0,
            )
        return self._client

    def verify_webhook(self, mode: str, token: str, challenge: str) -> Optional[str]:
        if mode == "subscribe" and token == settings.whatsapp_verify_token:
            log.info("WhatsApp webhook verified")
            return challenge
        log.warning("WhatsApp webhook verification failed")
        return None

    async def _send_text(self, to: str, text: str) -> None:
        try:
            resp = await self._http.post(
                f"/{settings.whatsapp_phone_number_id}/messages",
                json={
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": to,
                    "type": "text",
                    "text": {"preview_url": False, "body": text},
                },
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            log.error("Failed to send WhatsApp text to %s: %s", to, exc)

    async def _upload_media(self, file_path: Path) -> Optional[str]:
        mime = _resolve_mime(file_path)
        try:
            with open(file_path, "rb") as f:
                async with httpx.AsyncClient(base_url=WHATSAPP_API_BASE_URL) as client:
                    resp = await client.post(
                        f"/{settings.whatsapp_phone_number_id}/media",
                        headers={
                            "Authorization": f"Bearer {settings.whatsapp_access_token}"
                        },
                        data={"messaging_product": "whatsapp", "type": mime},
                        files={"file": (file_path.name, f, mime)},
                        timeout=60.0,
                    )
            resp.raise_for_status()
            return resp.json().get("id")
        except Exception as exc:
            log.error("Failed to upload %s to WhatsApp: %s", file_path.name, exc)
            return None

    async def _send_document(self, to: str, file_path: Path) -> None:
        media_id = await self._upload_media(file_path)
        if not media_id:
            await self._send_text(
                to, "Invoice generated but failed to upload to WhatsApp."
            )
            return
        mime = _resolve_mime(file_path)
        is_image = mime.startswith("image/")
        msg_type = "image" if is_image else "document"
        try:
            payload: dict[str, Any] = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": msg_type,
            }
            if is_image:
                payload["image"] = {"id": media_id}
            else:
                payload["document"] = {"id": media_id, "filename": file_path.name}
            resp = await self._http.post(
                f"/{settings.whatsapp_phone_number_id}/messages", json=payload
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            log.error("Failed to send %s to %s: %s", msg_type, to, exc)

    async def _mark_read(self, message_id: str) -> None:
        try:
            await self._http.post(
                f"/{settings.whatsapp_phone_number_id}/messages",
                json={
                    "messaging_product": "whatsapp",
                    "status": "read",
                    "message_id": message_id,
                },
            )
        except Exception as exc:
            log.warning("Failed to mark message read: %s", exc)

    async def handle_message(self, message: dict) -> None:
        from_phone: str = message.get("from", "")
        message_id: str = message.get("id", "")

        if not from_phone:
            return

        asyncio.create_task(self._mark_read(message_id))

        allowed = settings.allowed_whatsapp_set
        if allowed and from_phone not in allowed:
            await self._send_text(
                from_phone, f"Unauthorized. Your number is {from_phone}."
            )
            return

        if message.get("type") != "text":
            await self._send_text(
                from_phone, "Sorry, I can only process text messages right now."
            )
            return

        text: str = message.get("text", {}).get("body", "").strip()

        if text.lower() in ("/reset", "reset"):
            reset_session(from_phone)
            await self._send_text(
                from_phone,
                "Conversation reset. Start a new invoice whenever you're ready.",
            )
            return

        try:
            result = await run_agent(from_phone, text)
        except Exception:
            log.exception("Agent error for WhatsApp user %s", from_phone)
            await self._send_text(
                from_phone, "Something went wrong — please try again."
            )
            return

        if result.text:
            await self._send_text(from_phone, result.text)

        for pdf in result.pdf_files:
            path = Path(pdf["pdf_path"])
            if path.exists():
                await self._send_document(from_phone, path)
                try:
                    os.unlink(path)
                except OSError:
                    pass

    async def process_update(self, payload: dict) -> None:
        if payload.get("object") != "whatsapp_business_account":
            return
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                if change.get("field") != "messages":
                    continue
                value = change.get("value", {})
                if "statuses" in value and "messages" not in value:
                    continue
                for msg in value.get("messages", []):
                    asyncio.create_task(self.handle_message(msg))


_bot: Optional[WhatsAppBot] = None


def get_bot() -> WhatsAppBot:
    global _bot
    if _bot is None:
        _bot = WhatsAppBot()
    return _bot
