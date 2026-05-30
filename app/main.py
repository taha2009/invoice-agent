import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response
from telegram import Bot, BotCommand, InputFile

from app.agent import reset_session, run_agent
from app.config import settings
from app.whatsapp import get_bot as get_whatsapp_bot

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

_bot = Bot(token=settings.telegram_bot_token)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _set_webhook()
    await _bot.set_my_commands([BotCommand("reset", "Start a new conversation")])
    yield


app = FastAPI(lifespan=lifespan)


async def _set_webhook() -> None:
    if not settings.webhook_base_url:
        log.warning("WEBHOOK_BASE_URL is not set — skipping webhook registration")
        return
    kwargs = {"url": f"{settings.webhook_base_url}/webhook"}
    if settings.telegram_webhook_secret:
        kwargs["secret_token"] = settings.telegram_webhook_secret
    result = await _bot.set_webhook(**kwargs)
    log.info("setWebhook: %s", result)


@app.get("/debug/sheet")
async def debug_sheet() -> dict:
    import traceback

    try:
        from app.tools.sheets_ledger import get_sheet

        sheet = get_sheet()
        return {
            "ok": True,
            "title": sheet.title,
            "spreadsheet": sheet.spreadsheet.title,
        }
    except Exception:
        return {"ok": False, "error": traceback.format_exc()}


@app.post("/webhook")
async def webhook(request: Request) -> dict:
    if settings.telegram_webhook_secret:
        token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if token != settings.telegram_webhook_secret:
            raise HTTPException(status_code=403, detail="Forbidden")

    update = await request.json()
    message = update.get("message") or update.get("edited_message")
    if not message or "text" not in message:
        return {"ok": True}

    chat_id: int = message["chat"]["id"]
    user_id: int = message["from"]["id"]
    text: str = message["text"]

    if settings.allowed_ids and user_id not in settings.allowed_ids:
        await _bot.send_message(
            chat_id=chat_id, text=f"Unauthorized. Your user ID is {user_id}."
        )
        return {"ok": True}

    if text.startswith("/reset"):
        reset_session(user_id)
        await _bot.send_message(
            chat_id=chat_id,
            text="Conversation reset. Start a new invoice whenever you're ready.",
        )
        return {"ok": True}

    try:
        result = await run_agent(user_id, text)
    except Exception:
        log.exception("Agent error for user %s", user_id)
        await _bot.send_message(
            chat_id=chat_id, text="Something went wrong — please try again."
        )
        return {"ok": True}

    if result.text:
        await _bot.send_message(chat_id=chat_id, text=result.text)

    for pdf in result.pdf_files:
        try:
            with open(pdf["pdf_path"], "rb") as f:
                await _bot.send_document(
                    chat_id=chat_id,
                    document=InputFile(f, filename=pdf["pdf_filename"]),
                )
        finally:
            try:
                os.unlink(pdf["pdf_path"])
            except OSError:
                pass

    return {"ok": True}


@app.get("/whatsapp/webhook")
async def whatsapp_verify(request: Request) -> Response:
    params = request.query_params
    challenge = get_whatsapp_bot().verify_webhook(
        mode=params.get("hub.mode", ""),
        token=params.get("hub.verify_token", ""),
        challenge=params.get("hub.challenge", ""),
    )
    if challenge is None:
        raise HTTPException(status_code=403, detail="Forbidden")
    return Response(content=challenge, media_type="text/plain")


@app.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request) -> dict:
    payload = await request.json()
    await get_whatsapp_bot().process_update(payload)
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app", host="0.0.0.0", port=settings.port, reload=settings.debug
    )
