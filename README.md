# 🤖 TANEKOU BOT PO v1.0.0
**by eloadXFamily / TANEKOU TRADE**

Bot de trading automatique sur Pocket Option via Telegram.  
100% privé — aucun token, aucun frais, tu gardes tous tes profits.

---

## 📦 Structure du projet

```
TANEKOU_BOT_PO/
├── main.py                  ← Point d'entrée
├── config.py                ← Configuration centralisée
├── requirements.txt         ← Dépendances Python
├── .env.example             ← Template de configuration
├── core/
│   ├── po_client.py         ← Client WebSocket PocketOption
│   ├── signal_engine.py     ← Moteur de signaux (MACD/RSI/BB/EMA/Patterns)
│   ├── martingale.py        ← Gestion Martingale + circuit-breaker
│   └── trader.py            ← Orchestrateur de sessions
├── bot/
│   ├── handlers.py          ← Commandes + callbacks Telegram
│   └── keyboards.py         ← Claviers inline
├── db/
│   └── database.py          ← Base de données SQLite
└── data/                    ← Créé automatiquement au lancement
    ├── tanekou.db
    └── tanekou_bot.log
```

---

## 🚀 Installation

### 1. Prérequis
- Python 3.11+
- Un compte Telegram avec un bot créé via @BotFather
- Un compte PocketOption

### 2. Installer les dépendances

```bash
cd TANEKOU_BOT_PO
pip install -r requirements.txt
```

### 3. Configurer le bot

```bash
cp .env.example .env
```

Édite `.env` et remplis :

| Variable | Description | Comment l'obtenir |
|---|---|---|
| `TELEGRAM_TOKEN` | Token du bot | Via @BotFather → /newbot |
| `TELEGRAM_CHAT_ID` | Ton ID Telegram | Via @userinfobot |
| `PO_SSID` | Session PocketOption | Voir ci-dessous |
| `PO_DEMO` | true = démo, false = réel | À ta convenance |
| `BASE_AMOUNT` | Mise de base ($) | ex: 1.0 |

### 4. Obtenir ton SSID PocketOption

1. Ouvre **Chrome** et connecte-toi sur [pocketoption.com](https://pocketoption.com)
2. Appuie sur **F12** → onglet **Application**
3. Dans le panneau gauche : **Cookies** → `https://pocketoption.com`
4. Cherche le cookie nommé **`ssid`**
5. Copie sa valeur et colle-la dans `.env` sous `PO_SSID`

> ⚠️ Le SSID expire après déconnexion ou changement de mot de passe. Si le bot ne se connecte plus, re-copie ton SSID.

### 5. Lancer le bot

```bash
python main.py
```

---

## 📱 Commandes Telegram

| Commande | Description |
|---|---|
| `/start` | Affiche le menu principal |
| `/trade` | Lance une session de trading |
| `/stop` | Arrête le trading |
| `/stats` | Statistiques du jour + all-time |
| `/balance` | Solde PocketOption actuel |
| `/history` | 10 derniers trades |
| `/config` | Affiche la configuration + tableau Martingale |
| `/reset` | Reset la Martingale (après circuit-breaker) |
| `/mode` | Changer démo/réel |
| `/status` | État en temps réel de la session |

---

## 🧠 Stratégie de signaux

Le moteur analyse 5 indicateurs simultanément :

| Indicateur | Points max | Signal |
|---|---|---|
| MACD Divergence | 30 | Divergence haussière/baissière |
| RSI | 25 | Oversold (<35) / Overbought (>65) |
| Bollinger Bands | 20 | Rebond sur les bandes |
| EMA Cross 9/21 | 15 | Golden Cross / Death Cross |
| Patterns chandeliers | 10 | Hammer, Engulfing, Shooting Star |

**Score minimum pour trader : 65/100** (configurable via `MIN_SIGNAL_SCORE`)

---

## 💰 Martingale

Exemple avec mise de base $1 et multiplicateur 2.3 :

| Niveau | Mise | Cumul investi |
|---|---|---|
| 0 | $1.00 | $1.00 |
| 1 | $2.30 | $3.30 |
| 2 | $5.29 | $8.59 |
| 3 | $12.17 | $20.76 |
| 4 | $27.99 | $48.75 |

**Circuit-breaker** : si le niveau max est atteint, le bot se met en pause et t'alerte.

---

## 🛡️ Sécurité & Gestion du risque

- **Perte max journalière** : stop automatique si perte > X% du solde
- **Circuit-breaker Martingale** : pause si niveau max atteint
- **Mode DÉMO par défaut** : commence toujours en démo
- **Bot privé** : seul ton Chat ID peut l'utiliser
- **Confirmation requise** pour passer en mode réel

---

## ⚠️ Avertissement

Le trading de CFD/options binaires comporte un risque élevé de perte en capital.  
Ce bot est un outil d'automatisation — il ne garantit aucun profit.  
Commence toujours en mode DÉMO avant de passer en réel.  
Ne trade qu'avec des fonds que tu peux te permettre de perdre.

---

*TANEKOU BOT PO — eloadXFamily / TANEKOU TRADE*
