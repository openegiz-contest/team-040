"""Check the live dispatcher UI without issuing model commands. Requires Chrome."""

import argparse
import json
import os

from team.ui.tools.cdp import Browser


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.environ.get("TEAM_UI_URL", "http://127.0.0.1:8088"))
    parser.add_argument("--screenshot")
    args = parser.parse_args()
    with Browser(1280, 720) as browser:
        page = browser.new_page()
        page.goto(args.url)
        try:
            page.wait_for("document.body.dataset.boot === 'ready' && document.body.dataset.snapshot === 'ok' && document.body.dataset.link === 'ok'", timeout=25)
        finally:
            if args.screenshot:
                page.screenshot(args.screenshot)
        result = page.evaluate("Object.assign({}, document.body.dataset)")
        errors = list(page.console_errors)
        assert not errors, errors
        print(json.dumps(dict(result="PASS", live_url=args.url, body=result, console_errors=errors)), flush=True)


if __name__ == "__main__":
    main()
