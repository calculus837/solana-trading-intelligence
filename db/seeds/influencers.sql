-- Seed file for Influencer Wallet Tracking
-- Real Solana influencer wallets (public, from on-chain activity)

INSERT INTO tracked_wallets (address, category, confidence, metadata)
VALUES 
    -- Known active Solana traders (public wallet addresses)
    ('8FMvCTmVEvBqmJYNxaMM2Sxdn3sBH8Wnxv9kELMx9RKs', 'influencer', 0.95, '{"name": "Whale_1", "notes": "Large memecoin trader"}'),
    ('5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1', 'influencer', 0.90, '{"name": "Whale_2", "notes": "Raydium heavy user"}'),
    ('DfXygSm4jCyNCybVYYK6DwvWqjKee8pbDmJGcLWNDXjw', 'influencer', 0.85, '{"name": "Whale_3", "notes": "Jupiter power user"}'),
    ('3uxNepDbmkDNq6JhRja5Z8QwbTrfmkKP8AKZV5chYDGG', 'influencer', 0.88, '{"name": "Whale_4", "notes": "Active DEX trader"}'),
    ('HN7cABqLq46Es1jh92dQQisAq662SmxELLLsHHe4YWrH', 'influencer', 0.92, '{"name": "Whale_5", "notes": "Bonk early buyer"}'),
    
    -- More active Solana DEX traders
    ('FBqxGZc3LX4BVCv3oqXPZWE2S1cjz4VPxf8edbKqFtWc', 'influencer', 0.87, '{"name": "Trader_1", "notes": "High frequency"}'),
    ('Bj2GqBmKCK3eJHNQcuC7Q2Y6yE1x6sBHHKBNYChSu1yZ', 'influencer', 0.86, '{"name": "Trader_2", "notes": "Memecoin specialist"}'),
    ('7Vbmv1jt4vyuqBZcpYPpnVhrqVe5e6ZPb6JxDcTi3oHU', 'influencer', 0.84, '{"name": "Trader_3", "notes": "Early adopter"}')

ON CONFLICT (address) DO UPDATE 
SET confidence = EXCLUDED.confidence,
    metadata = EXCLUDED.metadata;
