import asyncio
import socket
import time
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter
from app.core.config import settings

router = APIRouter()


async def check_postgres() -> Dict[str, Any]:
    start_time = time.perf_counter()
    try:
        import asyncpg
        conn = await asyncio.wait_for(
            asyncpg.connect(
                user=settings.POSTGRES_USER,
                password=settings.POSTGRES_PASSWORD,
                database=settings.POSTGRES_DB,
                host=settings.POSTGRES_HOST,
                port=settings.POSTGRES_PORT,
            ),
            timeout=3.0,
        )
        val = await conn.fetchval("SELECT 1")
        await conn.close()
        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
        if val == 1:
            return {"status": "connected", "latency_ms": latency_ms, "message": "Database query succeeded (SELECT 1)"}
        return {"status": "degraded", "latency_ms": latency_ms, "message": f"Unexpected response: {val}"}
    except Exception as e:
        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return {"status": "offline", "latency_ms": latency_ms, "error": str(e)}


async def check_redis() -> Dict[str, Any]:
    start_time = time.perf_counter()
    try:
        import redis.asyncio as redis
        client = redis.from_url(settings.REDIS_URL, socket_connect_timeout=3.0)
        pong = await client.ping()
        await client.aclose()
        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
        if pong:
            return {"status": "connected", "latency_ms": latency_ms, "message": "Redis PING succeeded"}
        return {"status": "degraded", "latency_ms": latency_ms, "message": "Redis PING returned False"}
    except Exception as e:
        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return {"status": "offline", "latency_ms": latency_ms, "error": str(e)}


async def check_mqtt() -> Dict[str, Any]:
    start_time = time.perf_counter()
    host = settings.MQTT_BROKER_HOST
    port = settings.MQTT_BROKER_PORT
    try:
        loop = asyncio.get_event_loop()
        def _tcp_ping():
            with socket.create_connection((host, port), timeout=3.0):
                pass
        await loop.run_in_executor(None, _tcp_ping)
        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return {"status": "connected", "latency_ms": latency_ms, "message": f"MQTT TCP socket port {port} reachable"}
    except Exception as e:
        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return {"status": "offline", "latency_ms": latency_ms, "error": str(e)}


@router.get("/health")
async def get_health():
    pg_res, redis_res, mqtt_res = await asyncio.gather(
        check_postgres(),
        check_redis(),
        check_mqtt()
    )

    statuses = [pg_res["status"], redis_res["status"], mqtt_res["status"]]
    if all(s == "connected" for s in statuses):
        overall_status = "healthy"
    elif any(s == "connected" for s in statuses):
        overall_status = "degraded"
    else:
        overall_status = "down"

    return {
        "status": overall_status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": {
            "backend": {"status": "connected", "latency_ms": 0.0, "message": "FastAPI engine active"},
            "postgres": pg_res,
            "redis": redis_res,
            "mqtt": mqtt_res,
        }
    }
