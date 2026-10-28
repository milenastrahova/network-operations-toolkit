"""Bounded serial TCP connect sampler, not a TCP/application latency or ICMP RTT test."""
from __future__ import annotations
import asyncio
import time
from datetime import datetime, timezone
from .metrics import summary, variation


async def run_tcp_probe(host: str, port: int, *, count: int = 20,
                        interval_seconds: float = 0.2, timeout_seconds: float = 1.0) -> dict:
    if not (0 < port < 65536 and 1 <= count <= 10000 and 0 <= interval_seconds <= 3600
            and 0 < timeout_seconds <= 60):
        raise ValueError("Invalid/unsafe TCP sampler parameters")
    events = []
    values = []
    for i in range(count):
        began = time.perf_counter_ns()
        connected = False
        error_kind = None
        writer = None
        try:
            _reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout_seconds)
            connected = True
        except (OSError, asyncio.TimeoutError) as error:
            error_kind = type(error).__name__
        finally:
            elapsed = (time.perf_counter_ns() - began) / 1_000_000
            if writer is not None:
                writer.close()
                try:
                    await asyncio.wait_for(writer.wait_closed(), 0.3)
                except (OSError, asyncio.TimeoutError, ConnectionError):
                    pass
        if connected:
            values.append(elapsed)
        events.append({"index": i, "success": connected,
                       "connect_ms": round(elapsed, 6) if connected else None, "error_type": error_kind})
        if i + 1 < count:
            await asyncio.sleep(interval_seconds)
    return {"observed_at_utc": datetime.now(timezone.utc).isoformat(),
            "target": {"host": host, "port": port}, "method": "TCP_connect_duration_userspace",
            "attempts": count, "failures": count-len(values),
            "failure_rate_percent": (count-len(values))/count*100,
            "connect_ms": summary(values), "variation_ms": variation(values), "events": events,
            "limitations": "Connect duration includes kernel scheduling and handshake; not one-way network latency, ICMP RTT, or wire-level packet loss."}
