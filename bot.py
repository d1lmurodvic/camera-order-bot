import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters, ConversationHandler

logging.basicConfig(level=logging.INFO)

TOKEN = "8762636466:AAHzGbWOV2LhzbcKwfknLqMzELMwc848zXU"

ADMIN_ID = None
orders = {}
order_counter = [0]
workers = {}

PHONE, DESC = range(2)
WORKER_PHONE = 0

def main_menu_admin():
    keyboard = [
        [KeyboardButton("➕ Zakaz qo'shish")],
        [KeyboardButton("📋 Barcha zakazlar"), KeyboardButton("📊 Statistika")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def main_menu_worker():
    keyboard = [
        [KeyboardButton("📋 Mavjud zakazlar")],
        [KeyboardButton("🔧 Mening zakazlarim")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ADMIN_ID
    user_id = update.effective_user.id
    name = update.effective_user.first_name

    if ADMIN_ID is None:
        ADMIN_ID = user_id
        await update.message.reply_text(
            f"👋 Xush kelibsiz, *{name}*!\n\n"
            f"🔑 Siz *Admin* sifatida ro'yxatdan o'tdingiz.\n\n"
            f"Quyidagi tugmalardan foydalaning 👇",
            parse_mode="Markdown",
            reply_markup=main_menu_admin()
        )
    elif user_id == ADMIN_ID:
        await update.message.reply_text(
            f"👋 Xush kelibsiz, *Admin*!\n\nQuyidagi tugmalardan foydalaning 👇",
            parse_mode="Markdown",
            reply_markup=main_menu_admin()
        )
    elif user_id in workers:
        await update.message.reply_text(
            f"👷 Xush kelibsiz, *{name}*!\n\nQuyidagi tugmalardan foydalaning 👇",
            parse_mode="Markdown",
            reply_markup=main_menu_worker()
        )
    else:
        keyboard = [[KeyboardButton("📱 Telefon raqamni yuborish", request_contact=True)]]
        markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        await update.message.reply_text(
            f"👋 Salom, *{name}*!\n\n"
            f"📱 Ro'yxatdan o'tish uchun telefon raqamingizni yuboring:",
            parse_mode="Markdown",
            reply_markup=markup
        )

async def register_worker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact = update.message.contact
    user_id = update.effective_user.id
    name = update.effective_user.first_name
    phone = contact.phone_number

    workers[user_id] = {
        'name': name,
        'phone': phone
    }

    await update.message.reply_text(
        f"✅ Ro'yxatdan o'tdingiz!\n\n"
        f"👷 Ism: *{name}*\n"
        f"📞 Raqam: `{phone}`\n\n"
        f"Endi zakazlarni ko'rishingiz mumkin 👇",
        parse_mode="Markdown",
        reply_markup=main_menu_worker()
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    if text == "➕ Zakaz qo'shish" and user_id == ADMIN_ID:
        await update.message.reply_text(
            "📞 *Mijozning telefon raqamini kiriting:*\n\nMasalan: +998901234567",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove()
        )
        return PHONE

    elif text == "📋 Barcha zakazlar" and user_id == ADMIN_ID:
        await show_all_orders_admin(update, context)

    elif text == "📊 Statistika" and user_id == ADMIN_ID:
        await show_stats(update, context)

    elif text == "📋 Mavjud zakazlar" and user_id in workers:
        await show_available_orders(update, context)

    elif text == "🔧 Mening zakazlarim" and user_id in workers:
        await show_my_orders(update, context)

    else:
        await update.message.reply_text("❓ Noma'lum buyruq. /start ni bosing.")

async def get_phone_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['phone'] = update.message.text
    await update.message.reply_text(
        "📝 *Tavsif kiriting:*\n\n"
        "_(Manzil, kameralar soni, ish turi va boshqa ma'lumotlar)_",
        parse_mode="Markdown"
    )
    return DESC

async def get_desc_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    order_counter[0] += 1
    oid = order_counter[0]
    orders[oid] = {
        'phone': context.user_data['phone'],
        'desc': update.message.text,
        'worker_id': None,
        'worker_name': None
    }
    await update.message.reply_text(
        f"✅ *Zakaz #{oid} qo'shildi!*\n\n"
        f"📞 Raqam: `{context.user_data['phone']}`\n"
        f"📝 Tavsif: {update.message.text}",
        parse_mode="Markdown",
        reply_markup=main_menu_admin()
    )
    return ConversationHandler.END

async def show_all_orders_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not orders:
        await update.message.reply_text("📭 Hozircha zakaz yo'q.", reply_markup=main_menu_admin())
        return
    for oid, o in orders.items():
        status = f"👷 {o['worker_name']}" if o['worker_id'] else "⏳ Kutilmoqda"
        await update.message.reply_text(
            f"📦 *Zakaz #{oid}*\n"
            f"📞 Mijoz: `{o['phone']}`\n"
            f"📝 {o['desc']}\n"
            f"📌 Holat: {status}",
            parse_mode="Markdown"
        )

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total = len(orders)
    active = sum(1 for o in orders.values() if o['worker_id'])
    waiting = total - active
    await update.message.reply_text(
        f"📊 *Statistika*\n\n"
        f"📦 Jami zakazlar: *{total}*\n"
        f"🔧 Ishda: *{active}*\n"
        f"⏳ Kutilmoqda: *{waiting}*\n"
        f"👷 Ishchilar: *{len(workers)}*",
        parse_mode="Markdown",
        reply_markup=main_menu_admin()
    )

async def show_available_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    available = {oid: o for oid, o in orders.items() if not o['worker_id']}
    if not available:
        await update.message.reply_text("📭 Hozircha bo'sh zakaz yo'q.", reply_markup=main_menu_worker())
        return
    for oid, o in available.items():
        keyboard = [[InlineKeyboardButton("✅ Olish", callback_data=f"take_{oid}")]]
        await update.message.reply_text(
            f"📦 *Zakaz #{oid}*\n"
            f"📞 Mijoz: `{o['phone']}`\n"
            f"📝 {o['desc']}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def show_my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    my = {oid: o for oid, o in orders.items() if o['worker_id'] == user_id}
    if not my:
        await update.message.reply_text("📭 Sizda hozircha zakaz yo'q.", reply_markup=main_menu_worker())
        return
    for oid, o in my.items():
        keyboard = [[InlineKeyboardButton("🏁 Yakunlash", callback_data=f"done_{oid}")]]
        await update.message.reply_text(
            f"🔧 *Zakaz #{oid}*\n"
            f"📞 Mijoz: `{o['phone']}`\n"
            f"📝 {o['desc']}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def take_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    oid = int(query.data.split("_")[1])
    user_id = query.from_user.id
    name = query.from_user.first_name

    if oid not in orders:
        await query.edit_message_text("❌ Zakaz topilmadi.")
        return
    if orders[oid]['worker_id']:
        await query.edit_message_text("⚠️ Bu zakaz allaqachon olingan!")
        return

    orders[oid]['worker_id'] = user_id
    orders[oid]['worker_name'] = name

    keyboard = [[InlineKeyboardButton("🏁 Yakunlash", callback_data=f"done_{oid}")]]
    await query.edit_message_text(
        f"✅ *Zakaz #{oid} siz oldingiz!*\n\n"
        f"📞 Mijoz: `{orders[oid]['phone']}`\n"
        f"📝 {orders[oid]['desc']}\n\n"
        f"⚡ Ish yakunlangach tugmani bosing:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def done_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    oid = int(query.data.split("_")[1])

    if oid in orders:
        phone = orders[oid]['phone']
        desc = orders[oid]['desc']
        del orders[oid]
        await query.edit_message_text(
            f"🎉 *Zakaz #{oid} yakunlandi!*\n\n"
            f"📞 Mijoz: `{phone}`\n"
            f"📝 {desc}\n\n"
            f"✅ Ajoyib ish!",
            parse_mode="Markdown"
        )
    else:
        await query.edit_message_text("❌ Zakaz topilmadi.")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Bekor qilindi.", reply_markup=main_menu_admin())
    return ConversationHandler.END

def main():
    app = Application.builder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➕ Zakaz qo'shish$"), handle_message)],
        states={
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone_admin)],
            DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_desc_admin)],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.CONTACT, register_worker))
    app.add_handler(conv)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(take_order, pattern="^take_"))
    app.add_handler(CallbackQueryHandler(done_order, pattern="^done_"))

    app.run_polling()

if __name__ == "__main__":
    main()
