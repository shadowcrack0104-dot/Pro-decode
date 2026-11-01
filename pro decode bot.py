#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================
  💎 VPN DECODER PRO  —  v8.3.1  (CLEAN CONFIG + ADVANCED ADMIN)
================================================================
  • No header clutter — only config data
  • Premium formatted message & Inline Copy Buttons
  • Advanced Admin Panel (Add/Remove Admins, Channel Manager, Stats)
  • Broadcast system & Keep-alive Flask Server (Port 8080)
================================================================
"""

import os, io, re, sys, json, time, gzip, base64, struct
import pickle, hashlib, sqlite3, asyncio, logging, threading
import contextlib, traceback
from datetime import datetime
from pathlib import Path

import pytz
from Crypto.Cipher import AES, ChaCha20
from Crypto.Util.Padding import unpad

# ── OPTIONAL DEPS & FLASK KEEP-ALIVE ──
try:
    from Crypto.Cipher import ChaCha20_Poly1305
    HAVE_POLY = True
except ImportError:
    HAVE_POLY = False

try:
    from argon2.low_level import hash_secret_raw, Type
    HAVE_ARGON2 = True
except ImportError:
    HAVE_ARGON2 = False

try:
    import msgpack
    HAVE_MSGPACK = True
except ImportError:
    HAVE_MSGPACK = False

try:
    from flask import Flask
    HAVE_FLASK = True
except ImportError:
    HAVE_FLASK = False

try:
    from dotenv import load_dotenv as _ld
    _ld()
except Exception:
    pass

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters,
)
from telegram.error import Conflict, NetworkError, TimedOut

# ══════════════════════════════════════════════════════════════
#  ⚙️  CONFIG & USER IDENTITY
# ══════════════════════════════════════════════════════════════
BOT_TOKEN = os.getenv("BOT_TOKEN") or "9074615064:AAEdxaqujGCN_Oq9emrG7ovn_DB_-eKX2c8"

# Primary Owner Identity specified by user
PRIMARY_OWNER_ID = 7986731915
OWNER_USERNAME = "@King_X_vau"
OWNER_NAME = "𓆩—͟͟͞͞乂 ZRX PAPA 乂 ᭄𓆪"
DEFAULT_ADMIN = "@provai96"
DEFAULT_CHANNEL = "@Trickbuzz_BD"

DATABASE_PATH = os.getenv("DATABASE_PATH", "vpn_bot.db")
WHITEBOX_FILE = os.getenv("WHITEBOX_FILE", "whitebox_blob.txt")

BD_TZ = pytz.timezone("Asia/Dhaka")
BRAND     = "VPN DECODER PRO"
BRAND_VER = "8.3.1"

RATE_MIN_GAP   = 3
RATE_BURST_MAX = 5
RATE_BURST_WIN = 60
MAX_FILE_SIZE  = 10 * 1024 * 1024

# ══════════════════════════════════════════════════════════════
#  🔧 LOGGING
# ══════════════════════════════════════════════════════════════
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("vpn_pro.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logger = logging.getLogger("VPNPro")


def bd_time():     return datetime.now(BD_TZ).strftime("%I:%M:%S %p")


def esc(s):
    return (str(s).replace("&", "&amp;")
                   .replace("<", "&lt;")
                   .replace(">", "&gt;"))


# ══════════════════════════════════════════════════════════════
#  💾 DATABASE & SETTINGS MANAGEMENT
# ══════════════════════════════════════════════════════════════
_lock = threading.Lock()


@contextlib.contextmanager
def _db():
    c = sqlite3.connect(DATABASE_PATH, check_same_thread=False, timeout=10)
    c.row_factory = sqlite3.Row
    try:
        yield c
    finally:
        c.close()


def db_init():
    with _lock, _db() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                uid INTEGER PRIMARY KEY,
                username TEXT, first_name TEXT,
                joined_at TEXT DEFAULT CURRENT_TIMESTAMP,
                total_success INTEGER DEFAULT 0,
                total_failed  INTEGER DEFAULT 0,
                total_unlocks INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS admins (
                uid INTEGER PRIMARY KEY,
                added_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid INTEGER, filename TEXT, ext TEXT,
                decoder TEXT, success INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
        """)
        # Ensure primary owner is always in admin table
        c.execute("INSERT OR IGNORE INTO admins (uid) VALUES (?)", (PRIMARY_OWNER_ID,))
        # Default channel setting if not present
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", ("channel_link", DEFAULT_CHANNEL))
        c.commit()


def is_owner(uid):
    return uid == PRIMARY_OWNER_ID


def is_admin(uid):
    if uid == PRIMARY_OWNER_ID:
        return True
    with _lock, _db() as c:
        r = c.execute("SELECT 1 FROM admins WHERE uid=?", (uid,)).fetchone()
        return bool(r)


def get_channel_link():
    with _lock, _db() as c:
        r = c.execute("SELECT value FROM settings WHERE key='channel_link'").fetchone()
        return r["value"] if r else DEFAULT_CHANNEL


def set_channel_link(link):
    with _lock, _db() as c:
        c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('channel_link', ?)", (link,))
        c.commit()


def db_add_admin(uid):
    with _lock, _db() as c:
        c.execute("INSERT OR IGNORE INTO admins (uid) VALUES (?)", (uid,))
        c.commit()


def db_remove_admin(uid):
    if uid == PRIMARY_OWNER_ID:
        return False
    with _lock, _db() as c:
        c.execute("DELETE FROM admins WHERE uid=?", (uid,))
        c.commit()
        return True


def db_get_admins():
    with _lock, _db() as c:
        rows = c.execute("SELECT uid FROM admins").fetchall()
        return [r["uid"] for r in rows]


def db_user(uid):
    with _lock, _db() as c:
        r = c.execute("SELECT * FROM users WHERE uid=?", (uid,)).fetchone()
        return dict(r) if r else None


def db_upsert_user(uid, un, fn):
    with _lock, _db() as c:
        c.execute("""INSERT INTO users (uid, username, first_name)
                     VALUES (?,?,?) ON CONFLICT(uid) DO UPDATE SET
                     username=excluded.username,
                     first_name=excluded.first_name""", (uid, un, fn))
        c.commit()


def db_log(uid, fn, ext, decoder, success, unlock=False):
    with _lock, _db() as c:
        c.execute("INSERT OR IGNORE INTO users (uid) VALUES (?)", (uid,))
        c.execute("""INSERT INTO files (uid,filename,ext,decoder,success)
                     VALUES (?,?,?,?,?)""",
                  (uid, fn, ext, decoder, int(success)))
        c.execute("""UPDATE users SET
                     total_success = total_success + ?,
                     total_failed  = total_failed  + ?,
                     total_unlocks = total_unlocks + ?
                     WHERE uid=?""",
                  (1 if success else 0,
                   0 if success else 1,
                   1 if unlock else 0, uid))
        c.commit()


def db_admin_stats():
    with _lock, _db() as c:
        total_users   = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_files   = c.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        total_unlocks = c.execute(
            "SELECT COALESCE(SUM(total_unlocks),0) FROM users").fetchone()[0]
        total_success = c.execute(
            "SELECT COALESCE(SUM(total_success),0) FROM users").fetchone()[0]
        total_failed  = c.execute(
            "SELECT COALESCE(SUM(total_failed),0) FROM users").fetchone()[0]
        rows = c.execute("""
            SELECT uid, username, first_name,
                   total_success, total_failed, total_unlocks, joined_at
            FROM users
            ORDER BY total_unlocks DESC, total_success DESC
        """).fetchall()
        return {
            "total_users": total_users,
            "total_files": total_files,
            "total_unlocks": total_unlocks,
            "total_success": total_success,
            "total_failed": total_failed,
            "users": [dict(r) for r in rows],
        }


# ══════════════════════════════════════════════════════════════
#  🌐  DECODERS ENGINE (.dark, .ehi, .npvt, .ssc, .hc)
# ══════════════════════════════════════════════════════════════
_DT256 = b"$B&E)H@McQfThWmZq4t7w!z%C*F-JaNd"
_DT192 = b"F)J@NcRfUjXn2r4u7x!A%D*G"
_DTIV  = bytes.fromhex("232e39185523184a5723586242200e05")


def decode_dark(fb):
    if not HAVE_MSGPACK: return None
    def b64(d):
        c = d.replace("-", "+").replace("_", "/")
        if p := len(c) % 4: c += "=" * (4 - p)
        return base64.b64decode(c)
    def aes(d, k, iv):
        return AES.new(k, AES.MODE_CFB, iv=iv, segment_size=128).decrypt(d)
    with contextlib.suppress(Exception):
        raw = fb.decode("utf-8", errors="ignore").strip()
        if not raw: return None
        if "://" in raw: raw = raw.split("://", 1)[1]
        outer = json.loads(b64(raw).decode("utf-8"))
        if "encryptedLockedConfig" not in outer: return None
        do = aes(b64(outer["encryptedLockedConfig"]), _DT256, _DTIV)
        up = msgpack.unpackb(do, raw=False, strict_map_key=False)
        if "EncryptedLockedConfig" in up:
            di = aes(up["EncryptedLockedConfig"], _DT192, _DTIV)
            up["EncryptedLockedConfig"] = msgpack.unpackb(di, raw=False, strict_map_key=False)
        outer["encryptedLockedConfig"] = up
        return json.dumps(outer, indent=2, ensure_ascii=False)
    return None


_E1 = bytes.fromhex("7e1210f7aab956f7a668bda6e57feddb7f84ad840aef8d27b1b969959be3ab6c")
_E2 = bytes.fromhex("b2bc617c32d8b9eb1943a5ffa8051eea")
_EE = b"null=V5kU5+FFrY\x00"
_EB = (bytes.fromhex("221d572349555f1d112133236b1f4a3f"), bytes.fromhex("5543494c53443e3f4a6a4539384e776a"), bytes.fromhex("374c2541575e4d531a3c327b75431e5f"))
_ES = (bytes.fromhex("2c5d1147bbad422b3b334d4d235f1a53"), bytes.fromhex("522b01433a5e8b2fc7549e1ad368e541"), bytes.fromhex("337a1035aaedf3458ca167e92d74b839"))


def decode_ehi(fb):
    if not (HAVE_ARGON2 and HAVE_POLY): return None
    def parse(fb):
        try:
            f = io.BytesIO(fb)
            def ru():
                lb = f.read(2)
                if len(lb) < 2: return ""
                return f.read(struct.unpack(">H", lb)[0]).decode("utf-8", errors="ignore")
            ru(); f.read(8); ru(); f.read(8)
            plb = f.read(4)
            if len(plb) < 4: return None
            pl = struct.unpack(">I", plb)[0]
            f.read(8)
            return f.read(pl)
        except Exception:
            return None
    payload = parse(fb)
    if not payload: return None
    for iv in _EB + _ES:
        with contextlib.suppress(Exception):
            c1 = AES.new(_E1, AES.MODE_CBC, iv)
            l1 = unpad(c1.decrypt(payload), 16).decode("utf-8")
            pr = l1.split(":")
            if len(pr) >= 3:
                c2 = AES.new(_E2, AES.MODE_CBC, base64.b64decode(pr[0]))
                g = unpad(c2.decrypt(base64.b64decode(pr[2])), 16)
                if (st := g.find(b"{")) != -1:
                    return g[st:].decode("utf-8", errors="ignore")
    return None


_wb_cache = None
def _load_wb():
    global _wb_cache
    if _wb_cache is not None: return _wb_cache
    if not os.path.exists(WHITEBOX_FILE): return None
    try:
        with open(WHITEBOX_FILE, "r") as f: blob = f.read().strip()
        if not blob: return None
        _wb_cache = pickle.loads(gzip.decompress(base64.b64decode(blob)))
        return _wb_cache
    except Exception:
        return None


def decode_npvt(fb):
    wb = _load_wb()
    if not wb: return None
    try:
        raw = fb.decode("utf-8", errors="ignore").strip()
        if raw.startswith("NPVTSUB1"): raw = raw[8:].strip()
        elif raw.startswith("NPVT1"): raw = raw[5:].strip()
        pls = raw.split(",")
        if len(pls) < 2: return None
        return json.dumps({"raw_data": pls[1]}, indent=2)
    except Exception:
        return None


_SN = struct.pack("<Q", 0xF7479D9F87F3D074)
_S1 = bytes.fromhex("c8a6a8ea102d5a0baf8fdb1b39cd615c0d07c1edcbde4e82cfdd309bc4587f6b")
_S2 = bytes.fromhex("7f9db48ffde449ad19f9ed44b8b27eee334ab4a85b972dca8ff20e4e8ed44e4e")


def decode_ssc(fb):
    def cd(k, n, d):
        c = ChaCha20.new(key=k, nonce=n); c.seek(64); return c.decrypt(d)
    with contextlib.suppress(Exception):
        c = fb.decode("utf-8-sig", errors="ignore").strip()
        if c.startswith("ssc://"): c = c[6:][::-1]
        hx = "".join(c.split())
        l1 = cd(_S1, _SN, bytes.fromhex(hx))
        return l1.decode("utf-8", errors="ignore")
    return None


_HK = [bytes.fromhex(x) for x in [
    "2be4342943c6f91ff58987f41a1aafd179eeb4e053f5cea55b11d6a7db58bd7d",
    "3380aa278b744ba5b529a7f32fa803e48749280dae378345d9b526cf1dbce372",
    "cea9305c95168b162a335b137c61983b8df54e6375da01136547890f14c5fac3",
    "4beeace0e42bae8f29470cf40cf2dfacd5f4e1f751912bf52e803c8c85792193",
    "f8e5f6ebea90558eb32229da24fd0fb7d813091dafe89bb2954fda33b4c60f63",
    "81342f558a6273bac4548d473f54c4ffc7c41747dee81369acab9c787d41ab9c",
    "45635e6fc70486e2fd10d3c2b4780f02d0b4c5f4aa929fc54f86bb8fa4417944",
    "3d632a251c9820f2baf83e15498d27548fc67921cb437f8ce48505989378adea",
]]


def _hc_raw(fb):
    try:
        ed = fb.decode("utf-8", errors="ignore")
        kb = bytes.fromhex("e382e4b8adc386f09f9293")
        res = bytes(b ^ kb[i % len(kb)] for i, b in enumerate(ed.encode("latin-1"))).decode("utf-8")
        return {"protections": {"status": "unlocked"}, "config": {"raw_content": res[:2000]}}
    except Exception:
        return None


def decode_hc(fb):
    r = _hc_raw(fb)
    if not r: return None
    return json.dumps(r, indent=2, ensure_ascii=False)


def unlock_hc(fb):
    r = _hc_raw(fb)
    if not r: return None
    r["config"]["lockAllConfig"] = False
    r["config"]["expiryTime"] = 4070908800000
    return r


DECODERS = {
    "dark":  ("🌑 DarkTunnel",     "DarkTunnel",     decode_dark),
    "ehi":   ("🔒 HTTP Injector",  "HTTP Injector",  decode_ehi),
    "npvt":  ("🎭 NPVT Whitebox",  "NPVT Whitebox",  decode_npvt),
    "ssc":   ("🔐 SC VPN",         "SC VPN",         decode_ssc),
    "hc":    ("⚙️ HTTP Custom",    "HTTP Custom",    decode_hc),
}


def detect_and_decode(fb, filename):
    fl = (filename or "").lower()
    ext = Path(fl).suffix.lstrip(".")
    if ext in DECODERS:
        label, _, fn = DECODERS[ext]
        with contextlib.suppress(Exception):
            if o := fn(fb): return label, o
    for k, (label, _, fn) in DECODERS.items():
        if k == ext: continue
        with contextlib.suppress(Exception):
            if o := fn(fb): return label, o
    return None, None


# ══════════════════════════════════════════════════════════════
#  🧠  EXTRACTION & V2RAY BUILDERS
# ══════════════════════════════════════════════════════════════
UUID_RE = re.compile(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}')
IP_RE = re.compile(r'(?:\d{1,3}\.){3}\d{1,3}')


def extract_fields(decoded_json):
    try:
        data = json.loads(decoded_json)
    except Exception:
        data = {"raw": decoded_json}
    blob = json.dumps(data, ensure_ascii=False)
    out = {}
    if m := UUID_RE.search(blob):
        out["uuid"] = m.group(0)
    if m := IP_RE.search(blob):
        out["ip"] = m.group(0)
    out["name"] = data.get("name") or "VPN-Config"
    return out


def build_vmess_link(decoded_json):
    sm = extract_fields(decoded_json)
    if not sm.get("uuid") or not sm.get("ip"): return None
    try:
        vm = {
            "v": "2", "ps": sm.get("name"), "add": sm.get("ip"),
            "port": "443", "id": sm.get("uuid"), "aid": "0", "net": "ws"
        }
        return "vmess://" + base64.b64encode(json.dumps(vm).encode()).decode()
    except Exception:
        return None


def build_config_message(decoded_json, decoder_label):
    sm = extract_fields(decoded_json)
    L = [
        f"🔓 <b>{esc(decoder_label.upper())} DECRYPTED</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"📦 <b>Name</b>: <code>{esc(sm.get('name', 'N/A'))}</code>",
    ]
    if sm.get("ip"): L.append(f"🌍 <b>Server IP</b>: <code>{esc(sm['ip'])}</code>")
    if sm.get("uuid"): L.append(f"🆔 <b>UUID</b>: <code>{esc(sm['uuid'])}</code>")
    
    vlink = build_vmess_link(decoded_json)
    if vlink:
        L.extend(["", "🔗 <b>READY V2RAY LINK</b>", "━━━━━━━━━━━━━━━━━━━━", f"<code>{esc(vlink)}</code>"])
    
    L.extend(["", "━━━━━━━━━━━━━━━━━━━━", f"💎 <i>Powered by {BRAND} · {OWNER_USERNAME}</i>"])
    return "\n".join(L)


_COPY_STORE = {}


def build_copy_buttons(decoded_json, sm):
    uid_key = int(time.time() * 1000) % 100000000
    rows = [
        [InlineKeyboardButton("📋 Copy V2Ray Link", callback_data=f"cplink_{uid_key}")],
        [InlineKeyboardButton("👤 Owner", url=f"https://t.me/{OWNER_USERNAME.lstrip('@')}")],
    ]
    return InlineKeyboardMarkup(rows), uid_key


# ══════════════════════════════════════════════════════════════
#  🎛️  KEYBOARDS & MENUS
# ══════════════════════════════════════════════════════════════
def reply_menu(uid=None):
    kb = [
        [KeyboardButton("👤  Profile"),   KeyboardButton("📊  Stats")],
        [KeyboardButton("🗂️  Formats"),   KeyboardButton("ℹ️  Help")],
        [KeyboardButton("📞  Support"),   KeyboardButton("📢  Channel")],
    ]
    if uid and is_admin(uid):
        kb.append([KeyboardButton("🛡️  Admin Panel")])
    return ReplyKeyboardMarkup(kb, resize_keyboard=True, is_persistent=True)


# ══════════════════════════════════════════════════════════════
#  ⏱️  RATE LIMIT & EDIT
# ══════════════════════════════════════════════════════════════
_last = {}
_burst = {}


def rate_ok(uid):
    if is_admin(uid): return True, 0
    now = time.time()
    last = _last.get(uid, 0)
    if now - last < RATE_MIN_GAP:
        return False, int(RATE_MIN_GAP - (now - last)) + 1
    q = _burst.setdefault(uid, [])
    q[:] = [t for t in q if now - t < RATE_BURST_WIN]
    if len(q) >= RATE_BURST_MAX:
        return False, int(RATE_BURST_WIN - (now - q[0])) + 1
    _last[uid] = now
    q.append(now)
    return True, 0


async def safe_edit(msg, text, **kw):
    with contextlib.suppress(Exception):
        await msg.edit_text(text, **kw)


# ══════════════════════════════════════════════════════════════
#  🏠  COMMAND HANDLERS
# ══════════════════════════════════════════════════════════════
async def cmd_start(upd, ctx):
    uid = upd.effective_user.id
    u = upd.effective_user
    with contextlib.suppress(Exception):
        await asyncio.to_thread(db_upsert_user, uid, u.username or "", u.first_name or "")

    text = (
        f"╔══════════════════════════════════╗\n"
        f"║   💎  <b>{BRAND}</b>  💎    ║\n"
        f"║           <b>P R O</b>   ·   <i>v{BRAND_VER}</i>          ║\n"
        f"╚══════════════════════════════════╝\n\n"
        f"👋  Welcome, <b>{esc(u.first_name)}</b>\n"
        f"👑  Owner: <b>{OWNER_NAME} ({OWNER_USERNAME})</b>\n\n"
        f"┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
        f"┃   🎯  <b>SUPPORTED FORMATS</b>\n"
        f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n\n"
        f"  🌑  <b>DarkTunnel</b>      <code>.dark</code>\n"
        f"  🔒  <b>HTTP Injector</b>   <code>.ehi</code>\n"
        f"  🎭  <b>NPVT Whitebox</b>   <code>.npvt</code>\n"
        f"  🔐  <b>SC VPN</b>          <code>.ssc</code>\n"
        f"  ⚙️  <b>HTTP Custom</b>     <code>.hc</code>\n\n"
        f"💡  <i>Send any config file to decode & unlock!</i>"
    )
    await upd.message.reply_text(
        text, reply_markup=reply_menu(uid),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True)


async def cmd_help(upd, ctx):
    text = (
        "ℹ️  <b>HELP GUIDE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "📖  <b>How to use:</b>\n"
        "  1️⃣ Send any config file (.dark, .ehi, .hc, etc.)\n"
        "  2️⃣ Bot auto-detects, unlocks restrictions & extracts V2Ray links.\n\n"
        f"📞 Contact Owner: <b>{OWNER_USERNAME}</b>"
    )
    await upd.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_formats(upd, ctx):
    text = (
        "🗂️  <b>SUPPORTED FORMATS & ENGINES</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "  🌑 <code>.dark</code> - DarkTunnel\n"
        "  🔒 <code>.ehi</code>  - HTTP Injector\n"
        "  🎭 <code>.npvt</code> - NPVT Whitebox\n"
        "  🔐 <code>.ssc</code>  - SC VPN\n"
        "  ⚙️ <code>.hc</code>   - HTTP Custom (Auto-unlock)"
    )
    await upd.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_stats(upd, ctx):
    uid = upd.effective_user.id
    st = await asyncio.to_thread(db_user, uid)
    if not st:
        await upd.message.reply_text("❌ No data yet — send a file!")
        return
    tot = st["total_success"] + st["total_failed"]
    sr = round(st["total_success"] / tot * 100, 1) if tot else 0
    text = (
        "👤 <b>MY PROFILE & STATS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"  🆔 ID: <code>{uid}</code>\n"
        f"  ✅ Success: <b>{st['total_success']}</b>\n"
        f"  ❌ Failed: <b>{st['total_failed']}</b>\n"
        f"  🔓 Unlocks: <b>{st['total_unlocks']}</b>\n"
        f"  🎯 Success Rate: <b>{sr}%</b>"
    )
    await upd.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_contact(upd, ctx):
    text = (
        "📞  <b>SUPPORT & CONTACT</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"  👤 Owner: <b>{OWNER_NAME}</b> (<a href=\"https://t.me/{OWNER_USERNAME.lstrip('@')}\">{OWNER_USERNAME}</a>)\n"
        f"  📢 Channel: <b>{get_channel_link()}</b>"
    )
    await upd.message.reply_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


async def cmd_admin(upd, ctx):
    uid = upd.effective_user.id
    if not is_admin(uid):
        await upd.message.reply_text("⛔ Access denied.")
        return

    stats = await asyncio.to_thread(db_admin_stats)
    admins = db_get_admins()

    text = (
        "🛡️ <b>ADMIN CONTROL PANEL</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"  👥 Total Users: <b>{stats['total_users']}</b>\n"
        f"  📦 Files Decoded: <b>{stats['total_files']}</b>\n"
        f"  🔓 Total Unlocks: <b>{stats['total_unlocks']}</b>\n"
        f"  🔑 Admins count: <b>{len(admins)}</b>\n"
        f"  📢 Channel: <b>{get_channel_link()}</b>\n\n"
        "🛠️ <b>Commands:</b>\n"
        "  <code>/addadmin [user_id]</code> - Add admin\n"
        "  <code>/deladmin [user_id]</code> - Remove admin\n"
        "  <code>/setchannel [link]</code> - Update channel link\n"
        "  <code>/broadcast [text]</code> - Send broadcast message"
    )
    await upd.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_addadmin(upd, ctx):
    if not is_owner(upd.effective_user.id):
        await upd.message.reply_text("⛔ Only the primary owner can add admins.")
        return
    if not ctx.args:
        await upd.message.reply_text("⚠️ Usage: <code>/addadmin 123456789</code>", parse_mode=ParseMode.HTML)
        return
    try:
        new_admin = int(ctx.args[0])
        db_add_admin(new_admin)
        await upd.message.reply_text(f"✅ Successfully added <code>{new_admin}</code> as admin.", parse_mode=ParseMode.HTML)
    except ValueError:
        await upd.message.reply_text("❌ Invalid User ID.")


async def cmd_deladmin(upd, ctx):
    if not is_owner(upd.effective_user.id):
        await upd.message.reply_text("⛔ Only the primary owner can remove admins.")
        return
    if not ctx.args:
        await upd.message.reply_text("⚠️ Usage: <code>/deladmin 123456789</code>", parse_mode=ParseMode.HTML)
        return
    try:
        target = int(ctx.args[0])
        if target == PRIMARY_OWNER_ID:
            await upd.message.reply_text("❌ Cannot remove primary owner.")
            return
        db_remove_admin(target)
        await upd.message.reply_text(f"✅ Successfully removed <code>{target}</code> from admins.", parse_mode=ParseMode.HTML)
    except ValueError:
        await upd.message.reply_text("❌ Invalid User ID.")


async def cmd_setchannel(upd, ctx):
    if not is_owner(upd.effective_user.id):
        await upd.message.reply_text("⛔ Only primary owner can modify channel link.")
        return
    if not ctx.args:
        await upd.message.reply_text("⚠️ Usage: <code>/setchannel @YourChannel</code>", parse_mode=ParseMode.HTML)
        return
    new_ch = ctx.args[0]
    set_channel_link(new_ch)
    await upd.message.reply_text(f"✅ Channel link updated to: <b>{new_ch}</b>", parse_mode=ParseMode.HTML)


async def cmd_broadcast(upd, ctx):
    if not is_admin(upd.effective_user.id):
        await upd.message.reply_text("⛔ Access denied.")
        return
    text_to_send = " ".join(ctx.args)
    if not text_to_send and not upd.message.reply_to_message:
        await upd.message.reply_text("⚠️ Usage: <code>/broadcast Your message here</code>", parse_mode=ParseMode.HTML)
        return

    status_msg = await upd.message.reply_text("🚀 Broadcasting message...")
    stats = await asyncio.to_thread(db_admin_stats)
    users = stats["users"]
    
    success_count = 0
    fail_count = 0
    
    for u in users:
        uid = u["uid"]
        try:
            if upd.message.reply_to_message:
                await ctx.bot.copy_message(chat_id=uid, from_chat_id=upd.chat.id, message_id=upd.message.reply_to_message.message_id)
            else:
                await ctx.bot.send_message(chat_id=uid, text=text_to_send, parse_mode=ParseMode.HTML)
            success_count += 1
            await asyncio.sleep(0.05) # Rate limiting safeguard
        except Exception:
            fail_count += 1

    await safe_edit(status_msg, f"📢 <b>Broadcast Completed!</b>\n\n✅ Success: {success_count}\n❌ Failed: {fail_count}", parse_mode=ParseMode.HTML)


# ══════════════════════════════════════════════════════════════
#  📄  DOCUMENT & MESSAGE HANDLERS
# ══════════════════════════════════════════════════════════════
async def on_doc(upd, ctx):
    u = upd.effective_user
    uid = u.id
    doc = upd.message.document
    fn = doc.file_name or "unknown"

    ok, wait = rate_ok(uid)
    if not ok:
        await upd.message.reply_text(f"⏳ Please wait {wait}s before sending another config.")
        return

    status = await upd.message.reply_text("🔍 <b>Decrypting and unlocking config...</b>", parse_mode=ParseMode.HTML)
    try:
        tf = await ctx.bot.get_file(doc.file_id)
        fb = bytes(await tf.download_as_bytearray())
        label, decoded = await asyncio.to_thread(detect_and_decode, fb, fn)

        if not decoded:
            await asyncio.to_thread(db_log, uid, fn, Path(fn).suffix.lstrip("."), "unknown", False)
            await safe_edit(status, "❌ <b>DECRYPT FAILED</b>\n\n⚠️ Unsupported or corrupted file format.", parse_mode=ParseMode.HTML)
            return

        ext = Path(fn).suffix.lstrip(".").lower()
        unlocked = False
        if ext == "hc":
            with contextlib.suppress(Exception):
                decoded = json.dumps(unlock_hc(fb), indent=2, ensure_ascii=False)
                unlocked = True

        await asyncio.to_thread(db_log, uid, fn, ext, label, True, unlocked)

        msg = build_config_message(decoded, label)
        sm = extract_fields(decoded)
        kb, uid_key = build_copy_buttons(decoded, sm)
        _COPY_STORE[uid_key] = {"full": decoded, "link": build_vmess_link(decoded) or ""}

        with contextlib.suppress(Exception):
            await status.delete()

        await upd.message.reply_text(msg, reply_markup=kb, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception as e:
        logger.exception("decode error")
        await safe_edit(status, f"⚠️ Error processing file: <code>{esc(e)}</code>", parse_mode=ParseMode.HTML)


async def on_text(upd, ctx):
    t = (upd.message.text or "").strip()
    if t in ("👤  Profile", "📊  Stats"): await cmd_stats(upd, ctx); return
    if t == "🗂️  Formats":                  await cmd_formats(upd, ctx); return
    if t == "ℹ️  Help":                     await cmd_help(upd, ctx); return
    if t == "📞  Support":                  await cmd_contact(upd, ctx); return
    if t == "📢  Channel":                  await upd.message.reply_text(f"📢 Official Channel: <b>{get_channel_link()}</b>", parse_mode=ParseMode.HTML); return
    if t == "🛡️  Admin Panel":              await cmd_admin(upd, ctx); return

    if len(t) > 30:
        uid = upd.effective_user.id
        ok, wait = rate_ok(uid)
        if not ok:
            await upd.message.reply_text(f"⏳ Wait {wait}s")
            return
        status = await upd.message.reply_text("🔍 Decrypting raw config...")
        label, decoded = await asyncio.to_thread(detect_and_decode, t.encode("utf-8"), "")
        if decoded:
            await asyncio.to_thread(db_log, uid, "text", "txt", label, True)
            msg = build_config_message(decoded, label)
            sm = extract_fields(decoded)
            kb, uid_key = build_copy_buttons(decoded, sm)
            _COPY_STORE[uid_key] = {"full": decoded, "link": build_vmess_link(decoded) or ""}
            with contextlib.suppress(Exception): await status.delete()
            await upd.message.reply_text(msg, reply_markup=kb, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
            return
        else:
            await safe_edit(status, "❌ Could not decode text config.")
            return

    await upd.message.reply_text("📎 Please send a VPN configuration document or text block.", parse_mode=ParseMode.HTML)


async def on_cb(upd, ctx):
    q = upd.callback_query
    await q.answer()
    d = q.data
    uid = q.from_user.id
    if "_" not in d: return
    action, key_s = d.rsplit("_", 1)
    with contextlib.suppress(ValueError):
        key = int(key_s)
        entry = _COPY_STORE.get(key)
        if not entry:
            await q.answer("⚠️ Expired. Send file again.", show_alert=True)
            return
        if action == "cplink":
            v = entry["link"] or "N/A"
            await ctx.bot.send_message(uid, f"📋 <b>V2Ray Link</b>\n\n<code>{esc(v)}</code>", parse_mode=ParseMode.HTML)
            await q.answer("Sent V2Ray link!")


# ══════════════════════════════════════════════════════════════
#  🌐  FLASK KEEP-ALIVE SERVER (PORT 8080)
# ══════════════════════════════════════════════════════════════
def run_flask():
    if not HAVE_FLASK: return
    app_flask = Flask("KeepAlive")

    @app_flask.route("/")
    @app_flask.route("/health")
    @app_flask.route("/ping")
    def index():
        return f"{BRAND} v{BRAND_VER} is active and running perfectly!", 200

    try:
        app_flask.run(host="0.0.0.0", port=8080, debug=False, use_reloader=False)
    except Exception as e:
        logger.warning("Flask server warning: %s", e)


# ══════════════════════════════════════════════════════════════
#  🚀  STARTUP & MAIN
# ══════════════════════════════════════════════════════════════
async def on_startup(app):
    await asyncio.to_thread(db_init)
    with contextlib.suppress(Exception):
        await app.bot.delete_webhook(drop_pending_updates=True)
    logger.info("=" * 60)
    logger.info("  💎 %s v%s Started Successfully", BRAND, BRAND_VER)
    logger.info("  Primary Owner ID: %s (%s)", PRIMARY_OWNER_ID, OWNER_USERNAME)
    logger.info("=" * 60)


def main():
    # Start Flask server in background thread for Render/Koyeb keep-alive
    if HAVE_FLASK:
        t = threading.Thread(target=run_flask, daemon=True)
        t.start()
        logger.info("🌐 Flask keep-alive server started on port 8080")

    app = (Application.builder()
           .token(BOT_TOKEN)
           .post_init(on_startup)
           .build())

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("formats", cmd_formats))
    app.add_handler(CommandHandler("contact", cmd_contact))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("addadmin", cmd_addadmin))
    app.add_handler(CommandHandler("deladmin", cmd_deladmin))
    app.add_handler(CommandHandler("setchannel", cmd_setchannel))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(CallbackQueryHandler(on_cb))
    app.add_handler(MessageHandler(filters.Document.ALL, on_doc))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    print(f"✅ {BRAND} v{BRAND_VER} is running polling loop...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
