import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Optional, Tuple

import yt_dlp
from pyrogram import Client, filters
from pyrogram.types import Message
from pytgcalls import PyTgCalls

# ----------------- CONFIG -----------------
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
STRING_SESSION = os.getenv("STRING_SESSION", "")
BOT_NAME = os.getenv("BOT_NAME", "Elite VC Music Bot")

# cookies.txt in repo root by default
COOKIES_FILE = os.getenv("COOKIES_FILE", "cookies.txt")
COOKIE_PATH = Path(COOKIES_FILE)

# ----------------- LOGGING -----------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("vc-music-bot")

# ----------------- VALIDATION -----------------
missing = []
if not API_ID:
    missing.append("API_ID")
if not API_HASH:
    missing.append("API_HASH")
if not BOT_TOKEN:
    missing.append("BOT_TOKEN")
if not STRING_SESSION:
    missing.append("STRING_SESSION")

if missing:
    raise RuntimeError(f"Missing env vars: {', '.join(missing)}")

# ----------------- CLIENTS -----------------
bot = Client(
    "music_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)

user = Client(
    "music_user",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=STRING_SESSION,
)

music = PyTgCalls(user)

# ----------------- HELPERS -----------------
URL_RE = re.compile(r"^https?://", re.I)


def is_url(text: str) -> bool:
    return bool(URL_RE.match(text.strip()))


def fmt_time(seconds: Optional[int]) -> str:
    if not seconds:
        return "Live / Unknown"
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def extract_stream(query: str) -> Tuple[str, str, str, Optional[int]]:
    """
    Returns:
        stream_url, title, webpage_url, duration
    """
    source = query.strip() if is_url(query) else f"ytsearch1:{query.strip()}"

    ydl_opts = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "cachedir": False,
        "socket_timeout": 20,
        "retries": 3,
        "fragment_retries": 3,
    }

    if COOKIE_PATH.exists():
        ydl_opts["cookiefile"] = str(COOKIE_PATH)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(source, download=False)

    if "entries" in info:
        info = next((e for e in info["entries"] if e), None)
        if not info:
            raise RuntimeError("No playable result found.")

    stream_url = info["url"]
    title = info.get("title", "Unknown")
    webpage_url = info.get("webpage_url", query)
    duration = info.get("duration")

    return stream_url, title, webpage_url, duration


async def get_query(message: Message) -> Optional[str]:
    if len(message.command) < 2:
        return None
    return " ".join(message.command[1:]).strip()


async def ensure_group(message: Message) -> bool:
    if message.chat.type not in ("group", "supergroup"):
        await message.reply_text("This command works only in group voice chats.")
        return False
    return True


async def safe_edit(msg: Message, text: str):
    try:
        await msg.edit_text(text)
    except Exception:
        pass


# ----------------- COMMANDS -----------------
@bot.on_message(filters.command("start"))
async def start_cmd(_: Client, message: Message):
    await message.reply_text(
        f"**{BOT_NAME}**\n\n"
        "**Commands**\n"
        "/play <song name or url>\n"
        "/pause\n"
        "/resume\n"
        "/stop\n"
        "/leave\n"
        "/ping"
    )


@bot.on_message(filters.command("ping"))
async def ping_cmd(_: Client, message: Message):
    start = asyncio.get_event_loop().time()
    m = await message.reply_text("Pinging...")
    end = asyncio.get_event_loop().time()
    await m.edit_text(f"Pong! `{int((end - start) * 1000)} ms`")


@bot.on_message(filters.command("play"))
async def play_cmd(_: Client, message: Message):
    if not await ensure_group(message):
        return

    query = await get_query(message)
    if not query:
        await message.reply_text("Usage: `/play song name or url`")
        return

    status = await message.reply_text("Searching...")

    try:
        stream_url, title, webpage_url, duration = await asyncio.to_thread(
            extract_stream, query
        )

        await safe_edit(
            status,
            f"Playing now...\n\n"
            f"**Title:** {title}\n"
            f"**Duration:** {fmt_time(duration)}",
        )

        await asyncio.to_thread(music.play, message.chat.id, stream_url)

        await safe_edit(
            status,
            f"**Now Playing**\n\n"
            f"**Title:** {title}\n"
            f"**Duration:** {fmt_time(duration)}\n"
            f"**Source:** {webpage_url}",
        )

    except Exception as e:
        log.exception("Play error")
        await safe_edit(status, f"Play failed.\n\n`{e}`")


@bot.on_message(filters.command("pause"))
async def pause_cmd(_: Client, message: Message):
    if not await ensure_group(message):
        return
    try:
        await asyncio.to_thread(music.pause, message.chat.id)
        await message.reply_text("Paused.")
    except Exception as e:
        await message.reply_text(f"Pause failed: `{e}`")


@bot.on_message(filters.command("resume"))
async def resume_cmd(_: Client, message: Message):
    if not await ensure_group(message):
        return
    try:
        await asyncio.to_thread(music.resume, message.chat.id)
        await message.reply_text("Resumed.")
    except Exception as e:
        await message.reply_text(f"Resume failed: `{e}`")


@bot.on_message(filters.command("stop"))
async def stop_cmd(_: Client, message: Message):
    if not await ensure_group(message):
        return
    try:
        await asyncio.to_thread(music.stop, message.chat.id)
        await message.reply_text("Stopped.")
    except Exception as e:
        await message.reply_text(f"Stop failed: `{e}`")


@bot.on_message(filters.command("leave"))
async def leave_cmd(_: Client, message: Message):
    if not await ensure_group(message):
        return
    try:
        await asyncio.to_thread(music.leave, message.chat.id)
        await message.reply_text("Left voice chat.")
    except Exception as e:
        await message.reply_text(f"Leave failed: `{e}`")


# ----------------- MAIN -----------------
async def main():
    await user.start()
    await bot.start()
    music.start()

    me = await bot.get_me()
    log.info("Bot started as @%s", me.username or "unknown")
    print("Bot is running...")

    # Keep process alive
    await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Stopped.")
