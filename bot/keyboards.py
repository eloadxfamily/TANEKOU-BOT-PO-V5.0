"""
TANEKOU BOT PO — Claviers inline Telegram
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("▶️ Démarrer", callback_data="menu_start"),
            InlineKeyboardButton("⏹ Arrêter",   callback_data="menu_stop"),
        ],
        [
            InlineKeyboardButton("📊 Stats",     callback_data="menu_stats"),
            InlineKeyboardButton("💰 Solde",     callback_data="menu_balance"),
        ],
        [
            InlineKeyboardButton("⚙️ Config",    callback_data="menu_config"),
            InlineKeyboardButton("📜 Historique",callback_data="menu_history"),
        ],
        [
            InlineKeyboardButton("🔄 Reset MG",  callback_data="menu_reset"),
            InlineKeyboardButton("ℹ️ Status",    callback_data="menu_status"),
        ],
    ])


def pair_selection(active_pairs: list[str]) -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for i, pair in enumerate(active_pairs):
        row.append(InlineKeyboardButton(pair, callback_data=f"pair_{pair}"))
        if len(row) == 2 or i == len(active_pairs) - 1:
            buttons.append(row)
            row = []
    buttons.append([InlineKeyboardButton("↩️ Retour", callback_data="menu_back")])
    return InlineKeyboardMarkup(buttons)


def mode_selection() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🟡 Mode DÉMO",  callback_data="mode_demo"),
            InlineKeyboardButton("🔴 Mode RÉEL",  callback_data="mode_real"),
        ],
        [InlineKeyboardButton("↩️ Retour", callback_data="menu_back")],
    ])


def confirm_real_mode() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirmer RÉEL", callback_data="confirm_real_yes"),
            InlineKeyboardButton("❌ Annuler",         callback_data="confirm_real_no"),
        ],
    ])


def amount_selection() -> InlineKeyboardMarkup:
    amounts = [1, 2, 5, 10, 25, 50]
    buttons = []
    row = []
    for i, a in enumerate(amounts):
        row.append(InlineKeyboardButton(f"${a}", callback_data=f"amount_{a}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("↩️ Retour", callback_data="menu_back")])
    return InlineKeyboardMarkup(buttons)


def back_only() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("↩️ Menu principal", callback_data="menu_main")]
    ])
