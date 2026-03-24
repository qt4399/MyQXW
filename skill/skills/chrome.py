from urllib.parse import quote
from playwright.sync_api import sync_playwright

query = quote("手机功耗优化")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    page.goto(f"https://www.google.com/search?q={query}", wait_until="domcontentloaded")

    page.wait_for_selector("h3", timeout=10000)
    titles = page.locator("h3").all_inner_texts()
    print(titles[:5])

    browser.close()
