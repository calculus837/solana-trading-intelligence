# Fresh Wallet Matcher Module

CEX-to-Wallet linking logic for detecting fresh wallets funded from exchange withdrawals.

## Usage

```python
from matcher import CEXFreshWalletMatcher

matcher = CEXFreshWalletMatcher(redis, db, neo4j)
result = await matcher.process_withdrawal(withdrawal)
```
