"""Render team/presentation/index.html to presentation.pdf at the repository root.

One 16:9 page (1920x1080 CSS px, 20 x 11.25 in) per slide, each in the final
state of its slide; text stays text (selectable). The live three.js mine is
drawn in software WebGL (SwiftShader) and placed on the hero pages as a still.

    python team/presentation/tools/render_pdf.py [--out presentation.pdf]

Needs Google Chrome (found by team/ui/tools/cdp.py, or CHROME_PATH) and pypdf.
Serves the repository on a free local port for the run; nothing is downloaded.
Also writes team/presentation/img/mine-overview.jpg, the backdrop shown when a
browser has no WebGL.
"""

from __future__ import annotations

import argparse
import base64
import functools
import http.server
import io
import os
import sys
import threading

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "team", "ui", "tools"))

from cdp import Browser  # noqa: E402
from pypdf import PdfReader, PdfWriter  # noqa: E402


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def serve(root):
    handler = functools.partial(_Quiet, directory=root)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", default=os.path.join(ROOT, "presentation.pdf"))
    args = parser.parse_args()

    server = serve(ROOT)
    url = f"http://127.0.0.1:{server.server_address[1]}/team/presentation/index.html?print"
    writer = PdfWriter()
    try:
        with Browser(width=1920, height=1080,
                     extra_args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"]) as browser:
            page = browser.new_page()
            page.set_viewport(1920, 1080)
            page.send("Emulation.setEmulatedMedia", {"media": "print"})
            page.goto(url, timeout=60)
            page.wait_for("document.body.dataset.boot === 'ready'", timeout=90)
            state = page.evaluate("document.body.dataset.mine")
            if state != "ready":
                raise SystemExit(f"the 3D mine did not load in Chrome (state {state!r}); the PDF would lack it")
            still = page.evaluate("window.deck.still('overview')", timeout=60)
            if still and still.startswith("data:image/jpeg;base64,"):
                path = os.path.join(ROOT, "team", "presentation", "img", "mine-overview.jpg")
                with open(path, "wb") as handle:
                    handle.write(base64.b64decode(still.split(",", 1)[1]))
            count = page.evaluate("window.deck.count")
            for index in range(count):
                info = page.evaluate(f"window.deck.prepare({index})", timeout=90)
                result = page.send("Page.printToPDF", {
                    "paperWidth": 20, "paperHeight": 11.25,
                    "marginTop": 0, "marginBottom": 0, "marginLeft": 0, "marginRight": 0,
                    "printBackground": True, "preferCSSPageSize": True, "pageRanges": "1",
                }, timeout=120)
                reader = PdfReader(io.BytesIO(base64.b64decode(result["data"])))
                writer.add_page(reader.pages[0])
                print(f"page {index + 1:02d}/{count}: {info['label']}{' (3D still)' if info['hero'] else ''}")
            if page.console_errors:
                raise SystemExit(f"console errors: {page.console_errors}")
    finally:
        server.shutdown()
    writer.add_metadata({"/Title": "Team 040 — кого выводить и чего это стоит", "/Author": "Team 040"})
    writer.compress_identical_objects(remove_identicals=True, remove_orphans=True)
    with open(args.out, "wb") as handle:
        writer.write(handle)
    print(f"{args.out}: {len(writer.pages)} pages, {os.path.getsize(args.out) / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
