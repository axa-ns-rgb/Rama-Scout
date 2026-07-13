import os
import logging
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, Request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
import httpx
from parser_helper import parse_candidate
from notion_helper import create_candidate_entry

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
WEBHOOK_URL = os.environ["WEBHOOK_URL"].rstrip("/")
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates",
}

app = FastAPI()
bot_app = Application.builder().token(TELEGRAM_TOKEN).build()

_initialized = False


async def _ensure_initialized():
    global _initialized
    if not _initialized:
        await bot_app.initialize()
        _initialized = True


# --- Supabase state helpers ---

async def _store_pending(user_id: int, data: dict):
    async with httpx.AsyncClient(timeout=10) as http:
        await http.post(
            f"{SUPABASE_URL}/rest/v1/pending_candidates",
            headers=SUPABASE_HEADERS,
            json={"user_id": user_id, "data": data, "created_at": datetime.now(timezone.utc).isoformat()},
        )


async def _get_pending(user_id: int) -> dict | None:
    async with httpx.AsyncClient(timeout=10) as http:
        response = await http.get(
            f"{SUPABASE_URL}/rest/v1/pending_candidates",
            headers=SUPABASE_HEADERS,
            params={"user_id": f"eq.{user_id}", "select": "data,created_at"},
        )
    rows = response.json()
    if not rows:
        return None
    row = rows[0]
    created = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
    if datetime.now(timezone.utc) - created > timedelta(minutes=5):
        await _delete_pending(user_id)
        return None
    return row["data"]


async def _delete_pending(user_id: int):
    async with httpx.AsyncClient(timeout=10) as http:
        await http.delete(
            f"{SUPABASE_URL}/rest/v1/pending_candidates",
            headers=SUPABASE_HEADERS,
            params={"user_id": f"eq.{user_id}"},
        )


# --- Bot handlers ---

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hi! I'm the Candidate Pipeline Bot.\n\n"
        "Send me a free-text description of a potential candidate and I'll parse "
        "the details and save them to your Notion database.\n\n"
        "Example:\n"
        "John Doe, senior React developer, john@email.com, "
        "+1-555-0100, 5 years exp, strong in TypeScript and GraphQL, "
        "linkedin.com/in/johndoe, previously at Shopify"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Just send any message describing a candidate. I'll extract:\n"
        "• Name\n• Email\n• Phone\n• Position / Role\n"
        "• Experience level\n• Skills\n• LinkedIn\n• Notes\n\n"
        "Then confirm to save to Notion."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text

    status_msg = await update.message.reply_text("Parsing candidate info...")

    try:
        candidate = await parse_candidate(text)

        await _store_pending(user.id, {
            "candidate": candidate,
            "submitted_by": f"@{user.username}" if user.username else user.full_name,
        })

        preview = _format_preview(candidate)
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Save to Notion", callback_data="confirm"),
                InlineKeyboardButton("Discard", callback_data="discard"),
            ]
        ])

        await status_msg.edit_text(
            f"Parsed candidate info:\n\n{preview}\n\nSave this to Notion?",
            reply_markup=keyboard,
        )
    except Exception as e:
        logger.error("handle_message error: %s", e)
        await status_msg.edit_text("Something went wrong while parsing. Please try again.")


def _format_preview(c: dict) -> str:
    lines = []
    if c.get("name"):
        lines.append(f"Name: {c['name']}")
    if c.get("email"):
        lines.append(f"Email: {c['email']}")
    if c.get("phone"):
        lines.append(f"Phone: {c['phone']}")
    if c.get("position"):
        lines.append(f"Position: {c['position']}")
    if c.get("experience_level"):
        lines.append(f"Level: {c['experience_level']}")
    if c.get("skills"):
        lines.append(f"Skills: {', '.join(c['skills'])}")
    if c.get("linkedin"):
        lines.append(f"LinkedIn: {c['linkedin']}")
    if c.get("notes"):
        lines.append(f"Notes: {c['notes']}")
    return "\n".join(lines) if lines else "(No structured data found)"


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    if query.data == "discard":
        await _delete_pending(user.id)
        await query.edit_message_text("Discarded.")
        return

    if query.data == "confirm":
        pending = await _get_pending(user.id)
        if not pending:
            await query.edit_message_text("Session expired. Please send the candidate info again.")
            return

        await _delete_pending(user.id)
        await query.edit_message_text("Saving to Notion...")

        try:
            page_url = await create_candidate_entry(
                candidate=pending["candidate"],
                submitted_by=pending["submitted_by"],
            )
            await query.edit_message_text(f"Saved to Notion!\n\n{page_url}")
        except Exception as e:
            logger.error("Notion error: %s", e)
            await query.edit_message_text(f"Failed to save: {e}")


bot_app.add_handler(CommandHandler("start", cmd_start))
bot_app.add_handler(CommandHandler("help", cmd_help))
bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
bot_app.add_handler(CallbackQueryHandler(handle_callback))


@app.post("/webhook")
async def webhook(request: Request):
    await _ensure_initialized()
    data = await request.json()
    update = Update.de_json(data, bot_app.bot)
    await bot_app.process_update(update)
    return {"ok": True}


@app.get("/setup")
async def setup_webhook():
    """Call once after deploy to register the Telegram webhook."""
    await _ensure_initialized()
    await bot_app.bot.set_webhook(f"{WEBHOOK_URL}/webhook")
    return {"ok": True, "webhook": f"{WEBHOOK_URL}/webhook"}


@app.get("/health")
async def health():
    return {"status": "ok"}
