"""Offline classic-PCAP UDP stream analyzer; never calls packet gaps network loss."""
from __future__ import annotations
import ipaddress
import struct
from pathlib import Path
from .metrics import summary, variation

MAGIC_FORMATS = {b"\xd4\xc3\xb2\xa1": ("<", 1000), b"\xa1\xb2\xc3\xd4": (">", 1000),
                 b"\x4d\x3c\xb2\xa1": ("<", 1), b"\xa1\xb2\x3c\x4d": (">", 1)}


def _packet(data: bytes, linktype: int) -> dict | None:
    if linktype != 1:  # Ethernet only
        raise ValueError("Only Ethernet link type 1 supported")
    if len(data) < 14:
        return None
    ethernet_type = struct.unpack_from("!H", data, 12)[0]
    offset = 14
    if ethernet_type == 0x8100 and len(data) >= 18:  # single VLAN tag
        ethernet_type = struct.unpack_from("!H", data, 16)[0]
        offset = 18
    if ethernet_type != 0x0800 or len(data) < offset + 20:
        return None
    version, ihl = data[offset] >> 4, (data[offset] & 15) * 4
    if version != 4 or ihl < 20 or len(data) < offset + ihl + 8:
        return None
    total_length = struct.unpack_from("!H", data, offset + 2)[0]
    if total_length < ihl + 8 or len(data) < offset + total_length:
        return None
    frag = struct.unpack_from("!H", data, offset + 6)[0]
    if frag & 0x3fff:  # fragmented UDP cannot be analyzed safely here
        return None
    if data[offset + 9] != 17:
        return None
    src = str(ipaddress.IPv4Address(data[offset + 12:offset + 16]))
    dst = str(ipaddress.IPv4Address(data[offset + 16:offset + 20]))
    udp = offset + ihl
    src_port, dst_port, udp_len = struct.unpack_from("!HHH", data, udp)
    if udp_len < 8 or udp_len > total_length - ihl:
        return None
    return {"src": src, "dst": dst, "src_port": src_port, "dst_port": dst_port,
            "payload": data[udp+8:udp+udp_len]}


def analyze_pcap(path: Path, *, dst_port: int, sequence_offset: int = 0) -> dict:
    """Count unique 32-bit big-endian sequence ids within one UDP destination port.

    Intended for finite, single-source, NON-wrapping controlled packet captures.
    Missing sequence ids in capture can indicate capture drops, upstream gaps,
    a receiver filter, or true network loss; cannot distinguish them.
    """
    if dst_port < 1 or dst_port > 65535 or sequence_offset < 0:
        raise ValueError("Invalid port/sequence offset")
    with path.open("rb") as stream:
        header = stream.read(24)
        if len(header) != 24 or header[:4] not in MAGIC_FORMATS:
            raise ValueError("Not a supported classic PCAP file (PCAPNG not supported)")
        endian, divisor = MAGIC_FORMATS[header[:4]]
        _major, _minor, _zone, _sigfigs, snaplen, linktype = struct.unpack(endian+"HHiIII", header[4:])
        if snaplen == 0 or snaplen > 16_777_216:
            raise ValueError("Unsupported snaplen")
        if linktype != 1:
            raise ValueError("Only Ethernet captures supported")
        seen: set[int] = set()
        counts = {"records": 0, "matched_udp": 0, "short_payload": 0, "duplicate": 0, "out_of_order": 0}
        previous_max = -1
        times_ns: list[int] = []
        flow_seen: set[tuple] = set()
        samples = 0
        while True:
            packet_header = stream.read(16)
            if not packet_header:
                break
            if len(packet_header) != 16:
                raise ValueError("Truncated packet record header")
            sec, subsec, included, original = struct.unpack(endian+"IIII", packet_header)
            if included > snaplen or included > 16_777_216 or included > original:
                raise ValueError("Invalid captured packet length")
            frame = stream.read(included)
            if len(frame) != included:
                raise ValueError("Truncated frame data")
            counts["records"] += 1
            record = _packet(frame, linktype)
            if record is None or record["dst_port"] != dst_port:
                continue
            counts["matched_udp"] += 1
            flow_seen.add((record["src"], record["src_port"], record["dst"], record["dst_port"]))
            if len(flow_seen) > 1:
                raise ValueError("Multiple UDP flows on target port; capture/filter a single 4-tuple before analyzing sequence gaps")
            if len(record["payload"]) < sequence_offset + 4:
                counts["short_payload"] += 1
                continue
            seq = struct.unpack_from("!I", record["payload"], sequence_offset)[0]
            if seq in seen:
                counts["duplicate"] += 1
            elif seq < previous_max:
                counts["out_of_order"] += 1
            else:
                previous_max = seq
            seen.add(seq)
            times_ns.append(sec*1_000_000_000+subsec*divisor)
            samples += 1
        if not seen:
            missing = None
        else:
            missing = max(seen)-min(seen)+1-len(seen)
        gaps_ms = [(times_ns[i]-times_ns[i-1])/1_000_000 for i in range(1, len(times_ns))]
        regressions = sum(1 for d in gaps_ms if d < 0)
        return {"file": path.name, "method": "offline_udp_sequence_analysis",
                "dst_port": dst_port, "sequence_offset_bytes": sequence_offset,
                "records_read": counts["records"], "matching_datagrams": counts["matched_udp"],
                "sequence_observations": samples, "unique_sequences": len(seen),
                "sequence_span": [min(seen), max(seen)] if seen else None,
                "missing_sequences_in_capture": missing,
                "duplicates": counts["duplicate"], "out_of_order": counts["out_of_order"],
                "short_payload": counts["short_payload"],
                "capture_time_regressions": regressions,
                "arrival_intervals_ms": summary([d for d in gaps_ms if d >= 0]),
                "arrival_interval_variation_ms": variation([d for d in gaps_ms if d >= 0]),
                "limitations": "Single finite non-wrapping stream assumed. Missing ids are capture gaps, NOT proven on-wire loss; timestamps inherit capture clock/precision; no pcapng/IPv6/multiflow support."}
