"""
TANEKOU BOT PO — Gestionnaire de mise (Kelly Fractional)
Remplace la martingale par une mise fixe proportionnelle au solde.

Logique :
  mise = max(kelly_fraction * solde, base_amount)

Avantages vs martingale :
  - Pas d'escalade des pertes consécutives
  - Taille de position automatiquement réduite quand le solde baisse (drawdown control)
  - Taille de position augmente naturellement quand le solde croît (compounding)
"""
from dataclasses import dataclass, field
import logging

log = logging.getLogger("tanekou.stake_manager")


@dataclass
class StakeManager:
    kelly_fraction: float   # fraction du solde par trade, ex. 0.01 = 1 %
    base_amount: float      # mise minimale / fallback si solde inconnu

    session_wins: int   = 0
    session_losses: int = 0
    session_pnl: float  = 0.0

    def get_stake(self, balance: float) -> float:
        """Calcule la mise pour le prochain trade."""
        if balance <= 0:
            return self.base_amount
        stake = round(balance * self.kelly_fraction, 2)
        return max(stake, self.base_amount)

    def on_win(self, profit: float) -> dict:
        self.session_wins += 1
        self.session_pnl += profit
        log.info(f"✅ WIN — profit: +{profit:.2f} — PnL session: {self.session_pnl:+.2f}")
        return {
            "event":       "win",
            "profit":      profit,
            "session_pnl": self.session_pnl,
        }

    def on_loss(self, amount: float) -> dict:
        self.session_losses += 1
        self.session_pnl -= amount
        log.warning(f"❌ LOSS — perte: -{amount:.2f} — PnL session: {self.session_pnl:+.2f}")
        return {
            "event":       "loss",
            "amount":      amount,
            "session_pnl": self.session_pnl,
        }

    def force_reset(self) -> None:
        self.session_wins   = 0
        self.session_losses = 0
        self.session_pnl    = 0.0
        log.info("🔄 StakeManager reset")

    def summary(self) -> str:
        total   = self.session_wins + self.session_losses
        winrate = round(self.session_wins / total * 100, 1) if total > 0 else 0
        return (
            f"📊 *Gestion de mise — Kelly {self.kelly_fraction * 100:.1f}%*\n"
            f"Session — Gains : {self.session_wins} | Pertes : {self.session_losses}\n"
            f"Winrate : {winrate}%\n"
            f"PnL session : {self.session_pnl:+.2f}$"
        )


def build_stake_preview(kelly_fraction: float, base_amount: float) -> str:
    """Affiche la mise estimée pour différents niveaux de solde."""
    lines = [f"*Aperçu des mises (Kelly {kelly_fraction * 100:.1f}%) :*"]
    for balance in [50, 100, 200, 500, 1000]:
        stake = max(round(balance * kelly_fraction, 2), base_amount)
        lines.append(f"  Solde ${balance} → mise ${stake:.2f}")
    return "\n".join(lines)
