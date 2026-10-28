# Measurement accuracy and interpretation

| Metric | Definition in this project | Does NOT imply |
|---|---|---|
| TCP connect duration | `perf_counter_ns` difference before/after `asyncio.open_connection`, milliseconds | Wire RTT, one-way latency, kernel bypass performance |
| `connect_ms.p99` | Nearest rank `ceil(0.99*n)` of successful attempts | High-confidence HFT tail SLA from short tests |
| TCP failure rate | Refused/timed-out attempts / total explicit TCP attempts | Actual network packet loss |
| UDP sequence gap | Missing integer IDs between min/max observed in a **single** capture | Definite on-wire packet loss |
| UDP out-of-order | Newly observed sequence lower than greatest previously seen | Router reordering specifically; capture artifacts possible |
| Arrival interval variation | Absolute difference of adjacent observed capture intervals | RFC 3550 jitter or hardware timestamped arrival jitter |
| BGP snapshot drift | Change in observed peer state or bestpath | Fast or slow forwarding-plane convergence |

## Recommended validation for later versions

1. Run a separate sequenced sender and receiver with identical IDs, recording both sides. Compare sender logs with receiver logs and PCAP for capture-drop attribution.
2. Record OS version, NIC, CPU, clock source, affinity, congestion configuration and container boundaries alongside all measurements.
3. Use a large sample size and report histograms / outliers. Do not compare VM measurements to bare-metal microsecond latency claims.
4. For BGP, poll control-plane changes **and** continuously send sequenced UDP traffic; report both timelines separately.
