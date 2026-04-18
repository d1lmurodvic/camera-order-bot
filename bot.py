import logging
import os
import asyncpg
from datetime import datetime
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters,
    ConversationHandler
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(level=logging.INFO)

TOKEN = os.environ["BOT_TOKEN"]
DATABASE_URL = os.environ["DATABASE_URL"]
ADMIN_PHONE = "998770902226"

# Global
db_pool = None
admin_telegram_id = None
scheduler = AsyncIOScheduler()

# Conversation states
(PHONE, ADDRESS, DESC, DEADLINE,
 ADD_WORKER_ID, ADD_WORKER_ROLE,
 COMPLETE_PHOTO) = range(7)


# ─── DATABASE ───────────────────────────────────────

async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL)
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS workers (
                id SERIAL PRIMARY KEY,
                telegram_id BIGINT UNIQUE NOT NULL,
                name TEXT,
                phone TEXT,
                role TEXT DEFAULT 'worker',
                rating FLOAT DEFAULT 0,
                joined_at TIMESTAMP DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS orders (
                id SERIAL PRIMARY KEY,
                phone TEXT NOT NULL,
                address TEXT NOT NULL,
                description TEXT NOT NULL,
                deadline TEXT,
                worker_id BIGINT,
                status TEXT DEFAULT 'waiting',
                created_at TIMESTAMP DEFAULT NOW(),
                completed_at TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS completions (
                id SERIAL PRIMARY KEY,
                order_id INT,
                worker_id BIGINT,
                photo_file_id TEXT,
                completed_at TIMESTAMP DEFAULT NOW()
            );
        """)


# ─── KEYBOARDS ──────────────────────────────────────

def admin_menu():
    return ReplyKeyboardMarkup([
        [KeyboardButton("➕ Zakaz qo'shish")],
        [KeyboardButton("📋 Barcha zakazlar"), KeyboardButton("📊 Statistika")],
        [KeyboardButton("👷 Ishchilar"), KeyboardButton("➕ Ishchi qo'shish")]
    ], resize_keyboard=True)

def worker_menu():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📋 Mavjud zakazlar")],
        [KeyboardButton("🔧 Mening zakazlarim")]
    ], resize_keyboard=True)

def senior_menu():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📋 Mavjud zakazlar")],
        [KeyboardButton("🔧 Mening zakazlarim")],
        [KeyboardButton("👷 Ishchilar ro'yxati")]
    ], resize_keyboard=True)


# ─── HELPERS ────────────────────────────────────────

async def get_worker(telegram_id):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM workers WHERE telegram_id=$1", telegram_id
        )

async def get_all_workers():
    async with db_pool.acquire() as conn:
        return await conn.fetch("SELECT * FROM workers")

async def notify_all_workers(context, message):
    workers = await get_all_workers()
    for w in workers:
        try:
            await context.bot.send_message(w['telegram_id'], message, parse_mode="Markdown")
        except:
            pass

async def get_menu(worker):
    if worker['role'] == 'senior_worker':
        return senior_menu()
    return worker_menu()


# ─── START ──────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global admin_telegram_id
    user_id = update.effective_user.id
    name = update.effective_user.first_name

    # Admin tekshirish - kontakt yuborishi kerak
    worker = await get_worker(user_id)

    if worker:
        if worker['role'] == 'admin':
            admin_telegram_id = user_id
            await update.message.reply_text(
                f"👋 Xush kelibsiz, *Admin {name}*!\n\nQuyidagi tugmalardan foydalaning 👇",
                parse_mode="Markdown",
                reply_markup=admin_menu()
            )
        else:
            menu = await get_menu(worker)
            await update.message.reply_text(
                f"👋 Xush kelibsiz, *{name}*!\n\n"
                f"👷 Rolingiz: *{worker['role']}*\n\n"
                f"Quyidagi tugmalardan foydalaning 👇",
                parse_mode="Markdown",
                reply_markup=menu
            )
    else:
        # Ro'yxatdan o'tmagan — kontakt so'raymiz
        keyboard = [[KeyboardButton("📱 Telefon raqamni yuborish", request_contact=True)]]
        await update.message.reply_text(
            f"👋 Salom, *{name}*!\n\n"
            f"📱 Tasdiqlash uchun telefon raqamingizni yuboring:",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        )


# ─── KONTAKT QABUL ──────────────────────────────────

async def contact_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global admin_telegram_id
    contact = update.message.contact
    user_id = update.effective_user.id
    name = update.effective_user.first_name
    phone = contact.phone_number.replace("+", "")

    # Admin tekshirish
    if phone == ADMIN_PHONE:
        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO workers (telegram_id, name, phone, role)
                VALUES ($1, $2, $3, 'admin')
                ON CONFLICT (telegram_id) DO UPDATE SET role='admin'
            """, user_id, name, phone)
        admin_telegram_id = user_id
        await update.message.reply_text(
            f"🔑 *Siz Admin sifatida tasdiqlandi!*\n\n"
            f"👋 Xush kelibsiz, *{name}*!",
            parse_mode="Markdown",
            reply_markup=admin_menu()
        )
    else:
        # Ishchi ro'yxatda bormi?
        worker = await get_worker(user_id)
        if worker:
            menu = await get_menu(worker)
            await update.message.reply_text(
                f"✅ *Xush kelibsiz, {name}!*",
                parse_mode="Markdown",
                reply_markup=menu
            )
        else:
            await update.message.reply_text(
                "❌ Siz ro'yxatda yo'qsiz.\n\n"
                "Admin sizni qo'shishi kerak."
            )


# ─── ZAKAZ QO'SHISH ─────────────────────────────────

async def add_order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📞 *Mijozning telefon raqamini kiriting:*",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    return PHONE

async def order_get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['o_phone'] = update.message.text
    await update.message.reply_text("📍 *Manzilni kiriting:*", parse_mode="Markdown")
    return ADDRESS

async def order_get_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['o_address'] = update.message.text
    await update.message.reply_text("📝 *Tavsif kiriting:*\n_(kameralar soni, ish turi)_", parse_mode="Markdown")
    return DESC

async def order_get_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['o_desc'] = update.message.text
    await update.message.reply_text("📅 *Deadline kiriting:*\n_(masalan: 25-aprel yoki 3 kun)_", parse_mode="Markdown")
    return DEADLINE

async def order_get_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    deadline = update.message.text
    async with db_pool.acquire() as conn:
        oid = await conn.fetchval("""
            INSERT INTO orders (phone, address, description, deadline)
            VALUES ($1, $2, $3, $4) RETURNING id
        """,
            context.user_data['o_phone'],
            context.user_data['o_address'],
            context.user_data['o_desc'],
            deadline
        )

    await update.message.reply_text(
        f"✅ *Zakaz #{oid} qo'shildi!*\n\n"
        f"📞 `{context.user_data['o_phone']}`\n"
        f"📍 {context.user_data['o_address']}\n"
        f"📝 {context.user_data['o_desc']}\n"
        f"📅 {deadline}",
        parse_mode="Markdown",
        reply_markup=admin_menu()
    )

    await notify_all_workers(
        context,
        f"🔔 *Yangi zakaz #{oid} keldi!*\n\n"
        f"📍 {context.user_data['o_address']}\n"
        f"📝 {context.user_data['o_desc']}\n"
        f"📅 Deadline: {deadline}\n\n"
        f"📋 Ko'rish uchun: Mavjud zakazlar"
    )
    return ConversationHandler.END


# ─── ISHCHI QO'SHISH ────────────────────────────────

async def add_worker_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👤 *Ishchining Telegram ID sini kiriting:*\n\n"
        "_(ID ni bilish uchun ishchi @userinfobot ga /start yuborsun)_",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    return ADD_WORKER_ID

async def add_worker_get_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data['w_id'] = int(update.message.text)
    except:
        await update.message.reply_text("❌ ID noto'g'ri. Faqat raqam kiriting.")
        return ADD_WORKER_ID

    keyboard = [
        [InlineKeyboardButton("👷 Worker", callback_data="role_worker")],
        [InlineKeyboardButton("⭐ Senior Worker", callback_data="role_senior_worker")]
    ]
    await update.message.reply_text(
        "🎭 *Rolni tanlang:*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ADD_WORKER_ROLE

async def add_worker_set_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    role = query.data.replace("role_", "")
    w_id = context.user_data['w_id']

    async with db_pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT * FROM workers WHERE telegram_id=$1", w_id)
        if existing:
            await conn.execute("UPDATE workers SET role=$1 WHERE telegram_id=$2", role, w_id)
            await query.edit_message_text(f"✅ *Ishchi roli yangilandi:* `{role}`", parse_mode="Markdown")
        else:
            await conn.execute("""
                INSERT INTO workers (telegram_id, role) VALUES ($1, $2)
            """, w_id, role)
            await query.edit_message_text(
                f"✅ *Ishchi qo'shildi!*\n👤 ID: `{w_id}`\n🎭 Rol: `{role}`",
                parse_mode="Markdown"
            )

    try:
        role_text = "⭐ Senior Worker" if role == "senior_worker" else "👷 Worker"
        await context.bot.send_message(
            w_id,
            f"🎉 *Siz tizimga qo'shildingiz!*\n\n"
            f"🎭 Rolingiz: *{role_text}*\n\n"
            f"/start ni bosing.",
            parse_mode="Markdown"
        )
    except:
        pass

    await context.bot.send_message(
        update.effective_user.id,
        "Davom eting 👇",
        reply_markup=admin_menu()
    )
    return ConversationHandler.END


# ─── ZAKAZLAR ───────────────────────────────────────

async def show_all_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM orders WHERE status != 'done' ORDER BY id")

    if not rows:
        await update.message.reply_text("📭 Hozircha zakaz yo'q.", reply_markup=admin_menu())
        return

    for o in rows:
        status_map = {'waiting': '⏳ Kutilmoqda', 'active': '🔧 Ishda', 'done': '✅ Yakunlandi'}
        status = status_map.get(o['status'], o['status'])
        buttons = []
        if o['status'] == 'waiting':
            buttons.append(InlineKeyboardButton("✅ Olish", callback_data=f"take_{o['id']}"))
        buttons.append(InlineKeyboardButton("🗑 O'chirish", callback_data=f"delete_{o['id']}"))
        await update.message.reply_text(
            f"📦 *Zakaz #{o['id']}*\n"
            f"📞 `{o['phone']}`\n"
            f"📍 {o['address']}\n"
            f"📝 {o['description']}\n"
            f"📅 Deadline: {o['deadline']}\n"
            f"📌 {status}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([buttons])
        )

async def show_available_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM orders WHERE status='waiting' ORDER BY id")

    if not rows:
        worker = await get_worker(update.effective_user.id)
        menu = await get_menu(worker)
        await update.message.reply_text("📭 Hozircha bo'sh zakaz yo'q.", reply_markup=menu)
        return

    for o in rows:
        keyboard = [[InlineKeyboardButton("✅ Olish", callback_data=f"take_{o['id']}")]]
        await update.message.reply_text(
            f"📦 *Zakaz #{o['id']}*\n"
            f"📍 {o['address']}\n"
            f"📝 {o['description']}\n"
            f"📅 Deadline: {o['deadline']}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def show_my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    worker = await get_worker(user_id)
    menu = await get_menu(worker)

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM orders WHERE worker_id=$1 AND status='active'", user_id
        )

    if not rows:
        await update.message.reply_text("📭 Sizda hozircha aktiv zakaz yo'q.", reply_markup=menu)
        return

    for o in rows:
        keyboard = [[InlineKeyboardButton("🏁 Yakunlash", callback_data=f"done_{o['id']}")]]
        await update.message.reply_text(
            f"🔧 *Zakaz #{o['id']}*\n"
            f"📍 {o['address']}\n"
            f"📝 {o['description']}\n"
            f"📅 Deadline: {o['deadline']}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


# ─── ISHCHILAR RO'YXATI ─────────────────────────────

async def show_workers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    worker = await get_worker(user_id)

    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM workers WHERE role != 'admin'")

    if not rows:
        await update.message.reply_text("👷 Ishchilar yo'q.")
        return

    for w in rows:
        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM completions WHERE worker_id=$1", w['telegram_id']
            )
        role_text = "⭐ Senior" if w['role'] == 'senior_worker' else "👷 Worker"
        text = (
            f"{role_text} *{w['name'] or 'Noma\\'lum'}*\n"
            f"📞 `{w['phone'] or '-'}`\n"
            f"✅ Yakunlagan: *{count}* ta\n"
            f"🆔 `{w['telegram_id']}`"
        )

        if worker['role'] == 'admin':
            keyboard = [[
                InlineKeyboardButton("🗑 O'chirish", callback_data=f"delworker_{w['telegram_id']}"),
                InlineKeyboardButton("🔄 Rol", callback_data=f"changerole_{w['telegram_id']}")
            ]]
            await update.message.reply_text(text, parse_mode="Markdown",
                                             reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.message.reply_text(text, parse_mode="Markdown")


# ─── STATISTIKA ─────────────────────────────────────

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM orders")
        waiting = await conn.fetchval("SELECT COUNT(*) FROM orders WHERE status='waiting'")
        active = await conn.fetchval("SELECT COUNT(*) FROM orders WHERE status='active'")
        done = await conn.fetchval("SELECT COUNT(*) FROM orders WHERE status='done'")
        workers_count = await conn.fetchval("SELECT COUNT(*) FROM workers WHERE role != 'admin'")

    await update.message.reply_text(
        f"📊 *Statistika*\n\n"
        f"📦 Jami zakazlar: *{total}*\n"
        f"⏳ Kutilmoqda: *{waiting}*\n"
        f"🔧 Ishda: *{active}*\n"
        f"✅ Yakunlandi: *{done}*\n"
        f"👷 Ishchilar: *{workers_count}*",
        parse_mode="Markdown",
        reply_markup=admin_menu()
    )


# ─── CALLBACK HANDLERS ──────────────────────────────

async def take_order_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    oid = int(query.data.split("_")[1])

    async with db_pool.acquire() as conn:
        order = await conn.fetchrow("SELECT * FROM orders WHERE id=$1", oid)
        if not order or order['status'] != 'waiting':
            await query.answer("⚠️ Bu zakaz allaqachon olingan!", show_alert=True)
            return
        await conn.execute(
            "UPDATE orders SET worker_id=$1, status='active' WHERE id=$2", user_id, oid
        )
        worker = await conn.fetchrow("SELECT * FROM workers WHERE telegram_id=$1", user_id)

    await query.edit_message_text(
        f"✅ *Zakaz #{oid} siz oldingiz!*\n\n"
        f"📍 {order['address']}\n"
        f"📝 {order['description']}\n"
        f"📅 Deadline: {order['deadline']}\n\n"
        f"⚡ Yakunlagach tugmani bosing:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🏁 Yakunlash", callback_data=f"done_{oid}")
        ]])
    )

    if admin_telegram_id:
        await context.bot.send_message(
            admin_telegram_id,
            f"📌 *Zakaz #{oid} olindi!*\n\n"
            f"👷 {worker['name'] or 'Ishchi'}\n"
            f"📍 {order['address']}",
            parse_mode="Markdown"
        )

async def done_order_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    oid = int(query.data.split("_")[1])
    context.user_data['completing_order'] = oid

    await query.edit_message_text(
        f"📸 *Zakaz #{oid} uchun ish tugaganligi rasmini yuboring:*",
        parse_mode="Markdown"
    )
    return COMPLETE_PHOTO

async def complete_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    oid = context.user_data.get('completing_order')

    if not update.message.photo:
        await update.message.reply_text("❌ Iltimos rasm yuboring!")
        return COMPLETE_PHOTO

    photo_id = update.message.photo[-1].file_id

    async with db_pool.acquire() as conn:
        order = await conn.fetchrow("SELECT * FROM orders WHERE id=$1", oid)
        await conn.execute(
            "UPDATE orders SET status='done', completed_at=NOW() WHERE id=$1", oid
        )
        await conn.execute("""
            INSERT INTO completions (order_id, worker_id, photo_file_id)
            VALUES ($1, $2, $3)
        """, oid, user_id, photo_id)
        worker = await conn.fetchrow("SELECT * FROM workers WHERE telegram_id=$1", user_id)

    menu = await get_menu(worker)
    await update.message.reply_text(
        f"🎉 *Zakaz #{oid} yakunlandi!*\n\n✅ Ajoyib ish!",
        parse_mode="Markdown",
        reply_markup=menu
    )

    if admin_telegram_id:
        await context.bot.send_photo(
            admin_telegram_id,
            photo=photo_id,
            caption=(
                f"✅ *Zakaz #{oid} yakunlandi!*\n\n"
                f"👷 {worker['name'] or 'Ishchi'}\n"
                f"📍 {order['address']}\n"
                f"📝 {order['description']}"
            ),
            parse_mode="Markdown"
        )
    return ConversationHandler.END

async def delete_order_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    oid = int(query.data.split("_")[1])
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM orders WHERE id=$1", oid)
    await query.edit_message_text(f"🗑 *Zakaz #{oid} o'chirildi!*", parse_mode="Markdown")

async def delete_worker_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    w_id = int(query.data.split("_")[1])
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM workers WHERE telegram_id=$1", w_id)
    await query.edit_message_text("🗑 *Ishchi o'chirildi!*", parse_mode="Markdown")

async def change_role_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    w_id = int(query.data.split("_")[1])
    context.user_data['change_role_id'] = w_id
    keyboard = [
        [InlineKeyboardButton("👷 Worker", callback_data=f"setrole_worker_{w_id}")],
        [InlineKeyboardButton("⭐ Senior Worker", callback_data=f"setrole_senior_worker_{w_id}")]
    ]
    await query.edit_message_text("🎭 *Yangi rolni tanlang:*", parse_mode="Markdown",
                                   reply_markup=InlineKeyboardMarkup(keyboard))

async def set_role_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    w_id = int(parts[-1])
    role = "_".join(parts[1:-1])
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE workers SET role=$1 WHERE telegram_id=$2", role, w_id)
    await query.edit_message_text(f"✅ *Rol yangilandi:* `{role}`", parse_mode="Markdown")


# ─── MESSAGE HANDLER ────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    worker = await get_worker(user_id)

    if not worker:
        await update.message.reply_text("❌ Siz ro'yxatda yo'qsiz. /start bosing.")
        return

    role = worker['role']

    if text == "➕ Zakaz qo'shish" and role == 'admin':
        return await add_order_start(update, context)
    elif text == "📋 Barcha zakazlar" and role == 'admin':
        await show_all_orders(update, context)
    elif text == "📊 Statistika" and role == 'admin':
        await show_stats(update, context)
    elif text == "👷 Ishchilar" and role == 'admin':
        await show_workers(update, context)
    elif text == "➕ Ishchi qo'shish" and role == 'admin':
        return await add_worker_start(update, context)
    elif text == "📋 Mavjud zakazlar":
        await show_available_orders(update, context)
    elif text == "🔧 Mening zakazlarim":
        await show_my_orders(update, context)
    elif text == "👷 Ishchilar ro'yxati" and role == 'senior_worker':
        await show_workers(update, context)
    else:
        await update.message.reply_text("❓ Noma'lum buyruq. /start bosing.")


# ─── MONTHLY REPORT ─────────────────────────────────

async def monthly_report(context):
    if not admin_telegram_id:
        return
    async with db_pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM orders")
        done = await conn.fetchval("SELECT COUNT(*) FROM orders WHERE status='done'")
        workers_count = await conn.fetchval("SELECT COUNT(*) FROM workers WHERE role != 'admin'")

    await context.bot.send_message(
        admin_telegram_id,
        f"📊 *Oylik hisobot*\n\n"
        f"📦 Jami zakazlar: *{total}*\n"
        f"✅ Yakunlangan: *{done}*\n"
        f"👷 Ishchilar: *{workers_count}*",
        parse_mode="Markdown"
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    worker = await get_worker(update.effective_user.id)
    if worker and worker['role'] == 'admin':
        markup = admin_menu()
    elif worker:
        markup = await get_menu(worker)
    else:
        markup = ReplyKeyboardRemove()
    await update.message.reply_text("❌ Bekor qilindi.", reply_markup=markup)
    return ConversationHandler.END


# ─── MAIN ───────────────────────────────────────────

def main():
    app = Application.builder().token(TOKEN).build()

    # Zakaz qo'shish conversation
    order_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➕ Zakaz qo'shish$"), add_order_start)],
        states={
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_get_phone)],
            ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_get_address)],
            DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_get_desc)],
            DEADLINE: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_get_deadline)],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    # Ishchi qo'shish conversation
    worker_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➕ Ishchi qo'shish$"), add_worker_start)],
        states={
            ADD_WORKER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_worker_get_id)],
            ADD_WORKER_ROLE: [CallbackQueryHandler(add_worker_set_role, pattern="^role_")],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    # Yakunlash conversation
    complete_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(done_order_cb, pattern="^done_")],
        states={
            COMPLETE_PHOTO: [MessageHandler(filters.PHOTO, complete_photo)],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.CONTACT, contact_received))
    app.add_handler(order_conv)
    app.add_handler(worker_conv)
    app.add_handler(complete_conv)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(take_order_cb, pattern="^take_"))
    app.add_handler(CallbackQueryHandler(delete_order_cb, pattern="^delete_"))
    app.add_handler(CallbackQueryHandler(delete_worker_cb, pattern="^delworker_"))
    app.add_handler(CallbackQueryHandler(change_role_cb, pattern="^changerole_"))
    app.add_handler(CallbackQueryHandler(set_role_cb, pattern="^setrole_"))

    # Oylik hisobot scheduler
    scheduler.add_job(monthly_report, 'cron', day=1, hour=9,
                      args=[app])
    scheduler.start()

    app.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.run(init_db())
    main()
    
