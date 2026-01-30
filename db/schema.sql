-- Database Schema for Solana On-Chain Intelligence Engine
-- Focusing on PostgreSQL + TimescaleDB

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Tracked Wallets (Core Intelligence Targets)
CREATE TABLE IF NOT EXISTS tracked_wallets (
    wallet_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    address         VARCHAR(44) UNIQUE NOT NULL, -- Solana Pubkeys are 44 chars
    category        VARCHAR(20) NOT NULL CHECK (category IN (
        'influencer', 'cabal', 'fresh_wallet', 'market_maker', 'cex_hot'
    )),
    confidence      DECIMAL(5,4) DEFAULT 0.5,
    first_seen      TIMESTAMPTZ DEFAULT NOW(),
    last_activity   TIMESTAMPTZ,
    pnl_total       DECIMAL(20,8) DEFAULT 0,
    win_rate        DECIMAL(5,4) DEFAULT 0,
    avg_hold_time   INTERVAL,
    metadata        JSONB,
    CONSTRAINT valid_confidence CHECK (confidence >= 0 AND confidence <= 1)
);

CREATE INDEX idx_wallet_category ON tracked_wallets(category);
CREATE INDEX idx_wallet_confidence ON tracked_wallets(confidence DESC);

-- Fresh Wallet Clusters (CEX Withdrawal Correlations)
CREATE TABLE IF NOT EXISTS fresh_clusters (
    cluster_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cex_source      VARCHAR(20) NOT NULL,
    withdrawal_tx   VARCHAR(88) NOT NULL, -- Solana sigs are ~88 chars
    withdrawal_time TIMESTAMPTZ NOT NULL,
    amount          DECIMAL(30,18) NOT NULL,
    decimals        INTEGER NOT NULL,
    target_wallet   VARCHAR(44) NOT NULL,
    target_tx_count INTEGER DEFAULT 0,
    time_delta_ms   BIGINT NOT NULL,
    match_score     DECIMAL(5,4) NOT NULL,
    linked_parent   UUID REFERENCES tracked_wallets(wallet_id),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Transaction Events (Time-Series)
CREATE TABLE IF NOT EXISTS tx_events (
    event_time      TIMESTAMPTZ NOT NULL,
    slot            BIGINT NOT NULL,
    tx_hash         VARCHAR(88) NOT NULL,
    wallet_address  VARCHAR(44) NOT NULL,
    program_id      VARCHAR(44),
    action          VARCHAR(20) NOT NULL,
    token_in        VARCHAR(44),
    token_out       VARCHAR(44),
    amount_in       DECIMAL(30,18),
    amount_out      DECIMAL(30,18),
    fee             BIGINT,
    PRIMARY KEY (event_time, tx_hash)
);

-- Convert to hypertable if TimescaleDB is available
-- SELECT create_hypertable('tx_events', 'event_time', if_not_exists => TRUE);

-- ============================================================================
-- PERFORMANCE OPTIMIZATIONS
-- ============================================================================

-- Partial Index: Only index high-confidence wallets
-- Use last_activity filtering in queries (can't use NOW() in index predicate)
CREATE INDEX IF NOT EXISTS idx_active_targets ON tracked_wallets(address, last_activity DESC) 
WHERE confidence > 0.8;

-- TimescaleDB Compression Policy (requires TimescaleDB + hypertable)
-- Provides 90%+ disk savings for historical tx_events data
DO $$ 
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
        ALTER TABLE tx_events SET (
            timescaledb.compress, 
            timescaledb.compress_segmentby = 'wallet_address'
        );
        PERFORM add_compression_policy('tx_events', INTERVAL '1 day');
    END IF;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'TimescaleDB compression not applied: %', SQLERRM;
END $$;

-- ============================================================================
-- CABAL TRACKING TABLES
-- ============================================================================

-- Cabal Groups: Track coordinated wallet clusters
CREATE TABLE IF NOT EXISTS cabal_groups (
    group_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_name VARCHAR(50),
    combined_pnl DECIMAL(20,8) DEFAULT 0,
    wallet_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Cabal Membership: Many-to-many relationship between wallets and groups
CREATE TABLE IF NOT EXISTS cabal_membership (
    group_id UUID REFERENCES cabal_groups(group_id) ON DELETE CASCADE,
    wallet_id UUID REFERENCES tracked_wallets(wallet_id) ON DELETE CASCADE,
    joined_at TIMESTAMPTZ DEFAULT NOW(),
    correlation_score DECIMAL(5,4) DEFAULT 0,
    PRIMARY KEY (group_id, wallet_id)
);

CREATE INDEX idx_cabal_wallet ON cabal_membership(wallet_id);

-- ============================================================================
-- ANTI-RUG SIMULATION TABLE
-- ============================================================================

-- Simulation Results: Pre-flight checks to detect honey-pots
CREATE TABLE IF NOT EXISTS sim_results (
    sim_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    program_id VARCHAR(44) NOT NULL,
    token_mint VARCHAR(44) NOT NULL,
    sim_time TIMESTAMPTZ DEFAULT NOW(),
    buy_success BOOLEAN NOT NULL,
    sell_success BOOLEAN,
    buy_error VARCHAR(200),
    sell_error VARCHAR(200),
    is_honeypot BOOLEAN DEFAULT FALSE,
    notes TEXT
);

-- Index for quick honeypot lookups before execution
CREATE INDEX IF NOT EXISTS idx_sim_honeypot ON sim_results(program_id) 
WHERE is_honeypot = TRUE;

CREATE INDEX IF NOT EXISTS idx_sim_token ON sim_results(token_mint, sim_time DESC);

-- ============================================================================
-- EXECUTION & RISK MANAGEMENT TABLES
-- ============================================================================

-- Trade Execution Log: Full trade lifecycle tracking
CREATE TABLE IF NOT EXISTS trade_log (
    trade_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_source VARCHAR(20) NOT NULL CHECK (signal_source IN (
        'cabal', 'influencer', 'fresh_wallet', 'manual'
    )),
    signal_id UUID,  -- Reference to source signal
    token_mint VARCHAR(44) NOT NULL,
    entry_price DECIMAL(30,18),
    exit_price DECIMAL(30,18),
    entry_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    exit_time TIMESTAMPTZ,
    position_size DECIMAL(30,18) NOT NULL,
    position_size_sol DECIMAL(20,9),  -- Position in SOL terms
    realized_pnl DECIMAL(30,18),
    pnl_percentage DECIMAL(10,4),
    fees_paid DECIMAL(20,8) DEFAULT 0,
    priority_fee DECIMAL(20,8) DEFAULT 0,
    status VARCHAR(20) DEFAULT 'open' CHECK (status IN (
        'open', 'closed', 'stopped_out', 'rugged', 'panic_sold'
    )),
    failure_reason VARCHAR(100),
    sub_wallet_address VARCHAR(44),
    exit_tier VARCHAR(10) CHECK (exit_tier IN ('T1', 'T2', 'T3', 'SL', 'PANIC')),
    jito_bundle_id VARCHAR(100),
    slippage_expected DECIMAL(6,4),
    slippage_actual DECIMAL(6,4),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_trade_status ON trade_log(status);
CREATE INDEX idx_trade_source ON trade_log(signal_source);
CREATE INDEX idx_trade_token ON trade_log(token_mint, entry_time DESC);
CREATE INDEX idx_trade_open ON trade_log(status, entry_time) WHERE status = 'open';

-- Sub-wallet Registry: Ephemeral wallets for trade obfuscation
CREATE TABLE IF NOT EXISTS sub_wallets (
    wallet_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    address VARCHAR(44) UNIQUE NOT NULL,
    encrypted_key TEXT,  -- Encrypted private key (never plaintext!)
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_used TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT TRUE,
    is_retired BOOLEAN DEFAULT FALSE,
    balance_sol DECIMAL(20,9) DEFAULT 0,
    total_trades INTEGER DEFAULT 0,
    total_volume DECIMAL(30,18) DEFAULT 0,
    pnl DECIMAL(30,18) DEFAULT 0
);

CREATE INDEX idx_subwallet_active ON sub_wallets(is_active, last_used) 
WHERE is_active = TRUE AND is_retired = FALSE;

-- Circuit Breaker State: Global risk management
CREATE TABLE IF NOT EXISTS circuit_breaker_state (
    id SERIAL PRIMARY KEY,
    is_locked BOOLEAN DEFAULT FALSE,
    locked_at TIMESTAMPTZ,
    lock_reason VARCHAR(200),
    unlock_at TIMESTAMPTZ,
    daily_pnl DECIMAL(20,8) DEFAULT 0,
    daily_pnl_pct DECIMAL(6,4) DEFAULT 0,
    consecutive_losses INTEGER DEFAULT 0,
    open_position_count INTEGER DEFAULT 0,
    total_exposure DECIMAL(20,8) DEFAULT 0,
    last_trade_time TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    -- Limits (configurable)
    max_daily_drawdown_pct DECIMAL(5,4) DEFAULT 0.10,
    max_single_trade_pct DECIMAL(5,4) DEFAULT 0.02,
    max_position_size_pct DECIMAL(5,4) DEFAULT 0.05,
    max_open_positions INTEGER DEFAULT 10,
    lockdown_hours INTEGER DEFAULT 24
);

-- Initialize circuit breaker with default state
INSERT INTO circuit_breaker_state (id) VALUES (1) ON CONFLICT DO NOTHING;

-- Signal Attribution: Performance tracking per signal source
CREATE TABLE IF NOT EXISTS signal_attribution (
    source_id VARCHAR(100) PRIMARY KEY,
    source_type VARCHAR(20) NOT NULL CHECK (source_type IN (
        'cabal', 'influencer', 'fresh_wallet', 'cluster'
    )),
    source_name VARCHAR(100),
    total_trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    losing_trades INTEGER DEFAULT 0,
    total_pnl DECIMAL(30,18) DEFAULT 0,
    avg_pnl_percentage DECIMAL(10,4) DEFAULT 0,
    win_rate DECIMAL(5,4) DEFAULT 0,
    avg_hold_time INTERVAL,
    best_trade_pnl DECIMAL(30,18),
    worst_trade_pnl DECIMAL(30,18),
    sharpe_ratio DECIMAL(10,4),
    sortino_ratio DECIMAL(10,4),
    last_trade_time TIMESTAMPTZ,
    last_updated TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_attribution_type ON signal_attribution(source_type);
CREATE INDEX idx_attribution_winrate ON signal_attribution(win_rate DESC);

-- Trade Forensics: Failure analysis
CREATE TABLE IF NOT EXISTS trade_forensics (
    forensic_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trade_id UUID REFERENCES trade_log(trade_id),
    failure_category VARCHAR(30) NOT NULL CHECK (failure_category IN (
        'rug_pull', 'slippage', 'bad_signal', 'circuit_breaker', 
        'simulation_miss', 'execution_error', 'unknown'
    )),
    detected_at TIMESTAMPTZ DEFAULT NOW(),
    details JSONB,
    -- Rug-specific fields
    was_simulation_run BOOLEAN,
    simulation_result VARCHAR(20),
    time_since_simulation INTERVAL,
    -- Slippage-specific fields
    expected_output DECIMAL(30,18),
    actual_output DECIMAL(30,18),
    slippage_pct DECIMAL(6,4),
    -- Signal-specific fields
    signal_confidence DECIMAL(5,4),
    signal_age INTERVAL
);

CREATE INDEX idx_forensics_category ON trade_forensics(failure_category);
CREATE INDEX idx_forensics_trade ON trade_forensics(trade_id);
