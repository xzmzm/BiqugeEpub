#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re
import os
import sys
import time
import logging
import mimetypes
import urllib.parse
import argparse

# Import requests specifically for downloading the cover image
import requests
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError

# --- Global Playwright Instance ---
PLAYWRIGHT_INSTANCE = None
BROWSER_INSTANCE = None

# --- Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stdout)

OUTPUT_DIR = "output_epubs"
OUTPUT_FILENAME_TEMPLATE = "{title}.epub"
REQUEST_DELAY = 0.2
MAX_RETRIES = 3
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
# Headers for the requests call to download the cover image
REQUESTS_HEADERS = { 'User-Agent': USER_AGENT }


# --- Site Configuration ---
SITE_CONFIGS = {
    "69shuba.com": {
        "base_url": "https://www.69shuba.com",
        "encoding": "gbk",
        "metadata_url_template": "{base_url}/book/{book_id}.htm",
        "chapter_list_url_template": "{base_url}/book/{book_id}/",
        "metadata_selectors": {
            "title_meta": ('meta', {'property': 'og:title'}),
            "author_meta": ('meta', {'property': 'og:novel:author'}),
            "description_meta": ('meta', {'property': 'og:description'}),
            "cover_meta": ('meta', {'property': 'og:image'}),
            "title_fallback": '.booknav2 h1 a',
            "author_fallback_p_text": '作者：',
            "info_div": ('div', {'class': 'booknav2'}),
        },
        "chapter_list_selectors": {
            "full_list_container": ('div', {'class': 'catalog', 'id': 'catalog'}),
            "link_selector": 'li a',
        },
        "chapter_content_selectors": {
            "container": [('div', {'class': 'txtnav'})],
        },
        "ads_patterns": [
            r'www\.69shuba\.com', r'69书吧', r'https://www\.69shuba\.com',
            r'小提示：.*', r'章节错误？点此举报', r'Copyright \d+ 69书吧'
        ],
    }
}

# --- Core Logic ---

def initialize_browser():
    global PLAYWRIGHT_INSTANCE, BROWSER_INSTANCE
    if BROWSER_INSTANCE is None:
        logging.info("Initializing Playwright browser...")
        PLAYWRIGHT_INSTANCE = sync_playwright().start()
        BROWSER_INSTANCE = PLAYWRIGHT_INSTANCE.chromium.launch(headless=True)

def close_browser():
    global PLAYWRIGHT_INSTANCE, BROWSER_INSTANCE
    if BROWSER_INSTANCE:
        logging.info("Closing Playwright browser...")
        BROWSER_INSTANCE.close()
        PLAYWRIGHT_INSTANCE.stop()
        BROWSER_INSTANCE = None
        PLAYWRIGHT_INSTANCE = None

def fetch_page_with_playwright(url, context, logger=None):
    if logger is None: logger = logging.getLogger()
    initialize_browser()
    page = None
    try:
        logger.info(f"Fetching: {url}")
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_selector("body", timeout=15000)
        content = page.content()
        logger.debug(f"Successfully fetched content for {url}")
        return content
    except Exception as e:
        logger.warning(f"Playwright fetch failed for {url}: {e}")
        if page:
            page.screenshot(path=f"playwright_error_{urllib.parse.quote_plus(url)}.png")
        return None
    finally:
        if page:
            page.close()

def get_site_config(url, logger=None):
    if logger is None: logger = logging.getLogger()
    for domain, config in SITE_CONFIGS.items():
        if domain in url:
            logger.info(f"Detected site: {domain}")
            return config
    logger.warning(f"Could not determine site configuration for URL: {url}.")
    return None

def clean_html_content(content_container_tag, site_config):
    if not content_container_tag: return ""
    for br in content_container_tag.find_all("br"):
        br.replace_with("\n")
    text = content_container_tag.get_text(separator='\n')
    lines = text.splitlines()
    cleaned_lines = []
    for line in lines:
        cleaned_line = line.strip()
        ad_patterns = site_config.get('ads_patterns', [])
        for pattern in ad_patterns:
            cleaned_line = re.sub(pattern, '', cleaned_line, flags=re.IGNORECASE)
        cleaned_line = re.sub(r'\s{2,}', ' ', cleaned_line).strip()
        if cleaned_line:
            cleaned_lines.append(cleaned_line)
    return '\n'.join(f'<p>{line}</p>' for line in cleaned_lines)

def get_book_details(html_content, book_url, site_config, logger=None):
    if logger is None: logger = logging.getLogger()
    soup = BeautifulSoup(html_content, 'html.parser', from_encoding=site_config.get('encoding'))
    selectors = site_config['metadata_selectors']

    def find_content_by_meta_property(prop_name):
        selector_string = f"meta[property='{prop_name}']"
        tag = soup.select_one(selector_string)
        return tag['content'].strip() if tag and 'content' in tag.attrs else None

    title = (find_content_by_meta_property(selectors['title_meta'][1]['property']) or
             (soup.select_one(selectors['title_fallback']).get_text().strip() if soup.select_one(selectors['title_fallback']) else None) or
             "Unknown Title")

    author = find_content_by_meta_property(selectors['author_meta'][1]['property']) or "Unknown Author"
    if author == "Unknown Author":
        info_div_selector = f".{selectors['info_div'][1]['class']}"
        info_div = soup.select_one(info_div_selector)
        if info_div:
            for p in info_div.find_all('p'):
                if selectors['author_fallback_p_text'] in p.text:
                    author_link = p.find('a')
                    author = author_link.get_text(strip=True) if author_link else p.get_text(strip=True).replace(selectors['author_fallback_p_text'], '')
                    break

    description = find_content_by_meta_property(selectors['description_meta'][1]['property']) or "No description available."
    description = description.replace('简介：', '').strip()

    cover_image_src = find_content_by_meta_property(selectors['cover_meta'][1]['property'])
    cover_image_url = urllib.parse.urljoin(site_config['base_url'], cover_image_src) if cover_image_src else None

    logger.info(f"Title: {title}")
    logger.info(f"Author: {author}")
    return title, author, description, cover_image_url

def get_chapter_links(html_content, site_config):
    soup = BeautifulSoup(html_content, 'html.parser', from_encoding=site_config.get('encoding'))
    chapters = []
    selectors = site_config['chapter_list_selectors']
    container_config = selectors.get('full_list_container')
    container = None
    if container_config:
        tag_name, attrs = container_config
        if 'id' in attrs:
            selector_string = f"{tag_name}#{attrs['id']}"
        elif 'class' in attrs:
            selector_string = f"{tag_name}.{attrs['class']}"
        else:
            selector_string = tag_name
        container = soup.select_one(selector_string)

    if not container:
        logging.warning("Chapter list container not found. Searching entire document.")
        container = soup
        
    for link in container.select(selectors['link_selector']):
        href = link.get('href')
        title = link.text.strip()
        if href and title and not href.startswith('javascript:'):
            full_url = urllib.parse.urljoin(site_config['base_url'], href)
            if '/book/' in full_url or '/txt/' in full_url:
                chapters.append({'title': title, 'url': full_url})
    
    logging.info(f"Found {len(set(c['url'] for c in chapters))} unique chapter links.")
    # Remove duplicates while preserving order
    seen_urls = set()
    unique_chapters = []
    for chapter in chapters:
        if chapter['url'] not in seen_urls:
            unique_chapters.append(chapter)
            seen_urls.add(chapter['url'])
    return unique_chapters

def create_epub(title, author, description, chapters_data, book_url, cover_image_url, output_directory, logger=None):
    """
    Creates an EPUB file from the chapter data.
    """
    if logger is None: logger = logging.getLogger()
    book = epub.EpubBook()
    book.set_identifier(f'urn:uuid:{re.sub(r"[^w-]+", "-", book_url)}')
    book.set_title(title)
    book.set_language('zh')
    book.add_author(author)
    book.add_metadata('DC', 'description', description)
    book.add_metadata('DC', 'source', book_url)

    # --- Add Cover Image using requests ---
    if cover_image_url:
        try:
            logger.info(f"Downloading cover image: {cover_image_url}")
            img_response = requests.get(cover_image_url, headers=REQUESTS_HEADERS, timeout=30)
            img_response.raise_for_status()
            img_mimetype, _ = mimetypes.guess_type(cover_image_url)
            img_mimetype = img_mimetype or 'image/jpeg'
            cover_filename = f'cover{mimetypes.guess_extension(img_mimetype) or ".jpg"}'
            book.set_cover(cover_filename, img_response.content, create_page=True)
            logger.info("Cover image added.")
        except requests.exceptions.RequestException as e:
            logger.warning(f"Failed to download cover image: {e}")

    # --- Create Title Page ---
    title_page_content = f'<h1>{title}</h1><h2>{author}</h2><hr/><p>{description.replace("n", "<br/>")}</p>'
    title_page = epub.EpubHtml(title='Title Page', file_name='title_page.xhtml', lang='zh')
    title_page.content = title_page_content
    book.add_item(title_page)

    # --- Create Chapters ---
    epub_chapters = []
    for i, chapter_info in enumerate(chapters_data):
        chapter_title = chapter_info['title']
        file_name = f'chap_{i+1:04d}.xhtml'
        epub_chapter = epub.EpubHtml(title=chapter_title, file_name=file_name, lang='zh')
        epub_chapter.content = f'<h1>{chapter_title}</h1>{chapter_info["content_html"]}'
        book.add_item(epub_chapter)
        epub_chapters.append(epub_chapter)

    # --- Define CSS Style ---
    style = '''
    body { font-family: sans-serif; line-height: 1.6; margin: 1em; }
    h1 { text-align: center; margin-top: 2em; margin-bottom: 1em; font-size: 1.5em; font-weight: bold; page-break-before: always; }
    p { margin: 0 0 1em; text-indent: 2em; text-align: justify; }
    '''
    css_item = epub.EpubItem(uid="style_css", file_name="style/style.css", media_type="text/css", content=style)
    book.add_item(css_item)

    # --- Build Book ---
    book.toc = (epub.Link('title_page.xhtml', 'Title Page', 'titlepage'), *epub_chapters)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ['nav', title_page, *epub_chapters]
    
    # Sanitize filename
    sanitized_title = re.sub(r'[\\/*?:"<>|]', "", title).strip()
    output_filename = OUTPUT_FILENAME_TEMPLATE.format(title=sanitized_title or "Untitled_Book")
    os.makedirs(output_directory, exist_ok=True)
    output_path = os.path.join(output_directory, output_filename)
    epub.write_epub(output_path, book, {})
    logger.info(f"\nEPUB created successfully: {output_path}")

def main():
    parser = argparse.ArgumentParser(description='Download a book from 69shuba.com and create an EPUB.')
    parser.add_argument('url', help='The URL of the book index page (e.g., https://www.69shuba.com/book/88724/)')
    parser.add_argument('-s', '--start-chapter', type=int, default=1, help='Starting chapter number')
    parser.add_argument('-e', '--end-chapter', type=int, default=None, help='Ending chapter number')
    parser.add_argument('-o', '--output-dir', default=OUTPUT_DIR, help='Directory to save the EPUB file')
    args = parser.parse_args()

    book_url = args.url.strip().rstrip('/')
    site_config = get_site_config(book_url)
    if not site_config:
        return

    context = None
    try:
        initialize_browser()
        logging.info("Creating a persistent browser context for this run...")
        context = BROWSER_INSTANCE.new_context(user_agent=USER_AGENT)
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        match = re.search(r'/book/(\d+)', book_url)
        if not match:
            logging.error("Could not find book ID in the URL. Expected format: .../book/12345/")
            return
            
        book_id = match.group(1)
        base_url = site_config['base_url']
        metadata_url = site_config['metadata_url_template'].format(base_url=base_url, book_id=book_id)
        chapter_list_url = site_config['chapter_list_url_template'].format(base_url=base_url, book_id=book_id)

        logging.info("Performing initial fetch to solve Cloudflare challenge...")
        page = context.new_page()
        page.goto(metadata_url, wait_until="domcontentloaded", timeout=60000)
        try:
            frame = page.frame_locator('iframe[title*="Cloudflare"]')
            frame.get_by_role("checkbox").click(timeout=10000)
            logging.info("Cloudflare checkbox clicked.")
            page.wait_for_load_state("domcontentloaded", timeout=30000)
        except TimeoutError:
            logging.info("No visible Cloudflare checkbox, or it was passed automatically.")
        
        metadata_html = page.content()
        page.close()
        if not metadata_html: return

        chapter_list_html = fetch_page_with_playwright(chapter_list_url, context)
        if not chapter_list_html: return
        
        book_title, book_author, book_description, cover_url = get_book_details(metadata_html, metadata_url, site_config)
        all_chapters = get_chapter_links(chapter_list_html, site_config)
        
        start_index = args.start_chapter - 1
        end_index = args.end_chapter if args.end_chapter is not None else len(all_chapters)
        chapters_to_fetch = all_chapters[start_index:end_index]
        
        if not chapters_to_fetch:
            logging.error("No chapters found in the specified range.")
            return

        chapters_content_data = []
        total_to_fetch = len(chapters_to_fetch)
        for i, chapter_info in enumerate(chapters_to_fetch):
            logging.info(f"Fetching chapter {start_index + i + 1}/{len(all_chapters)}: {chapter_info['title']}")
            chapter_html = fetch_page_with_playwright(chapter_info['url'], context)
            if chapter_html:
                soup = BeautifulSoup(chapter_html, 'html.parser', from_encoding=site_config.get('encoding'))
                content_selector = site_config['chapter_content_selectors']['container'][0]
                content_div = soup.select_one(f"{content_selector[0]}.{content_selector[1]['class']}")
                if content_div:
                    cleaned_content = clean_html_content(content_div, site_config)
                    chapters_content_data.append({'title': chapter_info['title'], 'content_html': cleaned_content})
                else:
                    logging.warning(f"Could not find content container for: {chapter_info['title']}")
            time.sleep(REQUEST_DELAY)

        if chapters_content_data:
            create_epub(book_title, book_author, book_description, chapters_content_data, book_url, cover_url, args.output_dir)
        else:
            logging.error("Failed to fetch content for any chapters. EPUB not created.")

    finally:
        if context:
            context.close()
        close_browser()

if __name__ == "__main__":
    main()