from playwright.sync_api import sync_playwright, TimeoutError

url = "https://www.69shuba.com/book/88724.htm" 

def fetch_and_parse_book_page(target_url):
    with sync_playwright() as p:
        # Use headless=True for production runs, False is good for debugging
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        try:
            print(f"Navigating to {target_url}...")
            page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
            
            print("Cloudflare passed. Waiting for the main content container '.bookbox'...")
            page.wait_for_selector("div.bookbox", timeout=5000)
            
            print("Successfully loaded the book page content!")
            
            # Extract the book title
            title_locator = page.locator("div.booknav2 > h1")
            book_title = title_locator.inner_text()
            print(f"Book Title: {book_title}")

            # Extract the author using a specific locator
            author_locator = page.locator("p:has-text('作者：') > a")
            author_name = author_locator.inner_text()
            print(f"Author: {author_name}")

            # Extract the category
            category_locator = page.locator("p:has-text('分类：') > a")
            category_name = category_locator.inner_text()
            print(f"Category: {category_name}")
            
            # --- CORRECTED CHAPTERS LOOP ---
            print("\n--- Latest Chapters ---")
            chapter_links = page.locator("div.qustime ul li a")
            
            num_chapters = chapter_links.count()
            
            for i in range(min(5, num_chapters)): 
                chapter = chapter_links.nth(i)
                
                # No 'await' needed in the sync API
                chapter_text = chapter.inner_text().strip()
                chapter_url = chapter.get_attribute('href')
                
                print(f"- {chapter_text} (URL: {chapter_url})")

        except TimeoutError:
            print("TimeoutError: The selector was not found in headless mode.")
            # --- THIS IS THE CRITICAL DEBUGGING PART ---
            # Save a screenshot to see what the page looks like
            screenshot_path = "headless_failure.png"
            page.screenshot(path=screenshot_path)
            print(f"Screenshot of the failure saved to: {screenshot_path}")

            # Save the HTML content to see what the DOM contains
            html_path = "headless_failure.html"
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(page.content())
            print(f"HTML content of the failure saved to: {html_path}")
            
            print("\n--- Next Steps ---")
            print("1. Open 'headless_failure.png' to see if there's a CAPTCHA or a different block page.")
            print("2. Open 'headless_failure.html' and search for your selector ('bookbox') to see if it exists at all.")
        except Exception as e:
            print(f"An error occurred: {e}")
            page.screenshot(path="error_screenshot.png")
            print("Screenshot saved to error_screenshot.png")
        finally:
            browser.close()

# Run the function
fetch_and_parse_book_page(url)