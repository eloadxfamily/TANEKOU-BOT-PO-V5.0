import os
from dotenv import load_dotenv
from typing import List, Tuple

load_dotenv()


class Config:
    # ── Identité ─────────────────────────────────────────────
    BOT_NAME: str = "TANEKOU BOT PO"
    VERSION: str  = "2.0.0"
    AUTHOR: str   = "eloadXFamily / TANEKOU TRADE"

    # ── Telegram ──────────────────────────────────────────────
    TELEGRAM_TOKEN: str   = os.getenv("TELEGRAM_TOKEN", "")
    TELEGRAM_CHAT_ID: int = int(os.getenv("TELEGRAM_CHAT_ID", "0"))

    # ── Pocket Option ─────────────────────────────────────────
    PO_SSID: str  = os.getenv("PO_SSID", "")
    PO_DEMO: bool = os.getenv("PO_DEMO", "true").lower() in ("true", "1", "yes")

    # ── Gestion des mises (Kelly fractional — sans martingale) ─
    # BASE_AMOUNT sert de mise plancher si le solde est inconnu / trop faible.
    BASE_AMOUNT: float    = float(os.getenv("BASE_AMOUNT", "1.0"))
    # KELLY_FRACTION : fraction du solde risquée par trade (0.01 = 1 %).
    # Recommandé : 0.01–0.02. Ne pas dépasser 0.02.
    KELLY_FRACTION: float = float(os.getenv("KELLY_FRACTION", "0.01"))

    # ── Filtres de qualité de signal ──────────────────────────
    # Score minimum pour déclencher un trade (0-100).
    # Seuil élevé (>= 82) = moins de trades, meilleure sélection.
    MIN_SIGNAL_SCORE: int = int(os.getenv("MIN_SIGNAL_SCORE", "82"))
    # Nombre minimum d'indicateurs alignés dans la même direction.
    MIN_CONFLUENCES: int  = int(os.getenv("MIN_CONFLUENCES", "3"))

    # ── Filtres de session (UTC) ──────────────────────────────
    # Seules les fenêtres London Open + NY Open sont autorisées.
    # Désactivable via SESSION_FILTER_ENABLED=false dans .env.
    SESSION_FILTER_ENABLED: bool = os.getenv("SESSION_FILTER_ENABLED", "true").lower() in ("true", "1", "yes")
    # Chaque tuple = (heure_début_UTC, heure_fin_UTC) [début inclus, fin exclue]
    SESSION_WINDOWS: List[Tuple[int, int]] = [
        (8, 10),    # London Open
        (13, 15),   # New York Open
    ]

    # ── Risk management ───────────────────────────────────────
    TRADE_EXPIRATION: int         = int(os.getenv("TRADE_EXPIRATION", "60"))
    MAX_DAILY_LOSS_PERCENT: float = float(os.getenv("MAX_DAILY_LOSS_PERCENT", "10"))

    # Paramètres techniques (non exposés dans .env)
    CANDLE_PERIOD: int        = 60
    CANDLES_HISTORY: int      = 100
    RESULT_POLL_INTERVAL: int = 2
    WS_RECONNECT_DELAY: int   = 5
    WS_MAX_RETRIES: int       = 10

    # ── Paires disponibles ────────────────────────────────────
    ALL_PAIRS: List[str] = [
        "EURUSD_otc", "AUDCAD_otc", "GBPUSD_otc", "USDJPY_otc",
        "EURJPY_otc", "AUDUSD_otc", "NZDUSD_otc", "USDCAD_otc",
        "EURGBP_otc",
    ]

    _raw_pairs: str = os.getenv("ACTIVE_PAIRS", "EURUSD_otc,AUDCAD_otc,GBPUSD_otc,USDJPY_otc")
    ACTIVE_PAIRS: List[str] = [p.strip() for p in _raw_pairs.split(",") if p.strip()]

    # ── Validation ────────────────────────────────────────────
    @classmethod
    def validate(cls) -> List[str]:
        """Retourne la liste des erreurs de configuration (vide = tout OK)."""
        errors: List[str] = []

        if not cls.TELEGRAM_TOKEN or cls.TELEGRAM_TOKEN.startswith("123456"):
            errors.append("❌ TELEGRAM_TOKEN non configuré ou placeholder")

        if cls.TELEGRAM_CHAT_ID <= 0:
            errors.append("❌ TELEGRAM_CHAT_ID non configuré (doit être > 0)")

        if not cls.PO_SSID or cls.PO_SSID.startswith("XXX"):
            errors.append("❌ PO_SSID non configuré")

        if cls.BASE_AMOUNT <= 0:
            errors.append("❌ BASE_AMOUNT doit être supérieur à 0")

        if not 0.005 <= cls.KELLY_FRACTION <= 0.05:
            errors.append("⚠️  KELLY_FRACTION hors plage recommandée (0.005–0.05)")

        if not 70 <= cls.MIN_SIGNAL_SCORE <= 100:
            errors.append("❌ MIN_SIGNAL_SCORE doit être entre 70 et 100")

        if not 1 <= cls.MIN_CONFLUENCES <= 5:
            errors.append("❌ MIN_CONFLUENCES doit être entre 1 et 5")

        return errors

    @classmethod
    def is_valid(cls) -> bool:
        return len(cls.validate()) == 0

    @classmethod
    def summary(cls) -> str:
        mode = "🟡 DÉMO" if cls.PO_DEMO else "🔴 RÉEL"
        sessions = " | ".join(
            f"{s:02d}h-{e:02d}h UTC" for s, e in cls.SESSION_WINDOWS
        )
        filter_str = f"Actif ({sessions})" if cls.SESSION_FILTER_ENABLED else "Désactivé"
        return (
            f"*{cls.BOT_NAME} v{cls.VERSION}*\n"
            f"Mode : {mode}\n"
            f"Mise Kelly : {cls.KELLY_FRACTION * 100:.1f}% du solde (min ${cls.BASE_AMOUNT})\n"
            f"Score minimum signal : {cls.MIN_SIGNAL_SCORE}%\n"
            f"Confluences minimum : {cls.MIN_CONFLUENCES}\n"
            f"Filtre de session : {filter_str}\n"
            f"Expiration : {cls.TRADE_EXPIRATION}s\n"
            f"Paires actives : {', '.join(cls.ACTIVE_PAIRS)}\n"
            f"Perte max/jour : {cls.MAX_DAILY_LOSS_PERCENT}%"
        )
