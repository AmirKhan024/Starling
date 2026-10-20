"""apps/world/rig.py
--------------------
Runs the CAMERA RIG: a headless Chromium (via Playwright) that opens the
world server's /rig page, which renders every camera's view with three.js
on each frame tick and sends the JPEGs back to the world server.

It is a separate OS process so the cameras keep filming no matter what the
presenter does with their own browser (a hidden or closed tab would
otherwise stop rendering). It asks for the GPU (ANGLE/D3D11 on Windows) and
falls back to Chromium's software renderer if there is none.

Run:  python -m apps.world.rig --url http://127.0.0.1:8770
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from typing import Any, Optional

from starling_net.logging import get_logger, setup_logging

log = get_logger(__name__)

_GPU_ARGS = [
    "--use-angle=d3d11",
    "--enable-gpu",
    "--ignore-gpu-blocklist",
    "--enable-unsafe-swiftshader",
]
_STATUS_EVERY_S = 10.0


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Starling camera rig (headless renderer for the world's cameras)"
    )
    ap.add_argument("--url", default="http://127.0.0.1:8770")
    ap.add_argument("--software", action="store_true", help="force Chromium's software GL (no GPU)")
    args = ap.parse_args(argv)
    setup_logging(-1)

    from playwright.sync_api import sync_playwright

    stop = {"requested": False}

    def _sig(signum: int, frame: Any) -> None:
        stop["requested"] = True

    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    with sync_playwright() as p:
        launch_args = (
            ["--enable-unsafe-swiftshader"]
            if args.software or sys.platform != "win32"
            else _GPU_ARGS
        )
        browser = p.chromium.launch(headless=True, args=launch_args)
        page = browser.new_page(viewport={"width": 640, "height": 360})
        page.on(
            "console",
            lambda m: (
                log.info("rig_console", text=m.text[:300])
                if m.type in ("error", "warning")
                else None
            ),
        )
        page.on("pageerror", lambda e: log.error("rig_page_error", error=str(e)[:300]))
        while not stop["requested"]:
            try:
                page.goto(args.url.rstrip("/") + "/rig", wait_until="load", timeout=20000)
                break
            except Exception as exc:  # the world server is still starting
                log.info("rig_waiting_for_world", error=str(exc)[:120])
                time.sleep(1.0)
        renderer = page.evaluate(
            "() => { const g = document.createElement('canvas').getContext('webgl2');"
            " const e = g && g.getExtension('WEBGL_debug_renderer_info');"
            " return e ? g.getParameter(e.UNMASKED_RENDERER_WEBGL) : 'unknown'; }"
        )
        log.info("rig_started", gl_renderer=renderer)
        print(f"camera rig running (GL: {renderer})", file=sys.stderr, flush=True)  # CLI banner
        last = time.monotonic()
        while not stop["requested"]:
            page.wait_for_timeout(500)
            if time.monotonic() - last >= _STATUS_EVERY_S:
                last = time.monotonic()
                try:
                    log.info("rig_status", **page.evaluate("() => window.rigStats || {}"))
                except Exception as exc:
                    log.warning("rig_status_failed", error=str(exc)[:200])
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
