import asyncio
import logging
import os
import re
import sys
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from typing import Optional, Tuple

import yt_dlp
from pyrogram import Client, filters
from pyrogram.types import Message
from pytgcalls import PyTgCalls

# ---------------- CONFIG ----------------
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "").strip()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
STRING_SESSION = os.getenv("STRING_SESSION", "").strip()
BOT_NAME = os.getenv("BOT_NAME", "Elite VC Music Bot")

COOKIES_FILE = os.getenv("COOKIES_FILE", "cookies.txt").strip()
COOKIE_PATHS = [
    Path(COOKIES_FILE),
    Path("/etc/secrets/cookies.txt"),
]

PORT = int(os.getenv("PORT", "10000"))

# ---------------- LOGGING ----------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("vc-music-bot")

# ---------------- HTTP SERVER FOR RENDER ----------------
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"OK"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return

def run_web_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    server.serve_forever()

Thread(target=run_web_server, daemon=True).start()

# ---------------- VALIDATION ----------------
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

# ---------------- CLIENTS ----------------
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

# ---------------- HELPERS ----------------
URL_RE = re.compile(r"^https?://", re.I)

def is_url(text: str) -> bool:
    return bool(URL_RE.match(text.strip()))

def fmt_time(seconds: Optional[int]) -> str:
    if not seconds:
        return "Live / Unknown"
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

def cookiefile_path() -> Optional[str]:
    for p in COOKIE_PATHS:
        if p.exists() and p.is_file():
            return str(p)
    return None

def extract_stream(query: str) -> Tuple[str, str, str, Optional[int]]:
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

    cfile = cookiefile_path()
    if cfile:
        ydl_opts["cookiefile"] = cfile

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

async def maybe_async(func, *args, **kwargs):
    result = func(*args, **kwargs)
    if asyncio.iscoroutine(result):
        return await result
    return result

async def get_query(message: Message) -> Optional[str]:
    if len(message.command) < 2:
        return None
    return " ".join(message.command[1:]).strip()

async def ensure_group(message: Message) -> bool:
    if message.chat.type not in ("group", "supergroup"):
        await message.reply_text("This command works only inside a group or supergroup.")
        return False
    return True

async def safe_edit(msg: Message, text: str):
    try:
        await msg.edit_text(text)
    except Exception:
        pass

# ---------------- COMMANDS ----------------
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
            f"Joining and playing...\n\n"
            f"**Title:** {title}\n"
            f"**Duration:** {fmt_time(duration)}",
        )

        await maybe_async(music.play, message.chat.id, stream_url)

        await safe_edit(
            status,
            f"**Now Playing**\n\n"
            f"**Title:** {title}\n"
            f"**Duration:** {fmt_time(duration)}\n"
            f"**Source:** {webpage_url}",
        )

    except Exception as e:
        log.exception("Play failed")
        await safe_edit(status, f"Play failed.\n\n`{e}`")

@bot.on_message(filters.command("pause"))
async def pause_cmd(_: Client, message: Message):
    if not await ensure_group(message):
        return
    try:
        await maybe_async(music.pause, message.chat.id)
        await message.reply_text("Paused.")
    except Exception as e:
        await message.reply_text(f"Pause failed: `{e}`")

@bot.on_message(filters.command("resume"))
async def resume_cmd(_: Client, message: Message):
    if not await ensure_group(message):
        return
    try:
        await maybe_async(music.resume, message.chat.id)
        await message.reply_text("Resumed.")
    except Exception as e:
        await message.reply_text(f"Resume failed: `{e}`")

@bot.on_message(filters.command("stop"))
async def stop_cmd(_: Client, message: Message):
    if not await ensure_group(message):
        return
    try:
        await maybe_async(music.stop, message.chat.id)
        await message.reply_text("Stopped.")
    except Exception as e:
        await message.reply_text(f"Stop failed: `{e}`")

@bot.on_message(filters.command("leave"))
async def leave_cmd(_: Client, message: Message):
    if not await ensure_group(message):
        return
    try:
        await maybe_async(music.leave, message.chat.id)
        await message.reply_text("Left voice chat.")
    except Exception as e:
        await message.reply_text(f"Leave failed: `{e}`")

# ---------------- MAIN ----------------
async def main():
    try:
        await user.start()
        await bot.start()
        await maybe_async(music.start)

        me = await bot.get_me()
        log.info("Bot started as @%s", me.username or "unknown")
        print("Bot is running...")

        await asyncio.Event().wait()

    except Exception:
        traceback.print_exc()
        raise

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Stopped.")
    except Exception:
        traceback.print_exc()
        sys.exit(1)
