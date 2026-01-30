// Neo4j Constraints and Indices for Solana Engine

// Ensure unique addresses
CREATE CONSTRAINT wallet_address IF NOT EXISTS
FOR (w:Wallet) REQUIRE w.address IS UNIQUE;

CREATE CONSTRAINT contract_address IF NOT EXISTS
FOR (c:Contract) REQUIRE c.address IS UNIQUE;

// Indexes for performance
CREATE INDEX wallet_category IF NOT EXISTS FOR (w:Wallet) ON (w.category);
CREATE INDEX tx_timestamp IF NOT EXISTS FOR ()-[r:INTERACTED_WITH]-() ON (r.timestamp);

// Example seeding of CEX Hot Wallets (Solana)
MERGE (binance:Wallet {address: '5tz31f1q2v1e7t6z5r5r5r5r5r5r5r5r5r5r5r5r5r5r', exchange: 'Binance', type: 'cex_hot'})
SET binance.category = 'cex_hot';

MERGE (okx:Wallet {address: 'OKX_HOT_WALLET_ADDRESS_HERE', exchange: 'OKX', type: 'cex_hot'})
SET okx.category = 'cex_hot';
