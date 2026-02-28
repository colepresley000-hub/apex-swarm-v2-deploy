# ◇ POLYBOT — Polymarket Trading Engine

A comprehensive Polymarket prediction market trading bot with:
- **React Dashboard** — Real-time UI with market scanner, signals, portfolio, and AI analysis
- **Python Engine** — Production-ready backend with 4 trading strategies and risk management
- **AI Analysis** — Claude-powered market analysis with fair value estimation

## Architecture

```
┌─────────────────────────────────────────────────┐
│                POLYBOT Dashboard                 │
│  (React — signals, positions, order entry, AI)  │
└───────────────┬─────────────────────────────────┘
                │
┌───────────────▼─────────────────────────────────┐
│             Python Trading Engine                │
│  ┌──────────┐ ┌──────────┐ ┌─────────────────┐  │
│  │ Scanner  │ │ Signals  │ │ Risk Management │  │
│  └────┬─────┘ └────┬─────┘ └───────┬─────────┘  │
│       │             │               │            │
│  ┌────▼─────────────▼───────────────▼─────────┐  │
│  │          Order Execution Engine             │  │
│  └─────────────────┬──────────────────────────┘  │
└────────────────────┼─────────────────────────────┘
                     │
    ┌────────────────┼────────────────┐
    ▼                ▼                ▼
 Gamma API      CLOB API       WebSocket
 (markets)     (trading)      (real-time)
```

## Quick Start

### 1. Install Dependencies

```bash
pip install py-clob-client httpx python-dotenv
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your Polymarket credentials
```

### 3. Scan Markets (no trading, safe to run)

```bash
python polybot_engine.py --scan-only
```

### 4. Paper Trade

```bash
python polybot_engine.py --strategies VALUE MOMENTUM --max-position 50
```

### 5. Go Live (⚠️ uses real money!)

```bash
python polybot_engine.py --live --strategies VALUE --max-position 25 --min-edge 0.08
```

## Trading Strategies

| Strategy | Description | Risk | When to Use |
|----------|-------------|------|-------------|
| **Value Edge** | Detect mispriced markets via orderbook imbalance | Medium | Most markets — your bread and butter |
| **Spread Capture** | Post limit orders on both sides | Low | High-volume markets with wide spreads |
| **Momentum** | Ride recent price trends | High | Markets with clear directional moves |
| **Mean Reversion** | Fade extreme moves (z-score based) | Medium | After sharp price spikes |

## Risk Management

- **Kelly Criterion** sizing (configurable fraction, default half-Kelly)
- **Stop-loss** and **take-profit** per position
- **Max position size** and **total exposure** limits
- **Minimum edge** threshold before any trade
- **Volume & liquidity** filters to avoid illiquid markets

## Getting Your Polymarket Credentials

1. **Go to** [polymarket.com](https://polymarket.com) and create an account
2. **For Email/Magic wallet** (signature_type=1):
   - Your private key is derived from your email login
   - Your funder address is your Polymarket proxy wallet address
   - Find it in your browser's developer tools or Polymarket settings
3. **For MetaMask/EOA** (signature_type=0):
   - Export your private key from MetaMask
   - Set allowances for the Exchange contract before trading
4. **API credentials** will be auto-derived from your private key if not provided

## API Endpoints Used

| API | Base URL | Purpose |
|-----|----------|---------|
| Gamma | `https://gamma-api.polymarket.com` | Market discovery & metadata |
| CLOB | `https://clob.polymarket.com` | Prices, orderbooks & trading |
| Data | `https://data-api.polymarket.com` | Positions & trade history |
| WebSocket | `wss://ws-subscriptions-clob.polymarket.com` | Real-time updates |

## ⚠️ Disclaimers

- **This is not financial advice.** Prediction market trading carries real risk of loss.
- **Start with paper trading** and small positions until you understand the system.
- **No guarantees of profit.** Past performance doesn't predict future results.
- **You are responsible** for complying with your jurisdiction's laws regarding prediction markets.
- **Secure your private key.** Never share it or commit it to version control.
