"""
Solana Intel Engine - Robust Development Runner

Starts all services concurrently with pre-flight validation.
Prevents "start-fail" loops by ensuring dependencies are ready.

Usage: python run_dev.py
"""

import asyncio
import subprocess
import sys
import os
import socket
import logging
from typing import List

# Third-party imports for checks
try:
    import redis.asyncio as redis
    import asyncpg
    from dotenv import load_dotenv
except ImportError:
    print("❌ Missing dependencies! Run: pip install redis asyncpg python-dotenv")
    sys.exit(1)

load_dotenv()

# Colors for terminal output
class Colors:
    API = "\033[94m"      # Blue
    INGESTION = "\033[92m" # Green
    LOGIC = "\033[93m"     # Yellow
    ERROR = "\033[91m"     # Red
    SUCCESS = "\033[92m"   # Green
    RESET = "\033[0m"
    BOLD = "\033[1m"

# Enable ANSI on Windows
if sys.platform == "win32":
    os.system("")

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("runner")

def print_banner():
    print(f"""
{Colors.BOLD}{'='*60}
   SOLANA INTEL ENGINE - Robust Launcher
{'='*60}{Colors.RESET}
    """)

async def check_port(host: str, port: int) -> bool:
    """Check if a port is in use."""
    try:
        reader, writer = await asyncio.open_connection(host, port)
        writer.close()
        await writer.wait_closed()
        return True
    except:
        return False

async def preflight_checks() -> bool:
    """Run system checks before starting services."""
    print(f"{Colors.BOLD}>>> Running Pre-flight Checks...{Colors.RESET}")
    all_passed = True

    # 1. Check Redis
    redis_url = f"redis://{os.getenv('REDIS_HOST', 'localhost')}:{os.getenv('REDIS_PORT', '6379')}"
    try:
        r = redis.from_url(redis_url)
        await r.ping()
        print(f"  [OK] Redis connected")
        await r.aclose()
    except Exception as e:
        print(f"  {Colors.ERROR}[X] Redis check failed: {e}{Colors.RESET}")
        print("     -> Is Docker running? Try: docker compose up -d redis")
        all_passed = False

    # 2. Check Postgres
    pg_dsn = f"postgresql://{os.getenv('POSTGRES_USER', 'admin')}:{os.getenv('POSTGRES_PASSWORD', 'password')}@{os.getenv('POSTGRES_HOST', 'localhost')}:{os.getenv('POSTGRES_PORT', '5432')}/{os.getenv('POSTGRES_DB', 'solana_intel')}"
    try:
        conn = await asyncpg.connect(pg_dsn)
        await conn.close()
        print(f"  [OK] PostgreSQL connected")
    except Exception as e:
        print(f"  {Colors.ERROR}[X] Postgres check failed: {e}{Colors.RESET}")
        print("     -> Is Docker running? Try: docker compose up -d postgres")
        all_passed = False

    # 3. Check Ports (API)
    if await check_port("localhost", 8000):
        print(f"  {Colors.ERROR}[X] Port 8000 is already in use!{Colors.RESET}")
        print("     -> Kill existing python processes or stop other services.")
        all_passed = False
    else:
        print(f"  [OK] Port 8000 available")

    return all_passed

def kill_stale_processes():
    """Kill lingering Python processes related to the engine."""
    if sys.platform != "win32":
        return

    print(f"{Colors.BOLD}🧹 Cleaning up stale processes...{Colors.RESET}")
    # This is a basic cleanup. Be careful not to kill the runner itself.
    # In a real environment, we'd use psutil for precision.
    # For now, we rely on the user manually handling big messes, 
    # but we can try to close known conflicting windows if needed.
    pass

async def run_service(name: str, module: str, color: str):
    """Run a service and stream output."""
    print(f"{color}[{name}]{Colors.RESET} Starting...")
    
    cmd = [sys.executable, "-m", module]
    
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=os.path.dirname(os.path.abspath(__file__)),
            env={**os.environ, "PYTHONUNBUFFERED": "1"}
        )
        
        async for line in process.stdout:
            text = line.decode(errors='ignore').rstrip()
            if text:
                # Add service prefix
                print(f"{color}[{name}]{Colors.RESET} {text}")
                
        await process.wait()
        if process.returncode != 0:
            print(f"{Colors.ERROR}[{name}] Crashed with code {process.returncode}{Colors.RESET}")
            
    except asyncio.CancelledError:
        print(f"{Colors.BOLD}[{name}] Stopping...{Colors.RESET}")
        process.terminate()
        await process.wait()
    except Exception as e:
        print(f"{Colors.ERROR}[{name}] Failed to start: {e}{Colors.RESET}")

async def main():
    print_banner()
    
    # Run Checks
    if not await preflight_checks():
        print(f"\n{Colors.ERROR}!!! checks failed! Fix issues above and try again.{Colors.RESET}")
        sys.exit(1)
        
    print(f"\n{Colors.SUCCESS}>>> All systems go! Launching services...{Colors.RESET}\n")

    # Services to run
    services = [
        ("API", "api.server", Colors.API),
        ("INGESTION", "ingestion.main", Colors.INGESTION),
        ("LOGIC", "logic.main", Colors.LOGIC),
    ]
    
    tasks = [run_service(name, mod, col) for name, mod, col in services]
    
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        print("\n👋 Shutdown initiated...")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{Colors.BOLD}🛑 Stopping All Services...{Colors.RESET}")
        # Tasks are cancelled automatically by asyncio.run in newer python versions 
        # or we rely on the OS to cleanup subprocesses if they are attached.
        sys.exit(0)
