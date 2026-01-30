"""Trade Forensics - Post-trade failure analysis."""

from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional, Protocol
from enum import Enum
import logging
import json

logger = logging.getLogger(__name__)


class FailureCategory(str, Enum):
    """Categories of trade failures."""
    
    RUG_PULL = "rug_pull"           # Token rugged after simulation passed
    SLIPPAGE = "slippage"           # Execution slippage exceeded expected
    BAD_SIGNAL = "bad_signal"       # Signal was incorrect
    CIRCUIT_BREAKER = "circuit_breaker"  # Stopped by risk limits
    SIMULATION_MISS = "simulation_miss"  # Simulation failed to detect issue
    EXECUTION_ERROR = "execution_error"  # Technical execution failure
    UNKNOWN = "unknown"


@dataclass
class ForensicReport:
    """Forensic analysis of a failed trade."""
    
    forensic_id: str
    trade_id: str
    failure_category: FailureCategory
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    # General
    details: dict = field(default_factory=dict)
    
    # Rug-specific
    was_simulation_run: bool = False
    simulation_result: Optional[str] = None
    time_since_simulation: Optional[float] = None  # hours
    
    # Slippage-specific
    expected_output: Optional[Decimal] = None
    actual_output: Optional[Decimal] = None
    slippage_pct: Optional[Decimal] = None
    
    # Signal-specific
    signal_confidence: Optional[Decimal] = None
    signal_age_hours: Optional[float] = None
    
    @property
    def summary(self) -> str:
        """Generate a human-readable summary."""
        if self.failure_category == FailureCategory.RUG_PULL:
            return f"Rug pull detected. Simulation was {self.time_since_simulation:.1f}h old."
        elif self.failure_category == FailureCategory.SLIPPAGE:
            return f"Slippage was {self.slippage_pct:.2%} (expected {self.expected_output}, got {self.actual_output})"
        elif self.failure_category == FailureCategory.BAD_SIGNAL:
            return f"Signal was incorrect. Confidence was {self.signal_confidence:.2f}"
        else:
            return f"Trade failed: {self.failure_category.value}"


class DatabaseClient(Protocol):
    """Protocol for database client."""
    async def fetch(self, query: str, *args) -> list: ...
    async def execute(self, query: str, *args) -> None: ...


class TradeForensics:
    """
    Post-trade forensic analysis for failed trades.
    
    Categorizes failures to identify:
    - Rug pulls that simulation missed
    - Slippage issues
    - Bad signals from sources
    - Technical execution problems
    
    This data feeds back into:
    - Simulator improvements
    - Signal source penalties
    - Execution optimization
    """
    
    def __init__(self, db_client: DatabaseClient):
        """
        Initialize trade forensics.
        
        Args:
            db_client: Database client for persistence
        """
        self.db = db_client
    
    async def analyze_failure(
        self,
        trade_id: str,
        token_mint: str,
        loss_pct: Decimal,
        simulation_age_hours: float = None,
        slippage_actual: Decimal = None,
        slippage_expected: Decimal = None,
    ) -> ForensicReport:
        """
        Analyze a failed trade and categorize the failure.
        
        Args:
            trade_id: Trade ID
            token_mint: Token that was traded
            loss_pct: Percentage loss
            simulation_age_hours: How old the simulation was
            slippage_actual: Actual slippage experienced
            slippage_expected: Expected slippage
            
        Returns:
            ForensicReport with categorization
        """
        import uuid
        
        report = ForensicReport(
            forensic_id=str(uuid.uuid4()),
            trade_id=trade_id,
            failure_category=FailureCategory.UNKNOWN,
        )
        
        # Check for rug pull (> 80% loss, simulation passed)
        if loss_pct <= Decimal("-0.80"):
            # Check if simulation was run
            sim_query = """
                SELECT is_honeypot, sim_time
                FROM sim_results
                WHERE token_mint = $1
                ORDER BY sim_time DESC
                LIMIT 1
            """
            sim_results = await self.db.fetch(sim_query, token_mint)
            
            if sim_results:
                report.was_simulation_run = True
                report.simulation_result = "honeypot" if sim_results[0]["is_honeypot"] else "safe"
                report.time_since_simulation = simulation_age_hours
                
                if not sim_results[0]["is_honeypot"]:
                    report.failure_category = FailureCategory.RUG_PULL
                else:
                    report.failure_category = FailureCategory.SIMULATION_MISS
            else:
                report.was_simulation_run = False
                report.failure_category = FailureCategory.RUG_PULL
        
        # Check for slippage issue
        elif slippage_actual and slippage_expected:
            slippage_excess = slippage_actual - slippage_expected
            if slippage_excess > Decimal("0.05"):  # > 5% excess slippage
                report.failure_category = FailureCategory.SLIPPAGE
                report.expected_output = slippage_expected
                report.actual_output = slippage_actual
                report.slippage_pct = slippage_excess
        
        # Check for bad signal (mild loss, signal should have predicted)
        elif Decimal("-0.30") < loss_pct <= Decimal("-0.10"):
            report.failure_category = FailureCategory.BAD_SIGNAL
            
            # Get signal info from trade
            trade_query = """
                SELECT signal_source, signal_id
                FROM trade_log
                WHERE trade_id = $1
            """
            trade_results = await self.db.fetch(trade_query, uuid.UUID(trade_id))
            if trade_results:
                report.details["signal_source"] = trade_results[0]["signal_source"]
        
        # Persist report
        await self._save_report(report)
        
        return report
    
    async def _save_report(self, report: ForensicReport) -> None:
        """Save forensic report to database."""
        import uuid
        
        query = """
            INSERT INTO trade_forensics (
                forensic_id, trade_id, failure_category, detected_at,
                details, was_simulation_run, simulation_result,
                time_since_simulation, expected_output, actual_output,
                slippage_pct, signal_confidence
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
        """
        
        try:
            await self.db.execute(
                query,
                uuid.UUID(report.forensic_id),
                uuid.UUID(report.trade_id),
                report.failure_category.value,
                report.detected_at,
                json.dumps(report.details),
                report.was_simulation_run,
                report.simulation_result,
                report.time_since_simulation,
                report.expected_output,
                report.actual_output,
                report.slippage_pct,
                report.signal_confidence,
            )
            logger.info(f"Saved forensic report: {report.failure_category.value}")
        except Exception as e:
            logger.error(f"Failed to save forensic report: {e}")
    
    async def get_failure_summary(self, days: int = 7) -> dict:
        """Get summary of failures by category."""
        query = """
            SELECT 
                failure_category,
                COUNT(*) as count,
                COUNT(DISTINCT trade_id) as unique_trades
            FROM trade_forensics
            WHERE detected_at > NOW() - INTERVAL '%s days'
            GROUP BY failure_category
            ORDER BY count DESC
        """ % days
        
        try:
            results = await self.db.fetch(query)
            return {
                row["failure_category"]: {
                    "count": row["count"],
                    "unique_trades": row["unique_trades"],
                }
                for row in results
            }
        except Exception as e:
            logger.error(f"Failed to get failure summary: {e}")
            return {}
    
    async def get_simulation_misses(self, days: int = 7) -> list:
        """Get tokens where simulation failed to detect issues."""
        query = """
            SELECT 
                tf.trade_id,
                tl.token_mint,
                tf.time_since_simulation,
                tl.pnl_percentage
            FROM trade_forensics tf
            JOIN trade_log tl ON tf.trade_id = tl.trade_id
            WHERE tf.failure_category IN ('rug_pull', 'simulation_miss')
              AND tf.was_simulation_run = TRUE
              AND tf.detected_at > NOW() - INTERVAL '%s days'
            ORDER BY tf.detected_at DESC
        """ % days
        
        try:
            results = await self.db.fetch(query)
            return [
                {
                    "trade_id": str(row["trade_id"]),
                    "token": row["token_mint"],
                    "sim_age_hours": row["time_since_simulation"],
                    "loss_pct": row["pnl_percentage"],
                }
                for row in results
            ]
        except Exception as e:
            logger.error(f"Failed to get simulation misses: {e}")
            return []
