"""
TANEKOU BOT PO — Client PocketOption v2.1
==========================================
Fix v2.1 : _ws_open() async avec fallback automatique sur 3 niveaux
  Niveau 1 : additional_headers=dict  (websockets 10-12)
  Niveau 2 : extra_headers=list       (websockets < 10)
  Niveau 3 : sans headers             (fallback universel)
"""

import asyncio
import json
import logging
import re
import ssl
import time
from typing import Callable, Dict, List, Optional

log = logging.getLogger("tanekou.po_client")

WS_URLS = [
    "wss://api.pocketoption.com/binary/websocket/v2",
    "wss://api-l.pocketoption.com/binary/websocket/v2",
    "wss://api-eu.pocketoption.com/binary/websocket/v2",
]

_HTTP_HEADERS_DICT = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Origin":          "https://pocketoption.com",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control":   "no-cache",
    "Pragma":          "no-cache",
}
_HTTP_HEADERS_LIST = list(_HTTP_HEADERS_DICT.items())


async def _ws_open(url: str):
    """
    Ouvre la connexion WebSocket avec fallback automatique sur 3 niveaux.
    Résout l'erreur :
      BaseEventLoop.create_connection() got an unexpected keyword argument 'additional_headers'
    """
    import websockets

    ssl_ctx = ssl.create_default_context()
    common = dict(
        ping_interval=None,
        close_timeout=5,
        open_timeout=20,
        max_size=2 ** 23,
        ssl=ssl_ctx,
    )

    # Niveau 1 : additional_headers=dict (websockets 10-12)
    try:
        ws = await websockets.connect(url, additional_headers=_HTTP_HEADERS_DICT, **common)
        log.debug("WS ouvert (additional_headers=dict)")
        return ws
    except TypeError as e:
        log.debug(f"Niveau 1 refusé ({e}) — essai niveau 2")

    # Niveau 2 : extra_headers=list (websockets < 10)
    try:
        ws = await websockets.connect(url, extra_headers=_HTTP_HEADERS_LIST, **common)
        log.debug("WS ouvert (extra_headers=list)")
        return ws
    except TypeError as e:
        log.debug(f"Niveau 2 refusé ({e}) — essai sans headers")

    # Niveau 3 : sans headers (fallback universel)
    log.warning("Connexion sans headers personnalisés (fallback niveau 3)")
    ws = await websockets.connect(url, **common)
    return ws


def _parse_sio(raw: str):
    if not raw:
        return None
    eng = raw[0]
    if eng == "2":
        return eng, None, "ping", None
    if eng == "0":
        try:
            return eng, None, "open", json.loads(raw[1:]) if len(raw) > 1 else {}
        except Exception:
            return eng, None, "open", {}
    if eng != "4" or len(raw) < 2:
        return None
    sio = raw[1]
    if sio == "0":
        payload = {}
        try:
            if len(raw) > 2:
                payload = json.loads(raw[2:])
        except Exception:
            pass
        return eng, sio, "connect", payload
    if sio == "2":
        try:
            arr = json.loads(raw[2:])
            if isinstance(arr, list) and arr:
                return eng, sio, arr[0], arr[1] if len(arr) > 1 else {}
        except Exception:
            pass
        return eng, sio, None, None
    if sio == "5":
        rest = raw[2:]
        m = re.match(r"^\d+-", rest)
        if m:
            rest = rest[m.end():]
        try:
            arr = json.loads(rest)
            if isinstance(arr, list) and arr:
                return eng, sio, arr[0], arr[1] if len(arr) > 1 else {}
        except Exception:
            pass
        return eng, sio, None, None
    return eng, sio, None, None


def _build_event(event: str, data) -> str:
    return f"42{json.dumps([event, data], separators=(',', ':'))}"


class PocketOptionClient:
    def __init__(self, ssid: str, is_demo: bool = True):
        self.ssid    = ssid
        self.is_demo = is_demo
        self._ws              = None
        self._connected       = False
        self._authed          = False
        self._balance         = 0.0
        self._candles: Dict[str, list]           = {}
        self._pending: Dict[str, asyncio.Future] = {}
        self._recv_task       = None
        self._ping_task       = None
        self._url_idx         = 0
        self._ping_interval   = 25.0
        self._on_balance_cb: Optional[Callable] = None
        self._on_candle_cb:  Optional[Callable] = None

    async def connect(self, max_retries: int = 10) -> bool:
        delay = 3.0
        for attempt in range(max_retries):
            url = WS_URLS[self._url_idx % len(WS_URLS)]
            try:
                log.info(
                    f"Connexion PocketOption — tentative {attempt+1}/{max_retries} — {url}"
                )
                self._ws = await _ws_open(url)
                self._recv_task = asyncio.create_task(self._receive_loop())

                # Attente auth max 15 s
                for _ in range(150):
                    if self._authed:
                        break
                    await asyncio.sleep(0.1)

                if self._authed:
                    log.info("✅ PocketOption : connecté et authentifié")
                    return True

                log.warning("Auth non reçue dans le délai — nouvelle tentative")
                await self._cleanup_tasks()

            except ssl.SSLError as exc:
                log.warning(f"Erreur SSL : {exc}")
                await self._cleanup_tasks()
            except OSError as exc:
                log.warning(f"Réseau inaccessible (OSError) : {exc}")
                await self._cleanup_tasks()
            except Exception as exc:
                log.warning(f"Échec connexion : {type(exc).__name__}: {exc}")
                await self._cleanup_tasks()

            self._url_idx += 1
            log.info(f"Nouvelle tentative dans {delay:.0f}s…")
            await asyncio.sleep(delay)
            delay = min(delay * 1.5, 30.0)

        log.error("❌ Impossible de se connecter à PocketOption après toutes les tentatives")
        return False

    async def disconnect(self) -> None:
        self._authed    = False
        self._connected = False
        await self._cleanup_tasks()

    async def _cleanup_tasks(self) -> None:
        if self._ping_task and not self._ping_task.done():
            self._ping_task.cancel()
            self._ping_task = None
        if self._recv_task and not self._recv_task.done():
            self._recv_task.cancel()
            self._recv_task = None
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.cancel()
        self._pending.clear()
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    async def _heartbeat_loop(self) -> None:
        try:
            while self._ws and not self._ws.closed:
                await asyncio.sleep(self._ping_interval)
                if self._ws and not self._ws.closed:
                    await self._send_raw("3")
                    log.debug("❤ Heartbeat PONG")
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            log.debug(f"Heartbeat terminé : {exc}")

    async def _receive_loop(self) -> None:
        try:
            async for raw in self._ws:
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="replace")
                log.debug(f"← {raw[:200]}")
                try:
                    await self._dispatch(raw)
                except Exception as exc:
                    log.error(f"Erreur dispatch : {exc}", exc_info=True)
        except Exception as exc:
            log.warning(f"Connexion fermée : {exc}")
        finally:
            self._connected = False
            self._authed    = False
            for fut in list(self._pending.values()):
                if not fut.done():
                    fut.cancel()
            self._pending.clear()

    async def _dispatch(self, raw: str) -> None:
        parsed = _parse_sio(raw)
        if parsed is None:
            return
        eng, sio, event, data = parsed

        if eng == "0":
            if isinstance(data, dict):
                self._ping_interval = data.get("pingInterval", 25000) / 1000
            log.debug(f"Engine.IO OPEN — pingInterval={self._ping_interval}s")
            await self._send_raw("40")
            return

        if eng == "2":
            await self._send_raw("3")
            return

        if event == "connect":
            log.debug("Socket.IO CONNECTED — lancement auth")
            self._connected = True
            await self._do_auth()
            self._ping_task = asyncio.create_task(self._heartbeat_loop())
            return

        if event == "successauth":
            self._authed = True
            uid  = data.get("uid", "?") if isinstance(data, dict) else "?"
            mode = "DÉMO" if self.is_demo else "RÉEL"
            log.info(f"🔐 Auth OK — uid={uid} mode={mode}")
            await self._request_balance()
            return

        if event in ("failauth", "errorauth"):
            log.error(f"❌ Auth refusée — SSID probablement expiré : {data}")
            return

        if event in ("balance", "updateBalance", "getBalance"):
            if isinstance(data, dict):
                bal = (
                    data.get("balance")
                    or data.get("demoBalance")
                    or data.get("realBalance")
                )
                if bal is not None:
                    self._balance = float(bal)
                    log.debug(f"Balance : ${self._balance:.2f}")
                    if self._on_balance_cb:
                        asyncio.create_task(self._on_balance_cb(self._balance))
            return

        if event in (
            "candles", "candle", "history", "historyV2",
            "candle1", "liveCandle", "previousCandle",
        ):
            if isinstance(data, dict):
                symbol  = data.get("asset") or data.get("symbol", "")
                candles = data.get("candles") or data.get("data", [])
                if symbol and candles:
                    normalized = []
                    for c in candles:
                        if isinstance(c, dict):
                            normalized.append({
                                "time":  c.get("time")  or c.get("t", 0),
                                "open":  c.get("open")  or c.get("o", 0),
                                "high":  c.get("high")  or c.get("h", 0),
                                "low":   c.get("low")   or c.get("l", 0),
                                "close": c.get("close") or c.get("c", 0),
                            })
                    if normalized:
                        self._candles[symbol] = normalized
                        log.debug(f"Bougies : {symbol} ({len(normalized)})")
                        if self._on_candle_cb:
                            asyncio.create_task(self._on_candle_cb(symbol, normalized))
            return

        if event in (
            "openOrder", "buyResult", "tradeResult",
            "buysResult", "buyComplete", "tradeComplete",
        ):
            if isinstance(data, dict):
                rid = str(data.get("requestId") or data.get("id") or "")
                if rid in self._pending and not self._pending[rid].done():
                    self._pending[rid].set_result(data)
                    log.debug(f"Trade résolu : {rid}")
            return

        if event == "successcloseOption":
            if isinstance(data, dict):
                rid = str(data.get("id", "") or data.get("requestId", ""))
                if rid in self._pending and not self._pending[rid].done():
                    self._pending[rid].set_result(data)
            return

        log.debug(f"Event ignoré : {event}")

    async def _send_raw(self, msg: str) -> None:
        if self._ws and not self._ws.closed:
            log.debug(f"→ {msg[:200]}")
            await self._ws.send(msg)

    async def _send_event(self, event: str, data) -> None:
        await self._send_raw(_build_event(event, data))

    async def _do_auth(self) -> None:
        await self._send_event("auth", {
            "session":  self.ssid,
            "isDemo":   1 if self.is_demo else 0,
            "uid":      0,
            "platform": 2,
        })
        log.debug("Auth envoyé")

    async def _request_balance(self) -> None:
        await self._send_event("getBalance", {})

    async def get_balance(self) -> float:
        await self._request_balance()
        for _ in range(20):
            if self._balance > 0:
                break
            await asyncio.sleep(0.1)
        return self._balance

    async def get_candles(
        self, symbol: str, period: int = 60, count: int = 100
    ) -> List[dict]:
        self._candles.pop(symbol, None)
        await self._send_event("history", {
            "asset":  symbol,
            "period": period,
            "time":   int(time.time()),
            "count":  count,
        })
        for _ in range(80):
            if self._candles.get(symbol):
                return self._candles[symbol]
            await asyncio.sleep(0.1)
        log.warning(f"Pas de bougies pour {symbol}")
        return []

    async def subscribe_candles(self, symbol: str, period: int = 60) -> None:
        await self._send_event("subscribeSymbol", {"asset": symbol, "period": period})

    async def place_trade(
        self,
        symbol:     str,
        direction:  str,
        amount:     float,
        expiration: int,
    ) -> Optional[dict]:
        request_id = f"tnk_{int(time.time() * 1000)}"
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future

        await self._send_event("openOrder", {
            "asset":      symbol,
            "amount":     amount,
            "action":     direction,
            "isDemo":     1 if self.is_demo else 0,
            "requestId":  request_id,
            "optionType": 100,
            "time":       expiration,
        })
        log.info(
            f"Trade → {direction.upper()} {symbol} ${amount} "
            f"exp={expiration}s id={request_id}"
        )

        try:
            result = await asyncio.wait_for(future, timeout=expiration + 15)
            return result
        except asyncio.TimeoutError:
            log.warning(f"Trade {request_id} : timeout")
            return None
        finally:
            self._pending.pop(request_id, None)

    def set_on_balance(self, cb: Callable) -> None:
        self._on_balance_cb = cb

    def set_on_candle(self, cb: Callable) -> None:
        self._on_candle_cb = cb

    @property
    def is_connected(self) -> bool:
        return self._authed and self._ws is not None and not self._ws.closed

    @property
    def balance(self) -> float:
        return self._balance
