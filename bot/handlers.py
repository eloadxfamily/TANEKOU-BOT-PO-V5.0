"""
TANEKOU BOT PO — Handlers Telegram v2
Commandes + callbacks boutons inline
Sécurité : seul le TELEGRAM_CHAT_ID configuré peut contrôler le bot
"""
import logging
from typing import Optional
from telegram import Update, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes
)
from telegram.constants import ParseMode

from config import Config
from core.trader import TradingSession
from core.martingale import build_stake_preview
from db.database import get_today_stats, get_last_trades, get_global_stats
from bot.keyboards import (
    main_menu, pair_selection, mode_selection,
    confirm_real_mode, amount_selection, back_only
)

log = logging.getLogger("tanekou.bot")

# Session globale (une seule par instance)
_session: Optional[TradingSession] = None


# ── Sécurité ──────────────────────────────────────────────────────────────────

def _authorized(update: Update) -> bool:
    user_id = (
        update.effective_user.id
        if update.effective_user
        else update.callback_query.from_user.id if update.callback_query else 0
    )
    return user_id == Config.TELEGRAM_CHAT_ID


async def _deny(update: Update) -> None:
    msg = "⛔ Accès refusé — ce bot est privé."
    if update.message:
        await update.message.reply_text(msg)
    elif update.callback_query:
        await update.callback_query.answer(msg, show_alert=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _send(update: Update, text: str, keyboard: InlineKeyboardMarkup = None) -> None:
    kwargs = {"text": text, "parse_mode": ParseMode.MARKDOWN}
    if keyboard:
        kwargs["reply_markup"] = keyboard

    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(**kwargs)
        except Exception:
            await update.callback_query.message.reply_text(**kwargs)
    elif update.message:
        await update.message.reply_text(**kwargs)


def _get_notify(application: Application):
    """Retourne une coroutine de notification Telegram."""
    async def _notify(text: str):
        try:
            await application.bot.send_message(
                chat_id    = Config.TELEGRAM_CHAT_ID,
                text       = text,
                parse_mode = ParseMode.MARKDOWN,
            )
        except Exception as e:
            log.error(f"Erreur notification : {e}")
    return _notify


# ── Commandes ─────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await _deny(update); return

    mode = "🟡 DÉMO" if Config.PO_DEMO else "🔴 RÉEL"
    text = (
        f"👋 *{Config.BOT_NAME} v{Config.VERSION}*\n"
        f"by {Config.AUTHOR}\n\n"
        f"Mode actuel : {mode}\n"
        f"Paires : {', '.join(Config.ACTIVE_PAIRS)}\n\n"
        f"Commandes disponibles :\n"
        f"/trade — Démarrer le trading\n"
        f"/stop — Arrêter\n"
        f"/stats — Statistiques\n"
        f"/balance — Solde\n"
        f"/config — Configuration\n"
        f"/history — Derniers trades\n"
        f"/reset — Reset compteurs session\n"
        f"/mode — Changer démo/réel"
    )
    await _send(update, text, main_menu())


async def cmd_trade(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update): await _deny(update); return
    global _session

    if _session and _session.running:
        await _send(update, "⚠️ Session déjà en cours. Utilise /stop d'abord.", back_only())
        return

    await _send(update, "Choisis la paire à trader :", pair_selection(Config.ACTIVE_PAIRS))


async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update): await _deny(update); return
    global _session

    if not _session or not _session.running:
        await _send(update, "ℹ️ Aucune session en cours.", main_menu())
        return

    summary = await _session.stop()
    await _send(update, summary, main_menu())


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update): await _deny(update); return

    today   = get_today_stats(Config.PO_DEMO)
    global_ = get_global_stats(Config.PO_DEMO)
    mode    = "🟡 DÉMO" if Config.PO_DEMO else "🔴 RÉEL"

    text = (
        f"📊 *Statistiques — {mode}*\n\n"
        f"*Aujourd'hui*\n"
        f"Trades : {today['total_trades']}\n"
        f"Gains : {today['wins']} | Pertes : {today['losses']}\n"
        f"Winrate : {today['winrate']}%\n"
        f"Profit net : {today['net_profit']:+.2f}$\n\n"
        f"*All-time*\n"
        f"Trades total : {global_.get('total', 0)}\n"
        f"Winrate : {global_.get('winrate', 0)}%\n"
        f"Profit net : {global_.get('net_profit', 0):+.2f}$\n"
        f"Meilleur trade : +{global_.get('best_trade', 0):.2f}$\n"
        f"Pire trade : {global_.get('worst_trade', 0):.2f}$"
    )
    await _send(update, text, back_only())


async def cmd_balance(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update): await _deny(update); return
    global _session

    if _session and _session.po.is_connected:
        bal  = await _session.po.get_balance()
        mode = "🟡 DÉMO" if Config.PO_DEMO else "🔴 RÉEL"
        await _send(update, f"💰 Solde {mode} : *${bal:.2f}*", back_only())
    else:
        await _send(update, "ℹ️ Non connecté à PocketOption. Lance d'abord /trade.", back_only())


async def cmd_history(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update): await _deny(update); return

    trades = get_last_trades(Config.PO_DEMO, limit=10)
    if not trades:
        await _send(update, "📜 Aucun trade enregistré.", back_only())
        return

    lines = ["📜 *Derniers trades :*\n"]
    for t in trades:
        icon   = "✅" if t["result"] == "win" else ("❌" if t["result"] == "loss" else "⏳")
        profit = f"+${t['profit']:.2f}" if t["result"] == "win" else f"-${t['amount']:.2f}"
        lines.append(
            f"{icon} {t['pair']} {t['direction'].upper()} "
            f"${t['amount']:.2f} → {profit} "
            f"[{(t['opened_at'] or '')[:16]}]"
        )
    await _send(update, "\n".join(lines), back_only())


async def cmd_config(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update): await _deny(update); return

    preview = build_stake_preview(Config.KELLY_FRACTION, Config.BASE_AMOUNT)
    text    = Config.summary() + "\n\n" + preview
    await _send(update, text, back_only())


async def cmd_reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update): await _deny(update); return
    global _session

    if _session:
        await _session.reset_stake_manager()
    else:
        await _send(update, "ℹ️ Aucune session active.", main_menu())


async def cmd_mode(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update): await _deny(update); return

    mode = "🟡 DÉMO" if Config.PO_DEMO else "🔴 RÉEL"
    await _send(
        update,
        f"Mode actuel : {mode}\nChoisis un mode :",
        mode_selection()
    )


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update): await _deny(update); return
    global _session

    if not _session or not _session.running:
        await _send(update, "🔴 *Bot inactif*\nUtilise /trade pour démarrer.", main_menu())
        return

    mode = "🟡 DÉMO" if Config.PO_DEMO else "🔴 RÉEL"
    if _session.po.is_connected:
        try:
            raw_bal = await _session.po.get_balance()
            bal_str = f"${raw_bal:.2f}"
        except Exception:
            bal_str = "N/A"
    else:
        bal_str = "Non connecté"

    text = (
        f"🟢 *Bot actif*\n"
        f"Mode : {mode}\n"
        f"Paire : `{_session.active_pair}`\n"
        f"Solde : {bal_str}\n\n"
        + _session.stake_manager.summary()
    )
    await _send(update, text, back_only())


# ── Callbacks boutons ─────────────────────────────────────────────────────────

async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update): await _deny(update); return

    query = update.callback_query
    await query.answer()
    data  = query.data
    global _session

    if data == "menu_main":
        await _send(update, f"*{Config.BOT_NAME}* — Menu principal :", main_menu())

    elif data == "menu_start":
        await _send(update, "Choisis la paire :", pair_selection(Config.ACTIVE_PAIRS))

    elif data == "menu_stop":
        await cmd_stop(update, ctx)

    elif data == "menu_stats":
        await cmd_stats(update, ctx)

    elif data == "menu_balance":
        await cmd_balance(update, ctx)

    elif data == "menu_config":
        await cmd_config(update, ctx)

    elif data == "menu_history":
        await cmd_history(update, ctx)

    elif data == "menu_reset":
        await cmd_reset(update, ctx)

    elif data == "menu_status":
        await cmd_status(update, ctx)

    elif data == "menu_back":
        await _send(update, "Menu principal :", main_menu())

    elif data.startswith("pair_"):
        pair = data.replace("pair_", "")
        await _send(update, f"Paire sélectionnée : `{pair}`\nChoisis la mise de base :", amount_selection())
        ctx.user_data["selected_pair"] = pair

    elif data.startswith("amount_"):
        amount = float(data.replace("amount_", ""))
        Config.BASE_AMOUNT = amount
        pair = ctx.user_data.get("selected_pair", Config.ACTIVE_PAIRS[0])

        # Feedback immédiat — la connexion PO peut prendre quelques secondes
        mode_str = "🟡 DÉMO" if Config.PO_DEMO else "🔴 RÉEL"
        await _send(
            update,
            f"⏳ *Connexion à PocketOption en cours…*\n"
            f"Paire : `{pair}` | Mise : ${amount:.2f} | {mode_str}\n"
            f"_Patiente quelques secondes…_"
        )

        if _session:
            await _session.stop()

        _session = TradingSession(notify_cb=_get_notify(ctx.application))
        success  = await _session.start(pair)
        if not success:
            await _send(
                update,
                "❌ *Échec de connexion à PocketOption*\n\n"
                "💡 *Causes possibles :*\n"
                "• SSID expiré → reconnecte-toi sur pocketoption\.com, "
                "copie le cookie `session` et mets à jour `PO_SSID` dans ton `.env`\n"
                "• Réseau bloqué → vérifie que ton hébergeur autorise les WebSockets sortants\n"
                "• Serveur PO temporairement indisponible → réessaie dans 1 min",
                main_menu(),
            )

    elif data == "mode_demo":
        Config.PO_DEMO = True
        if _session:
            await _session.switch_mode(True)
        await _send(update, "✅ Mode DÉMO activé.", main_menu())

    elif data == "mode_real":
        await _send(
            update,
            "⚠️ *ATTENTION*\nTu vas trader avec de l'ARGENT RÉEL.\nConfirme :",
            confirm_real_mode()
        )

    elif data == "confirm_real_yes":
        Config.PO_DEMO = False
        if _session:
            await _session.switch_mode(False)
        await _send(update, "🔴 Mode RÉEL activé.", main_menu())

    elif data == "confirm_real_no":
        await _send(update, "Annulé — reste en mode DÉMO.", main_menu())


# ── Enregistrement ────────────────────────────────────────────────────────────

def register_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("trade",   cmd_trade))
    app.add_handler(CommandHandler("stop",    cmd_stop))
    app.add_handler(CommandHandler("stats",   cmd_stats))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("config",  cmd_config))
    app.add_handler(CommandHandler("reset",   cmd_reset))
    app.add_handler(CommandHandler("mode",    cmd_mode))
    app.add_handler(CommandHandler("status",  cmd_status))
    app.add_handler(CallbackQueryHandler(on_callback))
    log.info("Handlers Telegram enregistrés")
