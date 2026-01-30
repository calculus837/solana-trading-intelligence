# Solana On-Chain Intelligence & Execution Engine

A high-performance automated trading system for Solana that identifies "Smart Money" movements before they gain social consensus and executes trades with MEV protection.

## Features

### Intelligence Layer
- **Fresh Wallet Matcher** - Correlates CEX withdrawals to newly funded wallets
- **Cabal Correlation Engine** - Detects coordinated multi-wallet trading patterns
- **Pre-flight Simulation** - Honeypot and rug-pull detection before execution
- **Influencer Tracking** - Monitors known wallet addresses for alpha signals

### Execution Layer
- **Smart Order Router** - Finds best execution across DEXs via Jupiter
- **Jito MEV Protection** - Private bundle submission to avoid frontrunning
- **Sub-wallet Obfuscation** - Distributes trades across ephemeral wallets
- **Dynamic Priority Fees** - Urgency-based fee calculation

### Risk Management
- **Circuit Breaker** - Automatic lockdown on drawdown or consecutive losses
- **Position Sizing** - Confidence-based allocation with max limits
- **Tiered Exits** - Automated T1/T2/T3 profit taking and stop-loss

### Analytics
- **P&L Tracking** - Real-time trade logging and performance metrics
- **Signal Attribution** - Track win rates by source (cabal, influencer, etc.)
- **Trade Forensics** - Post-mortem analysis of failed trades

## Quick Start

### Prerequisites
- Python 3.11+
- Docker & Docker Compose
- Helius RPC API key (recommended)

### Installation

```bash
# Clone the repository
cd solana-intel-engine

# Create virtual environment
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install dependencies
pip install -e .

# Copy environment template
cp .env.example .env
# Edit .env with your API keys
```

### Start Infrastructure

```bash
# Start PostgreSQL, Neo4j, and Redis
docker compose up -d

# Verify services
docker compose ps
```

### High-Frequency Trading Setup (Sub-200ms)

To enable sub-200ms latency, you must upgrade from public RPC to a private Geyser gRPC connection:

1. Obtain a **Yellowstone Geyser** endpoint (e.g., from Helius).
2. Install additional dependencies:
   ```bash
   pip install yellowstone-grpc-client grpcio
   ```
3. Update `.env` with your gRPC credentials:
   ```env
   SOLANA_GEYSER_URL=http://grpc.mainnet.helius-rpc.com:10000
   SOLANA_GEYSER_TOKEN=your-private-token
   ```
4. Restart the engine. It will automatically detect the config and switch to High-Performance Mode.

### Initialize Database

The schema is automatically applied when PostgreSQL starts. To manually apply:

```bash
docker exec -i postgres-local psql -U admin -d solana_intel -f /docker-entrypoint-initdb.d/schema.sql
```

### Start the Engine (Stabilized)
The recommended way to run locally is using the robust developer launcher. This handles pre-flight checks (Redis, Postgres, Ports) and starts all services (Dashboard, Ingestion, Logic) concurrently.

```bash
# Robust Launcher (Recommended)
python run_dev.py
```

### Manual Startup (Advanced)

```bash
# Full engine (ingestion + execution)
python main.py

# Paper trading mode (no real trades)
python main.py --dry-run
```

## CLI Commands

```bash
# View system status
python cli.py status

# View P&L statistics
python cli.py stats
python cli.py stats --source cabal

# Emergency panic sell
python cli.py panic
python cli.py panic --confirm  # Skip confirmation

# Simulate token for honeypot
python cli.py simulate <TOKEN_MINT_ADDRESS>

# Circuit breaker controls
python cli.py breaker status
python cli.py breaker unlock --force
python cli.py breaker reset

# Operational Hardening
python cli.py graph-health            # Check Neo4j graph status
python cli.py forensics               # View recent trade failures
```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `POSTGRES_HOST` | PostgreSQL host | localhost |
| `REDIS_HOST` | Redis host | localhost |
| `NEO4J_URI` | Neo4j connection URI | bolt://localhost:7687 |
| `SOLANA_RPC_URL` | Solana RPC endpoint | - |
| `SOLANA_WS_URL` | Solana WebSocket endpoint | - |
| `JITO_BLOCK_ENGINE_URL` | Jito block engine | mainnet.block-engine.jito.wtf |
| `TRADING_CAPITAL` | Total capital in SOL | 1000 |
| `MAX_DAILY_DRAWDOWN_PCT` | Max daily loss before lockdown | 0.10 (10%) |
| `MAX_POSITION_SIZE_PCT` | Max single position size | 0.05 (5%) |
| `TELEGRAM_BOT_TOKEN` | Bot token for alerts | - |
| `TELEGRAM_CHAT_ID` | Chat ID for alerts | - |

### Risk Limits

Default circuit breaker settings:
- **Max Daily Drawdown**: 10%
- **Max Position Size**: 5% of capital
- **Max Open Positions**: 10
- **Max Consecutive Losses**: 3 (triggers 24h lockdown)

## Architecture

```
                    ┌─────────────────────────────────────────────┐
                    │           SOLANA BLOCKCHAIN                  │
                    └──────────────────┬──────────────────────────┘
                                       │
                    ┌──────────────────▼──────────────────────────┐
                    │         INGESTION LAYER                      │
                    │  WebSocket Listener → CEX Monitor → Redis    │
                    └──────────────────┬──────────────────────────┘
                                       │
        ┌──────────────────────────────┼──────────────────────────────┐
        │                              │                              │
┌───────▼───────┐              ┌───────▼───────┐              ┌───────▼───────┐
│  Fresh Wallet │              │    Cabal      │              │   Pre-flight  │
│    Matcher    │              │   Detector    │              │   Simulator   │
└───────┬───────┘              └───────┬───────┘              └───────┬───────┘
        │                              │                              │
        └──────────────────────────────┼──────────────────────────────┘
                                       │
                    ┌──────────────────▼──────────────────────────┐
                    │         EXECUTION ORCHESTRATOR               │
                    │  Signal → Validate → Size → Route → Execute  │
                    └──────────────────┬──────────────────────────┘
                                       │
        ┌──────────────────────────────┼──────────────────────────────┐
        │                              │                              │
┌───────▼───────┐              ┌───────▼───────┐              ┌───────▼───────┐
│  Sub-wallet   │              │    Smart      │              │     Jito      │
│   Manager     │              │    Router     │              │   Bundles     │
└───────────────┘              └───────────────┘              └───────────────┘
```

## Project Structure

```
solana-intel-engine/
├── main.py                 # Main entry point
├── cli.py                  # Command-line interface
├── pyproject.toml          # Python dependencies
├── docker-compose.yml      # Infrastructure services
├── .env.example            # Environment template
│
├── db/
│   └── schema.sql          # PostgreSQL schema (11 tables)
│
├── ingestion/              # Real-time data streaming
│   ├── listener.py         # WebSocket connection
│   ├── cex_monitor.py      # CEX withdrawal detection
│   ├── publisher.py        # Redis event publisher
│   └── events.py           # Event data models
│
├── logic/
│   ├── matcher/            # CEX-to-wallet correlation
│   ├── correlation/        # Cabal detection
│   ├── simulation/         # Honeypot detection
│   └── risk/               # Circuit breaker
│
├── execution/
│   ├── orchestrator.py     # Central execution hub
│   ├── router.py           # Smart order routing
│   ├── priority_fees.py    # Dynamic fees
│   ├── subwallets.py       # Wallet obfuscation
│   └── jito.py             # MEV protection
│
├── analytics/
│   ├── pnl_logger.py       # Trade P&L tracking
│   ├── attribution.py      # Signal performance
│   └── forensics.py        # Failure analysis
│
└── tests/                  # Unit tests (64 tests)
    ├── test_matcher.py
    ├── test_circuit_breaker.py
    ├── test_orchestrator.py
    └── test_jito.py
```

## Database Schema

| Table | Purpose |
|-------|---------|
| `tracked_wallets` | Wallet addresses and confidence scores |
| `fresh_clusters` | CEX withdrawal to wallet matches |
| `tx_events` | Transaction event log |
| `cabal_groups` | Detected wallet coordination groups |
| `cabal_membership` | Wallet-to-cabal relationships |
| `sim_results` | Token simulation cache |
| `trade_log` | Full trade lifecycle |
| `sub_wallets` | Ephemeral wallet registry |
| `circuit_breaker_state` | Risk management state |
| `signal_attribution` | Source performance tracking |
| `trade_forensics` | Trade failure analysis |

## Testing

```bash
# Run all tests
python -m pytest tests/ -v

# Run with coverage
python -m pytest tests/ --cov=. --cov-report=html

# Run specific test file
python -m pytest tests/test_circuit_breaker.py -v
```

## 🚀 Production Deployment Strategy

To achieve the sub-200ms latency required for high-frequency trading:

### 1. Server Location (Critical)
**AWS/GCP Frankfurt (eu-central-1)**
- This is the global "hub" for Jito and most Solana validators.
- Hosting here minimizes physical distance to the block leader.

### 2. Hardware Requirements
- **CPU**: High-frequency compute (e.g., AWS c6i.xlarge or better).
- **RAM**: 32GB+ to handle in-memory graph structures.
- **Network**: Enhanced Networking (AWS ENA) enabled.

### 3. Process Management
Use `systemd` or `supervisord` to keep the engine running 24/7:
```ini
[program:solana-engine]
command=python main.py
autostart=true
autorestart=true
stderr_logfile=/var/log/solana-engine.err.log
stdout_logfile=/var/log/solana-engine.out.log
```

### 4. Alerting
To enable critical alerts (Cabal detection, Trade execution, Risk events):
1. Create a Telegram bot via [@BotFather](https://t.me/botfather).
2. Get your Chat ID via [@userinfobot](https://t.me/userinfobot).
3. Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in your `.env`.

## Security Considerations

- **Never commit `.env` files** - Contains API keys and secrets
- **Sub-wallet keys** - Should be encrypted at rest (configure `KEY_ENCRYPTION_SECRET`)
- **Jito tips** - Uses official tip accounts with random selection
- **Circuit breaker** - Automatic protection against runaway losses

## Disclaimer

This software is for educational purposes only. Automated trading carries significant financial risk. Use at your own risk. The authors are not responsible for any financial losses incurred through the use of this software.

## License

MIT License - See LICENSE file for details.
