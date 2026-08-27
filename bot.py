import asyncio
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from aiogram import BaseMiddleware, Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
    FSInputFile,
    URLInputFile,
    LinkPreviewOptions,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_env_file(BASE_DIR / ".env")

BOT_TOKEN = (
    os.getenv("BOT_TOKEN")
    or os.getenv("TELEGRAM_TOKEN")
    or os.getenv("TELEGRAM_BOT_TOKEN")
    or os.getenv("БОТ_TOKEN")
    or os.getenv("БОТ_ТОКЕН")
    or ""
).strip().strip('"').strip("'").replace(" ", "")
GROUP_ID_RAW = (
    os.getenv("GROUP_ID")
    or os.getenv("ADMIN_GROUP_ID")
    or os.getenv("ИДЕНТИФИКАТОР_ГРУППЫ")
    or "-1003851301612"
).strip()
try:
    ADMIN_GROUP_ID = int(GROUP_ID_RAW)
except ValueError:
    ADMIN_GROUP_ID = -1003851301612

ADMIN_CHAT_IDS = list(dict.fromkeys([ADMIN_GROUP_ID, -1003851301612, -3851301612]))

logger.info("ENV has BOT_TOKEN=%s GROUP_ID=%s", bool(os.getenv("BOT_TOKEN")), bool(os.getenv("GROUP_ID")))
if (not BOT_TOKEN) or (":" not in BOT_TOKEN):
    raise SystemExit(
        "Railway не передал BOT_TOKEN в процесс. "
        "Variables → BOT_TOKEN и GROUP_ID на ЭТОМ сервисе → меню ⋮ → Redeploy."
    )

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)


class LogUpdateMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: Update, data: dict):
        if event.callback_query is not None:
            cq = event.callback_query
            logger.info("UPDATE CallbackQuery data=%s", cq.data)
        elif event.message is not None:
            msg = event.message
            logger.info(
                "UPDATE Message text=%s from=%s",
                msg.text,
                msg.from_user.id if msg.from_user else None,
            )
        return await handler(event, data)


dp.update.middleware(LogUpdateMiddleware())

# =======================
# In-memory storage (TODO: Redis/PostgreSQL)
# =======================
USER_CARTS: Dict[int, List[Dict[str, Any]]] = {}
USER_LANG: Dict[int, str] = {}
USER_ORDERS: Dict[int, List[Dict[str, Any]]] = {}
USER_MENU_MESSAGES: Dict[int, List[int]] = {}

LANGS = {
    "ru": {
        "menu": "🍣 Меню",
        "cart": "🛒 Корзина",
        "orders": "📋 Мои заказы",
        "lang": "🌐 Язык",
        "back": "🔙 Назад",
        "main_menu": "🏠 Главное меню",
        "choose_lang": "Выберите язык / Tilni tanlang",
        "empty_cart": "🛒 Ваша корзина пуста",
        "cart_total": "Итого: {} сум",
        "add_to_cart": "➕ Добавить в корзину",
        "added": "Добавлено в корзину",
        "cart_comment": "✏️ Комментарий к блюду",
        "order_phone": "📱 Введите номер телефона",
        "order_address": "📍 Выберите способ указания адреса",
        "order_address_text": "📝 Текстовый адрес",
        "order_address_geo": "📍 Отправить геолокацию",
        "order_pickup": "📦 Самовывоз",
        "order_address_text_input": "📝 Введите адрес доставки",
        "order_comment": "💬 Комментарий к заказу (необязательно)",
        "order_payment": "💳 Выберите способ оплаты",
        "payment_cash": "💵 Наличными",
        "payment_card": "💳 Картой",
        "confirm_order": "✅ Подтвердить заказ",
        "order_confirmed": "🎉 Заказ #{order_id} принят!\n⏰ Ожидайте звонка менеджера.",
        "invalid_phone": "❌ Неверный формат телефона.\nВведите номер в формате +998xxxxxxxxx или 9xxxxxxxxx",
        "phone_saved": "✅ Телефон сохранен",
        "address_saved": "✅ Адрес сохранен",
        "comment_saved": "✅ Комментарий сохранен",
        "checkout": "🛒 Оформление заказа",
        "order_history": "📋 История заказов",
        "no_orders": "📋 У вас пока нет заказов",
        "repeat_order": "🔄 Повторить заказ",
        "remove_item": "🗑 Удалить",
        "item_comment": "✏️ Изменить комментарий",
        "clear_cart": "🗑 Очистить корзину",
        "quantity": "Количество: {}",
        "price": "{} сум",
        "admin_order_received": "🆕 Новый заказ #{order_id}\n👤 Пользователь: {user_info}",
        "choose_order_comment": "💬 Хотите добавить комментарий к заказу?",
        "skip_comment": "Пропустить",
        "need_address": "❌ Адрес не выбран",
        "need_payment": "❌ Способ оплаты не выбран",
        "send_failed": "❌ Ошибка при отправке заказа. Попробуйте еще раз.",
        "admin_not_configured": "❌ ADMIN_GROUP_ID не задан. Заказ не отправлен администраторам.",
    },
    "uz": {
        "menu": "🍣 Menyu",
        "cart": "🛒 Savat",
        "orders": "📋 Buyurtmalarim",
        "lang": "🌐 Til",
        "back": "🔙 Orqaga",
        "main_menu": "🏠 Asosiy menyu",
        "choose_lang": "Выберите язык / Tilni tanlang",
        "empty_cart": "🛒 Savatingiz boʻsh",
        "cart_total": "Jami: {} soʻm",
        "add_to_cart": "➕ Savatga qoʻshish",
        "added": "Savatga qoʻshildi",
        "cart_comment": "✏️ Taom uchun izoh",
        "order_phone": "📱 Telefon raqamini kiriting",
        "order_address": "📍 Yetkazib berish usulini tanlang",
        "order_address_text": "📝 Matnli manzil",
        "order_address_geo": "📍 Geolocation yuborish",
        "order_pickup": "📦 Olib ketish",
        "order_address_text_input": "📝 Yetkazib berish manzilini kiriting",
        "order_comment": "💬 Buyurtma uchun izoh (ixtiyoriy)",
        "order_payment": "💳 Toʻlov usulini tanlang",
        "payment_cash": "💵 Naqd pul",
        "payment_card": "💳 Karta orqali",
        "confirm_order": "✅ Buyurtmani tasdiqlash",
        "order_confirmed": "🎉 Buyurtma #{order_id} qabul qilindi!\n⏰ Menejer qoʻngʻirogʻini kuting.",
        "invalid_phone": "❌ Notoʻgʻri telefon formati.\n+998xxxxxxxxx yoki 9xxxxxxxxx formatida kiriting",
        "phone_saved": "✅ Telefon saqlandi",
        "address_saved": "✅ Manzil saqlandi",
        "comment_saved": "✅ Izoh saqlandi",
        "checkout": "🛒 Buyurtma berish",
        "order_history": "📋 Buyurtmalar tarixi",
        "no_orders": "📋 Hozircha buyurtmalar yoʻq",
        "repeat_order": "🔄 Buyurtmani takrorlash",
        "remove_item": "🗑 Oʻchirish",
        "item_comment": "✏️ Izohni oʻzgartirish",
        "clear_cart": "🗑 Savatni tozalash",
        "quantity": "Miqdor: {}",
        "price": "{} soʻm",
        "admin_order_received": "🆕 Yangi buyurtma #{order_id}\n👤 Foydalanuvchi: {user_info}",
        "choose_order_comment": "💬 Buyurtmaga izoh qoʻshasizmi?",
        "skip_comment": "O'tkazib yuborish",
        "need_address": "❌ Manzil tanlanmagan",
        "need_payment": "❌ Toʻlov usuli tanlanmagan",
        "send_failed": "❌ Buyurtmani yuborishda xatolik. Qayta urinib koʻring.",
        "admin_not_configured": "❌ ADMIN_GROUP_ID sozlanmagan.",
    },
}


def t(uid: int, key: str) -> str:
    lang = USER_LANG.get(uid, "ru")
    return LANGS.get(lang, LANGS["ru"]).get(key, key)


def all_texts(*keys: str) -> set:
    values = set()
    for lang in LANGS.values():
        for key in keys:
            values.add(lang[key])
    return values


class OrderState(StatesGroup):
    phone = State()
    address_type = State()
    address_text = State()
    address_geo = State()
    comment = State()
    item_comment = State()
    payment = State()
    confirm = State()


MENU = {
    "sushi_mini": [
        {"id": "sm1", "name": "Ролл с огурцом", "price": 20000, "desc": "Огурец, рис, нори", "photo": "sm1.jpg"},
        {"id": "sm2", "name": "Ролл с авокадо", "price": 30000, "desc": "Авокадо, рис, нори", "photo": "sm2.jpg"},
        {"id": "sm3", "name": "Ролл с лососем", "price": 50000, "desc": "Лосось, рис, нори", "photo": "sm3.jpg"},
        {"id": "sm4", "name": "Ролл с тунцом", "price": 50000, "desc": "Тунец, рис, нори", "photo": "sm4.jpg"},
        {"id": "sm5", "name": "Ролл с угрем", "price": 50000, "desc": "Угорь, рис, нори", "photo": "sm5.jpg"},
        {"id": "sm6", "name": "Чука", "price": 35000, "desc": "Салат чука, рис, нори", "photo": "sm6.jpg"},
    ],
    "rolls_salmon": [
        {"id": "rs1", "name": "Топчик", "price": 65000, "desc": "Лосось, сыр творожный, огурец", "photo": "rs1.jpg"},
        {"id": "rs2", "name": "Акира", "price": 65000, "desc": "Лосось, сыр творожный, кунжут", "photo": "rs2.jpg"},
        {"id": "rs3", "name": "Филадельфия лайт", "price": 75000, "desc": "Лосось, сыр творожный, огурец", "photo": "rs3.jpg"},
        {"id": "rs4", "name": "Филадельфия", "price": 90000, "desc": "Лосось, сыр творожный", "photo": "rs4.jpg"},
        {"id": "rs5", "name": "Филадельфия с огурцом", "price": 90000, "desc": "Лосось, сыр творожный, огурец", "photo": "rs5.jpg"},
        {"id": "rs6", "name": "Филадельфия с тунцом", "price": 95000, "desc": "Тунец, сыр творожный, огурец", "photo": "rs6.jpg"},
    ],
    "rolls_seafood": [
        {"id": "rf1", "name": "Тай Пэй", "price": 65000, "desc": "Креветка темпура, огурец, майонез, болгарский перец", "photo": "rf1.jpg"},
        {"id": "rf2", "name": "Калифорния с креветкой", "price": 65000, "desc": "Креветка, майонез, огурец, икра массаго", "photo": "rf2.jpg"},
        {"id": "rf3", "name": "Эби", "price": 75000, "desc": "Креветка, сыр творожный, огурец, кунжут, спайс соус", "photo": "rf3.jpg"},
        {"id": "rf4", "name": "Филадельфия с угрем", "price": 95000, "desc": "Угорь, сыр творожный, соус унаги", "photo": "rf4.jpg"},
    ],
    "rolls_chicken_crab": [
        {"id": "rm1", "name": "Чикен", "price": 55000, "desc": "Курица, помидор, огурец, салат, сыр, кунжут", "photo": "rm1.jpg"},
        {"id": "rm2", "name": "Пирамида", "price": 65000, "desc": "Лосось, сыр творожный, авокадо, икра массаго", "photo": "rm2.jpg"},
        {"id": "rm3", "name": "Калифорния", "price": 65000, "desc": "Снежный краб, майонез, огурец, икра массаго", "photo": "rm3.jpg"},
        {"id": "rm4", "name": "Бомба", "price": 75000, "desc": "Лосось, креветка, сыр творожный, огурец, икра массаго", "photo": "rm4.jpg"},
    ],
    "sushi_baked": [
        {"id": "sb1", "name": "Тори-Спайс", "price": 55000, "desc": "Курица, сыр творожный, огурец, соус спайс", "photo": "sb1.jpg"},
        {"id": "sb2", "name": "Саке-Эби", "price": 85000, "desc": "Лосось, креветка темпура, сыр творожный, чука", "photo": "sb2.jpg"},
        {"id": "sb3", "name": "Запечённый с угрем", "price": 75000, "desc": "Угорь, сыр творожный, огурец, сырная шапка, икра масаго", "photo": "sb3.jpg"},
        {"id": "sb4", "name": "Запечённый с лососем", "price": 75000, "desc": "Лосось, сыр творожный, краб, сырная шапка", "photo": "sb4.jpg"},
        {"id": "sb5", "name": "Запечённый Массаго", "price": 70000, "desc": "Лосось, сыр творожный, огурец, сырная шапка", "photo": "sb5.jpg"},
        {"id": "sb6", "name": "Запечённый Цезарь", "price": 55000, "desc": "Курица, соус цезарь, салатный лист, сырная шапка", "photo": "sb6.jpg"},
        {"id": "sb7", "name": "Запечённый с курицей", "price": 50000, "desc": "Курица, соус фирменный, огурец, сырная шапка", "photo": "sb7.jpg"},
        {"id": "sb8", "name": "Запечённый с крабом", "price": 60000, "desc": "Снежный краб, сыр творожный, огурец, массаго, сырная шапка", "photo": "sb8.jpg"},
        {"id": "sb9", "name": "Full Cheese", "price": 50000, "desc": "Сыр творожный, сыр гауда, сырная шапка", "photo": "sb9.jpg"},
        {"id": "sb10", "name": "Америка", "price": 75000, "desc": "Снежный краб, сыр творожный, огурец, массаго, сырная шапка", "photo": "sb10.jpg"},
        {"id": "sb11", "name": "Фьюжн", "price": 45000, "desc": "Курица, яблоко, сыр творожный, сырная шапка", "photo": "sb11.jpg"},
        {"id": "sb12", "name": "Аляска", "price": 80000, "desc": "Лосось, угорь, огурец, сыр творожный, сырная шапка", "photo": "sb12.jpg"},
    ],
    "sushi_fried": [
        {"id": "sf1", "name": "Жареный Цезарь", "price": 50000, "desc": "Курица, соус цезарь, салатный лист, сыр", "photo": "sf1.jpg"},
        {"id": "sf2", "name": "Жареный Джинджер", "price": 60000, "desc": "Креветка темпура, имбирь, майонез", "photo": "sf2.jpg"},
        {"id": "sf3", "name": "Жареный Три брата", "price": 85000, "desc": "Лосось, угорь, тунец, майонез, огурец", "photo": "sf3.jpg"},
        {"id": "sf4", "name": "Жареный Киото", "price": 70000, "desc": "Лосось, огурец, сыр творожный, чука", "photo": "sf4.jpg"},
        {"id": "sf5", "name": "Жареный Эби темпура", "price": 60000, "desc": "Креветка темпура, сыр сливочный", "photo": "sf5.jpg"},
        {"id": "sf6", "name": "Жареная Филадельфия", "price": 75000, "desc": "Лосось, сыр творожный, огурец", "photo": "sf6.jpg"},
    ],
    "sushi_doggers": [
        {"id": "sd1", "name": "Доггер Цезарь", "price": 60000, "desc": "Курица, салатный лист, сыр, соус цезарь", "photo": "sd1.jpg"},
        {"id": "sd2", "name": "Доггер с крабом", "price": 65000, "desc": "Снежный краб, майонез, соус унаги, огурец, массаго", "photo": "sd2.jpg"},
        {"id": "sd3", "name": "Доггер с лососем", "price": 80000, "desc": "Лосось, сыр творожный, огурец, кунжут, соус унаги", "photo": "sd3.jpg"},
    ],
    "sushi_sets": [
        {"id": "ss1", "name": "Сет Пожар", "price": 230000, "desc": "Жареный цезарь, жареный Джинджер, жареный Эби темпура, жареный Киото", "photo": "ss1.jpg"},
        {"id": "ss2", "name": "Сет Мини", "price": 165000, "desc": "Филадельфия + жареный Три брата", "photo": "ss2.jpg"},
        {"id": "ss3", "name": "Сет Хит 2026", "price": 275000, "desc": "Филадельфия, Акира, жареный цезарь, жареный Три брата", "photo": "ss3.jpg"},
        {"id": "ss4", "name": "Сет Трио", "price": 120000, "desc": "Жареный Эби темпура, Киото, Акира", "photo": "ss4.jpg"},
        {"id": "ss5", "name": "Сет Full Лосось", "price": 210000, "desc": "Филадельфия, Филадельфия с тунцом, Ролл с лососем", "photo": "ss5.jpg"},
        {"id": "ss6", "name": "Сет Ассорти", "price": 225000, "desc": "Жареный Три брата, Филадельфия с тунцом, Эби", "photo": "ss6.jpg"},
    ],
    "pizza_meat": [
        {"id": "pm1", "name": "Пицца Пепперони", "price": 60000, "desc": "Колбаски пепперони, моцарелла, томатный соус", "photo": "pm1.jpg"},
        {"id": "pm2", "name": "Пицца Цезарь", "price": 60000, "desc": "Соус цезарь, сыр моцарелла, куриное филе, помидоры, салатные листья, сыр пармезан", "photo": "pm2.jpg"},
        {"id": "pm3", "name": "4 сезона", "price": 55000, "desc": "Пицца соус, сыр моцарелла, колбаса, грибы, помидоры, курица", "photo": "pm3.jpg"},
        {"id": "pm4", "name": "Шеф Охота", "price": 65000, "desc": "Сыр моцарелла, охотничьи колбаски, пепперони, ветчина, пицца соус, чесночный соус", "photo": "pm4.jpg"},
        {"id": "pm5", "name": "Грация", "price": 60000, "desc": "Пицца соус, сыр моцарелла, сыр пармезан, ветчина, грибы шампиньоны, зелёный лук", "photo": "pm5.jpg"},
        {"id": "pm6", "name": "Итальяно", "price": 55000, "desc": "Цезарь соус, сыр моцарелла, куриное филе, грибы шампиньоны, сыр пармезан", "photo": "pm6.jpg"},
        {"id": "pm8", "name": "Маргарита", "price": 50000, "desc": "Пицца соус, сыр моцарелла, помидоры", "photo": "pm8.jpg"},
        {"id": "pm9", "name": "Восточный", "price": 75000, "desc": "Пицца соус, сыр моцарелла, говядина, маринованные огурцы, красный лук, казы, зелёный лук", "photo": "pm9.jpg"},
        {"id": "pm0", "name": "4 Сыра", "price": 50000, "desc": "Пицца соус, сыр моцарелла, сыр пармезан, сыр гауда, сыр творожный", "photo": "pm0.jpg"},
    ],
}

CATEGORY_TITLES = {
    "sushi_mini": ("🍣 Мини-роллы", "🍣 Mini rollar"),
    "rolls_salmon": ("🍣 Роллы с лососем", "🍣 Losos rollari"),
    "rolls_seafood": ("🦐 Морепродукты", "🦐 Dengiz mahsulotlari"),
    "rolls_chicken_crab": ("🍗 Курица и краб", "🍗 Tovuq va krab"),
    "sushi_baked": ("🔥 Запечённые", "🔥 Pishirilgan"),
    "sushi_fried": ("🍳 Жареные", "🍳 Qovurilgan"),
    "sushi_doggers": ("🌭 Доггеры", "🌭 Doggerlar"),
    "sushi_sets": ("🍱 Сеты", "🍱 Setlar"),
    "pizza_meat": ("🍕 Пицца", "🍕 Pizza"),
}

MENU_CATEGORIES = {}
for _cat_id, _items in MENU.items():
    titles = CATEGORY_TITLES.get(_cat_id, (_cat_id, _cat_id))
    MENU_CATEGORIES[_cat_id] = {
        "title_ru": titles[0],
        "title_uz": titles[1],
        "items": [
            {
                **item,
                "name_ru": item["name"],
                "name_uz": item["name"],
            }
            for item in _items
        ],
    }


def photo_file(item: Dict[str, Any]):
    raw = item.get("photo") or ""
    filename = Path(raw).name
    candidates = [
        BASE_DIR / raw,
        BASE_DIR / "photos" / filename,
        BASE_DIR / filename,
        Path(raw),
        Path("photos") / filename,
    ]
    for path in candidates:
        if path.exists() and path.is_file():
            return FSInputFile(str(path))
    url = item.get("photo_url")
    if url:
        return URLInputFile(url, filename=filename or f"{item.get('id', 'item')}.jpg")
    return None


def get_main_keyboard(uid: int) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t(uid, "menu")), KeyboardButton(text=t(uid, "cart"))],
            [KeyboardButton(text=t(uid, "orders")), KeyboardButton(text=t(uid, "lang"))],
        ],
        resize_keyboard=True,
        is_persistent=True,
        one_time_keyboard=False,
        input_field_placeholder="Выберите пункт меню",
    )


def get_main_inline(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=t(uid, "menu"), callback_data="open_menu"),
                InlineKeyboardButton(text=t(uid, "cart"), callback_data="open_cart"),
            ],
            [
                InlineKeyboardButton(text=t(uid, "orders"), callback_data="open_orders"),
                InlineKeyboardButton(text=t(uid, "lang"), callback_data="open_lang"),
            ],
        ]
    )


def get_back_keyboard(uid: int, target: str = "menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t(uid, "back"), callback_data=f"back_to_{target}")]]
    )


def get_address_keyboard(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(uid, "order_address_text"), callback_data="addr_type_text")],
            [InlineKeyboardButton(text=t(uid, "order_address_geo"), callback_data="addr_type_geo")],
            [InlineKeyboardButton(text=t(uid, "order_pickup"), callback_data="addr_type_pickup")],
            [InlineKeyboardButton(text=t(uid, "back"), callback_data="back_to_cart")],
        ]
    )


def get_payment_keyboard(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=t(uid, "payment_cash"), callback_data="payment_cash"),
                InlineKeyboardButton(text=t(uid, "payment_card"), callback_data="payment_card"),
            ],
            [InlineKeyboardButton(text=t(uid, "back"), callback_data="back_to_comment")],
        ]
    )


def get_geo_keyboard(uid: int) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t(uid, "order_address_geo"), request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def get_comment_keyboard(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(uid, "skip_comment"), callback_data="skip_order_comment")],
            [InlineKeyboardButton(text=t(uid, "back"), callback_data="back_to_address")],
        ]
    )


def get_lang_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Русский", callback_data="lang_ru"),
                InlineKeyboardButton(text="Oʻzbekcha", callback_data="lang_uz"),
            ]
        ]
    )


def format_price(price: float) -> str:
    return f"{int(price):,}".replace(",", " ")


def clean_phone(phone: str) -> Optional[str]:
    digits = re.sub(r"[^\d]", "", phone or "")
    if digits.startswith("8") and len(digits) == 11:
        digits = "7" + digits[1:]
    elif digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 12 and digits.startswith("998"):
        return digits
    if len(digits) == 9 and digits.startswith("9"):
        return "998" + digits
    return None


def generate_line_id() -> str:
    return str(uuid.uuid4())[:8]


async def save_user_cart(uid: int, cart: List[Dict]):
    USER_CARTS[uid] = cart


async def get_user_cart(uid: int) -> List[Dict]:
    return USER_CARTS.get(uid, [])


async def add_to_cart(uid: int, item_id: str, quantity: int = 1):
    cart = await get_user_cart(uid)
    for item in cart:
        if item["item_id"] == item_id:
            item["quantity"] += quantity
            await save_user_cart(uid, cart)
            return
    menu_item = next(
        (i for cat in MENU_CATEGORIES.values() for i in cat["items"] if i["id"] == item_id),
        None,
    )
    if not menu_item:
        return
    cart.append(
        {
            "line_id": generate_line_id(),
            "item_id": item_id,
            "name_ru": menu_item["name_ru"],
            "name_uz": menu_item["name_uz"],
            "price": menu_item["price"],
            "quantity": quantity,
            "comment": "",
        }
    )
    await save_user_cart(uid, cart)


async def remove_from_cart(uid: int, line_id: str):
    cart = await get_user_cart(uid)
    cart[:] = [item for item in cart if item["line_id"] != line_id]
    await save_user_cart(uid, cart)


async def update_cart_comment(uid: int, line_id: str, comment: str):
    cart = await get_user_cart(uid)
    for item in cart:
        if item["line_id"] == line_id:
            item["comment"] = comment
            break
    await save_user_cart(uid, cart)


async def clear_user_cart(uid: int):
    USER_CARTS[uid] = []


async def delete_user_messages(uid: int):
    for msg_id in USER_MENU_MESSAGES.get(uid, []):
        try:
            await bot.delete_message(uid, msg_id)
        except Exception:
            pass
    USER_MENU_MESSAGES[uid] = []


def escape_md(text: str) -> str:
    chars = r"_*[]()~`>#+-=|{}.!"
    out = []
    for ch in str(text):
        if ch in chars:
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


async def send_admin_order(bot_: Bot, order_data: Dict) -> bool:
    total = sum(item["quantity"] * item["price"] for item in order_data["items"])
    header = (
        t(0, "admin_order_received")
        .replace("{order_id}", str(order_data["id"]))
        .replace("{user_info}", order_data["user_name"])
    )
    lines = [
        escape_md(header),
        "",
        f"👤 {escape_md(order_data['user_name'])}",
        f"📱 {escape_md(order_data['phone'])}",
        f"📍 {escape_md(order_data.get('address') or '')}",
        "",
        f"🛒 {escape_md(t(0, 'cart_total').format(format_price(total)))}",
        "",
        escape_md("📋 Товары:"),
    ]
    for item in order_data["items"]:
        item_total = item["quantity"] * item["price"]
        title = item.get("name_ru") or item.get("name") or item.get("item_id")
        lines.append(
            f"• {escape_md(title)} x{escape_md(item['quantity'])} \\- {escape_md(format_price(item_total))}"
        )
        if item.get("comment"):
            lines.append(f"  _{escape_md(item['comment'])}_")
    lines.append("")
    lines.append(f"💬 {escape_md(order_data.get('comment') or '---')}")
    lines.append(f"💳 {escape_md(order_data['payment_method'])}")
    lat = order_data.get("lat")
    lon = order_data.get("lon")
    if lat is not None and lon is not None:
        navi = f"https://yandex.ru/navi/?whatshere[point]={lon},{lat}&whatshere[zoom]=18"
        lines.append(f"🧭 Яндекс Навигатор: {escape_md(navi)}")

    text_md = "\n".join(lines)
    plain = text_md.replace("\\", "").replace("*", "").replace("_", "")
    last_error = None

    for chat_id in ADMIN_CHAT_IDS:
        try:
            await bot_.send_message(
                chat_id,
                text_md,
                parse_mode="MarkdownV2",
                link_preview_options=LinkPreviewOptions(is_disabled=True),
                disable_web_page_preview=True,
            )
            logger.info("Заказ отправлен в %s", chat_id)
            return True
        except Exception as e:
            last_error = e
            logger.error("MarkdownV2 в %s: %s", chat_id, e)
            try:
                await bot_.send_message(
                    chat_id,
                    plain,
                    link_preview_options=LinkPreviewOptions(is_disabled=True),
                    disable_web_page_preview=True,
                )
                logger.info("Заказ отправлен текстом в %s", chat_id)
                return True
            except Exception as e2:
                last_error = e2
                logger.error("Текст в %s: %s", chat_id, e2)
    logger.error("Не удалось отправить заказ админам: %s", last_error)
    return False


def item_name(uid: int, item: Dict) -> str:
    lang = USER_LANG.get(uid, "ru")
    if lang == "uz":
        return item.get("name_uz") or item.get("name_ru") or item.get("name") or ""
    return item.get("name_ru") or item.get("name") or item.get("name_uz") or ""


def short_name(name: str, limit: int = 18) -> str:
    name = name or ""
    return name if len(name) <= limit else name[: limit - 1] + "…"


def cart_text_and_kb(uid: int, cart: List[Dict]):
    total = sum(item["quantity"] * item["price"] for item in cart)
    text = f"{t(uid, 'cart_total').format(format_price(total))}\n"
    keyboard = []
    for item in cart:
        item_total = item["quantity"] * item["price"]
        name = item_name(uid, item)
        text += f"\n{name}\n{t(uid, 'quantity').format(item['quantity'])} — {format_price(item_total)}"
        if item.get("comment"):
            text += f"\n✏️ {item['comment']}"
        text += "\n"
        label = short_name(name)
        keyboard.append(
            [
                InlineKeyboardButton(
                    text=f"{t(uid, 'remove_item')} {label}",
                    callback_data=f"remove_{item['line_id']}",
                ),
                InlineKeyboardButton(
                    text=f"{t(uid, 'item_comment')} {label}",
                    callback_data=f"comment_{item['line_id']}",
                ),
            ]
        )
    keyboard.extend(
        [
            [InlineKeyboardButton(text=t(uid, "checkout"), callback_data="checkout")],
            [InlineKeyboardButton(text=t(uid, "clear_cart"), callback_data="clear_cart")],
            [InlineKeyboardButton(text=t(uid, "back"), callback_data="back_to_menu")],
        ]
    )
    return text, InlineKeyboardMarkup(inline_keyboard=keyboard)


async def render_cart(target: Message, uid: int, edit: bool = False):
    cart = await get_user_cart(uid)
    if not cart:
        if edit:
            try:
                await target.edit_text(t(uid, "empty_cart"))
            except Exception:
                await target.answer(t(uid, "empty_cart"), reply_markup=get_main_keyboard(uid))
        else:
            await target.answer(t(uid, "empty_cart"), reply_markup=get_main_keyboard(uid))
        return
    text, kb = cart_text_and_kb(uid, cart)
    if edit:
        try:
            await target.edit_text(text, reply_markup=kb)
            return
        except Exception:
            pass
    await target.answer(text, reply_markup=kb)


async def start_checkout(message: Message, state: FSMContext, uid: int):
    await state.set_state(OrderState.phone)
    await message.answer(t(uid, "order_phone"), reply_markup=get_back_keyboard(uid, "cart"))


async def send_main_menu(message: Message, uid: int):
    hint = (
        "👇 Меню, корзина и заказы — на кнопках внизу экрана."
        if USER_LANG.get(uid, "ru") == "ru"
        else "👇 Menyu, savat va buyurtmalar — pastdagi tugmalarda."
    )
    await message.answer(hint, reply_markup=get_main_keyboard(uid))


async def show_menu(message: Message, uid: int):
    await delete_user_messages(uid)
    lang = USER_LANG.get(uid, "ru")
    buttons = []
    for cat_id, category in MENU_CATEGORIES.items():
        title = category["title_ru"] if lang == "ru" else category["title_uz"]
        buttons.append([InlineKeyboardButton(text=title, callback_data=f"cat_{cat_id}")])
    buttons.append([InlineKeyboardButton(text=t(uid, "back"), callback_data="back_to_menu")])
    msg = await message.answer(t(uid, "menu"), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    USER_MENU_MESSAGES.setdefault(uid, []).append(msg.message_id)


@dp.message(CommandStart())
async def start_handler(message: Message, state: FSMContext):
    uid = message.from_user.id
    USER_LANG.setdefault(uid, "ru")
    await delete_user_messages(uid)
    await state.clear()
    await send_main_menu(message, uid)


@dp.message(F.text.in_(all_texts("lang")))
async def lang_prompt(message: Message):
    await message.answer(t(message.from_user.id, "choose_lang"), reply_markup=get_lang_keyboard())


@dp.callback_query(F.data.startswith("lang_"))
async def set_lang(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    USER_LANG[uid] = callback.data.split("_", 1)[1]
    await state.clear()
    await send_main_menu(callback.message, uid)
    await callback.answer()


@dp.message(F.text.in_(all_texts("menu")))
async def menu_handler(message: Message):
    await show_menu(message, message.from_user.id)


@dp.callback_query(F.data == "open_menu")
async def open_menu_cb(callback: CallbackQuery):
    await callback.answer()
    await show_menu(callback.message, callback.from_user.id)


@dp.callback_query(F.data == "open_cart")
async def open_cart_cb(callback: CallbackQuery):
    await callback.answer()
    await render_cart(callback.message, callback.from_user.id)


@dp.callback_query(F.data == "open_orders")
async def open_orders_cb(callback: CallbackQuery):
    await callback.answer()
    await show_orders(callback.message, callback.from_user.id)


@dp.callback_query(F.data == "open_lang")
async def open_lang_cb(callback: CallbackQuery):
    await callback.message.answer(
        t(callback.from_user.id, "choose_lang"),
        reply_markup=get_lang_keyboard(),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("cat_"))
async def category_handler(callback: CallbackQuery):
    uid = callback.from_user.id
    cat_id = callback.data.split("_", 1)[1]
    await delete_user_messages(uid)
    category = MENU_CATEGORIES.get(cat_id)
    if not category:
        await callback.answer()
        return
    lang = USER_LANG.get(uid, "ru")
    items = category["items"]
    for index, item in enumerate(items):
        name = item.get("name_ru") or item.get("name")
        if lang != "ru":
            name = item.get("name_uz") or name
        desc = item.get("desc") or ""
        caption = name
        if desc:
            caption += f"\n{desc}"
        caption += f"\n{t(uid, 'price').format(format_price(item['price']))}"
        rows = [
            [InlineKeyboardButton(text=t(uid, "add_to_cart"), callback_data=f'add_{item["id"]}')],
            [InlineKeyboardButton(text=t(uid, "item_comment"), callback_data=f'note_{item["id"]}')],
        ]
        if index == len(items) - 1:
            rows.append([InlineKeyboardButton(text=t(uid, "back"), callback_data="back_to_menu")])
        kb = InlineKeyboardMarkup(inline_keyboard=rows)
        photo = photo_file(item)
        try:
            if photo is None:
                raise FileNotFoundError(item.get("photo"))
            msg = await callback.message.answer_photo(photo, caption=caption, reply_markup=kb)
        except Exception as e:
            logger.warning("Не удалось отправить фото %s: %s", item.get("id"), e)
            msg = await callback.message.answer(caption, reply_markup=kb)
        USER_MENU_MESSAGES.setdefault(uid, []).append(msg.message_id)
    await callback.answer()


@dp.callback_query(F.data.startswith("add_"))
async def add_to_cart_handler(callback: CallbackQuery):
    uid = callback.from_user.id
    item_id = callback.data.split("_", 1)[1]
    await add_to_cart(uid, item_id)
    await callback.answer(t(uid, "added"), show_alert=True)


@dp.callback_query(F.data.startswith("note_"))
async def note_from_menu_handler(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    item_id = callback.data.split("_", 1)[1]
    await add_to_cart(uid, item_id)
    cart = await get_user_cart(uid)
    line = next((i for i in cart if i["item_id"] == item_id), None)
    if not line:
        await callback.answer()
        return
    await state.update_data(line_id=line["line_id"])
    await state.set_state(OrderState.item_comment)
    await callback.message.answer(f"{t(uid, 'cart_comment')}: {item_name(uid, line)}")
    await callback.answer()


@dp.message(F.text.in_(all_texts("cart")))
async def cart_handler(message: Message):
    await render_cart(message, message.from_user.id)


@dp.callback_query(F.data.startswith("remove_"))
async def remove_item_handler(callback: CallbackQuery):
    uid = callback.from_user.id
    line_id = callback.data.split("_", 1)[1]
    await remove_from_cart(uid, line_id)
    await callback.answer()
    await render_cart(callback.message, uid, edit=True)


@dp.callback_query(F.data.startswith("comment_"))
async def item_comment_handler(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    line_id = callback.data.split("_", 1)[1]
    await state.update_data(line_id=line_id)
    await state.set_state(OrderState.item_comment)
    await callback.message.answer(t(uid, "cart_comment"))
    await callback.answer()


@dp.message(OrderState.item_comment)
async def process_item_comment(message: Message, state: FSMContext):
    uid = message.from_user.id
    line_id = (await state.get_data()).get("line_id")
    if line_id:
        await update_cart_comment(uid, line_id, message.text or "")
    await state.clear()
    await message.answer(t(uid, "comment_saved"))
    await render_cart(message, uid)


@dp.callback_query(F.data == "checkout")
async def checkout_handler(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    cart = await get_user_cart(uid)
    if not cart:
        await callback.answer(t(uid, "empty_cart"), show_alert=True)
        return
    await callback.answer()
    await start_checkout(callback.message, state, uid)


@dp.message(OrderState.phone)
async def process_phone(message: Message, state: FSMContext):
    uid = message.from_user.id
    phone = clean_phone(message.text or "")
    if not phone:
        await message.answer(t(uid, "invalid_phone"))
        return
    await state.update_data(phone=phone)
    await state.set_state(OrderState.address_type)
    await message.answer(t(uid, "phone_saved"))
    await message.answer(t(uid, "order_address"), reply_markup=get_address_keyboard(uid))


@dp.callback_query(F.data.startswith("addr_type_"), OrderState.address_type)
async def choose_address_type(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    addr_type = callback.data.split("_", 2)[2]
    await state.update_data(address_type=addr_type)
    if addr_type == "pickup":
        await state.update_data(address=t(uid, "order_pickup"), lat=None, lon=None)
        await state.set_state(OrderState.comment)
        await callback.message.edit_text(t(uid, "choose_order_comment"), reply_markup=get_comment_keyboard(uid))
    elif addr_type == "text":
        await state.set_state(OrderState.address_text)
        await callback.message.edit_text(t(uid, "order_address_text_input"), reply_markup=get_back_keyboard(uid, "address"))
    elif addr_type == "geo":
        await state.set_state(OrderState.address_geo)
        await callback.message.answer(t(uid, "order_address_geo"), reply_markup=get_geo_keyboard(uid))
    await callback.answer()


@dp.message(OrderState.address_text)
async def process_address_text(message: Message, state: FSMContext):
    uid = message.from_user.id
    await state.update_data(address=message.text, lat=None, lon=None)
    await state.set_state(OrderState.comment)
    await message.answer(t(uid, "address_saved"))
    await message.answer(t(uid, "choose_order_comment"), reply_markup=get_comment_keyboard(uid))


@dp.message(OrderState.address_geo, F.location)
async def process_location(message: Message, state: FSMContext):
    uid = message.from_user.id
    loc = message.location
    lat = float(loc.latitude)
    lon = float(loc.longitude)
    address = f"Геолокация: {lat:.6f}, {lon:.6f}"
    await state.update_data(address=address, lat=lat, lon=lon)
    await state.set_state(OrderState.comment)
    await message.answer(t(uid, "address_saved"), reply_markup=ReplyKeyboardRemove())
    await message.answer(t(uid, "choose_order_comment"), reply_markup=get_comment_keyboard(uid))


@dp.callback_query(F.data == "skip_order_comment", OrderState.comment)
async def skip_comment(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    await state.update_data(comment="")
    await state.set_state(OrderState.payment)
    await callback.message.edit_text(t(uid, "order_payment"), reply_markup=get_payment_keyboard(uid))
    await callback.answer()


@dp.message(OrderState.comment)
async def process_order_comment(message: Message, state: FSMContext):
    uid = message.from_user.id
    await state.update_data(comment=message.text or "")
    await state.set_state(OrderState.payment)
    await message.answer(t(uid, "order_payment"), reply_markup=get_payment_keyboard(uid))


@dp.callback_query(F.data.startswith("payment_"), OrderState.payment)
async def choose_payment(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    payment_method_key = callback.data.split("_", 1)[1]
    await state.update_data(payment_method=t(uid, f"payment_{payment_method_key}"))
    await state.set_state(OrderState.confirm)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(uid, "confirm_order"), callback_data="confirm_order")],
            [InlineKeyboardButton(text=t(uid, "back"), callback_data="back_to_payment")],
        ]
    )
    await callback.message.edit_text(t(uid, "confirm_order"), reply_markup=kb)
    await callback.answer()


@dp.callback_query(F.data == "confirm_order")
async def confirm_order(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    data = await state.get_data()
    cart = await get_user_cart(uid)
    if not cart:
        await callback.answer(t(uid, "empty_cart"), show_alert=True)
        return
    if not data.get("phone"):
        await state.set_state(OrderState.phone)
        await callback.message.answer(t(uid, "order_phone"), reply_markup=get_back_keyboard(uid, "cart"))
        await callback.answer()
        return
    if not data.get("address"):
        await callback.answer(t(uid, "need_address"), show_alert=True)
        return
    if not data.get("payment_method"):
        await callback.answer(t(uid, "need_payment"), show_alert=True)
        return

    order_id = len(USER_ORDERS.get(uid, [])) + 1
    order_data = {
        "id": order_id,
        "user_id": uid,
        "user_name": callback.from_user.full_name,
        "phone": data["phone"],
        "address": data["address"],
        "lat": data.get("lat"),
        "lon": data.get("lon"),
        "payment_method": data["payment_method"],
        "items": [dict(item) for item in cart],
        "comment": data.get("comment", ""),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    success = await send_admin_order(bot, order_data)
    if success:
        await clear_user_cart(uid)
        USER_ORDERS.setdefault(uid, []).append(order_data)
        confirm_text = t(uid, "order_confirmed").format(order_id=order_id)
        try:
            await callback.message.edit_text(confirm_text)
        except Exception:
            await callback.message.answer(confirm_text)
        await callback.message.answer(t(uid, "main_menu"), reply_markup=get_main_keyboard(uid))
        await state.clear()
    else:
        await callback.answer(t(uid, "send_failed"), show_alert=True)
    await callback.answer()


async def show_orders(message: Message, uid: int):
    orders = USER_ORDERS.get(uid, [])
    if not orders:
        await message.answer(t(uid, "no_orders"), reply_markup=get_main_keyboard(uid))
        return
    text = t(uid, "order_history")
    buttons = []
    for order in orders[-5:]:
        total = sum(item["quantity"] * item["price"] for item in order["items"])
        text += f"\n🆕 #{order['id']} - {format_price(total)} сум"
        buttons.append(
            [InlineKeyboardButton(text=f"{t(uid, 'repeat_order')} #{order['id']}", callback_data=f"repeat_{order['id']}")]
        )
    buttons.append([InlineKeyboardButton(text=t(uid, "back"), callback_data="back_to_menu")])
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@dp.message(F.text.in_(all_texts("orders")))
async def orders_handler(message: Message):
    await show_orders(message, message.from_user.id)


@dp.callback_query(F.data.startswith("repeat_"))
async def repeat_order_handler(callback: CallbackQuery):
    uid = callback.from_user.id
    try:
        order_id = int(callback.data.split("_", 1)[1])
    except ValueError:
        await callback.answer()
        return
    order = next((o for o in USER_ORDERS.get(uid, []) if o["id"] == order_id), None)
    if not order:
        await callback.answer(t(uid, "no_orders"), show_alert=True)
        return
    await save_user_cart(uid, [dict(item) | {"line_id": generate_line_id()} for item in order["items"]])
    await callback.answer()
    await render_cart(callback.message, uid)


@dp.callback_query(F.data == "clear_cart")
async def clear_cart_handler(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    await clear_user_cart(uid)
    await state.clear()
    try:
        await callback.message.edit_text(t(uid, "empty_cart"))
    except Exception:
        await callback.message.answer(t(uid, "empty_cart"), reply_markup=get_main_keyboard(uid))
    await callback.answer()


@dp.callback_query(F.data.startswith("back_to_"))
async def back_handler(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    target = callback.data.split("back_to_", 1)[1]
    data = await state.get_data()

    if target == "menu":
        await delete_user_messages(uid)
        await state.clear()
        await send_main_menu(callback.message, uid)
    elif target == "cart":
        await state.clear()
        await render_cart(callback.message, uid)
    elif target == "address":
        await state.set_state(OrderState.address_type)
        await callback.message.edit_text(t(uid, "order_address"), reply_markup=get_address_keyboard(uid))
    elif target == "comment":
        await state.set_state(OrderState.comment)
        await callback.message.edit_text(t(uid, "choose_order_comment"), reply_markup=get_comment_keyboard(uid))
    elif target == "payment":
        await state.set_state(OrderState.payment)
        await callback.message.edit_text(t(uid, "order_payment"), reply_markup=get_payment_keyboard(uid))
    elif target == "checkout":
        if data.get("phone"):
            await state.set_state(OrderState.address_type)
            await callback.message.edit_text(t(uid, "order_address"), reply_markup=get_address_keyboard(uid))
        else:
            await start_checkout(callback.message, state, uid)
    else:
        await state.clear()
        await send_main_menu(callback.message, uid)
    await callback.answer()


async def main():
    logger.info("Запуск бота...")
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="menu", description="Меню"),
            BotCommand(command="cart", description="Корзина"),
        ]
    )
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
