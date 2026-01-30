"""
Trade Service - Manages trade execution and position tracking for the dashboard.

Provides:
- Execute copy trades
- Track open positions
- Trade history
- Real-time PnL updates
"""

import asyncio
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, List, Dict
from enum import Enum

logger = logging.getLogger(__name__)


class TradeStatus(str, Enum):
    PENDING = "pending"
    EXECUTED = "executed"
    PARTIAL_EXIT = "partial_exit"
    CLOSED = "closed"
    FAILED = "failed"


@dataclass
class Position:
    """Active trading position."""
    trade_id: str
    token_mint: str
    token_symbol: Optional[str]
    entry_price: Decimal
    current_price: Decimal
    amount_tokens: Decimal
    amount_sol: Decimal
    entry_time: datetime
    status: TradeStatus = TradeStatus.EXECUTED
    pnl_pct: float = 0.0
    pnl_sol: Decimal = Decimal("0")
    source: str = "copy_trade"  # "copy_trade", "manual", "signal"
    source_id: Optional[str] = None  # Alert ID or wallet address


@dataclass
class TradeRecord:
    """Completed trade record."""
    trade_id: str
    token_mint: str
    token_symbol: Optional[str]
    action: str  # "buy" or "sell"
    amount_sol: Decimal
    amount_tokens: Decimal
    price: Decimal
    tx_signature: Optional[str]
    timestamp: datetime
    source: str


class TradeService:
    """
    Service for managing trades from the dashboard.
    
    Integrates with Jupiter for execution and tracks positions in memory.
    """
    
    def __init__(self):
        self.positions: Dict[str, Position] = {}
        self.trade_history: List[TradeRecord] = []
        self.total_pnl_sol: Decimal = Decimal("0")
        self._price_update_task: Optional[asyncio.Task] = None
        self._sio = None  # Socket.io instance for broadcasts
        
    def set_socket(self, sio):
        """Set Socket.io instance for real-time broadcasts."""
        self._sio = sio
        
    async def start_price_updates(self):
        """Start background task for price updates."""
        if self._price_update_task is None:
            self._price_update_task = asyncio.create_task(self._update_prices_loop())
            logger.info("📊 Price update loop started")
            
    async def stop_price_updates(self):
        """Stop price update task."""
        if self._price_update_task:
            self._price_update_task.cancel()
            self._price_update_task = None
            
    async def _update_prices_loop(self):
        """Periodically update prices and broadcast PnL."""
        while True:
            try:
                await asyncio.sleep(10)  # Update every 10 seconds
                await self._update_all_prices()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Price update error: {e}")
                
    async def _update_all_prices(self):
        """Fetch current prices and update positions."""
        if not self.positions:
            return
            
        try:
            from execution.jupiter_client import JupiterClient
            
            async with JupiterClient() as client:
                for trade_id, pos in self.positions.items():
                    price = await client.get_token_price(pos.token_mint)
                    if price:
                        pos.current_price = price
                        # Calculate PnL
                        if pos.entry_price > 0:
                            pos.pnl_pct = float((price - pos.entry_price) / pos.entry_price * 100)
                            pos.pnl_sol = (price - pos.entry_price) * pos.amount_tokens
                            
            # Broadcast update
            if self._sio:
                await self._sio.emit("trade:pnl_update", self.get_pnl_summary())
                
        except Exception as e:
            logger.debug(f"Price update failed: {e}")
            
    async def execute_copy_trade(
        self,
        token_mint: str,
        amount_sol: float,
        source: str = "copy_trade",
        source_id: Optional[str] = None,
        token_symbol: Optional[str] = None,
    ) -> Dict:
        """
        Execute a copy trade (buy).
        
        Args:
            token_mint: Token to buy
            amount_sol: Amount of SOL to spend
            source: Trade source identifier
            source_id: ID of triggering alert/signal
            token_symbol: Optional token symbol for display
            
        Returns:
            Trade result dict
        """
        trade_id = str(uuid.uuid4())
        
        try:
            from execution.jupiter_client import JupiterClient
            
            amount_lamports = int(amount_sol * 1e9)
            
            async with JupiterClient() as client:
                # Get quote
                quote = await client.get_quote(
                    input_mint=JupiterClient.SOL_MINT,
                    output_mint=token_mint,
                    amount=amount_lamports,
                    slippage_bps=100,
                )
                
                if not quote:
                    return {
                        "success": False,
                        "trade_id": trade_id,
                        "error": "Failed to get quote"
                    }
                    
                # For now, simulate the trade (no actual execution without private key)
                # In production, this would call get_swap_transaction and sign/send
                
                entry_price = quote.price
                tokens_received = Decimal(str(quote.out_amount))
                
                # Create position
                position = Position(
                    trade_id=trade_id,
                    token_mint=token_mint,
                    token_symbol=token_symbol,
                    entry_price=entry_price,
                    current_price=entry_price,
                    amount_tokens=tokens_received,
                    amount_sol=Decimal(str(amount_sol)),
                    entry_time=datetime.now(timezone.utc),
                    source=source,
                    source_id=source_id,
                )
                
                self.positions[trade_id] = position
                
                # Log trade
                trade_record = TradeRecord(
                    trade_id=trade_id,
                    token_mint=token_mint,
                    token_symbol=token_symbol,
                    action="buy",
                    amount_sol=Decimal(str(amount_sol)),
                    amount_tokens=tokens_received,
                    price=entry_price,
                    tx_signature=None,  # Simulated
                    timestamp=datetime.now(timezone.utc),
                    source=source,
                )
                self.trade_history.append(trade_record)
                
                # Broadcast
                if self._sio:
                    await self._sio.emit("trade:executed", {
                        "trade_id": trade_id,
                        "token": token_symbol or token_mint[:8],
                        "action": "buy",
                        "amount_sol": float(amount_sol),
                        "tokens": float(tokens_received),
                    })
                
                logger.info(f"✅ Copy trade executed: {trade_id[:8]}... | {amount_sol} SOL -> {token_symbol or token_mint[:8]}")
                
                return {
                    "success": True,
                    "trade_id": trade_id,
                    "token_mint": token_mint,
                    "amount_sol": amount_sol,
                    "tokens_received": float(tokens_received),
                    "entry_price": float(entry_price),
                }
                
        except Exception as e:
            logger.error(f"Copy trade failed: {e}")
            return {
                "success": False,
                "trade_id": trade_id,
                "error": str(e)
            }
            
    async def close_position(self, trade_id: str) -> Dict:
        """Close an open position (sell all)."""
        position = self.positions.get(trade_id)
        if not position:
            return {"success": False, "error": "Position not found"}
            
        try:
            # Calculate final PnL
            final_pnl = position.pnl_sol
            self.total_pnl_sol += final_pnl
            
            # Log trade
            trade_record = TradeRecord(
                trade_id=trade_id,
                token_mint=position.token_mint,
                token_symbol=position.token_symbol,
                action="sell",
                amount_sol=position.amount_sol + position.pnl_sol,
                amount_tokens=position.amount_tokens,
                price=position.current_price,
                tx_signature=None,
                timestamp=datetime.now(timezone.utc),
                source=position.source,
            )
            self.trade_history.append(trade_record)
            
            # Remove position
            del self.positions[trade_id]
            
            # Broadcast
            if self._sio:
                await self._sio.emit("trade:exited", {
                    "trade_id": trade_id,
                    "pnl_sol": float(final_pnl),
                    "pnl_pct": position.pnl_pct,
                })
                
            logger.info(f"✅ Position closed: {trade_id[:8]}... | PnL: {final_pnl:.4f} SOL")
            
            return {
                "success": True,
                "trade_id": trade_id,
                "pnl_sol": float(final_pnl),
                "pnl_pct": position.pnl_pct,
            }
            
        except Exception as e:
            logger.error(f"Close position failed: {e}")
            return {"success": False, "error": str(e)}
            
    def get_positions(self) -> List[Dict]:
        """Get all open positions."""
        return [
            {
                "trade_id": p.trade_id,
                "token": p.token_symbol or p.token_mint[:8],
                "token_mint": p.token_mint,
                "entry_price": float(p.entry_price),
                "current_price": float(p.current_price),
                "amount_sol": float(p.amount_sol),
                "pnl_pct": p.pnl_pct,
                "pnl_sol": float(p.pnl_sol),
                "entry_time": p.entry_time.isoformat(),
                "source": p.source,
            }
            for p in self.positions.values()
        ]
        
    def get_trade_history(self, limit: int = 50) -> List[Dict]:
        """Get recent trade history."""
        return [
            {
                "trade_id": t.trade_id,
                "token": t.token_symbol or t.token_mint[:8],
                "action": t.action,
                "amount_sol": float(t.amount_sol),
                "price": float(t.price),
                "timestamp": t.timestamp.isoformat(),
                "source": t.source,
            }
            for t in reversed(self.trade_history[-limit:])
        ]
        
    def get_pnl_summary(self) -> Dict:
        """Get overall PnL summary."""
        unrealized = sum(p.pnl_sol for p in self.positions.values())
        return {
            "total_pnl_sol": float(self.total_pnl_sol + unrealized),
            "realized_pnl_sol": float(self.total_pnl_sol),
            "unrealized_pnl_sol": float(unrealized),
            "open_positions": len(self.positions),
            "total_trades": len(self.trade_history),
        }


# Global instance
trade_service = TradeService()
