from playwright.sync_api import sync_playwright, TimeoutError

url = "https://www.69shuba.com/book/88724.htm"

def solve_captcha_and_scrape(target_url):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False) # Start in headless
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        try:
            print(f"Navigating to {target_url}...")
            page.goto(target_url, wait_until="domcontentloaded", timeout=60000)

            # --- NEW CAPTCHA HANDLING LOGIC ---
            print("Page loaded. Checking for Cloudflare CAPTCHA iframe...")
            
            # Use a locator for the iframe. Cloudflare iframes often have "challenge" in the title.
            captcha_frame_locator = page.frame_locator('iframe[title*="Cloudflare"]')

            # Wait for the checkbox inside the iframe to appear
            checkbox_locator = captcha_frame_locator.locator('input[type="checkbox"]')
            
            try:
                print("CAPTCHA iframe found. Waiting for the checkbox...")
                checkbox_locator.wait_for(timeout=5000) # Wait up to 15 seconds for it
                
                print("Checkbox found! Attempting to click it...")
                checkbox_locator.click()
                print("Checkbox clicked.")

            except TimeoutError:
                # If the checkbox doesn't appear after a while, maybe we passed without it.
                print("CAPTCHA checkbox did not appear. Assuming we passed or it's not present.")

            # --- END OF NEW LOGIC ---

            # Now, wait for the *actual* page content to load after the CAPTCHA is solved
            print("Waiting for the final page content ('.bookbox')...")
            page.wait_for_selector("div.bookbox", timeout=5000)
            print("Successfully bypassed CAPTCHA and loaded the book page!")

            # Your data extraction logic...
            book_title = page.locator("div.booknav2 > h1").inner_text()
            print(f"Title: {book_title}")

        except TimeoutError:
            print("\n--- TIMEOUT ERROR ---")
            print("Failed to solve CAPTCHA or load the final page.")
            page.screenshot(path="captcha_failure.png")
            print("Screenshot saved to 'captcha_failure.png' for review.")
        
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
        
        finally:
            context.close()
            browser.close()

solve_captcha_and_scrape(url)