import os
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

BOT_TOKEN = os.environ.get("BOT_TOKEN")
QUESTIONS_FILE = os.path.join(os.path.dirname(__file__), "questions.txt")


def load_questions(filepath: str) -> list[dict]:
    """
    فایل متنی با فرمت زیر رو می‌خونه:
        سوال: / پرسش: / س: / سوال ۱: / ۱- / 1-  → شروع سوال
        جواب: / پاسخ: / ج: / پ:               → شروع جواب
    شماره‌گذاری و مترادف‌ها همه قبوله.
    خطوط خالی بین سوال‌ها مجازه.
    """
    # پترن تشخیص شروع سوال
    Q_PATTERN = re.compile(
        r'^(?:'
        r'(?:سوال|پرسش|س)[\s\d\u06F0-\u06F9]*[:.\-–]'  # سوال: / پرسش: / س: / سوال ۱:
        r'|[\d\u06F0-\u06F9]+[\s]*[.\-–\)]\s*'           # 1- / ۱. / ۱) 
        r')',
        re.UNICODE
    )
    # پترن تشخیص شروع جواب
    A_PATTERN = re.compile(
        r'^(?:جواب|پاسخ|ج|پ)[\s\d\u06F0-\u06F9]*[:.\-–]',
        re.UNICODE
    )

    qa_list = []
    current_q = None
    current_a = None

    def strip_prefix(line: str, pattern: re.Pattern) -> str:
        """پیشوند کلیدواژه رو حذف می‌کنه"""
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


# بارگذاری سوالات موقع اجرا
try:
    qa_list = load_questions(QUESTIONS_FILE)
    print(f"✅ {len(qa_list)} سوال بارگذاری شد.")
except FileNotFoundError:
    print(f"⚠️  فایل {QUESTIONS_FILE} پیدا نشد. از لیست پیش‌فرض استفاده می‌شود.")
    qa_list = [
        {"q": "سوال نمونه: این یک سوال آزمایشی است.", "a": "این یک پاسخ آزمایشی است."},
    ]

# user_data[user_id] = {"index": int, "answer_shown": bool}
user_data: dict = {}


def get_keyboard(answer_shown: bool) -> InlineKeyboardMarkup:
    if answer_shown:
        buttons = [[InlineKeyboardButton("➡️ سوال بعدی", callback_data="next")]]
    else:
        buttons = [
            [
                InlineKeyboardButton("💡 نمایش پاسخ", callback_data="show_answer"),
                InlineKeyboardButton("➡️ سوال بعدی", callback_data="next"),
            ]
        ]
    return InlineKeyboardMarkup(buttons)


def format_question(index: int, show_answer: bool = False) -> str:
    item = qa_list[index]
    total = len(qa_list)
    text = f"📚 *{index + 1} از {total}*\n\n{item['q']}"
    if show_answer:
        text += f"\n\n✅ *پاسخ:* {item['a']}"
    return text


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_data[user_id] = {"index": 0, "answer_shown": False}
    await update.message.reply_text(
        format_question(0),
        parse_mode="Markdown",
        reply_markup=get_keyboard(False),
    )


async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_data[user_id] = {"index": 0, "answer_shown": False}
    await update.message.reply_text(
        "🔄 از ابتدا شروع شد!\n\n" + format_question(0),
        parse_mode="Markdown",
        reply_markup=get_keyboard(False),
    )


async def reload_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دستور /reload — سوالات رو دوباره از فایل می‌خونه بدون نیاز به ریستارت بات"""
    global qa_list
    try:
        qa_list = load_questions(QUESTIONS_FILE)
        await update.message.reply_text(f"✅ {len(qa_list)} سوال دوباره بارگذاری شد.")
    except Exception as e:
        await update.message.reply_text(f"❌ خطا: {e}")


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if user_id not in user_data:
        user_data[user_id] = {"index": 0, "answer_shown": False}

    state = user_data[user_id]
    action = query.data

    if action == "show_answer":
        state["answer_shown"] = True
        await query.edit_message_text(
            format_question(state["index"], show_answer=True),
            parse_mode="Markdown",
            reply_markup=get_keyboard(True),
        )

    elif action == "next":
        next_index = state["index"] + 1
        if next_index >= len(qa_list):
            await query.edit_message_text(
                f"🎉 *تبریک!*\nهمه {len(qa_list)} سوال تموم شد.\n\nبرای شروع دوباره /restart بزن.",
                parse_mode="Markdown",
            )
            return
        state["index"] = next_index
        state["answer_shown"] = False
        await query.edit_message_text(
            format_question(next_index),
            parse_mode="Markdown",
            reply_markup=get_keyboard(False),
        )


def main() -> None:
    if not BOT_TOKEN:
        raise ValueError("متغیر محیطی BOT_TOKEN تنظیم نشده!")

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("restart", restart))
    app.add_handler(CommandHandler("reload", reload_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("بات در حال اجرا است...")
    app.run_polling()


if __name__ == "__main__":
    main()
