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
    }
}

def get_site_config(url):
    """Determines the site config based on the URL."""
    for domain, config in SITE_CONFIGS.items():
        # Check if the domain is present in the URL's netloc
        try:
            parsed_url = requests.utils.urlparse(url)
            if domain in parsed_url.netloc:
                logging.info(f"Detected site: {domain}")
                return config
        except Exception as e:
            logging.warning(f"URL parsing failed for {url}: {e}. Trying simple string search.")
            # Fallback to simple string search if parsing fails
            if domain in url:
                logging.info(f"Detected site (fallback): {domain}")
                return config

    logging.warning(f"Could not determine site configuration for URL: {url}. No supported domain found.")
    return None # Return None if no config found

# --- Helper Functions ---
# --- Helper Functions ---

def fetch_url(url):
    """Fetches content from a URL with retries and delay."""
    retries = 0
    while retries < MAX_RETRIES:
        try:
            response = requests.get(url, headers=HEADERS, timeout=30)
            response.raise_for_status() # Raise an exception for bad status codes
            # Try to detect encoding, fallback to gb18030 if detection fails or is incorrect
            detected_encoding = response.apparent_encoding if response.apparent_encoding else 'gb18030'
            response.encoding = detected_encoding
            # Force gb18030 if common Chinese characters are garbled with apparent_encoding
            # Check a larger portion of text for potential garbled characters
            if '�' in response.text[:2000]:
                 logging.warning(f"Garbled characters detected with encoding {detected_encoding} for {url}. Forcing gb18030.")
                 response.encoding = 'gb18030'

            logging.info(f"Fetched: {url} (Status: {response.status_code}, Encoding: {response.encoding})")
            time.sleep(REQUEST_DELAY)
            return response.text
        except requests.exceptions.Timeout:
            retries += 1
            logging.warning(f"Timeout fetching {url}. Retrying ({retries}/{MAX_RETRIES})...")
            time.sleep(2 ** retries) # Exponential backoff
        except requests.exceptions.RequestException as e:
            retries += 1
            logging.warning(f"Error fetching {url}: {e}. Retrying ({retries}/{MAX_RETRIES})...")
            time.sleep(2 ** retries) # Exponential backoff

    logging.error(f"Failed to fetch {url} after {MAX_RETRIES} retries.")
    return None

def clean_html_content(content_container_tag, site_config): # Changed parameter, added site_config
    """Removes unwanted tags and cleans up chapter text for EPUB HTML."""
    if not content_container_tag:
        return ""

    # Work on a copy to avoid modifying the original soup object
    # Use html.parser for consistency
    tag_copy = BeautifulSoup(str(content_container_tag), 'html.parser').find(content_container_tag.name, recursive=False, attrs=content_container_tag.attrs)
    # Handle case where find returns None
    if not tag_copy:
        logging.warning("Failed to parse content container tag copy.")
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
                logging.warning(f"Invalid regex pattern in site config: {pattern} - {e}")

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

def get_book_details(html_content, book_url, site_config): # Added site_config, changed html source name
    """Extracts book title, author, description, and cover image URL from the relevant page."""
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
            logging.warning(f"Error applying selector '{selector_key}' ({selector}): {e}")
        return None

    # Helper to get content/text
    def get_content(tag, attr='content'):
        if not tag: return None
        try:
            if attr and tag.has_attr(attr): return tag[attr].strip()
            return tag.text.strip()
        except Exception as e:
            logging.warning(f"Error getting content/attribute '{attr}' from tag {tag}: {e}")
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
                          logging.debug(f"Found author using author_link_selector: {author}")

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
                              logging.debug(f"Found author using fallback 1 (p/div/span): {author}")
                              break

             # Fallback 2: Search the entire container text using regex
             if not found:
                 container_text = info_container.get_text(" ", strip=True)
                 # Regex to find label and capture following non-whitespace chars
                 match = re.search(re.escape(author_label) + r'\s*([^\s<]+)', container_text) # Avoid matching tags
                 if match:
                     author = match.group(1).strip()
                     found = True
                     logging.debug(f"Found author using fallback 2 (regex): {author}")

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
             logging.warning(f"Could not construct absolute cover URL from src: {cover_image_src}")
             cover_image_url = None

    # Author fallback logic moved up

    logging.info(f"Title: {title}")
    logging.info(f"Author: {author}")
    logging.info(f"Status: {status}")
    logging.info(f"Description: {description[:100]}...") # Log first 100 chars
    logging.info(f"Cover Image URL: {cover_image_url}")
    return title, author, description, cover_image_url

def get_chapter_links(index_html, book_url, site_config): # Added site_config
    """Extracts chapter links and titles from the index page."""
    # Explicitly use encoding hint from site_config for parsing, if available
    site_encoding = site_config.get('encoding')
    if site_encoding:
        logging.debug(f"Using encoding hint for BeautifulSoup in get_chapter_links: {site_encoding}")
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
            logging.warning(f"Error applying selector '{selector_key}' ({selector}): {e}")
        return None

    # Find the chapter list container
    container_selector = selectors.get('container')
    container_fallback_selector = selectors.get('container_fallback')
    chapter_list_container = find_element('container') or find_element('container_fallback')

    # Check if a container was found *if* one was expected.
    # If a container was expected but not found, log an error, but still allow fallback attempts below.
    if container_selector is not None and not chapter_list_container:
        logging.warning(f"Expected chapter list container not found using selectors: {container_selector}, {container_fallback_selector}. Will attempt fallback link selection.")

    # --- Select Links based on Config ---
    links_elements = []
    skip_dt_count = selectors.get('skip_dt_count', 0)
    link_selector = selectors.get('link_selector', 'a') # Default to 'a'

    # Find the main chapter list container (div#list)
    chapter_list_container = soup.find('div', {'id': 'list'})

    if not chapter_list_container:
        logging.error("Main chapter list container (div#list) not found.")
        return []
    logging.debug(f"Found chapter list container: {chapter_list_container.name}#{chapter_list_container.get('id')}") # DEBUG

    # Find the dl tag within the list_div
    dl_tag = chapter_list_container.find('dl')

    if not dl_tag:
        logging.error("DL tag within div#list not found.")
        return []
    logging.debug("Found DL tag within container.") # DEBUG

    if skip_dt_count > 0:
        # Logic for sites like bqg5 that need skipping based on <dt>
        dt_elements = dl_tag.find_all('dt')
        logging.debug(f"Found {len(dt_elements)} dt elements.") # DEBUG
        if len(dt_elements) >= skip_dt_count:
            target_dt = dt_elements[skip_dt_count - 1] # e.g., if skip_dt_count is 2, use the second dt (index 1)
            logging.debug(f"Target DT ({skip_dt_count}): {target_dt.text[:50]}...") # DEBUG
            # Find all dd siblings after the target dt
            chapter_dd_siblings = target_dt.find_next_siblings('dd')
            logging.debug(f"Found {len(list(chapter_dd_siblings))} dd siblings after target DT.") # DEBUG - Convert generator to list for count
            # Re-iterate after counting
            chapter_dd_siblings = target_dt.find_next_siblings('dd')
            for dd_index, dd_element in enumerate(chapter_dd_siblings):
                # Find the link within the dd element
                link = dd_element.find('a')
                if link:
                    logging.debug(f"  Found link in dd {dd_index+1}: {link.get('href')} - {link.text.strip()}") # DEBUG
                    links_elements.append(link)
                else:
                    logging.debug(f"  No link found in dd {dd_index+1}") # DEBUG
        else:
             # Fallback to selecting all links if dt structure not found as expected
             logging.warning(f"Expected {skip_dt_count} <dt> elements for skipping, but found {len(dt_elements)}. Falling back to selecting all links within DL.")
             links_elements = dl_tag.find_all('a') # Select all links within the dl
             logging.debug(f"Fallback: Found {len(links_elements)} links directly within DL.") # DEBUG
    else:
        # Simpler logic for sites like 69shuba (or if no skipping needed)
        links_elements = dl_tag.find_all('a') # Select all links within the dl

    # After all attempts, check if links were found
    if not links_elements:
        logging.error("Failed to find any chapter links after all selection attempts.")
        return []

    # --- Process Selected Links ---
    chapters = []
    seen_urls = set() # Avoid duplicate chapters
    base_site_url = site_config.get("base_url", book_url) # Use for joining relative URLs

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
                path = requests.utils.urlparse(full_url).path
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
                        logging.debug(f"Skipping latest chapter link in header: {title} ({full_url})")
                        continue # Skip this link

                # --- General processing ---
                # Simple title cleaning (remove potential artifacts)
                title = re.sub(r'^（\d+）', '', title).strip() # Remove leading (number) if present
                # Remove common prefixes/suffixes if needed
                # title = title.replace('最新章节 ', '')

                chapters.append({'title': title, 'url': full_url})
                seen_urls.add(full_url)
            else: # DEBUG: Log why a link was skipped
                logging.debug(f"Skipping link: Title='{title}', Href='{href}', LikelyChapter={is_likely_chapter}, Seen={full_url in seen_urls}")

    logging.info(f"Found {len(chapters)} potential chapter links.")
    logging.debug(f"Final chapter list before return: {[c['title'] for c in chapters[:5]]}...") # DEBUG first 5 titles
    # Reverse chapter order for sites that list newest first (like 69shuba)
    if "69shuba.com" in site_config.get("base_url", ""):
         logging.info("Reversing chapter order for 69shuba.com.")
         chapters.reverse()
    return chapters

def create_epub(title, author, description, chapters_data, book_url, cover_image_url, output_directory):
    """Creates an EPUB file from the chapter data."""
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
        logging.info(f"Attempting to download cover image: {cover_image_url}")
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
            logging.info(f"Cover image downloaded and added ({img_mimetype}).")
        except requests.exceptions.RequestException as e:
            logging.warning(f"Could not download or add cover image: {e}")

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
        logging.info(f"Added chapter {i+1}: {chapter_title}")

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

    # Use the provided output directory or the default
    target_output_dir = output_directory if output_directory else OUTPUT_DIR
    # Create output directory if it doesn't exist
    os.makedirs(target_output_dir, exist_ok=True)

    # Sanitize filename
    sanitized_title = re.sub(r'[\\/*?:"<>|]',"", title) # Remove invalid characters
    sanitized_title = re.sub(r'\s+', '_', sanitized_title) # Replace spaces with underscores
    output_filename = OUTPUT_FILENAME_TEMPLATE.format(title=sanitized_title)
    output_path = os.path.join(target_output_dir, output_filename)

    # Save EPUB file
    try:
        epub.write_epub(output_path, book, {})
        logging.info(f"\nEPUB created successfully: {output_path}")
    except Exception as e:
        logging.error(f"Error writing EPUB file: {e}")

# --- Main Execution ---
if __name__ == "__main__":
    import argparse
    # import sys # Already imported at top

    parser = argparse.ArgumentParser(description='Download chapters from bqg5.com or 69shuba.com book index page and create an EPUB.')
    # Changed default to None, make URL required, removed nargs='?'
    parser.add_argument('url', help='The URL of the book index page (e.g., https://www.bqg5.com/0_521/ or https://www.69shuba.com/book/85122/)')
    parser.add_argument('-s', '--start-chapter', type=int, default=1, help='Starting chapter number (inclusive, default: 1)')
    parser.add_argument('-e', '--end-chapter', type=int, default=None, help='Ending chapter number (inclusive, default: last chapter)')
    parser.add_argument('-o', '--output-dir', default=None, help=f'Directory to save the EPUB file (default: {OUTPUT_DIR})')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging') # DEBUG argument
    args = parser.parse_args()

    # --- Configure Logging Level ---
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
            # Extract book ID for template (e.g., 85122 from https://www.69shuba.com/book/85122/)
            # Make regex more general if needed
            book_id_match = re.search(r'/(?:book|txt|info)/(\d+)', book_index_url)
            if not book_id_match:
                # Try extracting last digits if pattern fails
                book_id_match = re.search(r'/(\d+)/?$', book_index_url.split('/')[-1] if book_index_url.endswith('/') else book_index_url)
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

    # --- Process Data ---
    if index_html and metadata_html:
        # Use metadata_html for details, index_html for chapters
        # Pass metadata_url for resolving relative cover images if needed
        book_title, book_author, book_description, cover_url = get_book_details(metadata_html, metadata_url, site_config)

        chapter_links = get_chapter_links(index_html, book_index_url, site_config)

        # --- Apply Chapter Range ---
        start_chapter_num = args.start_chapter
        end_chapter_num = args.end_chapter
        original_chapter_count = len(chapter_links)

        # Convert chapter numbers to 0-based list indices
        start_index = start_chapter_num - 1
        end_index = end_chapter_num if end_chapter_num is not None else original_chapter_count

        # Validate indices
        if start_index < 0:
            logging.warning(f"Start chapter {start_chapter_num} is invalid. Using chapter 1.")
            start_index = 0
        if end_index > original_chapter_count:
            logging.warning(f"End chapter {end_chapter_num} is greater than total chapters ({original_chapter_count}). Using last chapter.")
            end_index = original_chapter_count
        if start_index >= end_index:
             logging.warning(f"Start chapter ({start_chapter_num}) is greater than or equal to end chapter ({end_chapter_num}). Only downloading chapter {start_chapter_num}.")
             end_index = start_index + 1 # Ensure at least the start chapter is included

        # Slice the chapter list
        if start_index > 0 or end_index < original_chapter_count:
             logging.info(f"Selecting chapters from {start_index + 1} to {end_index} (inclusive).")
             chapter_links = chapter_links[start_index:end_index]
        else:
             logging.info(f"Selecting all {original_chapter_count} chapters.")

        if chapter_links:
            chapters_content_data = []
            total_chapters = len(chapter_links)
            logging.info(f"Attempting to fetch content for {total_chapters} chapters...")

            for i, chapter_info in enumerate(chapter_links):
                logging.info(f"Processing chapter {i+1}/{total_chapters}: {chapter_info['title']} ({chapter_info['url']})")
                chapter_html_page = fetch_url(chapter_info['url'])
                if chapter_html_page:
                    soup = BeautifulSoup(chapter_html_page, 'html.parser')
                    # Find the main content div using selectors from config
                    content_div = None
                    content_selectors = site_config.get('chapter_content_selectors', {}).get('container', [])
                    for selector_info in content_selectors:
                         try:
                             if isinstance(selector_info, tuple) and len(selector_info) == 2:
                                  content_div = soup.find(selector_info[0], selector_info[1])
                             elif isinstance(selector_info, str): # Simple CSS selector
                                  content_div = soup.select_one(selector_info)
                             if content_div:
                                 logging.debug(f"Found content container using: {selector_info}")
                                 break # Found it
                         except Exception as e:
                             logging.warning(f"Error applying content selector {selector_info}: {e}")
                             continue # Try next selector

                    if content_div:
                        # Clean the content *container* before adding
                        # Pass site_config to cleaning function for site-specific rules
                        cleaned_content_html = clean_html_content(content_div, site_config) # Pass the tag object and config
                        if cleaned_content_html: # Ensure content was actually extracted
                            chapters_content_data.append({
                                'title': chapter_info['title'],
                                'content_html': cleaned_content_html
                            })
                        else:
                            logging.warning(f"Content div found but no text extracted for chapter: {chapter_info['title']}")
                    else:
                        logging.warning(f"Could not find content div for chapter: {chapter_info['title']} at {chapter_info['url']} using selectors {content_selectors}")
                else:
                    logging.warning(f"Skipping chapter due to fetch error: {chapter_info['title']}")

            if chapters_content_data:
                logging.info(f"\nCollected content for {len(chapters_content_data)} chapters. Creating EPUB...")
                # Pass the original book_index_url as the source URL for metadata and the output directory
                create_epub(book_title, book_author, book_description, chapters_content_data, book_index_url, cover_url, args.output_dir)
            else:
                logging.error("No chapter content collected. EPUB creation aborted.")
        else:
            logging.error("No chapter links found. Aborting.")
    else:
        logging.error("Failed to fetch book index and/or metadata page(s). Aborting.")

    logging.info("Script finished.")