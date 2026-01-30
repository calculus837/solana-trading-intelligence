-- Seed influencer wallets for tracking
-- These are example "smart money" addresses for testing

INSERT INTO tracked_wallets (address, category, confidence, metadata) VALUES 
    ('5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1', 'influencer', 0.90, '{"name": "Smart Money 1", "tags": ["meme-degen", "high-freq"]}'),
    ('HN7cABqLq46Es1jh92dQQisAq662SmxELLLsHHe4YWrH', 'influencer', 0.85, '{"name": "Smart Money 2", "tags": ["early-buyer"]}'),
    ('CccdDHU8n1vVj7dTeWHwJKFJXzj7gPQjpNdBQZQBsqhi', 'influencer', 0.88, '{"name": "Smart Money 3", "tags": ["whale"]}')
ON CONFLICT (address) DO UPDATE 
    SET confidence = EXCLUDED.confidence,
        metadata = EXCLUDED.metadata;

-- Verify
SELECT address, category, confidence, metadata->>'name' as name FROM tracked_wallets WHERE category = 'influencer';
