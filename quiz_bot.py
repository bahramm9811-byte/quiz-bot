import os
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

BOT_TOKEN = os.environ.get("BOT_TOKEN")
QUESTIONS_FILE = os.path.join(os.path.dirname(__file__), "questions.txt")


def load_questions(filepath: str) -> list[dict]:
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
    current_q = None
    current_a = None

    def strip_prefix(line: str, pattern: re.Pattern) -> str:
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


try:
    qa_list = load_questions(QUESTIONS_FILE)
    print(f"✅ {len(qa_list)} سوال بارگذاری شد.")
except FileNotFoundError:
    print(f"⚠️  فایل {QUESTIONS_FILE} پیدا نشد.")
    qa_list = [
        {"q": "سوال نمونه: این یک سوال آزمایشی است.", "a": "این یک پاسخ آزمایشی است."},
    ]

# user_data[user_id] = {"index": int}
user_data: dict = {}


def escape_md2(text: str) -> str:
    """کاراکترهای خاص MarkdownV2 رو escape می‌کنه"""
    special = r'_*[]()~`>#+-=|{}.!'
    return re.sub(r'([' + re.escape(special) + r'])', r'\\\1', text)


def get_keyboard(index: int) -> InlineKeyboardMarkup:
    """کیبورد فقط با دکمه سوال بعدی"""
    buttons = [[InlineKeyboardButton("➡️ سوال بعدی", callback_data=f"next:{index}")]]
    return InlineKeyboardMarkup(buttons)


def format_question(index: int) -> str:
    """سوال رو با پاسخ spoiler فرمت می‌کنه"""
    item = qa_list[index]
    total = len(qa_list)

    q_text = escape_md2(item['q'])
    a_text = escape_md2(item['a'])

    text = (
        f"📚 *{escape_md2(str(index + 1))} از {escape_md2(str(total))}*\n\n"
        f"❓ {q_text}\n\n"
        f"💡 *نکته:* ||{a_text}||"
    )
    return text


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_data[user_id] = {"index": 0}
    await update.message.reply_text(
        format_question(0),
        parse_mode="MarkdownV2",
        reply_markup=get_keyboard(0),
    )


async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_data[user_id] = {"index": 0}
    await update.message.reply_text(
        "🔄 *از ابتدا شروع شد\\!*\n\n" + format_question(0),
        parse_mode="MarkdownV2",
        reply_markup=get_keyboard(0),
    )


async def reload_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
        user_data[user_id] = {"index": 0}

    action = query.data

    if action.startswith("next:"):
        # index رو از callback_data می‌خونیم تا مطمئن باشیم درسته
        current_index = int(action.split(":")[1])
        next_index = current_index + 1

        if next_index >= len(qa_list):
            # دکمه سوال قبلی رو غیرفعال کن (فقط متن عوض کن، پیام جدید نفرست)
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(
                f"🎉 *تبریک\\!*\nهمه {escape_md2(str(len(qa_list)))} سوال تموم شد\\!\n\nبرای شروع دوباره /restart بزن\\.",
                parse_mode="MarkdownV2",
            )
            return

        user_data[user_id]["index"] = next_index

        # دکمه سوال قبلی رو حذف کن (نشون بده دیگه فعال نیست)
        await query.edit_message_reply_markup(reply_markup=None)

        # پیام جدید بفرست (روی هم انباشته می‌شن)
        await query.message.reply_text(
            format_question(next_index),
            parse_mode="MarkdownV2",
            reply_markup=get_keyboard(next_index),
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
