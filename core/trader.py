"""
TANEKOU BOT PO — Orchestrateur de trading v2
Coordonne : filtres de session → signaux → validation → exécution → Kelly sizing → DB → notification Telegram

Changements v2 :
  - Martingale supprimée → StakeManager (Kelly fractional, mise fixe)
  - Filtre de session London Open (08-10 UTC) + NY Open (13-15 UTC)
  - Seuil de confluences minimum (MIN_CONFLUENCES)
"""
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional, Callable

from config import Config
from core.po_client import PocketOptionClient
from core.signal_engine import Signal, analyze
from core.martingale import StakeManager
from db.database import (
    insert_trade, update_trade_result,
    record_trade_result, get_today_stats
)

log = logging.getLogger("tanekou.trader")


class TradingSession:
    """Gère une session de trading complète."""

    def __init__(self, notify_cb: Callable, cfg: Config = None):
        self.cfg          = cfg or Config
        self.notify       = notify_cb
        self.po           = PocketOptionClient(
            ssid=self.cfg.PO_SSID,
            is_demo=self.cfg.PO_DEMO,
        )
        self.stake_manager = StakeManager(
            kelly_fraction=self.cfg.KELLY_FRACTION,
            base_amount=self.cfg.BASE_AMOUNT,
        )
        self.running       = False
        self.active_pair   = None
        self.starting_bal  = 0.0
        self._task         = None

    # ── Filtres de session ────────────────────────────────────

    def _is_session_allowed(self) -> bool:
        """Retourne True si l'heure UTC actuelle est dans une fenêtre de trading autorisée."""
        if not self.cfg.SESSION_FILTER_ENABLED:
            return True
        h = datetime.now(timezone.utc).hour
        return any(start <= h < end for start, end in self.cfg.SESSION_WINDOWS)

    def _next_session_info(self) -> str:
        """Retourne l'heure de la prochaine session (pour les notifications)."""
        h = datetime.now(timezone.utc).hour
        for start, end in sorted(self.cfg.SESSION_WINDOWS):
            if h < start:
                return f"prochaine session : {start:02d}h UTC"
        return f"prochaine session : {self.cfg.SESSION_WINDOWS[0][0]:02d}h UTC (demain)"

    # ── Cycle de vie ──────────────────────────────────────────

    async def start(self, pair: str) -> bool:
        """Démarre la session sur une paire donnée."""
        if self.running:
            return False

        connected = await self.po.connect()
        if not connected:
            await self.notify("❌ Impossible de se connecter à PocketOption. Vérifie ton SSID.")
            return False

        self.active_pair  = pair
        self.starting_bal = await self.po.get_balance()
        self.running      = True
        self.stake_manager.force_reset()

        mode = "🟡 DÉMO" if self.cfg.PO_DEMO else "🔴 RÉEL"
        sessions = " | ".join(
            f"{s:02d}h-{e:02d}h UTC" for s, e in self.cfg.SESSION_WINDOWS
        )
        filter_str = f"Actif ({sessions})" if self.cfg.SESSION_FILTER_ENABLED else "Désactivé"

        await self.notify(
            f"🚀 *{self.cfg.BOT_NAME}* démarré\n"
            f"Mode : {mode}\n"
            f"Paire : `{pair}`\n"
            f"Mise Kelly : {self.cfg.KELLY_FRACTION * 100:.1f}% du solde\n"
            f"Score min : {self.cfg.MIN_SIGNAL_SCORE} | Confluences min : {self.cfg.MIN_CONFLUENCES}\n"
            f"Filtre session : {filter_str}\n"
            f"Solde initial : ${self.starting_bal:.2f}"
        )

        self._task = asyncio.create_task(self._trading_loop())
        return True

    async def stop(self) -> str:
        """Arrête la session et retourne le résumé."""
        self.running = False
        if self._task and not self._task.done():
            self._task.cancel()

        final_bal = "N/A"
        if self.po.is_connected:
            try:
                bal       = await self.po.get_balance()
                final_bal = f"${bal:.2f}"
            except Exception:
                pass

        await self.po.disconnect()

        stats   = get_today_stats(self.cfg.PO_DEMO)
        summary = (
            f"🛑 *Session arrêtée*\n\n"
            f"📊 *Résultats session*\n"
            f"Trades : {stats['total_trades']}\n"
            f"Gains : {stats['wins']} | Pertes : {stats['losses']}\n"
            f"Winrate : {stats['winrate']}%\n"
            f"Profit net : {stats['net_profit']:+.2f}$\n"
            f"Solde final : {final_bal}"
        )
        return summary

    # ── Boucle principale ─────────────────────────────────────

    async def _trading_loop(self) -> None:
        log.info(f"Boucle trading démarrée — paire {self.active_pair}")
        await self.po.subscribe_candles(self.active_pair, self.cfg.CANDLE_PERIOD)

        while self.running:
            try:
                # 1. Contrôle perte journalière
                await self._check_daily_loss()
                if not self.running:
                    break

                # 2. Filtre de session
                if not self._is_session_allowed():
                    log.debug("Hors fenêtre de session — attente 5 min")
                    await asyncio.sleep(300)
                    continue

                # 3. Récupération des bougies
                candles = await self.po.get_candles(
                    self.active_pair,
                    self.cfg.CANDLE_PERIOD,
                    self.cfg.CANDLES_HISTORY,
                )
                if len(candles) < 50:
                    log.debug("Pas assez de bougies — attente")
                    await asyncio.sleep(5)
                    continue

                # 4. Analyse du signal
                signal = analyze(candles)

                if signal is None:
                    log.debug("Aucun signal")
                    await asyncio.sleep(self.cfg.CANDLE_PERIOD)
                    continue

                if signal.score < self.cfg.MIN_SIGNAL_SCORE:
                    log.debug(f"Score insuffisant ({signal.score}/{self.cfg.MIN_SIGNAL_SCORE})")
                    await asyncio.sleep(self.cfg.CANDLE_PERIOD)
                    continue

                if signal.confluence_count < self.cfg.MIN_CONFLUENCES:
                    log.debug(
                        f"Confluences insuffisantes "
                        f"({signal.confluence_count}/{self.cfg.MIN_CONFLUENCES})"
                    )
                    await asyncio.sleep(self.cfg.CANDLE_PERIOD)
                    continue

                # 5. Signal validé → notification + exécution
                await self._notify_signal(signal)
                await self._execute_trade(signal)

                # Pause (au moins une bougie)
                await asyncio.sleep(self.cfg.CANDLE_PERIOD)

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"Erreur boucle trading : {e}", exc_info=True)
                await self.notify(f"⚠️ Erreur trading : `{str(e)[:100]}`")
                await asyncio.sleep(10)

    # ── Exécution d'un trade ──────────────────────────────────

    async def _execute_trade(self, signal: Signal) -> None:
        # Calcul de la mise via Kelly
        try:
            balance = await self.po.get_balance()
        except Exception:
            balance = 0.0
        stake = self.stake_manager.get_stake(balance)

        trade_id = f"tnk_{int(time.time() * 1000)}"
        insert_trade(
            trade_id       = trade_id,
            pair           = self.active_pair,
            direction      = signal.direction,
            amount         = stake,
            martingale_level = 0,          # toujours 0, martingale supprimée
            signal_score   = signal.score,
            signal_type    = signal.label,
            is_demo        = self.cfg.PO_DEMO,
            expiration_sec = self.cfg.TRADE_EXPIRATION,
        )

        await self.notify(
            f"⚡ *Trade ouvert*\n"
            f"Paire : `{self.active_pair}`\n"
            f"Direction : {'📈 CALL' if signal.direction == 'call' else '📉 PUT'}\n"
            f"Mise : ${stake:.2f} ({self.cfg.KELLY_FRACTION * 100:.1f}% Kelly)\n"
            f"Signal : {signal.score}/100 — {signal.confluence_count} confluences\n"
            f"Raisons : {signal.label[:80]}"
        )

        result = await self.po.place_trade(
            symbol     = self.active_pair,
            direction  = signal.direction,
            amount     = stake,
            expiration = self.cfg.TRADE_EXPIRATION,
        )

        await self._handle_result(trade_id, stake, signal, result)

    async def _handle_result(
        self, trade_id: str, stake: float, signal: Signal, result: Optional[dict]
    ) -> None:
        if result is None:
            await self.notify("⏱️ Résultat non reçu (timeout) — trade ignoré")
            return

        profit_raw = (
            result.get("profit")
            or result.get("win")
            or result.get("result_amount")
            or 0
        )
        try:
            profit = float(profit_raw)
        except (TypeError, ValueError):
            profit = 0.0

        is_win  = profit > 0
        outcome = "win" if is_win else "loss"
        payout  = round(profit / stake * 100, 1) if is_win and stake > 0 else 0

        update_trade_result(trade_id, outcome, profit if is_win else -stake, payout)
        record_trade_result(outcome, profit if is_win else -stake, self.cfg.PO_DEMO)

        if is_win:
            self.stake_manager.on_win(profit)
            try:
                current_bal = await self.po.get_balance()
                bal_str     = f"${current_bal:.2f}"
            except Exception:
                bal_str = "N/A"
            msg = (
                f"✅ *Trade GAGNÉ*\n"
                f"Profit : +${profit:.2f}\n"
                f"Solde : {bal_str}"
            )
        else:
            self.stake_manager.on_loss(stake)
            msg = (
                f"❌ *Trade PERDU*\n"
                f"Perte : -${stake:.2f}\n"
                + self.stake_manager.summary()
            )

        await self.notify(msg)

    # ── Contrôle de la perte journalière ─────────────────────

    async def _check_daily_loss(self) -> None:
        if self.starting_bal <= 0:
            return
        stats    = get_today_stats(self.cfg.PO_DEMO)
        net      = stats.get("net_profit", 0)
        if net == 0:
            return
        loss_pct = abs(net) / self.starting_bal * 100
        if net < 0 and loss_pct >= self.cfg.MAX_DAILY_LOSS_PERCENT:
            self.running = False
            await self.notify(
                f"🛑 *STOP — Perte journalière max atteinte*\n"
                f"Perte : {net:.2f}$ ({loss_pct:.1f}% du solde)\n"
                f"Limite configurée : {self.cfg.MAX_DAILY_LOSS_PERCENT}%\n"
                f"Trading arrêté pour aujourd'hui."
            )

    # ── Notify signal ─────────────────────────────────────────

    async def _notify_signal(self, signal: Signal) -> None:
        direction_str = "📈 CALL (HAUSSE)" if signal.direction == "call" else "📉 PUT (BAISSE)"
        await self.notify(
            f"🔍 *Signal validé*\n"
            f"Score : {signal.score}/100\n"
            f"Confluences : {signal.confluence_count}/{self.cfg.MIN_CONFLUENCES} min\n"
            f"Direction : {direction_str}\n"
            f"Raisons : {signal.label[:80]}"
        )

    # ── Actions manuelles ─────────────────────────────────────

    async def reset_stake_manager(self) -> None:
        self.stake_manager.force_reset()
        await self.notify("🔄 Compteurs de session réinitialisés — trading continue")

    async def switch_pair(self, new_pair: str) -> None:
        self.active_pair = new_pair
        await self.po.subscribe_candles(new_pair, self.cfg.CANDLE_PERIOD)
        await self.notify(f"🔀 Paire changée → `{new_pair}`")

    async def switch_mode(self, demo: bool) -> None:
        self.cfg.PO_DEMO = demo
        self.po.is_demo  = demo
        mode = "🟡 DÉMO" if demo else "🔴 RÉEL"
        await self.notify(f"Mode switché vers {mode} — redémarre pour appliquer")
