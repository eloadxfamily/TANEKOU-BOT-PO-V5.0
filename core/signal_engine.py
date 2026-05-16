"""
TANEKOU BOT PO — Moteur de signaux v2
Combine : MACD divergence | RSI | Bollinger Bands | EMA Cross | Patterns chandeliers
Retourne un score 0-100, une direction ('call' | 'put') et un compte de confluences.

Seuils recommandés (config.py) :
  MIN_SIGNAL_SCORE = 82   — filtre les signaux faibles
  MIN_CONFLUENCES  = 3    — exige au moins 3 indicateurs alignés
"""
from dataclasses import dataclass
from typing import Optional
import pandas as pd


@dataclass
class Signal:
    direction:       str   # 'call' | 'put'
    score:           int   # 0-100
    label:           str   # ex. "MACD Divergence + RSI Oversold"
    components:      dict  # détail de chaque indicateur
    confluence_count: int  # nombre d'indicateurs alignés dans la direction retenue


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta    = close.diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs       = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _macd(close: pd.Series):
    ema12       = _ema(close, 12)
    ema26       = _ema(close, 26)
    macd_line   = ema12 - ema26
    signal_line = _ema(macd_line, 9)
    histogram   = macd_line - signal_line
    return macd_line, signal_line, histogram


def _bollinger(close: pd.Series, period: int = 20, std_dev: float = 2.0):
    sma   = close.rolling(period).mean()
    std   = close.rolling(period).std()
    upper = sma + std_dev * std
    lower = sma - std_dev * std
    return upper, sma, lower


def _is_hammer(o, h, l, c) -> bool:
    body        = abs(c - o)
    lower_wick  = o - l if c >= o else c - l
    upper_wick  = h - max(o, c)
    return body > 0 and lower_wick >= 2 * body and upper_wick <= 0.3 * body


def _is_shooting_star(o, h, l, c) -> bool:
    body        = abs(c - o)
    upper_wick  = h - max(o, c)
    lower_wick  = min(o, c) - l
    return body > 0 and upper_wick >= 2 * body and lower_wick <= 0.3 * body


def _is_bullish_engulfing(prev_o, prev_c, curr_o, curr_c) -> bool:
    return (prev_c < prev_o) and (curr_c > curr_o) and (curr_c > prev_o) and (curr_o < prev_c)


def _is_bearish_engulfing(prev_o, prev_c, curr_o, curr_c) -> bool:
    return (prev_c > prev_o) and (curr_c < curr_o) and (curr_c < prev_o) and (curr_o > prev_c)


def analyze(candles: list[dict]) -> Optional[Signal]:
    """
    Analyse une liste de bougies et retourne un Signal si le score >= seuil.

    Chaque bougie : {"time": int, "open": float, "high": float, "low": float, "close": float}
    Retourne None si données insuffisantes.
    Le filtre MIN_SIGNAL_SCORE et MIN_CONFLUENCES est appliqué dans trader.py.
    """
    if len(candles) < 50:
        return None

    df    = pd.DataFrame(candles).sort_values("time").reset_index(drop=True)
    close = df["close"]
    open_ = df["open"]
    high  = df["high"]
    low   = df["low"]

    # ── Indicateurs ───────────────────────────────────────────
    rsi                          = _rsi(close)
    macd_line, signal_line, histogram = _macd(close)
    bb_upper, _, bb_lower        = _bollinger(close)
    ema9  = _ema(close, 9)
    ema21 = _ema(close, 21)

    idx   = len(df) - 1
    prev  = len(df) - 2
    prev2 = len(df) - 3

    rsi_now    = rsi.iloc[idx]
    hist_now   = histogram.iloc[idx]
    hist_prev  = histogram.iloc[prev]
    close_now  = close.iloc[idx]
    close_prev = close.iloc[prev]
    ema9_now   = ema9.iloc[idx]
    ema21_now  = ema21.iloc[idx]
    ema9_prev  = ema9.iloc[prev]
    ema21_prev = ema21.iloc[prev]
    bb_low_now = bb_lower.iloc[idx]
    bb_up_now  = bb_upper.iloc[idx]

    components  = {}
    call_score  = 0
    put_score   = 0

    # ── RSI (max 25 pts) ─────────────────────────────────────
    if rsi_now < 25:
        call_score += 25
        components["RSI"] = f"Oversold extrême ({rsi_now:.1f}) → CALL +25"
    elif rsi_now < 35:
        call_score += 15
        components["RSI"] = f"Oversold ({rsi_now:.1f}) → CALL +15"
    elif rsi_now > 75:
        put_score += 25
        components["RSI"] = f"Overbought extrême ({rsi_now:.1f}) → PUT +25"
    elif rsi_now > 65:
        put_score += 15
        components["RSI"] = f"Overbought ({rsi_now:.1f}) → PUT +15"
    else:
        components["RSI"] = f"Neutre ({rsi_now:.1f})"

    # ── MACD Divergence (max 30 pts) ─────────────────────────
    price_lower_low   = close.iloc[idx] < close.iloc[prev2]
    macd_higher_low   = macd_line.iloc[idx] > macd_line.iloc[prev2]
    price_higher_high = close.iloc[idx] > close.iloc[prev2]
    macd_lower_high   = macd_line.iloc[idx] < macd_line.iloc[prev2]

    if price_lower_low and macd_higher_low:
        call_score += 30
        components["MACD"] = "Divergence haussière → CALL +30"
    elif price_higher_high and macd_lower_high:
        put_score += 30
        components["MACD"] = "Divergence baissière → PUT +30"
    elif hist_now > 0 and hist_prev <= 0:
        call_score += 15
        components["MACD"] = "Histogramme croise 0 (haussier) → CALL +15"
    elif hist_now < 0 and hist_prev >= 0:
        put_score += 15
        components["MACD"] = "Histogramme croise 0 (baissier) → PUT +15"
    else:
        components["MACD"] = "Neutre"

    # ── Bollinger Bands (max 20 pts) ─────────────────────────
    if close_now <= bb_low_now and close_prev > bb_lower.iloc[prev]:
        call_score += 20
        components["BB"] = "Rebond bande inf → CALL +20"
    elif close_now >= bb_up_now and close_prev < bb_upper.iloc[prev]:
        put_score += 20
        components["BB"] = "Rebond bande sup → PUT +20"
    else:
        components["BB"] = "Neutre"

    # ── EMA Cross (max 15 pts) ────────────────────────────────
    golden_cross = ema9_now > ema21_now and ema9_prev <= ema21_prev
    death_cross  = ema9_now < ema21_now and ema9_prev >= ema21_prev

    if golden_cross:
        call_score += 15
        components["EMA"] = "Golden cross 9/21 → CALL +15"
    elif death_cross:
        put_score += 15
        components["EMA"] = "Death cross 9/21 → PUT +15"
    elif ema9_now > ema21_now:
        call_score += 5
        components["EMA"] = "Tendance haussière → CALL +5"
    elif ema9_now < ema21_now:
        put_score += 5
        components["EMA"] = "Tendance baissière → PUT +5"

    # ── Patterns chandeliers (max 10 pts) ────────────────────
    o, h, l, c = open_.iloc[idx], high.iloc[idx], low.iloc[idx], close.iloc[idx]
    po, pc     = open_.iloc[prev], close.iloc[prev]

    if _is_hammer(o, h, l, c):
        call_score += 10
        components["Pattern"] = "Hammer → CALL +10"
    elif _is_shooting_star(o, h, l, c):
        put_score += 10
        components["Pattern"] = "Shooting Star → PUT +10"
    elif _is_bullish_engulfing(po, pc, o, c):
        call_score += 10
        components["Pattern"] = "Bullish Engulfing → CALL +10"
    elif _is_bearish_engulfing(po, pc, o, c):
        put_score += 10
        components["Pattern"] = "Bearish Engulfing → PUT +10"
    else:
        components["Pattern"] = "Neutre"

    # ── Résultat ──────────────────────────────────────────────
    max_score = 100

    if call_score >= put_score and call_score > 0:
        score_pct        = min(int(call_score / max_score * 100), 99)
        direction_key    = "CALL"
        confluence_count = sum(1 for v in components.values() if direction_key in v)
        labels           = [v for v in components.values() if direction_key in v]
        return Signal(
            direction        = "call",
            score            = score_pct,
            label            = " | ".join(labels) if labels else "Signal haussier composite",
            components       = components,
            confluence_count = confluence_count,
        )

    elif put_score > call_score and put_score > 0:
        score_pct        = min(int(put_score / max_score * 100), 99)
        direction_key    = "PUT"
        confluence_count = sum(1 for v in components.values() if direction_key in v)
        labels           = [v for v in components.values() if direction_key in v]
        return Signal(
            direction        = "put",
            score            = score_pct,
            label            = " | ".join(labels) if labels else "Signal baissier composite",
            components       = components,
            confluence_count = confluence_count,
        )

    return None
