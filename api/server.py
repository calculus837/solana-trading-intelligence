"""
FastAPI Server for Solana Intel Engine Dashboard.

Provides:
- Static file serving for the frontend
- Socket.io server for real-time updates
- REST endpoints for forensics and graph queries
- Redis PubSub bridge
"""

import os
import asyncio
import logging
import json
from contextlib import asynccontextmanager

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import socketio
import redis.asyncio as redis
import asyncpg
from neo4j import AsyncGraphDatabase

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("dashboard-api")

# Environment variables
REDIS_URL = f"redis://{os.getenv('REDIS_HOST', 'localhost')}:{os.getenv('REDIS_PORT', '6379')}"
POSTGRES_DSN = f"postgresql://{os.getenv('POSTGRES_USER', 'admin')}:{os.getenv('POSTGRES_PASSWORD', 'password')}@{os.getenv('POSTGRES_HOST', 'localhost')}:{os.getenv('POSTGRES_PORT', '5432')}/{os.getenv('POSTGRES_DB', 'solana_intel')}"
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_AUTH = (os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "password"))

# Debug: Log connection strings (mask password)
logger.info(f"📋 POSTGRES_DSN: postgresql://*****@{os.getenv('POSTGRES_HOST', 'localhost')}:{os.getenv('POSTGRES_PORT', '5432')}/{os.getenv('POSTGRES_DB', 'solana_intel')}")
logger.info(f"📋 NEO4J_URI: {NEO4J_URI}")

# Connection Globals
db_pool = None
neo4j_driver = None
redis_client = None

# Socket.io Setup
# socketio_path must match what the frontend expects
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
socket_app = socketio.ASGIApp(sio, socketio_path='/socket.io')

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle events: connect/disconnect DBs and start background tasks."""
    global db_pool, neo4j_driver, redis_client
    
    # Import trade service
    from api.trade_service import trade_service
    
    # 0. Set Start Time
    import time
    app.state.start_time = time.time()
    
    # 1. Connect Databases
    try:
        db_pool = await asyncpg.create_pool(POSTGRES_DSN, min_size=1, max_size=5)
        neo4j_driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
        logger.info("✅ Databases connected")
    except Exception as e:
        logger.error(f"❌ Database connection failed: {e}")
    
    # 2. Initialize trade service with Socket.io
    trade_service.set_socket(sio)
    await trade_service.start_price_updates()
    
    # 3. Start Redis Listener Task
    redis_task = asyncio.create_task(redis_listener())
    
    yield
    
    # 4. Cleanup
    await trade_service.stop_price_updates()
    if db_pool: await db_pool.close()
    if neo4j_driver: await neo4j_driver.close()
    redis_task.cancel()
    logger.info("👋 Shutdown complete")

# FastAPI App
app = FastAPI(lifespan=lifespan)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Helpers
async def redis_listener():
    """Subscribe to Redis channels and broadcast via Socket.io."""
    retry_delay = 1
    max_delay = 30
    
    while True:
        try:
            logger.info(f"🔄 Connecting to Redis at {REDIS_URL}...")
            r = redis.from_url(REDIS_URL, decode_responses=True)
            
            # Test connection
            await r.ping()
            logger.info("✅ Redis connected")
            
            pubsub = r.pubsub()
            await pubsub.subscribe("solana:alerts", "solana:transactions")
            logger.info("🎧 Redis listener subscribed to channels")
            
            # Reset retry delay on successful connection
            retry_delay = 1
            
            async for message in pubsub.listen():
                if message["type"] == "message":
                    channel = message["channel"]
                    data = message["data"]
                    
                    logger.info(f"📨 Received: {channel} -> {data[:100]}...")
                    
                    # Broadcast to frontend
                    try:
                        parsed = json.loads(data)
                        await sio.emit("message", {"channel": channel, "data": parsed})
                        logger.info(f"📤 Emitted to {len(sio.manager.get_namespaces())} clients")
                    except json.JSONDecodeError as e:
                        logger.warning(f"Invalid JSON: {e}")
                    
        except asyncio.CancelledError:
            logger.info("Redis listener cancelled")
            break
        except Exception as e:
            logger.error(f"❌ Redis listener error: {e}")
            logger.info(f"🔄 Retrying in {retry_delay}s...")
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, max_delay)

# Routes
@app.get("/api/forensics")
async def get_forensics(limit: int = 10):
    """Fetch recent forensics logs."""
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT failure_category, details, detected_at 
            FROM trade_forensics 
            ORDER BY detected_at DESC 
            LIMIT $1
        """, limit)
        return [dict(row) for row in rows]

@app.get("/api/graph/wallet/{address}")
async def get_wallet_graph(address: str):
    """Query Neo4j for wallet connections."""
    query = """
        MATCH (w:Wallet {address: $address})-[r]-(n)
        RETURN w, r, n
        LIMIT 50
    """
    try:
        async with neo4j_driver.session() as session:
            result = await session.run(query, address=address)
            nodes = []
            links = []
            seen_nodes = set()
            
            async for record in result:
                # Process source
                w = record["w"]
                if w.element_id not in seen_nodes:
                    nodes.append({"id": w["address"], "label": list(w.labels)[0]})
                    seen_nodes.add(w.element_id)
                
                # Process target
                n = record["n"]
                if n.element_id not in seen_nodes:
                    # Handle different node types (Wallet, Transaction, etc)
                    props = dict(n)
                    label = list(n.labels)[0]
                    node_id = props.get("address", props.get("tx_hash", "unknown"))
                    nodes.append({"id": node_id, "label": label, **props})
                    seen_nodes.add(n.element_id)
                
                # Process link
                r = record["r"]
                links.append({
                    "source": w["address"], 
                    "target": n.get("address") or n.get("tx_hash"),
                    "type": r.type
                })
                
            return {"nodes": nodes, "links": links}
    except Exception as e:
        logger.error(f"Graph query failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/status")
async def get_status():
    """Get engine service status for dashboard display."""
    import time
    
    status = {
        "uptime_seconds": int(time.time() - app.state.start_time) if hasattr(app.state, 'start_time') else 0,
        "services": {
            "redis": {"status": "unknown", "message": ""},
            "postgres": {"status": "unknown", "message": ""},
            "neo4j": {"status": "unknown", "message": ""},
        },
        "websocket_clients": 0,
    }
    
    # Check Redis
    try:
        r = redis.from_url(REDIS_URL, decode_responses=True)
        await r.ping()
        status["services"]["redis"] = {"status": "connected", "message": "OK"}
    except Exception as e:
        status["services"]["redis"] = {"status": "error", "message": str(e)[:50]}
    
    # Check PostgreSQL
    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            status["services"]["postgres"] = {"status": "connected", "message": "OK"}
        except Exception as e:
            status["services"]["postgres"] = {"status": "error", "message": str(e)[:50]}
    else:
        status["services"]["postgres"] = {"status": "disconnected", "message": "Pool not initialized"}
    
    # Check Neo4j
    if neo4j_driver:
        try:
            async with neo4j_driver.session() as session:
                await session.run("RETURN 1")
            status["services"]["neo4j"] = {"status": "connected", "message": "OK"}
        except Exception as e:
            status["services"]["neo4j"] = {"status": "error", "message": str(e)[:50]}
    else:
        status["services"]["neo4j"] = {"status": "disconnected", "message": "Driver not initialized"}
    
    # WebSocket clients (approximate)
    try:
        status["websocket_clients"] = len(sio.manager.rooms.get("/", {}).get(None, set()))
    except:
        pass
    
    return status

# ============================================================================
# ANALYTICS ENDPOINTS - Performance Tracking
# ============================================================================

@app.get("/api/analytics/leaderboard")
async def get_analytics_leaderboard(source_type: str = None, min_trades: int = 1, limit: int = 20):
    """Get top performing signal sources ranked by win rate."""
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not connected")
    
    async with db_pool.acquire() as conn:
        query = """
            SELECT 
                source_id,
                source_type,
                source_name,
                total_trades,
                winning_trades,
                losing_trades,
                total_pnl,
                CASE WHEN total_trades > 0 
                    THEN ROUND(winning_trades::numeric / total_trades * 100, 1) 
                    ELSE 0 
                END as win_rate,
                EXTRACT(EPOCH FROM avg_hold_time) / 3600 as avg_hold_time_hours,
                last_updated
            FROM signal_attribution
            WHERE total_trades >= $1
            ORDER BY win_rate DESC, total_pnl DESC
            LIMIT $2
        """
        
        params = [min_trades, limit]
        
        try:
            rows = await conn.fetch(query, *params)
            return {
                "leaderboard": [dict(row) for row in rows],
                "count": len(rows)
            }
        except Exception as e:
            logger.error(f"Leaderboard query failed: {e}")
            # Return empty on table not exists
            return {"leaderboard": [], "count": 0, "error": str(e)}

@app.get("/api/analytics/summary")
async def get_analytics_summary():
    """Get aggregate statistics by source type."""
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not connected")
    
    async with db_pool.acquire() as conn:
        try:
            rows = await conn.fetch("""
                SELECT 
                    source_type,
                    COUNT(*) as source_count,
                    SUM(total_trades) as total_trades,
                    SUM(winning_trades) as total_wins,
                    SUM(total_pnl) as total_pnl,
                    CASE WHEN SUM(total_trades) > 0 
                        THEN ROUND(SUM(winning_trades)::numeric / SUM(total_trades) * 100, 1) 
                        ELSE 0 
                    END as overall_win_rate
                FROM signal_attribution
                GROUP BY source_type
                ORDER BY total_pnl DESC
            """)
            return {"summary": [dict(row) for row in rows]}
        except Exception as e:
            logger.error(f"Summary query failed: {e}")
            return {"summary": [], "error": str(e)}

@app.get("/api/analytics/daily")
async def get_analytics_daily(days: int = 7):
    """Get daily PnL summary."""
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not connected")
    
    async with db_pool.acquire() as conn:
        try:
            rows = await conn.fetch("""
                SELECT 
                    DATE(entry_time) as date,
                    COUNT(*) as trade_count,
                    COUNT(*) FILTER (WHERE realized_pnl > 0) as wins,
                    COUNT(*) FILTER (WHERE realized_pnl <= 0) as losses,
                    SUM(realized_pnl) as daily_pnl,
                    AVG(realized_pnl) as avg_pnl
                FROM trade_log
                WHERE entry_time > NOW() - INTERVAL '1 day' * $1
                    AND status = 'closed'
                GROUP BY DATE(entry_time)
                ORDER BY date DESC
            """, days)
            return {
                "daily": [dict(row) for row in rows],
                "period_days": days
            }
        except Exception as e:
            logger.error(f"Daily query failed: {e}")
            return {"daily": [], "period_days": days, "error": str(e)}

@app.post("/api/analyze/{address}")
async def analyze_wallet(address: str):
    """Run forensic analysis on a wallet address."""
    
    # 1. Check if it's a known Cabal/Influencer in DB
    is_cabal = False
    is_influencer = False
    cluster_id = None
    tags = []
    risk_score = 50
    win_rate = 50
    
    if db_pool:
        try:
            # Check tracked_wallets
            row = await db_pool.fetchrow(
                "SELECT category, confidence, metadata FROM tracked_wallets WHERE address = $1", 
                address
            )
            if row:
                logger.info(f"🔍 Found wallet in DB: {address[:8]}... category={row['category']}")
                if row['category'] == 'influencer':
                    is_influencer = True
                    tags.append("Influencer")
                    tags.append("High Signal")
                    risk_score = 15  # Low risk - known good actor
                    win_rate = int(row['confidence'] * 100) if row['confidence'] else 75
                elif row['category'] == 'cabal':
                    is_cabal = True
                    cluster_id = "Known_Cabal"
                    tags.append("Cabal Member")
                    tags.append("High Risk")
                    risk_score = 95
                    win_rate = 80
        except Exception as e:
            logger.error(f"Database query failed: {e}")
    else:
        logger.warning("Database pool not available for wallet analysis")
    
    # 2. Query Neo4j for detected cabal cluster membership
    if not is_cabal and not is_influencer and neo4j_driver:
        try:
            async with neo4j_driver.session() as session:
                result = await session.run(
                    """
                    MATCH (w:Wallet {address: $address})-[:MEMBER_OF]->(c:Cluster)
                    RETURN c.cluster_id AS cluster_id, 
                           c.member_count AS member_count,
                           c.shared_contracts_count AS shared_contracts
                    LIMIT 1
                    """,
                    address=address
                )
                record = await result.single()
                
                if record:
                    is_cabal = True
                    cluster_id = record["cluster_id"]
                    member_count = record["member_count"] or 0
                    shared_contracts = record["shared_contracts"] or 0
                    
                    logger.info(f"🔴 Cabal cluster detected for {address[:8]}...: {cluster_id[:8]}...")
                    tags.append("Cabal Member")
                    tags.append("Detected Cluster")
                    
                    # Risk score based on cluster size
                    risk_score = min(99, 50 + (member_count * 5) + (shared_contracts * 3))
                    win_rate = 70 + min(20, member_count * 2)
        except Exception as e:
            logger.error(f"Neo4j query failed: {e}")
    
    # 3. Fallback for unknown wallets (no mock randomness - honest "unknown" status)
    if not is_cabal and not is_influencer:
        tags.append("Unknown")
        risk_score = 50  # Neutral
        win_rate = 50
        
    return {
        "wallet": address,
        "is_cabal": is_cabal,
        "is_influencer": is_influencer,
        "cluster_id": cluster_id,
        "risk_score": risk_score,
        "win_rate": win_rate,
        "tags": tags,
        "analysis_timestamp": asyncio.get_event_loop().time()
    }

@app.get("/api/graph/demo")
async def get_demo_graph():
    """Return mock graph data for demo/testing without Neo4j."""
    # Generate a sample cabal cluster
    center = "DemoWallet123456789abcdefghij"
    
    nodes = [
        {"id": center, "label": "Wallet", "type": "target"},
        {"id": "Cabal_AlphaWhales", "label": "Cabal", "type": "group"},
    ]
    links = [
        {"source": center, "target": "Cabal_AlphaWhales", "type": "MEMBER_OF"},
    ]
    
    # Add connected wallets
    for i in range(6):
        wallet_id = f"Wallet_{chr(65+i)}{'x'*10}{i}"
        nodes.append({"id": wallet_id, "label": "Wallet", "type": "member"})
        links.append({"source": wallet_id, "target": "Cabal_AlphaWhales", "type": "MEMBER_OF"})
        # Some wallets trade with each other
        if i > 0:
            links.append({"source": f"Wallet_{chr(64+i)}{'x'*10}{i-1}", "target": wallet_id, "type": "TRADED_WITH"})
    
    # Add some token nodes
    for i in range(3):
        token_id = f"Token_{['BONK', 'WIF', 'POPCAT'][i]}"
        nodes.append({"id": token_id, "label": "Token", "type": "asset"})
        links.append({"source": center, "target": token_id, "type": "HOLDS"})
    
    return {"nodes": nodes, "links": links}

# ============================================================================
# TRADE EXECUTION ENDPOINTS
# ============================================================================

from pydantic import BaseModel
from typing import Optional

class TradeRequest(BaseModel):
    token_mint: str
    amount_sol: float
    token_symbol: Optional[str] = None
    source: str = "copy_trade"
    source_id: Optional[str] = None

@app.post("/api/trade/execute")
async def execute_trade(request: TradeRequest):
    """Execute a copy trade (buy)."""
    from api.trade_service import trade_service
    
    result = await trade_service.execute_copy_trade(
        token_mint=request.token_mint,
        amount_sol=request.amount_sol,
        source=request.source,
        source_id=request.source_id,
        token_symbol=request.token_symbol,
    )
    
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error", "Trade failed"))
    
    return result

@app.get("/api/trade/positions")
async def get_positions():
    """Get all open positions."""
    from api.trade_service import trade_service
    return {
        "positions": trade_service.get_positions(),
        "summary": trade_service.get_pnl_summary(),
    }

@app.get("/api/trade/history")
async def get_trade_history(limit: int = 50):
    """Get recent trade history."""
    from api.trade_service import trade_service
    return {"trades": trade_service.get_trade_history(limit)}

@app.post("/api/trade/close/{trade_id}")
async def close_position(trade_id: str):
    """Close an open position."""
    from api.trade_service import trade_service
    
    result = await trade_service.close_position(trade_id)
    
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error", "Close failed"))
    
    return result

@app.get("/api/trade/pnl")
async def get_pnl():
    """Get PnL summary."""
    from api.trade_service import trade_service
    return trade_service.get_pnl_summary()

# Mount Socket.io at root path (it uses /socket.io internally)
app.mount("/socket.io", socket_app)

# Mount Static Files (Frontend)
# Must be last to avoid catching API routes
app.mount("/", StaticFiles(directory="web", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
