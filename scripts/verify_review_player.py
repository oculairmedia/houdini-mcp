"""Playwright acceptance for a published local review (isolated headless browser)."""

import argparse
import json
from pathlib import Path


def main():
    from playwright.sync_api import sync_playwright

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("index", type=Path)
    parser.add_argument("--browser", type=Path)
    args = parser.parse_args()
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True, executable_path=str(args.browser) if args.browser else None
        )
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(args.index.resolve().as_uri())
        page.wait_for_function(
            "document.querySelector('#counter').textContent.includes('Frame 1 ')"
        )
        assert page.locator("#views img").count() == 2
        page.locator("#frame").fill("1")
        page.wait_for_function(
            "[...document.querySelectorAll('#views img')].every(i=>i.dataset.frame==='1.01' && i.complete && i.naturalWidth>0)"
        )
        assert "Continuous boundary" in page.locator("#annotation").inner_text()
        page.locator("#speed").select_option("0.5")
        page.get_by_role("button", name="Play", exact=True).click()
        page.wait_for_function(
            "document.querySelector('#counter').textContent.includes('Frame 4 ')"
        )
        assert page.get_by_role("button", name="Play", exact=True).count() == 1
        page.locator("h1").click()
        page.keyboard.press("ArrowLeft")
        page.wait_for_function(
            "[...document.querySelectorAll('#views img')].every(i=>i.dataset.frame==='3')"
        )
        assert page.locator("#error").inner_text() == ""
        assert not errors, errors
        page.screenshot(path=str(args.index.parent / "player-acceptance.png"), full_page=True)
        report = {
            "passed": True,
            "checks": [
                "two-view image decode",
                "synchronized scrubbing",
                "annotation binding",
                "half-speed playback",
                "end-of-sequence stop",
                "keyboard frame step",
            ],
            "page_errors": errors,
        }
        (args.index.parent / "player-acceptance.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report))
        browser.close()


if __name__ == "__main__":
    main()
