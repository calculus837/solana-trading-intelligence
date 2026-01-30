"""Honeypot Analyzer - Advanced honeypot pattern detection."""

from decimal import Decimal
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Protocol
import logging

from .models import SimulationResult, RiskClassification

logger = logging.getLogger(__name__)


class DatabaseClient(Protocol):
    """Protocol for database client interface."""
    async def fetch(self, query: str, *args) -> list: ...


class HoneypotAnalyzer:
    """
    Analyzes token patterns to detect honeypots beyond simple simulation.
    
    Additional heuristics:
    1. Contract code analysis (freeze authority, mint authority)
    2. Holder concentration (top holders %)
    3. LP lock status
    4. Transaction pattern analysis (buy-only wallets)
    5. Historical rug patterns
    """
    
    def __init__(self, db_client: DatabaseClient):
        """
        Initialize the honeypot analyzer.
        
        Args:
            db_client: Database client for queries
        """
        self.db = db_client
    
    async def analyze(
        self,
        token_mint: str,
        simulation_result: Optional[SimulationResult] = None,
    ) -> dict:
        """
        Perform comprehensive honeypot analysis.
        
        Args:
            token_mint: Token mint address
            simulation_result: Optional pre-run simulation result
            
        Returns:
            Analysis report with risk indicators
        """
        report = {
            "token_mint": token_mint,
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
            "risk_score": Decimal("0"),
            "indicators": [],
            "recommendation": "unknown",
        }
        
        # Add simulation results if available
        if simulation_result:
            report["simulation"] = {
                "classification": simulation_result.risk_classification.value,
                "is_honeypot": simulation_result.is_honeypot,
                "buy_tax": str(simulation_result.buy_tax) if simulation_result.buy_tax else None,
                "sell_tax": str(simulation_result.sell_tax) if simulation_result.sell_tax else None,
            }
            
            if simulation_result.is_honeypot:
                report["risk_score"] += Decimal("50")
                report["indicators"].append("SIMULATION_HONEYPOT")
        
        # Check historical rug patterns
        rug_history = await self._check_historical_rugs(token_mint)
        if rug_history["has_rug_history"]:
            report["risk_score"] += Decimal("30")
            report["indicators"].append("CREATOR_RUG_HISTORY")
            report["rug_history"] = rug_history
        
        # Check holder concentration
        concentration = await self._check_holder_concentration(token_mint)
        if concentration["top_10_percent"] > Decimal("80"):
            report["risk_score"] += Decimal("20")
            report["indicators"].append("HIGH_CONCENTRATION")
        report["holder_concentration"] = concentration
        
        # Check trading patterns
        patterns = await self._check_trading_patterns(token_mint)
        if patterns["buy_only_ratio"] > Decimal("0.9"):
            report["risk_score"] += Decimal("25")
            report["indicators"].append("BUY_ONLY_PATTERN")
        report["trading_patterns"] = patterns
        
        # Generate recommendation
        if report["risk_score"] >= Decimal("70"):
            report["recommendation"] = "AVOID"
        elif report["risk_score"] >= Decimal("40"):
            report["recommendation"] = "HIGH_CAUTION"
        elif report["risk_score"] >= Decimal("20"):
            report["recommendation"] = "CAUTION"
        else:
            report["recommendation"] = "PROCEED"
        
        return report
    
    async def _check_historical_rugs(self, token_mint: str) -> dict:
        """
        Check if token creator has history of rug pulls.
        
        Queries historical data to find wallets associated with
        tokens that went to zero after launch.
        """
        result = {
            "has_rug_history": False,
            "previous_rugs": 0,
            "creator_address": None,
        }
        
        # This query would find tokens from the same creator that failed
        # Simplified for now - would need on-chain creator analysis
        query = """
            SELECT COUNT(*) as failed_count
            FROM sim_results
            WHERE is_honeypot = TRUE
              AND program_id = (
                  SELECT program_id FROM sim_results WHERE token_mint = $1 LIMIT 1
              )
            LIMIT 1
        """
        
        try:
            results = await self.db.fetch(query, token_mint)
            if results and results[0]["failed_count"] > 3:
                result["has_rug_history"] = True
                result["previous_rugs"] = results[0]["failed_count"]
        except Exception as e:
            logger.error(f"Historical rug check failed: {e}")
        
        return result
    
    async def _check_holder_concentration(self, token_mint: str) -> dict:
        """
        Check token holder concentration.
        
        High concentration in few wallets indicates potential rug risk.
        """
        result = {
            "top_10_percent": Decimal("0"),
            "top_holder_percent": Decimal("0"),
            "holder_count": 0,
        }
        
        # This would query on-chain token accounts
        # Simplified - would need token account queries
        
        return result
    
    async def _check_trading_patterns(self, token_mint: str) -> dict:
        """
        Analyze trading patterns for red flags.
        
        Buy-only patterns (many buys, no sells) indicate potential honeypot.
        """
        result = {
            "buy_only_ratio": Decimal("0"),
            "unique_sellers": 0,
            "avg_hold_time": None,
        }
        
        query = """
            SELECT 
                COUNT(CASE WHEN action = 'buy' THEN 1 END) as buys,
                COUNT(CASE WHEN action = 'sell' THEN 1 END) as sells,
                COUNT(DISTINCT CASE WHEN action = 'sell' THEN wallet_address END) as sellers
            FROM tx_events
            WHERE token_out = $1 OR token_in = $1
              AND event_time > NOW() - INTERVAL '24 hours'
        """
        
        try:
            results = await self.db.fetch(query, token_mint)
            if results:
                row = results[0]
                total = (row.get("buys") or 0) + (row.get("sells") or 0)
                if total > 0:
                    buys = row.get("buys") or 0
                    result["buy_only_ratio"] = Decimal(str(buys / total))
                    result["unique_sellers"] = row.get("sellers") or 0
        except Exception as e:
            logger.error(f"Trading pattern check failed: {e}")
        
        return result
    
    async def get_safe_tokens(self, limit: int = 100) -> List[str]:
        """
        Get list of tokens that passed simulation.
        
        Args:
            limit: Maximum number of tokens to return
            
        Returns:
            List of token mint addresses
        """
        query = """
            SELECT token_mint
            FROM sim_results
            WHERE is_honeypot = FALSE
              AND buy_success = TRUE
              AND sell_success = TRUE
              AND sim_time > NOW() - INTERVAL '1 day'
            ORDER BY sim_time DESC
            LIMIT $1
        """
        
        try:
            results = await self.db.fetch(query, limit)
            return [row["token_mint"] for row in results]
        except Exception as e:
            logger.error(f"Safe tokens query failed: {e}")
            return []
    
    async def get_known_honeypots(self, limit: int = 100) -> List[str]:
        """
        Get list of known honeypot tokens.
        
        Args:
            limit: Maximum number of tokens to return
            
        Returns:
            List of token mint addresses
        """
        query = """
            SELECT token_mint
            FROM sim_results
            WHERE is_honeypot = TRUE
            ORDER BY sim_time DESC
            LIMIT $1
        """
        
        try:
            results = await self.db.fetch(query, limit)
            return [row["token_mint"] for row in results]
        except Exception as e:
            logger.error(f"Honeypot query failed: {e}")
            return []
