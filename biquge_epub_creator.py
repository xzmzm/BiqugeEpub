import requests
from bs4 import BeautifulSoup
import ebooklib
from ebooklib import epub
import time
import re
import os
import logging
import mimetypes # Added for guessing image type
import sys # For exit
import json # Added for handling JSON chapter lists
# import cgi # For FCGI handling (REPLACED with os/urllib.parse)
import io # For in-memory file handling
import tempfile # For temporary file creation
from http.server import SimpleHTTPRequestHandler, HTTPServer # For dev server
import urllib.parse # For parsing URL in dev server
# --- Configuration ---
# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

BASE_URL = "https://www.bqg5.com"
# Default book, can be changed via command-line argument
DEFAULT_BOOK_INDEX_URL = "https://www.bqg5.com/0_521/"
OUTPUT_DIR = "output_epubs"
OUTPUT_FILENAME_TEMPLATE = "{title}.epub"
REQUEST_DELAY = 0.5 # Delay between requests in seconds to avoid overwhelming the server
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7',
    'Referer': BASE_URL, # Add Referer header
}
MAX_RETRIES = 3

# --- Site Configuration ---
SITE_CONFIGS = {
    "bqg5.com": {
        "base_url": "https://www.bqg5.com",
        "encoding": "gb18030", # Hint for fallback
        "metadata_selectors": {
            "title_meta": ('meta', {'property': 'og:title'}),
            "title_fallback": 'h1',
            "author_meta": ('meta', {'property': 'og:novel:author'}),
            "author_fallback_p_text": '作\xa0\xa0\xa0\xa0者：', # Non-breaking spaces
            "status_meta": ('meta', {'property': 'og:novel:status'}),
            "description_meta": ('meta', {'property': 'og:description'}),
            "cover_meta": ('meta', {'property': 'og:image'}),
            "cover_fallback": '#fmimg img',
            "info_div": ('div', {'id': 'info'}),
        },
        "chapter_list_selectors": {
            "container": ('div', {'id': 'list'}), # Target the main div
            "container_fallback": 'dl', # Fallback if div#list not found (less likely needed now)
            "link_selector": 'a', # General fallback selector
            "skip_dt_count": 2, # Skip links before the second <dt> (the one titled "《...》免费章节")
            "link_area_selector": 'dd a', # Links are within <a> tags inside <dd> siblings following the target <dt>
        },
        "chapter_content_selectors": {
            "container": [('div', {'id': 'content'}), ('div', {'class_': 'content'}), ('div', {'id': 'booktxt'})], # List of selectors to try
        },
        "ads_patterns": [
            r'天才一秒记住本站地址.*',
            r'手机版阅读网址.*',
            r'bqg\d*\.(com|cc|net)',
            r'请记住本书首发域名.*',
            r'最新网址.*',
            r'\(.*?\)', # Maybe too broad? Keep for now.
        ],
        "needs_metadata_fetch": False, # Metadata and chapters on same page
    },
    "69shuba.com": {
        "base_url": "https://www.69shuba.com",
        "encoding": "utf-8", # Hint
        "metadata_url_template": "{base_url}/book/{book_id}.htm", # Template to get metadata page
        "metadata_selectors": {
            # Selectors based on inspecting www.69shuba.com/book/85122.htm
            # Prioritize Open Graph meta tags
            "title_meta": ('meta', {'property': 'og:title'}),
            "author_meta": ('meta', {'property': 'og:novel:author'}),
            "status_meta": ('meta', {'property': 'og:novel:status'}),
            "description_meta": ('meta', {'property': 'og:description'}),
            "cover_meta": ('meta', {'property': 'og:image'}),
            # Fallbacks (corrected selectors)
            "title_fallback": '.booknav2 h1 a', # Get text from link inside h1
            "author_fallback_p_text": '作者：', # Text label before author link
            "cover_fallback": '.bookimg2 img', # Image tag within its div
            "info_div": ('div', {'class': 'booknav2'}), # Container for author fallback search
            # Removed description_fallback as meta tag is better and reliable fallback is complex
        },
        "chapter_list_url_template": "{base_url}/book/{book_id}/", # Added for consistency
        "chapter_list_selectors": {
            # Selectors based on inspecting www.69shuba.com/book/85122/
            "container": ('div', {'class': 'catalog', 'id': 'catalog'}), # Chapters are in div.catalog#catalog -> ul
            "link_selector": 'ul li a', # Links are <a> within <li> within <ul>
            "skip_dt_count": 0, # No complex skipping needed
            "link_area_selector": 'ul li a', # Direct selection
        },
        "chapter_content_selectors": {
            # Selector based on inspecting www.69shuba.com/txt/85122/39443178
            "container": [('div', {'class': 'txtnav'})], # Content seems to be in div.txtnav
        },
        "ads_patterns": [
             # Add patterns specific to 69shuba if found during testing
             r'www\.69shuba\.com', # Example: remove site name mentions
             r'69书吧', # Example: remove site name mentions
             r'https://www\.69shuba\.com', # Remove full links
             r'小提示：.*', # Remove footer hint
             r'章节错误？点此举报', # Remove error link text
             r'Copyright \d+ 69书吧', # Remove copyright
        ],
        "needs_metadata_fetch": True, # Metadata is on .htm page, chapters on / page
    },
    "dxmwx.org": {
    "base_url": "https://www.dxmwx.org",
    "encoding": "utf-8", # Hint
    "metadata_url_template": "{base_url}/book/{book_id}.html", # Metadata page URL
    "chapter_list_url_template": "{base_url}/chapter/{book_id}.html", # Chapter list page URL
    "metadata_selectors": {
        # Selectors based on inspecting https://www.dxmwx.org/book/57132.html (Metadata Page)
        # Prioritize Open Graph meta tags
        "title_meta": ('meta', {'property': 'og:novel:book_name'}), # Use book_name for title
        "author_meta": ('meta', {'property': 'og:novel:author'}),
        "status_meta": ('meta', {'property': 'og:novel:status'}),
        "description_meta": ('meta', {'property': 'og:description'}),
        "cover_meta": ('meta', {'property': 'og:image'}),
        # Fallbacks (less critical now, based on /book/ page structure)
        "title_fallback": "div[style*='font-size: 24px'] span", # Title span in styled div
        "author_fallback_p_text": '著', # Text label after author link
        "cover_fallback": '.imgwidth img', # Image tag within its div
        "info_div": ('div', {'style': 'float: left; width: 60%;'}), # Container div for author fallback
        "author_link_selector": "a[href*='/list/']", # Author link selector within info_div
    },
    "chapter_list_selectors": {
        # Selectors based on inspecting https://www.dxmwx.org/chapter/57132.html
        # Chapters are in multiple divs, need to select all relevant links
        "container": None, # No single container, select links directly from body/main area
        "link_selector": "a[href^='/read/']", # Select links whose href starts with /read/
        "skip_dt_count": 0,
        "link_area_selector": "a[href^='/read/']", # Use same selector here
    },
    "chapter_content_selectors": {
        # Selector based on inspecting https://www.dxmwx.org/read/57132_50211576.html
        "container": [('div', {'id': 'Lab_Contents'})], # Content is in div#Lab_Contents
    },
    "ads_patterns": [
        r'大熊猫文学',
        r'www\.dxmwx\.org',
        # Add more patterns if needed
    ],
    "needs_metadata_fetch": True, # Metadata and chapters are on DIFFERENT pages
    },
    "ixdzs8.com": {
        "base_url": "https://ixdzs8.com",
        "encoding": "utf-8", # Hint
        # Metadata is on the main page (e.g., /read/571203/)
        "metadata_selectors": {
            # Selectors based on inspecting https://ixdzs8.com/read/571203/
            # Prioritize Open Graph meta tags
            "title_meta": ('meta', {'property': 'og:novel:book_name'}),
            "author_meta": ('meta', {'property': 'og:novel:author'}),
            "status_meta": ('meta', {'property': 'og:novel:status'}),
            "description_meta": ('meta', {'property': 'og:description'}),
            "cover_meta": ('meta', {'property': 'og:image'}),
            # Fallbacks
            "title_fallback": 'div.n-text h1',
            "author_fallback_p_text": '作者:', # Text label before author link in <p>
            "cover_fallback": 'div.n-img img',
            "info_div": ('div', {'class': 'n-text'}), # Container for author fallback search
        },
        # Chapter list requires a POST request
        "chapter_list_method": "post_json",
        "chapter_list_url_template": "{base_url}/novel/clist/",
        "chapter_list_payload_key": "bid", # Key for book ID in POST data
        "chapter_content_selectors": {
            # Selector based on inspecting https://ixdzs8.com/read/571203/p35.html
            "container": [('section', {})], # Content is within the <section> tag inside article.page-content
        },
        "ads_patterns": [
            r'爱下电子书',
            r'ixdzs8\.com',
            r'ixdzs\.hk',
            r'ixdzs\.tw',
            r'\(AdProvider = window\.AdProvider.*', # JS ad block
            r'<ins class="eas.*?</ins>', # Ad placeholder
            r'<script>\(AdProvider.*?\{\}\);</script>', # Ad script
            # Add more patterns if needed
        ],
        "needs_metadata_fetch": False, # Metadata on the same page as the chapter list trigger
    }
}

def get_site_config(url, logger=None):
    """Determines the site config based on the URL."""
    if logger is None: logger = logging.getLogger() # Use default logger if none provided
    for domain, config in SITE_CONFIGS.items():
        # Check if the domain is present in the URL's netloc
        try:
            parsed_url = urllib.parse.urlparse(url) # Use urllib.parse consistently
            if domain in parsed_url.netloc:
                logger.info(f"Detected site: {domain}")
                return config
        except Exception as e:
            logger.warning(f"URL parsing failed for {url}: {e}. Trying simple string search.")
            # Fallback to simple string search if parsing fails
            if domain in url:
                logger.info(f"Detected site (fallback): {domain}")
                return config

    logger.warning(f"Could not determine site configuration for URL: {url}. No supported domain found.")
    return None # Return None if no config found

# --- Helper Functions ---
# --- Helper Functions ---

def fetch_url(url, method='GET', data=None, logger=None):
    """Fetches content from a URL with retries and delay, supporting GET and POST."""
    if logger is None: logger = logging.getLogger() # Use default logger if none provided
    retries = 0
    while retries < MAX_RETRIES:
        try:
            if method.upper() == 'POST':
                logger.debug(f"Making POST request to {url} with data: {data}")
                response = requests.post(url, headers=HEADERS, data=data, timeout=30)
            else: # Default to GET
                logger.debug(f"Making GET request to {url}")
                response = requests.get(url, headers=HEADERS, timeout=30)

            response.raise_for_status() # Raise an exception for bad status codes

            # Handle JSON response directly for POST requests expecting JSON
            if method.upper() == 'POST' and 'application/json' in response.headers.get('Content-Type', ''):
                logger.info(f"Fetched JSON: {url} (Status: {response.status_code})")
                time.sleep(REQUEST_DELAY)
                try:
                    return response.json() # Return parsed JSON object
                except requests.exceptions.JSONDecodeError as e: # Use requests' exception
                    logger.error(f"Failed to decode JSON response from {url}: {e}")
                    return None # Indicate JSON decode failure

            # --- HTML Response Handling ---
            # Try to detect encoding, fallback to site config hint or utf-8
            site_config = get_site_config(url, logger=logger) # Get config again for encoding hint, pass logger
            fallback_encoding = site_config.get('encoding', 'utf-8') if site_config else 'utf-8'
            detected_encoding = response.apparent_encoding if response.apparent_encoding else fallback_encoding
            response.encoding = detected_encoding
            # Force gb18030 if common Chinese characters are garbled with apparent_encoding
            # Check a larger portion of text for potential garbled characters
            response.encoding = detected_encoding
            # Force fallback encoding if common Chinese characters are garbled
            # Check a larger portion of text for potential garbled characters
            # Use a more general check for garbled text
            try:
                text_preview = response.text[:2000]
                if '�' in text_preview:
                    logger.warning(f"Garbled characters detected with encoding {detected_encoding} for {url}. Forcing {fallback_encoding}.")
                    response.encoding = fallback_encoding
            except Exception as e:
                logger.warning(f"Could not check for garbled characters: {e}")

            logger.info(f"Fetched HTML: {url} (Status: {response.status_code}, Encoding: {response.encoding})")
            time.sleep(REQUEST_DELAY)
            return response.text # Return HTML text
        except requests.exceptions.Timeout:
            retries += 1
            logger.warning(f"Timeout fetching {url}. Retrying ({retries}/{MAX_RETRIES})...")
            time.sleep(2 ** retries) # Exponential backoff
        except requests.exceptions.RequestException as e:
            retries += 1
            logger.warning(f"Error fetching {url}: {e}. Retrying ({retries}/{MAX_RETRIES})...")
            time.sleep(2 ** retries) # Exponential backoff

    logger.error(f"Failed to fetch {url} after {MAX_RETRIES} retries.")
    return None

def clean_html_content(content_container_tag, site_config, logger=None): # Changed parameter, added site_config
    """Removes unwanted tags and cleans up chapter text for EPUB HTML."""
    if logger is None: logger = logging.getLogger() # Use default logger if none provided
    if not content_container_tag:
        return ""

    # Work on a copy to avoid modifying the original soup object
    # Use html.parser for consistency
    tag_copy = BeautifulSoup(str(content_container_tag), 'html.parser').find(content_container_tag.name, recursive=False, attrs=content_container_tag.attrs)
    # Handle case where find returns None
    if not tag_copy:
        logger.warning("Failed to parse content container tag copy.")
        # Fallback to using the original tag, but this might modify the main soup
        tag_copy = content_container_tag

    # Remove script and style elements *within the container*
    # Line 65 (remove div) is REMOVED. Keep other unwanted tags.
    for script in tag_copy(["script", "style", "ins", "a"]): # Also remove links within content
        if script: # Check if tag exists before extracting
            script.extract()

    # Convert <br> tags to newlines first
    for br in tag_copy.find_all("br"):
        br.replace_with("\n")

    # Get text content, preserving line breaks from converted <br> tags
    text = tag_copy.get_text(separator='\n')

    # Clean whitespace and specific patterns
    lines = text.splitlines()
    cleaned_lines = []
    for line in lines:
        cleaned_line = line.strip()
        # Replace common placeholders/ads specific to the site
        cleaned_line = cleaned_line.replace('    ', '') # Remove specific space sequence often used for indentation
        cleaned_line = cleaned_line.replace(' ', ' ') # Replace non-breaking space
        cleaned_line = cleaned_line.replace(' ', ' ') # Replace full-width space (added)

        # Remove potential leftover promotional text using patterns from site_config
        ad_patterns = site_config.get('ads_patterns', [])
        for pattern in ad_patterns:
            try:
                cleaned_line = re.sub(pattern, '', cleaned_line, flags=re.IGNORECASE)
            except re.error as e:
                logger.warning(f"Invalid regex pattern in site config: {pattern} - {e}")

        # General cleanup (remove multiple spaces)
        cleaned_line = re.sub(r'\s{2,}', ' ', cleaned_line).strip()

        if cleaned_line: # Only keep non-empty lines
            # Specific check for 69shuba chapter title repetition / author line
            # Make this check more robust or part of config if needed
            if "作者：" in cleaned_line and len(cleaned_lines) > 0 and "69shuba.com" in site_config["base_url"]:
                 continue
            # Check if it looks like a chapter title and it's the first line
            is_chapter_title_line = (cleaned_line.startswith("第") and ("章 " in cleaned_line or "回 " in cleaned_line))
            if is_chapter_title_line and len(cleaned_lines) == 0:
                 continue

            cleaned_lines.append(cleaned_line)

    # Format as simple HTML paragraphs
    # Add indentation using CSS class later if desired
    content_html = '\n'.join(f'<p>{line}</p>' for line in cleaned_lines)
    return content_html.strip()

# --- Main Logic ---

def get_book_details(html_content, book_url, site_config, logger=None): # Added site_config, changed html source name
    """Extracts book title, author, description, and cover image URL from the relevant page."""
    if logger is None: logger = logging.getLogger() # Use default logger if none provided
    soup = BeautifulSoup(html_content, 'html.parser')
    selectors = site_config['metadata_selectors']

    # Helper to find element using config
    def find_element(selector_key, soup_obj=soup):
        selector = selectors.get(selector_key)
        if not selector: return None
        # Handle different selector types robustly
        try:
            if isinstance(selector, str): # Simple CSS selector
                return soup_obj.select_one(selector)
            elif isinstance(selector, tuple) and len(selector) == 2 and isinstance(selector[1], dict): # (tag_name, {attrs})
                return soup_obj.find(selector[0], selector[1])
            elif isinstance(selector, tuple) and len(selector) == 1: # Assume (tag_name,)
                return soup_obj.find(selector[0])
        except Exception as e:
            logger.warning(f"Error applying selector '{selector_key}' ({selector}): {e}")
        return None

    # Helper to get content/text
    def get_content(tag, attr='content'):
        if not tag: return None
        try:
            if attr and tag.has_attr(attr): return tag[attr].strip()
            return tag.text.strip()
        except Exception as e:
            logger.warning(f"Error getting content/attribute '{attr}' from tag {tag}: {e}")
        return None
    # Title
    title = get_content(find_element('title_meta')) or get_content(find_element('title_fallback'), attr=None) or "Unknown Title"

    # Author
    author = get_content(find_element('author_meta'))
    # Fallback using text label search within info container
    if not author or author == "Unknown Author":
         info_container = find_element('info_div') # Find the container for author info
         if info_container:
             author_label = selectors.get('author_fallback_p_text', '作者：') # Get site-specific label
             author_link_selector = selectors.get('author_link_selector') # Get site-specific link selector (e.g., for dxmwx)
             found = False

             # Try finding the specific author link first if a selector is provided
             if author_link_selector:
                  # Find the element containing the label first
                  # Use lambda to search text content across different tags
                  label_element = info_container.find(lambda tag: tag.name != 'script' and author_label in tag.get_text())
                  if label_element:
                      # Search for the specific link *within* the label element
                      author_link = label_element.select_one(author_link_selector)
                      if author_link:
                          author = author_link.text.strip()
                          found = True
                          logger.debug(f"Found author using author_link_selector: {author}")

             # Fallback 1: Search common tags like <p> for the label
             if not found:
                 possible_tags = info_container.find_all(['p', 'div', 'span']) # Search common tags
                 for tag in possible_tags:
                      if author_label in tag.text:
                          # Try extracting text directly after label
                          author = tag.text.replace(author_label, '').strip()
                          # If empty, try finding any 'a' tag within this element
                          if not author and tag.find('a'):
                              author = tag.find('a').text.strip()
                          if author: # Found author in this tag
                              found = True
                              logger.debug(f"Found author using fallback 1 (p/div/span): {author}")
                              break

             # Fallback 2: Search the entire container text using regex
             if not found:
                 container_text = info_container.get_text(" ", strip=True)
                 # Regex to find label and capture following non-whitespace chars
                 match = re.search(re.escape(author_label) + r'\s*([^\s<]+)', container_text) # Avoid matching tags
                 if match:
                     author = match.group(1).strip()
                     found = True
                     logger.debug(f"Found author using fallback 2 (regex): {author}")

    author = author or "Unknown Author"

    # Status
    status = get_content(find_element('status_meta')) or "Unknown Status" # Add fallback if needed

    # Description
    description = get_content(find_element('description_meta')) or get_content(find_element('description_fallback'), attr=None) or "No description available."
    # Clean up description if needed (e.g., remove "简介：")
    description = description.replace('简介：', '').strip()
    # Limit description length?
    # description = description[:500] + '...' if len(description) > 503 else description

    # Cover Image
    cover_image_src = get_content(find_element('cover_meta'))
    if not cover_image_src:
        cover_image_tag = find_element('cover_fallback')
        cover_image_src = get_content(cover_image_tag, attr='src')

    # Ensure cover URL is absolute
    cover_image_url = None
    if cover_image_src:
        # Sometimes src might be relative to base_url, sometimes to book_url
        # Try joining with book_url first, then base_url as fallback
        cover_image_url = requests.compat.urljoin(book_url, cover_image_src)
        # Basic check if URL looks valid (starts with http)
        if not cover_image_url.startswith('http'):
             base_site_url = site_config.get("base_url", book_url)
             cover_image_url = requests.compat.urljoin(base_site_url, cover_image_src)
        # If still not valid, set to None
        if not cover_image_url.startswith('http'):
             logger.warning(f"Could not construct absolute cover URL from src: {cover_image_src}")
             cover_image_url = None

    # Author fallback logic moved up

    logger.info(f"Title: {title}")
    logger.info(f"Author: {author}")
    logger.info(f"Status: {status}")
    logger.info(f"Description: {description[:100]}...") # Log first 100 chars
    logger.info(f"Cover Image URL: {cover_image_url}")
    return title, author, description, cover_image_url

def get_chapter_links(index_html, book_url, site_config, logger=None):
    """Extracts chapter links and titles. Handles HTML parsing or POST JSON fetching."""
    if logger is None: logger = logging.getLogger() # Use default logger if none provided
    chapters = []
    base_site_url = site_config.get("base_url", book_url)

    # --- Handle POST JSON method (e.g., ixdzs8.com) ---
    if site_config.get("chapter_list_method") == "post_json":
        logger.info("Fetching chapter list via POST JSON method.")
        post_url_template = site_config.get("chapter_list_url_template")
        payload_key = site_config.get("chapter_list_payload_key", "bid") # Default to 'bid'

        if not post_url_template:
            logger.error("Missing 'chapter_list_url_template' in site config for POST JSON.")
            return []

        try:
            # Extract book ID (bid) from the main book_url (e.g., https://ixdzs8.com/read/571203/)
            book_id_match = re.search(r'/read/(\d+)/?', book_url)
            if not book_id_match:
                raise ValueError("Could not extract book ID (bid) from book URL for POST.")
            book_id = book_id_match.group(1)

            post_url = post_url_template.format(base_url=base_site_url)
            post_data = {payload_key: book_id}

            # Use fetch_url with POST method
            json_response = fetch_url(post_url, method='POST', data=post_data, logger=logger)

            if json_response and isinstance(json_response, dict) and json_response.get("rs") == 200:
                chapter_list_data = json_response.get("data", [])
                if not isinstance(chapter_list_data, list):
                     logger.error(f"Unexpected data format in JSON response: 'data' is not a list. Response: {json_response}")
                     return []

                seen_urls = set()
                for item in chapter_list_data:
                    if isinstance(item, dict) and item.get("ctype") == "0": # Check if it's a chapter link
                        title = item.get("title", "").strip()
                        ordernum = item.get("ordernum")
                        if title and ordernum:
                            # Construct chapter URL (e.g., https://ixdzs8.com/read/571203/p35.html)
                            chapter_url = f"{base_site_url}/read/{book_id}/p{ordernum}.html"
                            if chapter_url not in seen_urls:
                                chapters.append({'title': title, 'url': chapter_url})
                                seen_urls.add(chapter_url)
                            else:
                                logger.debug(f"Skipping duplicate chapter URL from JSON: {chapter_url}")
                        else:
                            logger.warning(f"Skipping invalid chapter data from JSON: {item}")
                logger.info(f"Found {len(chapters)} chapter links from JSON POST.")
                # Note: JSON list is usually already in correct order, no reversal needed.
                return chapters
            else:
                logger.error(f"Failed to fetch or parse chapter list JSON from {post_url}. Response: {json_response}")
                return []

        except (ValueError, KeyError, AttributeError, requests.exceptions.RequestException) as e:
            logger.error(f"Error fetching/processing chapter list via POST JSON: {e}")
            return []

    # --- Handle HTML Parsing Method (default) ---
    logger.info("Fetching chapter list via HTML parsing method.")
    # Explicitly use encoding hint from site_config for parsing, if available
    site_encoding = site_config.get('encoding')
    if site_encoding:
        logger.debug(f"Using encoding hint for BeautifulSoup in get_chapter_links: {site_encoding}")
        soup = BeautifulSoup(index_html, 'html.parser', from_encoding=site_encoding)
    else:
        soup = BeautifulSoup(index_html, 'html.parser') # Default parser if no hint
    chapters = []
    selectors = site_config['chapter_list_selectors']

    # Helper to find element using config (can be reused or defined locally)
    def find_element(selector_key, soup_obj=soup):
        selector = selectors.get(selector_key)
        if not selector: return None
        try:
            if isinstance(selector, str): return soup_obj.select_one(selector)
            elif isinstance(selector, tuple): return soup_obj.find(selector[0], selector[1])
        except Exception as e:
            logger.warning(f"Error applying selector '{selector_key}' ({selector}): {e}")
        return None

    # Find the chapter list container
    container_selector = selectors.get('container')
    container_fallback_selector = selectors.get('container_fallback')
    chapter_list_container = find_element('container') or find_element('container_fallback')

    # Check if a container was found *if* one was expected.
    # If a container was expected but not found, log an error, but still allow fallback attempts below.
    if container_selector is not None and not chapter_list_container:
        logger.warning(f"Expected chapter list container not found using selectors: {container_selector}, {container_fallback_selector}. Will attempt fallback link selection.")

    # --- Select Links based on Config ---
    links_elements = []
    skip_dt_count = selectors.get('skip_dt_count', 0)
    link_selector = selectors.get('link_selector', 'a') # Default to 'a' if not specified

    # Use the container found via site config (or soup if no container specified)
    search_area = chapter_list_container if chapter_list_container else soup

    # Apply the site-specific link selector within the search area
    try:
        links_elements = search_area.select(link_selector)
        logger.debug(f"Found {len(links_elements)} link elements using selector '{link_selector}' in {'container' if chapter_list_container else 'soup'}.")
    except Exception as e:
        logger.error(f"Error applying link selector '{link_selector}': {e}")
        links_elements = []

    # Note: The complex logic involving skip_dt_count and dl/dd tags (previously lines 577-605)
    # is removed as it was too specific to bqg5.com.
    # If similar complex logic is needed for other sites, it should be handled
    # via more sophisticated site-specific configurations or functions.
    # For 69shuba, the simple `ul li a` selector applied to the container is sufficient.

    # After all attempts, check if links were found
    if not links_elements:
        logger.error("Failed to find any chapter links after all selection attempts.")
        return []

    # --- Process Selected Links ---
    chapters = []
    seen_urls = set() # Avoid duplicate chapters
    # --- Process Selected Links (HTML Parsing specific part) ---
    # This part remains largely the same as before, processing the links_elements found via HTML selectors
    seen_urls = set() # Avoid duplicate chapters

    for link in links_elements:
        href = link.get('href')
        title = link.text.strip()

        # Basic filtering for valid chapter links
        if href and title and not href.startswith(('javascript:', '#')) and len(title) > 0:
            # Construct absolute URL if relative
            full_url = requests.compat.urljoin(base_site_url, href)

            # Additional filter: check if URL path looks like a chapter
            is_likely_chapter = False
            try:
                path = urllib.parse.urlparse(full_url).path # Use urllib.parse consistently
                # Common patterns: /book_id/chapter_id.html, /txt/book_id/chapter_id, /read/book_id/chapter_id/, /digits/digits.html etc.
                # Updated regex to handle bqg5 structure like /1_1529/457152.html
                if re.search(r'/\d+/\d+(?:\.html)?$', path) or \
                   re.search(r'/txt/\d+/\d+', path) or \
                   re.search(r'/read/\d+/\d+', path) or \
                   re.search(r'/\d+_\d+/\d+\.html$', path): # Added this pattern
                    is_likely_chapter = True
            except Exception:
                pass # Ignore URL parsing errors for filtering

            # Filter out known non-chapter links (e.g., '/info/', '/reviews/')
            if '/comm/' in full_url or '/info/' in full_url or '/review' in full_url or '/jifen.html' in full_url or '/dns.html' in full_url or '/zhuomian.php' in full_url or '/login.php' in full_url or '/register.php' in full_url: # Added more specific filters based on HTML
                is_likely_chapter = False

            # Also filter out links that are just the book index URL itself
            if full_url.rstrip('/') == book_url.rstrip('/'):
                 is_likely_chapter = False


            if is_likely_chapter and full_url not in seen_urls:
                # --- Site-specific filtering ---
                # For dxmwx.org, skip the "Latest Chapter" link in the header
                if "dxmwx.org" in site_config.get("base_url", ""):
                    parent_span = link.find_parent('span')
                    if parent_span and "最新章节：" in parent_span.get_text():
                        logger.debug(f"Skipping latest chapter link in header: {title} ({full_url})")
                        continue # Skip this link

                # --- General processing ---
                # Simple title cleaning (remove potential artifacts)
                title = re.sub(r'^（\d+）', '', title).strip() # Remove leading (number) if present
                # Remove common prefixes/suffixes if needed
                # title = title.replace('最新章节 ', '')

                chapters.append({'title': title, 'url': full_url})
                seen_urls.add(full_url)
            else: # DEBUG: Log why a link was skipped
                logger.debug(f"Skipping link: Title='{title}', Href='{href}', LikelyChapter={is_likely_chapter}, Seen={full_url in seen_urls}")

    logger.info(f"Found {len(chapters)} potential chapter links.")
    logger.debug(f"Final chapter list before return: {[c['title'] for c in chapters[:5]]}...") # DEBUG first 5 titles
    # Reverse chapter order for sites that list newest first (like 69shuba)
    if "69shuba.com" in site_config.get("base_url", ""):
         logger.info("Reversing chapter order for 69shuba.com.")
         chapters.reverse()
    return chapters

def create_epub(title, author, description, chapters_data, book_url, cover_image_url, output_directory, return_bytes=False, logger=None):
    """
    Creates an EPUB file from the chapter data.

    Args:
        title (str): Book title.
        author (str): Book author.
        description (str): Book description.
        chapters_data (list): List of dicts, each with 'title' and 'content_html'.
        book_url (str): Original URL of the book index/metadata page.
        cover_image_url (str): URL of the cover image, or None.
        output_directory (str or None): Directory to save the EPUB. If None and return_bytes is False, uses OUTPUT_DIR.
                                        If None and return_bytes is True, EPUB is not saved to disk.
        return_bytes (bool): If True, returns the EPUB content as bytes and the filename.
                             If False, saves the EPUB to disk and returns None.

    Returns:
        tuple (bytes, str) or None: If return_bytes is True, returns (epub_content, epub_filename).
                                    Otherwise, returns None.
    """
    if logger is None: logger = logging.getLogger() # Use default logger if none provided
    book = epub.EpubBook()

    # Set metadata
    # Generate a unique ID based on the book URL
    unique_id = re.sub(r'[^\w\-]+', '-', book_url)
    book.set_identifier(f'urn:uuid:{unique_id}')
    book.set_title(title)
    book.set_language('zh') # Assuming Chinese content
    book.add_author(author)
    book.add_metadata('DC', 'description', description)
    book.add_metadata('DC', 'source', book_url)

    # --- Add Cover Image ---
    cover_image_content = None
    cover_item = None
    if cover_image_url:
        logger.info(f"Attempting to download cover image: {cover_image_url}")
        try:
            img_response = requests.get(cover_image_url, headers=HEADERS, timeout=30, stream=True)
            img_response.raise_for_status()
            cover_image_content = img_response.content
            # Guess image type from URL or fallback
            img_mimetype, _ = mimetypes.guess_type(cover_image_url)
            if not img_mimetype:
                img_mimetype = 'image/jpeg' # Default fallback
            cover_item = epub.EpubItem(uid='cover_image', file_name=f'cover.{mimetypes.guess_extension(img_mimetype) or ".jpg"}', media_type=img_mimetype, content=cover_image_content)
            book.add_item(cover_item)
            book.set_cover(cover_item.file_name, cover_image_content) # Use set_cover for better compatibility
            logger.info(f"Cover image downloaded and added ({img_mimetype}).")
        except requests.exceptions.RequestException as e:
            logger.warning(f"Could not download or add cover image: {e}")

    # Create chapters and add to book
    epub_chapters = []
    toc = [] # For Table of Contents

    # Add a title page
    title_page_content = f'''
<?xml version='1.0' encoding='utf-8'?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
  <title>{title}</title>
  <link rel="stylesheet" type="text/css" href="style/style.css" />
</head>
<body class="titlepage">
  <h1>{title}</h1>
  <h2>{author}</h2>
  <hr/>
  <p class="description">{description}</p>
  <p class="source">Source: {book_url}</p>
</body>
</html>
'''
    title_page = epub.EpubHtml(title='Title Page', file_name='title_page.xhtml', lang='zh')
    title_page.content = title_page_content
    book.add_item(title_page)


    for i, chapter_info in enumerate(chapters_data):
        chapter_title = chapter_info['title']
        chapter_content_html = chapter_info['content_html']
        file_name = f'chap_{i+1:04d}.xhtml'

        # Create EpubHtml object for the chapter
        epub_chapter = epub.EpubHtml(title=chapter_title,
                                     file_name=file_name,
                                     lang='zh')
        # Basic HTML structure for the chapter content
        # Ensure content is wrapped in body and includes CSS link
        epub_chapter.content = f'''
<?xml version='1.0' encoding='utf-8'?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
  <title>{chapter_title}</title>
  <link rel="stylesheet" type="text/css" href="style/style.css" />
</head>
<body>
  <h1>{chapter_title}</h1>
  {chapter_content_html}
</body>
</html>
'''
        # Add CSS link
        epub_chapter.add_item(epub.EpubItem(uid="style", file_name="style/style.css", media_type="text/css", content='')) # Placeholder, will add content later

        book.add_item(epub_chapter)
        epub_chapters.append(epub_chapter)
        # Add chapter to TOC
        toc.append(epub.Link(file_name, chapter_title, f'chap_{i+1:04d}'))
        logger.info(f"Added chapter {i+1}: {chapter_title}")

    # Define Table of Contents (including title page link if desired)
    # book.toc = (epub.Link('title_page.xhtml', 'Title Page', 'titlepage'), (epub.Section('Chapters'), tuple(toc)))
    book.toc = tuple(toc)


    # Add default NCX and Nav file
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    # Define CSS style
    # Basic styling for readability
    style = '''
@namespace epub "http://www.idpf.org/2007/ops";
body {
    font-family: sans-serif;
    line-height: 1.6;
    margin: 1em;
}
h1 {
    text-align: center;
    margin-top: 2em;
    margin-bottom: 1em;
    font-size: 1.5em;
    font-weight: bold;
    page-break-before: always; /* Start each chapter h1 on a new page */
}
p {
    margin-top: 0;
    margin-bottom: 1em;
    text-indent: 2em; /* Indent paragraphs */
    text-align: justify; /* Justify text */
}
/* Styles for Title Page */
.titlepage {
    text-align: center;
    margin-top: 20%;
}
.titlepage h1 {
    font-size: 2em;
    page-break-before: auto; /* Don't force page break before title */
}
.titlepage h2 {
    font-size: 1.5em;
    font-style: italic;
    margin-top: 0.5em;
}
.titlepage hr {
    width: 50%;
    margin-top: 1em;
    margin-bottom: 1em;
}
.titlepage p {
    text-indent: 0; /* No indent for description/source */
    text-align: center;
    font-size: 0.9em;
    color: #555;
}
.description {
    margin-top: 2em;
    font-style: italic;
}
.source {
    margin-top: 1em;
    font-size: 0.8em;
}
'''
    # Create CSS file item
    style_item = epub.EpubItem(uid="style_css", file_name="style/style.css", media_type="text/css", content=style)
    book.add_item(style_item)

    # Update chapters to link the actual CSS file
    for chapter in epub_chapters:
        chapter.add_item(style_item)
    title_page.add_item(style_item)


    # Create spine (order of items in the book)
    # Start with title page, then chapters
    # 'cover' is often automatically added by set_cover, but explicitly adding is safer.
    # If set_cover creates its own page, we might not need title_page in the spine.
    # Let's try including both cover (if exists) and title_page.
    spine_items = ['nav', title_page] + epub_chapters
    book.spine = ['cover'] + spine_items if cover_item else spine_items

    # Sanitize filename
    sanitized_title = re.sub(r'[\\/*?:"<>|]',"", title) # Remove invalid characters
    sanitized_title = re.sub(r'\s+', '_', sanitized_title).strip('_') # Replace spaces and strip leading/trailing underscores
    if not sanitized_title: sanitized_title = "Untitled_Book" # Handle empty titles after sanitization
    output_filename = OUTPUT_FILENAME_TEMPLATE.format(title=sanitized_title)

    if return_bytes:
        # Write EPUB to an in-memory buffer
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".epub") as temp_epub:
                epub.write_epub(temp_epub.name, book, {})
                temp_epub.seek(0)
                epub_content = temp_epub.read()
            os.unlink(temp_epub.name) # Clean up the temporary file
            logger.info(f"EPUB '{output_filename}' created in memory ({len(epub_content)} bytes).")
            return epub_content, output_filename
        except Exception as e:
            logger.error(f"Error writing EPUB to memory buffer: {e}")
            # Attempt to clean up temp file if it exists and writing failed partially
            if 'temp_epub' in locals() and temp_epub and os.path.exists(temp_epub.name):
                try:
                    os.unlink(temp_epub.name)
                except OSError:
                    pass # Ignore cleanup error if it happens
            raise # Re-raise the exception to be handled by the caller
    else:
        # Save EPUB file to disk (original behavior)
        target_output_dir = output_directory if output_directory else OUTPUT_DIR
        os.makedirs(target_output_dir, exist_ok=True)
        output_path = os.path.join(target_output_dir, output_filename)
        try:
            epub.write_epub(output_path, book, {})
            logger.info(f"\nEPUB created successfully: {output_path}")
            return None # Indicate success, no bytes returned
        except Exception as e:
            logger.error(f"Error writing EPUB file to disk: {e}")
            raise # Re-raise the exception

import os
import urllib.parse

def handle_fcgi_request():
    """Handles incoming FCGI requests (parsing QUERY_STRING)."""
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - FCGI - %(levelname)s - %(message)s')
    logging.info("FCGI request received.")

    # Parse QUERY_STRING environment variable instead of using cgi.FieldStorage
    query_string = os.environ.get('QUERY_STRING', '')
    params = urllib.parse.parse_qs(query_string)
    logging.debug(f"FCGI Query Params: {params}")

    # Get values from parsed parameters (note: parse_qs returns lists)
    url = params.get('url', [None])[0]
    start_chapter = params.get('start', ['1'])[0] # Default to '1'
    end_chapter = params.get('end', [None])[0] # Default to None

    # --- Basic Input Validation ---
    if not url:
        print("Status: 400 Bad Request")
        print("Content-Type: text/plain")
        print()
        print("Error: 'url' parameter is required.")
        logging.error("FCGI Error: Missing 'url' parameter.")
        return

    try:
        start_chapter_num = int(start_chapter)
        if start_chapter_num < 1: start_chapter_num = 1
    except (ValueError, TypeError):
        print("Status: 400 Bad Request")
        print("Content-Type: text/plain")
        print()
        print("Error: 'start' parameter must be a positive integer.")
        logging.error(f"FCGI Error: Invalid 'start' parameter: {start_chapter}")
        return

    end_chapter_num = None
    if end_chapter is not None:
        try:
            end_chapter_num = int(end_chapter)
            if end_chapter_num < start_chapter_num:
                 print("Status: 400 Bad Request")
                 print("Content-Type: text/plain")
                 print()
                 print("Error: 'end' chapter cannot be less than 'start' chapter.")
                 logging.error(f"FCGI Error: 'end' chapter ({end_chapter}) less than 'start' ({start_chapter}).")
                 return
        except (ValueError, TypeError):
            print("Status: 400 Bad Request")
            print("Content-Type: text/plain")
            print()
            print("Error: 'end' parameter must be an integer.")
            logging.error(f"FCGI Error: Invalid 'end' parameter: {end_chapter}")
            return

    logging.info(f"FCGI Params: url='{url}', start={start_chapter_num}, end={end_chapter_num}")

    # --- Call Core Logic ---
    try:
        # Fetch site config based on URL
        site_config = get_site_config(url)
        if not site_config:
            raise ValueError(f"Unsupported website URL: {url}")

        # Fetch metadata and chapter list (similar to CLI logic)
        # Pass the default logger for FCGI mode
        logger = logging.getLogger() # Get default logger for FCGI
        index_html, metadata_html, metadata_url, chapter_list_fetch_url = fetch_initial_pages(url, site_config, logger=logger)
        if not index_html or not metadata_html:
             raise ConnectionError("Failed to fetch necessary pages.")

        book_title, book_author, book_description, cover_url = get_book_details(metadata_html, metadata_url, site_config, logger=logger)
        chapter_links = get_chapter_links(index_html, chapter_list_fetch_url or url, site_config, logger=logger) # Use chapter list url if available

        # Apply chapter range
        chapter_links = filter_chapters_by_range(chapter_links, start_chapter_num, end_chapter_num, logger=logger)

        if not chapter_links:
            raise ValueError("No chapters found for the specified range.")

        # Fetch chapter content
        chapters_content_data = fetch_chapters_content(chapter_links, site_config, logger=logger)
        if not chapters_content_data:
             raise ValueError("Failed to fetch content for any chapters.")

        # Create EPUB in memory
        epub_content, epub_filename = create_epub(
            book_title, book_author, book_description, chapters_content_data,
            metadata_url, cover_url, output_directory=None, return_bytes=True, logger=logger # Request bytes
        )

        # --- Send Response ---
        print(f"Content-Disposition: attachment; filename=\"{epub_filename}\"")
        print("Content-Type: application/epub+zip")
        print(f"Content-Length: {len(epub_content)}")
        print("Status: 200 OK") # Optional, but good practice
        print() # End of headers

        # Write EPUB bytes to stdout
        # Need to flush stdout and potentially write in binary mode
        sys.stdout.buffer.write(epub_content)
        sys.stdout.buffer.flush()
        logging.info(f"Successfully sent EPUB: {epub_filename}")

    except Exception as e:
        logging.exception("FCGI Error during EPUB generation:") # Log traceback
        print("Status: 500 Internal Server Error")
        print("Content-Type: text/plain")
        print()
        print(f"Error generating EPUB: {e}")

# --- Helper function to consolidate initial page fetching ---
# Renamed from fetch_initial_pages_fcgi
def fetch_initial_pages(book_url, site_config, logger=None):
    """Fetches initial index/metadata pages based on site config. Returns tuple."""
    if logger is None: logger = logging.getLogger() # Use default logger if none provided
    index_html = None
    metadata_html = None
    metadata_url = book_url
    chapter_list_fetch_url = None # URL used to fetch the chapter list

    if site_config.get('needs_metadata_fetch', False):
        try:
            book_id_match = re.search(r'/(?:book|txt|info|read|chapter)/(\d+)', book_url)
            if not book_id_match:
                path_part = urllib.parse.urlparse(book_url).path # Use urllib.parse consistently
                book_id_match = re.search(r'/(\d+)/?$', path_part)
                if not book_id_match:
                    book_id_match = re.search(r'_(\d+)', book_url)
            if not book_id_match:
                raise ValueError("Could not extract book ID from URL for metadata lookup")

            book_id = book_id_match.group(1)
            metadata_url_template = site_config.get('metadata_url_template')
            chapter_list_url_template = site_config.get('chapter_list_url_template')
            if not metadata_url_template or not chapter_list_url_template:
                 raise ValueError("Missing 'metadata_url_template' or 'chapter_list_url_template' in site config")

            metadata_url = metadata_url_template.format(base_url=site_config['base_url'], book_id=book_id)
            logger.info(f"Fetching metadata page: {metadata_url}")
            metadata_html = fetch_url(metadata_url, logger=logger)
            if not metadata_html:
                 raise ConnectionError(f"Failed to fetch metadata page: {metadata_url}")

            chapter_list_fetch_url = chapter_list_url_template.format(base_url=site_config['base_url'], book_id=book_id)
            logger.info(f"Fetching chapter list page: {chapter_list_fetch_url}")
            index_html = fetch_url(chapter_list_fetch_url, logger=logger)
            if not index_html:
                 raise ConnectionError(f"Failed to fetch chapter list page: {chapter_list_fetch_url}")

        except (ValueError, ConnectionError, KeyError, AttributeError) as e:
             logger.error(f"Error preparing URLs or fetching initial pages for {site_config['base_url']}: {e}")
             raise # Re-raise the exception to be caught by the main handler
    else:
        # Metadata and chapters on the same page
        logger.info(f"Fetching book index/metadata page: {book_url}")
        index_html = fetch_url(book_url, logger=logger)
        metadata_html = index_html
        metadata_url = book_url
        chapter_list_fetch_url = book_url # Chapter list is fetched from the main URL

    return index_html, metadata_html, metadata_url, chapter_list_fetch_url

# --- Helper function to consolidate chapter range filtering ---
def filter_chapters_by_range(chapter_links, start_chapter_num, end_chapter_num, logger=None):
    """Filters chapter links based on start/end numbers."""
    if logger is None: logger = logging.getLogger() # Use default logger if none provided
    original_chapter_count = len(chapter_links)
    if original_chapter_count == 0:
        return []

    start_index = start_chapter_num - 1
    end_index = end_chapter_num if end_chapter_num is not None else original_chapter_count

    # Validate indices
    if start_index < 0:
        logger.warning(f"Start chapter {start_chapter_num} is invalid. Using chapter 1.")
        start_index = 0
    if end_index > original_chapter_count:
        logger.warning(f"End chapter {end_chapter_num} is greater than total chapters ({original_chapter_count}). Using last chapter.")
        end_index = original_chapter_count
    if start_index >= end_index:
         logger.warning(f"Start chapter ({start_chapter_num}) is greater than or equal to end chapter ({end_chapter_num}). Only processing chapter {start_chapter_num}.")
         end_index = start_index + 1 # Ensure at least the start chapter is included

    # Slice the chapter list
    if start_index > 0 or end_index < original_chapter_count:
         logger.info(f"Selecting chapters from {start_index + 1} to {end_index} (inclusive).")
         return chapter_links[start_index:end_index]
    else:
         logger.info(f"Selecting all {original_chapter_count} chapters.")
         return chapter_links

# --- Helper function to consolidate chapter content fetching ---
def fetch_chapters_content(chapter_links, site_config, logger=None):
    """Fetches and cleans content for a list of chapter links."""
    if logger is None: logger = logging.getLogger() # Use default logger if none provided
    chapters_content_data = []
    total_chapters = len(chapter_links)
    logger.info(f"Attempting to fetch content for {total_chapters} chapters...")

    for i, chapter_info in enumerate(chapter_links):
        logger.info(f"Processing chapter {i+1}/{total_chapters}: {chapter_info['title']} ({chapter_info['url']})")
        chapter_html_page = fetch_url(chapter_info['url'], logger=logger)
        if chapter_html_page:
            soup = BeautifulSoup(chapter_html_page, 'html.parser')
            content_div = None
            content_selectors = site_config.get('chapter_content_selectors', {}).get('container', [])
            for selector_info in content_selectors:
                 try:
                     if isinstance(selector_info, tuple) and len(selector_info) == 2:
                          content_div = soup.find(selector_info[0], selector_info[1])
                     elif isinstance(selector_info, str):
                          content_div = soup.select_one(selector_info)
                     if content_div:
                         logger.debug(f"Found content container using: {selector_info}")
                         break
                 except Exception as e:
                     logger.warning(f"Error applying content selector {selector_info}: {e}")
                     continue

            if content_div:
                cleaned_content_html = clean_html_content(content_div, site_config, logger=logger)
                if cleaned_content_html:
                    chapters_content_data.append({
                        'title': chapter_info['title'],
                        'content_html': cleaned_content_html
                    })
                else:
                    logger.warning(f"Content div found but no text extracted for chapter: {chapter_info['title']}")
            else:
                logger.warning(f"Could not find content div for chapter: {chapter_info['title']} at {chapter_info['url']} using selectors {content_selectors}")
        else:
            logger.warning(f"Skipping chapter due to fetch error: {chapter_info['title']}")
    return chapters_content_data

# --- Local Development Server ---

class EpubRequestHandler(SimpleHTTPRequestHandler):
    """Custom request handler to serve static files and handle EPUB generation."""

    # Override log_message to potentially suppress standard request logging if desired
    # def log_message(self, format, *args):
    #     # Uncomment the line below to disable standard GET/POST logging
    #     # return
    #     super().log_message(format, *args)


    def do_GET(self):
        """Handle GET requests."""
        parsed_path = urllib.parse.urlparse(self.path)
        path = parsed_path.path
        query = parsed_path.query

        # Route EPUB generation requests
        if path == '/generate-epub':
            self.handle_epub_request(query)
        # Route static file requests (including root path for index.html)
        else:
            # Let SimpleHTTPRequestHandler handle serving files like index.html, style.css, script.js
            # It defaults to serving from the current working directory.
            super().do_GET()

    def handle_epub_request(self, query_string):
        """Handles the /generate-epub request."""
        # Use the main script's logger
        logger = logging.getLogger()
        logger.info(f"HTTP Server: Received EPUB request with query: {query_string}")
        params = urllib.parse.parse_qs(query_string)

        url = params.get('url', [None])[0]
        start_chapter = params.get('start', ['1'])[0] # Default to '1'
        end_chapter = params.get('end', [None])[0] # Default to None

        # --- Basic Input Validation ---
        if not url:
            self.send_error(400, "Error: 'url' parameter is required.")
            logger.error("HTTP Server Error: Missing 'url' parameter.")
            return

        try:
            start_chapter_num = int(start_chapter)
            if start_chapter_num < 1: start_chapter_num = 1
        except (ValueError, TypeError):
            self.send_error(400, "Error: 'start' parameter must be a positive integer.")
            logger.error(f"HTTP Server Error: Invalid 'start' parameter: {start_chapter}")
            return

        end_chapter_num = None
        if end_chapter is not None and end_chapter != '': # Check for empty string too
            try:
                end_chapter_num = int(end_chapter)
                if end_chapter_num < start_chapter_num:
                    self.send_error(400, "Error: 'end' chapter cannot be less than 'start' chapter.")
                    logger.error(f"HTTP Server Error: 'end' chapter ({end_chapter}) less than 'start' ({start_chapter}).")
                    return
            except (ValueError, TypeError):
                self.send_error(400, "Error: 'end' parameter must be an integer.")
                logger.error(f"HTTP Server Error: Invalid 'end' parameter: {end_chapter}")
                return

        logger.info(f"HTTP Server Params: url='{url}', start={start_chapter_num}, end={end_chapter_num}")

        # --- Call Core Logic ---
        try:
            site_config = get_site_config(url)
            if not site_config:
                raise ValueError(f"Unsupported website URL: {url}")

            # Fetch pages (using the same helper as FCGI)
            index_html, metadata_html, metadata_url, chapter_list_fetch_url = fetch_initial_pages(url, site_config)
            if not index_html or not metadata_html:
                 raise ConnectionError("Failed to fetch necessary pages.")

            book_title, book_author, book_description, cover_url = get_book_details(metadata_html, metadata_url, site_config)
            chapter_links = get_chapter_links(index_html, chapter_list_fetch_url or url, site_config)

            # Filter chapters
            chapter_links = filter_chapters_by_range(chapter_links, start_chapter_num, end_chapter_num)
            if not chapter_links:
                raise ValueError("No chapters found for the specified range.")

            # Fetch content
            chapters_content_data = fetch_chapters_content(chapter_links, site_config)
            if not chapters_content_data:
                 raise ValueError("Failed to fetch content for any chapters.")

            # Create EPUB in memory
            epub_content, epub_filename = create_epub(
                book_title, book_author, book_description, chapters_content_data,
                metadata_url, cover_url, output_directory=None, return_bytes=True
            )

            # --- Send Response ---
            self.send_response(200)
            self.send_header('Content-Type', 'application/epub+zip')

            # Generate ASCII fallback filename (replace non-ASCII with '_')
            ascii_filename = ''.join(c if c.isascii() else '_' for c in epub_filename)
            # Ensure it's not empty and ends with .epub
            if not ascii_filename.strip('_'): ascii_filename = "book.epub"
            if not ascii_filename.endswith('.epub'): ascii_filename = os.path.splitext(ascii_filename)[0] + ".epub"

            # Encode the original filename using RFC 5987
            encoded_filename = urllib.parse.quote(epub_filename)

            # Set Content-Disposition with both filename (fallback) and filename* (preferred)
            disposition = f'attachment; filename="{ascii_filename}"; filename*=UTF-8\'\'{encoded_filename}'
            self.send_header('Content-Disposition', disposition)

            self.send_header('Content-Length', str(len(epub_content)))
            self.end_headers()
            self.wfile.write(epub_content)
            logger.info(f"HTTP Server: Successfully sent EPUB: {epub_filename}")

        except Exception as e:
            logger.exception("HTTP Server Error during EPUB generation:")
            # Send a more informative error message if possible
            error_message = f"Error generating EPUB: {e}"
            # Ensure error message is encodable
            try:
                error_bytes = error_message.encode('utf-8')
                self.send_response(500)
                self.send_header('Content-Type', 'text/plain; charset=utf-8')
                self.send_header('Content-Length', str(len(error_bytes)))
                self.end_headers()
                self.wfile.write(error_bytes)
            except Exception as send_err:
                 # Fallback if sending the detailed error fails
                 logger.error(f"Failed to send detailed error response: {send_err}")
                 self.send_error(500, "Internal server error during EPUB generation.")


def run_dev_server(port):
    """Starts the local development HTTP server."""
    # Ensure directory exists for SimpleHTTPRequestHandler if needed (though not strictly necessary here)
    # os.makedirs(os.path.dirname(__file__) or '.', exist_ok=True) # Ensure current dir exists

    server_address = ('', port) # Listen on all interfaces
    httpd = HTTPServer(server_address, EpubRequestHandler)
    print(f"Starting local development server...")
    print(f"Serving files from: {os.getcwd()}")
    print(f"Open http://localhost:{port}/ or http://127.0.0.1:{port}/ in your browser.")
    print("Press Ctrl+C to stop the server.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
        httpd.server_close()
    except OSError as e:
        print(f"\nError starting server: {e}")
        print(f"Perhaps port {port} is already in use?")


# --- Main Execution ---
if __name__ == "__main__":
    import argparse
    # import sys # Already imported at top

    parser = argparse.ArgumentParser(description='Download chapters from bqg5.com or 69shuba.com book index page and create an EPUB.')
    # Make URL optional initially, will check later if required for CLI mode
    parser.add_argument('url', nargs='?', default=None, help='The URL of the book index page (Required for CLI mode, e.g., https://www.bqg5.com/0_521/)')
    parser.add_argument('-s', '--start-chapter', type=int, default=1, help='Starting chapter number (inclusive, default: 1)')
    parser.add_argument('-e', '--end-chapter', type=int, default=None, help='Ending chapter number (inclusive, default: last chapter)')
    parser.add_argument('-o', '--output-dir', default=None, help=f'Directory to save the EPUB file (default: {OUTPUT_DIR})')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging') # DEBUG argument
    parser.add_argument('--fcgi', action='store_true', help='Run in FCGI mode') # FCGI argument
    parser.add_argument('--serve', action='store_true', help='Run a local development web server') # Add serve argument
    parser.add_argument('--port', type=int, default=8000, help='Port for the development server (default: 8000)') # Add port argument
    args = parser.parse_args() # Parse arguments here

    # --- Validate Arguments Based on Mode ---
    if not args.serve and not args.fcgi and args.url is None:
        parser.error("the following arguments are required in CLI mode: url")

    # --- Determine Execution Mode ---
    if args.serve:
        # --- Run Development Server ---
        # Configure logging for the server
        log_level = logging.DEBUG if args.debug else logging.INFO
        # Use a distinct format for server logs
        logging.basicConfig(level=log_level, format='%(asctime)s - Server - %(levelname)s - %(message)s')
        run_dev_server(args.port)
        sys.exit(0)
    elif args.fcgi:
        # --- Run FCGI Handler ---
        # Logging is configured within handle_fcgi_request
        handle_fcgi_request()
        sys.exit(0)
    else:
        # --- Standard CLI Execution ---
        log_level = logging.DEBUG if args.debug else logging.INFO
        logging.basicConfig(level=log_level, format='%(asctime)s - CLI - %(levelname)s - %(message)s')
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logging.debug("Debug logging enabled.")

    # Clean up URL whitespace
    book_index_url = args.url.strip()

    # --- Site Detection and Config ---
    # Detect site *before* potentially modifying the trailing slash
    site_config = get_site_config(book_index_url)
    if not site_config:
         logging.error(f"Unsupported website URL provided: {book_index_url}")
         sys.exit(1) # Exit if site is not supported

    # Ensure trailing slash for bqg5.com, remove for others
    if "bqg5.com" in site_config.get("base_url", ""):
        if not book_index_url.endswith('/'):
            book_index_url += '/'
            logging.debug("Ensured trailing slash for bqg5.com URL.")
    else:
        # Original behavior for other sites: remove trailing slash
        book_index_url = book_index_url.rstrip('/')
        logging.debug("Removed trailing slash for non-bqg5.com URL (if present).")

    logging.info(f"Starting EPUB creation for: {book_index_url}")
    logging.info(f"Using config for: {site_config['base_url']}")

    # --- Fetch Initial Pages ---
    index_html = None # Page with chapter links
    metadata_html = None # Page with book metadata (title, author, etc.)
    metadata_url = book_index_url # Default: metadata on index page

    if site_config.get('needs_metadata_fetch', False):
        # Derive metadata URL (e.g., .htm page for 69shuba)
        try:
            # Extract book ID for template (e.g., 85122 from https://www.69shuba.com/book/85122/ or 571203 from https://ixdzs8.com/read/571203/)
            # Make regex more general to handle different URL structures
            book_id_match = re.search(r'/(?:book|txt|info|read|chapter)/(\d+)', book_index_url) # Added 'read', 'chapter'
            if not book_id_match:
                # Try extracting last digits if pattern fails (less reliable)
                # Ensure we don't match the domain part if URL ends like .com/12345
                path_part = requests.utils.urlparse(book_index_url).path
                book_id_match = re.search(r'/(\d+)/?$', path_part)
                if not book_id_match:
                     # Try extracting digits after _
                     book_id_match = re.search(r'_(\d+)', book_index_url)

            if not book_id_match:
                raise ValueError("Could not extract book ID from URL for metadata lookup")

            book_id = book_id_match.group(1)
            metadata_url_template = site_config.get('metadata_url_template')
            chapter_list_url_template = site_config.get('chapter_list_url_template') # Get chapter list template
            if not metadata_url_template or not chapter_list_url_template:
                 raise ValueError("Missing 'metadata_url_template' or 'chapter_list_url_template' in site config")

            metadata_url = metadata_url_template.format(base_url=site_config['base_url'], book_id=book_id)
            logging.info(f"Fetching metadata page: {metadata_url}")
            metadata_html = fetch_url(metadata_url)
            if not metadata_html:
                 raise ConnectionError(f"Failed to fetch metadata page: {metadata_url}")

            # Construct and fetch the chapter list page URL using the template
            chapter_list_fetch_url = chapter_list_url_template.format(base_url=site_config['base_url'], book_id=book_id)
            logging.info(f"Fetching chapter list page: {chapter_list_fetch_url}")
            index_html = fetch_url(chapter_list_fetch_url)
            if not index_html:
                 raise ConnectionError(f"Failed to fetch chapter list page: {chapter_list_fetch_url}")

            # Important: Update book_index_url to the chapter list URL for subsequent use (e.g., resolving relative chapter links)
            book_index_url = chapter_list_fetch_url

        except (ValueError, ConnectionError, KeyError, AttributeError) as e:
             logging.error(f"Error preparing URLs or fetching initial pages for {site_config['base_url']}: {e}")
             metadata_html = None # Ensure it's None if fetch failed
             index_html = None
    else:
        # For sites like bqg5, metadata and chapters are on the same page
        logging.info(f"Fetching book index/metadata page: {book_index_url}")
        index_html = fetch_url(book_index_url)
        metadata_html = index_html # Use the same HTML for both
        metadata_url = book_index_url # URL where metadata was found

    # --- Process Data (CLI Mode) ---
    if index_html and metadata_html:
        # Use metadata_html for details, index_html for chapters (metadata_url needed for cover resolution)
        # Pass metadata_url for resolving relative cover images if needed
        book_title, book_author, book_description, cover_url = get_book_details(metadata_html, metadata_url, site_config)

        # Use chapter_list_fetch_url if available (for sites where metadata/chapters are separate)
        chapter_list_source_url = chapter_list_fetch_url or book_index_url
        chapter_links = get_chapter_links(index_html, chapter_list_source_url, site_config)

        # Apply chapter range using helper
        chapter_links = filter_chapters_by_range(chapter_links, args.start_chapter, args.end_chapter)

        if chapter_links:
            # Fetch chapter content using helper
            chapters_content_data = fetch_chapters_content(chapter_links, site_config)

            if chapters_content_data:
                logging.info(f"\nCollected content for {len(chapters_content_data)} chapters. Creating EPUB...")
                # Pass the metadata_url as the source URL for metadata
                # Pass args.output_dir for CLI mode
                create_epub(book_title, book_author, book_description, chapters_content_data, metadata_url, cover_url, args.output_dir)
            else:
                logging.error("No chapter content collected. EPUB creation aborted.")
        else:
            logging.error("No chapter links found. Aborting.")
    else:
        logging.error("Failed to fetch book index and/or metadata page(s). Aborting.")

    logging.info("Script finished.")