"""scripts/measure_drift.py
---------------------------
Stdlib-only NTP-style UDP clock-offset measurement between Starling node
hosts.

STARLING_BUILD_STATE.md §15 predicts most debugging hours go to clock
issues. Measuring drift from day one is how that's caught early instead of
during a demo: run this alongside the real nodes, pointed at each other's
`--listen-port`, and it appends every measurement to
`results/clock_drift.csv` and prints the mean/max absolute offset.

Protocol (classic NTP four-timestamp exchange, one UDP datagram round trip):
  client sends t1 (its own clock) ->
  server stamps t2 (receipt) and t3 (send) and echoes t1, t2, t3 back ->
  client stamps t4 (receipt) and computes
    offset = ((t2 - t1) + (t3 - t4)) / 2
    delay  = (t4 - t1) - (t3 - t2)

Every instance of this script both serves (so peers can measure against
it) and pings its configured peers, symmetrically.

Usage
-----
    python scripts/measure_drift.py --listen-port 6000 \\
        --peers 192.168.1.11:6000 192.168.1.12:6000 \\
        --interval 60 --iterations 0   # 0 = run forever
"""

from __future__ import annotations

import argparse
import csv
import socket
import statistics
import struct
import threading
import time
from pathlib import Path
from typing import Optional

_MAGIC = b"STARLING-DRIFT-PING"
_CLIENT_FMT = "!d"
_SERVER_FMT = "!ddd"


def _serve(listen_port: int, stop_event: threading.Event) -> None:
    """UDP responder: echoes back (t1, t2, t3) for each ping received."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", listen_port))
    sock.settimeout(0.5)
    try:
        while not stop_event.is_set():
            try:
                data, addr = sock.recvfrom(1024)
            except socket.timeout:
                continue
            if not data.startswith(_MAGIC):
                continue
            t2 = time.time()
            (t1,) = struct.unpack(_CLIENT_FMT, data[len(_MAGIC):])
            t3 = time.time()
            sock.sendto(_MAGIC + struct.pack(_SERVER_FMT, t1, t2, t3), addr)
    finally:
        sock.close()


def ping(peer_host: str, peer_port: int, timeout: float = 2.0) -> Optional[dict]:
    """One NTP-style round trip against a peer. None on timeout."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        t1 = time.time()
        sock.sendto(_MAGIC + struct.pack(_CLIENT_FMT, t1), (peer_host, peer_port))
        try:
            data, _ = sock.recvfrom(1024)
        except socket.timeout:
            return None
        t4 = time.time()
    finally:
        sock.close()

    if not data.startswith(_MAGIC):
        return None
    t1_echo, t2, t3 = struct.unpack(_SERVER_FMT, data[len(_MAGIC):])
    offset = ((t2 - t1_echo) + (t3 - t4)) / 2.0
    delay = (t4 - t1_echo) - (t3 - t2)
    return {"offset_s": offset, "delay_s": delay}


def _parse_peer(spec: str) -> tuple[str, int]:
    host, port = spec.rsplit(":", 1)
    return host, int(port)


def _append_csv(out_path: Path, rows: list[dict]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not out_path.exists()
    with out_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "peer", "offset_s", "delay_s"])
        if is_new:
            writer.writeheader()
        writer.writerows(rows)


def run(
    listen_port: int,
    peers: list[str],
    interval_s: float = 60.0,
    iterations: int = 1,
    out_path: Path = Path("results/clock_drift.csv"),
) -> None:
    """Serve + ping `peers` every `interval_s` seconds. `iterations=0` runs forever."""
    stop_event = threading.Event()
    server_thread = threading.Thread(
        target=_serve, args=(listen_port, stop_event), daemon=True
    )
    server_thread.start()

    try:
        round_num = 0
        while iterations == 0 or round_num < iterations:
            rows = []
            offsets = []
            for spec in peers:
                host, port = _parse_peer(spec)
                result = ping(host, port)
                if result is None:
                    print(f"[measure_drift] {spec}: no response (timeout)")
                    continue
                offsets.append(result["offset_s"])
                rows.append({
                    "timestamp": time.time(),
                    "peer": spec,
                    "offset_s": result["offset_s"],
                    "delay_s": result["delay_s"],
                })

            if rows:
                _append_csv(out_path, rows)

            if offsets:
                abs_offsets = [abs(o) for o in offsets]
                print(
                    f"[measure_drift] round {round_num}: "
                    f"mean_offset={statistics.mean(offsets):+.6f}s  "
                    f"max_abs_offset={max(abs_offsets):.6f}s"
                )

            round_num += 1
            if iterations == 0 or round_num < iterations:
                time.sleep(interval_s)
    finally:
        stop_event.set()
        server_thread.join(timeout=2)


def main(argv: Optional[list] = None) -> None:
    parser = argparse.ArgumentParser(
        description="NTP-style UDP clock-offset measurement between Starling nodes"
    )
    parser.add_argument("--listen-port", type=int, required=True)
    parser.add_argument("--peers", nargs="+", required=True, help="host:port list")
    parser.add_argument("--interval", type=float, default=60.0)
    parser.add_argument("--iterations", type=int, default=0, help="0 = run forever")
    parser.add_argument("--out", default="results/clock_drift.csv")
    args = parser.parse_args(argv)

    run(
        listen_port=args.listen_port,
        peers=args.peers,
        interval_s=args.interval,
        iterations=args.iterations,
        out_path=Path(args.out),
    )


if __name__ == "__main__":
    main()
