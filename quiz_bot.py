import os
import re
import asyncio
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

BOT_TOKEN = os.environ.get("BOT_TOKEN")
QUESTIONS_DIR = Path(__file__).parent / "questions"


# ─── بارگذاری سوالات ───────────────────────────────────────────────

def load_questions(filepath: Path) -> list[dict]:
    Q_PATTERN = re.compile(
        r'^\*{0,2}(?:'
        r'(?:سوال|پرسش|س)[\s\d\u06F0-\u06F9]*[:.\-–]'
        r'|[\d\u06F0-\u06F9]+[\s]*[.\-–\)]\s*'
        r')\*{0,2}',
        re.UNICODE
    )
    A_PATTERN = re.compile(
        r'^\*{0,2}(?:جواب|پاسخ|ج|پ)[\s\d\u06F0-\u06F9]*[:.\-–]\*{0,2}',
        re.UNICODE
    )

    qa_list = []
    current_q = current_a = None

    def strip_prefix(line, pattern):
        m = pattern.match(line)
        return line[m.end():].strip() if m else line.strip()

    with open(filepath, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if Q_PATTERN.match(line):
                if current_q and current_a:
                    qa_list.append({"q": current_q, "a": current_a})
                current_q = strip_prefix(line, Q_PATTERN)
                current_a = None
            elif A_PATTERN.match(line):
                current_a = strip_prefix(line, A_PATTERN)
        if current_q and current_a:
            qa_list.append({"q": current_q, "a": current_a})

    return qa_list


def scan_library() -> dict:
    """
    ساختار پوشه questions/ رو اسکن میکنه:
    { "درس": { "فصل": [{q,a}, ...] } }
    """
    lib = {}
    if not QUESTIONS_DIR.exists():
        QUESTIONS_DIR.mkdir(parents=True)
        return lib
    for course_dir in sorted(QUESTIONS_DIR.iterdir()):
        if not course_dir.is_dir():
            continue
        lib[course_dir.name] = {}
        for txt_file in sorted(course_dir.glob("*.txt")):
            try:
                qs = load_questions(txt_file)
                if qs:
                    lib[course_dir.name][txt_file.stem] = qs
            except Exception as e:
                print(f"خطا در {txt_file}: {e}")
    return lib


library: dict = scan_library()
print(f"✅ {len(library)} درس بارگذاری شد.")

user_sessions: dict = {}


# ─── ابزارها ───────────────────────────────────────────────────────

def escape_md2(text: str) -> str:
    return re.sub(r'([_*\[\]()~`>#+=|{}.!\-])', r'\\\1', str(text))


def get_questions(user_id: int) -> list[dict]:
    s = user_sessions.get(user_id, {})
    return library.get(s.get("course", ""), {}).get(s.get("chapter", ""), [])


async def cancel_timer(user_id: int):
    s = user_sessions.get(user_id, {})
    task = s.get("timer_task")
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    if user_id in user_sessions:
        user_sessions[user_id]["timer_task"] = None


def format_question(index: int, qs: list, course: str, chapter: str) -> str:
    item = qs[index]
    return (
        f"📚 *{escape_md2(str(index+1))} از {escape_md2(str(len(qs)))}*"
        f"  •  {escape_md2(course)} / {escape_md2(chapter)}\n\n"
        f"❓ {escape_md2(item['q'])}\n\n"
        f"💡 *نکته:* ||{escape_md2(item['a'])}||"
    )


def nav_keyboard(index: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("➡️ سوال بعدی", callback_data=f"next:{index}"),
        InlineKeyboardButton("↩️ فصل‌ها", callback_data="back_chapter"),
    ]])


# ─── تایمر ۴۰ ثانیه ────────────────────────────────────────────────

async def auto_next_timer(user_id: int, current_index: int, context, chat_id: int):
    await asyncio.sleep(40)
    s = user_sessions.get(user_id)
    if not s or s.get("index") != current_index:
        return
    qs = get_questions(user_id)
    next_index = current_index + 1
    s["timer_task"] = None

    if next_index >= len(qs):
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🎉 *تبریک\\!*\nهمه {escape_md2(str(len(qs)))} سوال تموم شد\\!\n\n/start برای برگشت به منو",
            parse_mode="MarkdownV2"
        )
        return

    s["index"] = next_index
    await context.bot.send_message(
        chat_id=chat_id,
        text=format_question(next_index, qs, s["course"], s["chapter"]),
        parse_mode="MarkdownV2",
        reply_markup=nav_keyboard(next_index),
    )
    task = asyncio.create_task(auto_next_timer(user_id, next_index, context, chat_id))
    s["timer_task"] = task


# ─── دستورات ───────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await cancel_timer(user_id)
    user_sessions[user_id] = {"course": None, "chapter": None, "index": 0, "timer_task": None}
    await show_courses(update, context)


async def show_courses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not library:
        text = "⚠️ هیچ درسی پیدا نشد\\.\nپوشه `questions/` رو بررسی کن\\."
        if update.message:
            await update.message.reply_text(text, parse_mode="MarkdownV2")
        else:
            await update.callback_query.edit_message_text(text, parse_mode="MarkdownV2")
        return

    buttons = [[InlineKeyboardButton(f"📖 {c}", callback_data=f"course:{c}")] for c in library]
    markup = InlineKeyboardMarkup(buttons)
    text = "📚 *یه درس انتخاب کن:*"
    if update.message:
        await update.message.reply_text(text, parse_mode="MarkdownV2", reply_markup=markup)
    else:
        await update.callback_query.edit_message_text(text, parse_mode="MarkdownV2", reply_markup=markup)


async def reload_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global library
    library = scan_library()
    total_ch = sum(len(v) for v in library.values())
    await update.message.reply_text(
        f"✅ {escape_md2(str(len(library)))} درس و {escape_md2(str(total_ch))} فصل دوباره بارگذاری شد\\.",
        parse_mode="MarkdownV2"
    )


# ─── مدیریت دکمه‌ها ────────────────────────────────────────────────

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    data = query.data

    if user_id not in user_sessions:
        user_sessions[user_id] = {"course": None, "chapter": None, "index": 0, "timer_task": None}

    s = user_sessions[user_id]

    # ── انتخاب درس ──
    if data.startswith("course:"):
        await cancel_timer(user_id)
        course = data[7:]
        s["course"] = course
        s["chapter"] = None
        chapters = library.get(course, {})
        buttons = []
        for ch, qs in chapters.items():
            buttons.append([InlineKeyboardButton(
                f"📗 {ch}  ({len(qs)} سوال)", callback_data=f"chapter:{ch}"
            )])
        buttons.append([InlineKeyboardButton("▶️ پخش خودکار همه فصل‌ها", callback_data="autoall")])
        buttons.append([InlineKeyboardButton("◀️ بازگشت به درس‌ها", callback_data="back_courses")])
        await query.edit_message_text(
            f"📖 *{escape_md2(course)}*\n\nیه فصل انتخاب کن:",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    # ── انتخاب فصل ──
    elif data.startswith("chapter:"):
        await cancel_timer(user_id)
        chapter = data[8:]
        s["chapter"] = chapter
        s["index"] = 0
        qs = get_questions(user_id)
        await query.edit_message_text(
            format_question(0, qs, s["course"], chapter),
            parse_mode="MarkdownV2",
            reply_markup=nav_keyboard(0),
        )
        task = asyncio.create_task(auto_next_timer(user_id, 0, context, chat_id))
        s["timer_task"] = task

    # ── سوال بعدی (دستی) ──
    elif data.startswith("next:"):
        await cancel_timer(user_id)
        current_index = int(data.split(":")[1])
        qs = get_questions(user_id)
        next_index = current_index + 1

        await query.edit_message_reply_markup(reply_markup=None)

        if next_index >= len(qs):
            await query.message.reply_text(
                f"🎉 *تبریک\\!*\nهمه {escape_md2(str(len(qs)))} سوال تموم شد\\!\n\n/start برای برگشت به منو",
                parse_mode="MarkdownV2"
            )
            return

        s["index"] = next_index
        await query.message.reply_text(
            format_question(next_index, qs, s["course"], s["chapter"]),
            parse_mode="MarkdownV2",
            reply_markup=nav_keyboard(next_index),
        )
        task = asyncio.create_task(auto_next_timer(user_id, next_index, context, chat_id))
        s["timer_task"] = task

    # ── پخش خودکار همه فصل‌ها ──
    elif data == "autoall":
        await cancel_timer(user_id)
        course = s.get("course")
        if not course:
            return
        all_qs = []
        for ch, qs in library[course].items():
            for q in qs:
                all_qs.append({**q, "_ch": ch})

        total = len(all_qs)
        await query.edit_message_text(
            f"▶️ *پخش خودکار*  •  {escape_md2(course)}\n"
            f"{escape_md2(str(total))} سوال  •  هر ۱ ثانیه",
            parse_mode="MarkdownV2"
        )

        async def send_all():
            for i, item in enumerate(all_qs):
                text = (
                    f"📚 *{escape_md2(str(i+1))} از {escape_md2(str(total))}*"
                    f"  •  {escape_md2(item['_ch'])}\n\n"
                    f"❓ {escape_md2(item['q'])}\n\n"
                    f"💡 *نکته:* ||{escape_md2(item['a'])}||"
                )
                await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="MarkdownV2")
                await asyncio.sleep(1)
            await context.bot.send_message(
                chat_id=chat_id,
                text="✅ *پخش تموم شد\\!*\n\n/start برای برگشت به منو",
                parse_mode="MarkdownV2"
            )

        asyncio.create_task(send_all())

    # ── برگشت به فصل‌ها ──
    elif data == "back_chapter":
        await cancel_timer(user_id)
        course = s.get("course")
        if not course:
            await show_courses(update, context)
            return
        chapters = library.get(course, {})
        buttons = []
        for ch, qs in chapters.items():
            buttons.append([InlineKeyboardButton(
                f"📗 {ch}  ({len(qs)} سوال)", callback_data=f"chapter:{ch}"
            )])
        buttons.append([InlineKeyboardButton("▶️ پخش خودکار همه فصل‌ها", callback_data="autoall")])
        buttons.append([InlineKeyboardButton("◀️ بازگشت به درس‌ها", callback_data="back_courses")])
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            f"📖 *{escape_md2(course)}*\n\nیه فصل انتخاب کن:",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    # ── برگشت به درس‌ها ──
    elif data == "back_courses":
        await cancel_timer(user_id)
        await show_courses(update, context)


# ─── اجرا ──────────────────────────────────────────────────────────

def main():
    if not BOT_TOKEN:
        raise ValueError("متغیر محیطی BOT_TOKEN تنظیم نشده!")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reload", reload_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    print("بات در حال اجرا است...")
    app.run_polling()


if __name__ == "__main__":
    main()
