"""CSV Data Loader - Load historical data from Solscan CSV exports."""

import csv
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional
from pathlib import Path

from .models import HistoricalTransaction, SignalType

logger = logging.getLogger(__name__)


class CSVDataLoader:
    """Loads historical transaction data from Solscan CSV exports."""
    
    def __init__(self, data_dir: str = None):
        """
        Initialize CSV loader.
        
        Args:
            data_dir: Directory containing CSV files
        """
        self.data_dir = Path(data_dir) if data_dir else Path(__file__).parent / "data"
        
    def load_all(self) -> List[HistoricalTransaction]:
        """
        Load all CSV files from the data directory.
        
        Returns:
            List of HistoricalTransaction objects from all CSV files
        """
        if not self.data_dir.exists():
            logger.warning(f"Data directory not found: {self.data_dir}")
            return []
            
        transactions = []
        csv_files = list(self.data_dir.glob("*.csv"))
        
        if not csv_files:
            logger.warning(f"No CSV files found in {self.data_dir}")
            return []
            
        logger.info(f"Found {len(csv_files)} CSV files to load")
        
        for csv_file in csv_files:
            try:
                txs = self.load_file(csv_file)
                transactions.extend(txs)
                logger.info(f"Loaded {len(txs)} transactions from {csv_file.name}")
            except Exception as e:
                logger.error(f"Failed to load {csv_file.name}: {e}")
                
        return transactions
        
    def load_file(self, filepath: Path) -> List[HistoricalTransaction]:
        """
        Load transactions from a single CSV file.
        
        Supports Solscan export format with columns:
        - Signature, Time, Action, From, To, Amount, Token, TokenAddress
        
        Args:
            filepath: Path to CSV file
            
        Returns:
            List of HistoricalTransaction objects
        """
        transactions = []
        
        with open(filepath, 'r', encoding='utf-8') as f:
            # Detect delimiter
            sample = f.read(2000)
            f.seek(0)
            
            # Try to detect if it's comma or semicolon separated
            if sample.count(';') > sample.count(','):
                delimiter = ';'
            else:
                delimiter = ','
                
            reader = csv.DictReader(f, delimiter=delimiter)
            
            for row in reader:
                tx = self._parse_row(row, filepath.stem)
                if tx:
                    transactions.append(tx)
                    
        return transactions
        
    def _parse_row(self, row: dict, wallet_hint: str = None) -> Optional[HistoricalTransaction]:
        """
        Parse a CSV row into a HistoricalTransaction.
        
        Handles multiple CSV formats from different sources.
        """
        try:
            # Normalize column names (handle different capitalizations)
            row = {k.lower().strip(): v for k, v in row.items()}
            
            # Extract signature/tx hash
            tx_hash = (
                row.get('signature') or 
                row.get('tx_hash') or 
                row.get('hash') or 
                row.get('txhash') or
                ""
            )
            
            # Extract timestamp
            time_str = (
                row.get('human time') or 
                row.get('time') or 
                row.get('timestamp') or 
                row.get('date') or 
                row.get('block_time') or
                ""
            )
            
            if not time_str:
                return None
                
            # Parse various timestamp formats
            timestamp = self._parse_timestamp(time_str)
            if not timestamp:
                return None
                
            # Extract action (buy/sell) using Flow if available
            action = 'buy' # Default
            flow = row.get('flow', '').lower()
            if flow:
                if flow == 'in':
                    action = 'buy'
                elif flow == 'out':
                    action = 'sell'
            else:
                # Fallback to action string
                action_str = row.get('action', '').lower()
                if 'transfer in' in action_str or 'receive' in action_str:
                    action = 'buy'
                elif 'transfer out' in action_str or 'send' in action_str:
                    action = 'sell'
                
            # Extract token info
            token_mint = (
                row.get('token address') or 
                row.get('tokenaddress') or 
                row.get('token_address') or 
                row.get('mint') or
                row.get('token_mint') or
                ""
            )
            
            if not token_mint:
                return None
                
            # Skip wrapped SOL
            if token_mint == "So11111111111111111111111111111111111111112" or token_mint == "SOL":
                return None
                
            token_symbol = (
                row.get('token') or 
                row.get('symbol') or 
                row.get('token_symbol') or
                None
            )
            
            # Extract amounts
            # Handle Solscan 'Amount' (raw) + 'Decimals' vs generic 'Amount' (formatted)
            amount_str = row.get('amount') or row.get('value') or "0"
            decimals_str = row.get('decimals') or "0"
            
            try:
                # Remove commas
                amount_val = Decimal(str(amount_str).replace(',', ''))
                decimals = int(decimals_str)
                
                # If decimals are present, amount is likely raw units
                if decimals > 0:
                    amount_tokens = amount_val / (Decimal(10) ** decimals)
                else:
                    amount_tokens = amount_val
            except:
                amount_tokens = Decimal("0")
                
            # Extract SOL amount/Value (USD) if available
            # Solscan 'Value' is usually USD value
            value_str = row.get('value') or "0"
            try:
                amount_sol = Decimal(str(value_str).replace(',', '')) 
                # Note: This might be USD value, but we use it as a proxy for sizing if SOL not available
            except:
                amount_sol = Decimal("0")
                
            # Extract wallet address
            wallet_address = (
                row.get('from') or 
                row.get('to') or 
                row.get('owner') or 
                row.get('wallet') or
                wallet_hint or
                ""
            )
            
            return HistoricalTransaction(
                tx_hash=tx_hash,
                wallet_address=wallet_address,
                timestamp=timestamp,
                token_mint=token_mint,
                token_symbol=token_symbol,
                action=action,
                amount_sol=abs(amount_sol),
                amount_tokens=abs(amount_tokens),
            )
            
        except Exception as e:
            logger.debug(f"Failed to parse row: {e}")
            return None
            
    def _parse_timestamp(self, time_str: str) -> Optional[datetime]:
        """Parse timestamp from various formats."""
        formats = [
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%d/%m/%Y %H:%M:%S",
            "%m/%d/%Y %H:%M:%S",
            "%Y/%m/%d %H:%M:%S",
            "%b %d, %Y %H:%M:%S",
        ]
        
        for fmt in formats:
            try:
                dt = datetime.strptime(time_str, fmt)
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
                
        # Try Unix timestamp
        try:
            ts = float(time_str)
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except:
            pass
            
        return None


def create_sample_csv(output_path: str = None):
    """
    Create a sample CSV file showing the expected format.
    
    Args:
        output_path: Where to save the sample file
    """
    sample_data = """Signature,Time,Action,From,To,Amount,Token,TokenAddress
5abcd1234567890abcdef,2026-01-01 12:00:00,Transfer In,So1234...,MyWallet...,1000.5,BONK,DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263
6efgh2345678901bcdefg,2026-01-01 12:05:00,Transfer In,So5678...,MyWallet...,500.0,WIF,EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm
7ijkl3456789012cdefgh,2026-01-02 09:30:00,Transfer Out,MyWallet...,So9999...,250.0,BONK,DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263
"""
    
    if output_path is None:
        output_path = Path(__file__).parent / "data" / "sample_transactions.csv"
        
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', newline='') as f:
        f.write(sample_data)
        
    print(f"Sample CSV created at: {output_path}")
    return output_path
