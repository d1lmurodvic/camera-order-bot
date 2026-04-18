import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters, ConversationHandler

logging.basicConfig(level=logging.INFO)

TOKEN = "8762636466:AAHzGbWOV2LhzbcKwfknLqMzELMwc848zXU"
ADMIN_ID = None  # Keyin to'ldiramiz

orders = {}
order_counter = [0]

PHONE, DESC = range(2)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Xush kelibsiz!\n\n"
        "📋 /orders - Zakazlarni ko'rish\n"
        "➕ /add - Zakaz qo'shish (faqat admin)"
    )

async def add_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ADMIN_ID
    if ADMIN_ID is None:
        ADMIN_ID = update.effective_user.id
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Siz admin emassiz!")
        return ConversationHandler.END
    await update.message.reply_text("📞 Mijoz telefon raqamini kiriting:")
    return PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['phone'] = update.message.text
    await update.message.reply_text("📝 Tavsif kiriting (manzil, kameralar soni va h.k):")
    return DESC

async def get_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    order_counter[0] += 1
    oid = order_counter[0]
    orders[oid] = {
        'phone': context.user_data['phone'],
        'desc': update.message.text,
        'worker': None
    }
    await update.message.reply_text(f"✅ Zakaz #{oid} qo'shildi!")
    return ConversationHandler.END

async def show_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not orders:
        await update.message.reply_text("📭 Hozircha zakaz yo'q.")
        return
    for oid, o in orders.items():
        if o['worker']:
            continue
        keyboard = [[InlineKeyboardButton("✅ Olish", callback_data=f"take_{oid}")]]
        await update.message.reply_text(
            f"📦 Zakaz #{oid}\n📞 {o['phone']}\n📝 {o['desc']}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def take_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    oid = int(query.data.split("_")[1])
    if oid not in orders:
        await query.edit_message_text("❌ Zakaz topilmadi.")
        return
    orders[oid]['worker'] = query.from_user.id
    keyboard = [[InlineKeyboardButton("🏁 Yakunlash", callback_data=f"done_{oid}")]]
    await query.edit_message_text(
        f"📦 Zakaz #{oid}\n📞 {orders[oid]['phone']}\n📝 {orders[oid]['desc']}\n\n👷 Siz oldingiz!",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def done_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    oid = int(query.data.split("_")[1])
    if oid in orders:
        del orders[oid]
    await query.edit_message_text(f"🎉 Zakaz #{oid} yakunlandi va o'chirildi!")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Bekor qilindi.")
    return ConversationHandler.END

def main():
    app = Application.builder().token(TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("add", add_order)],
        states={
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)],
            DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_desc)],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("orders", show_orders))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(take_order, pattern="^take_"))
    app.add_handler(CallbackQueryHandler(done_order, pattern="^done_"))
    app.run_polling()

if __name__ == "__main__":
    main()
