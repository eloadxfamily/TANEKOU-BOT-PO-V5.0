"""
TANEKOU BOT PO — Point d'entrée principal
Lancez avec : python main.py
"""
import logging
import os
import sys
from telegram.ext import Application

from config import Config
from db.database import init_db
from bot.handlers import register_handlers


def _setup_logging() -> None:
    """Configure le logging APRÈS que data/ soit créé."""
    os.makedirs("data", exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("data/tanekou_bot.log", encoding="utf-8"),
        ],
    )
    # Réduire le bruit des libs externes
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)


log = logging.getLogger("tanekou.main")


def main() -> None:
    # ── Dossier data + logging ────────────────────────────────
    _setup_logging()
    errors = Config.validate()
    if errors:
        print("Erreurs de configuration détectées :")
        for e in errors:
            print(f"  {e}")
        print("\nCopie .env.example en .env et remplis les valeurs manquantes.")
        sys.exit(1)

    # ── Initialisation DB ─────────────────────────────────────
    init_db()
    log.info("Base de données initialisée")

    # ── Démarrage du bot Telegram ─────────────────────────────
    mode = "DÉMO" if Config.PO_DEMO else "RÉEL"
    log.info(f"Démarrage {Config.BOT_NAME} v{Config.VERSION} — Mode {mode}")
    print(f"\n{'='*50}")
    print(f"  {Config.BOT_NAME} v{Config.VERSION}")
    print(f"  by {Config.AUTHOR}")
    print(f"  Mode : {mode}")
    print(f"{'='*50}\n")

    app = Application.builder().token(Config.TELEGRAM_TOKEN).build()
    register_handlers(app)

    log.info("Bot démarré — en attente de commandes Telegram")
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
