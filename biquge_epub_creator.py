import requests
from bs4 import BeautifulSoup
import ebooklib
from ebooklib import epub
import time
import re
import os
import logging
import mimetypes # Added for guessing image type

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

def clean_html_content(html_content):
    """Removes unwanted tags and cleans up chapter text for EPUB HTML."""
    # Remove script and style elements
    for script in html_content(["script", "style", "ins", "div"]): # Remove divs as well, assuming content is directly in #content
        script.extract()

    # Convert <br> tags to newlines first
    for br in html_content.find_all("br"):
        br.replace_with("\n")

    # Get text content, preserving line breaks from converted <br> tags
    text = html_content.get_text(separator='\n')

    # Clean whitespace and specific patterns
    lines = text.splitlines()
    cleaned_lines = []
    for line in lines:
        cleaned_line = line.strip()
        # Replace common placeholders/ads specific to the site
        cleaned_line = cleaned_line.replace('    ', '') # Remove specific space sequence often used for indentation
        cleaned_line = cleaned_line.replace(' ', ' ') # Replace non-breaking space
        # Remove potential leftover promotional text (adjust regex as needed)
        cleaned_line = re.sub(r'天才一秒记住本站地址.*', '', cleaned_line, flags=re.IGNORECASE)
        cleaned_line = re.sub(r'手机版阅读网址.*', '', cleaned_line, flags=re.IGNORECASE)
        cleaned_line = re.sub(r'bqg\d*\.(com|cc|net)', '', cleaned_line, flags=re.IGNORECASE) # Remove site name mentions
        cleaned_line = re.sub(r'请记住本书首发域名.*', '', cleaned_line, flags=re.IGNORECASE)
        cleaned_line = re.sub(r'最新网址.*', '', cleaned_line, flags=re.IGNORECASE)
        cleaned_line = re.sub(r'\(.*?\)', '', cleaned_line) # Remove text in parentheses often used for ads/notes

        if cleaned_line: # Only keep non-empty lines
            cleaned_lines.append(cleaned_line)

    # Format as simple HTML paragraphs
    # Add indentation using CSS class later if desired
    content_html = '\n'.join(f'<p>{line}</p>' for line in cleaned_lines)
    return content_html.strip()

# --- Main Logic ---

def get_book_details(index_html, book_url):
    """Extracts book title, author, description, and cover image URL from the index page."""
    soup = BeautifulSoup(index_html, 'html.parser')
    # Try multiple selectors for title and author as site structure might vary
    title_tag = soup.find('meta', property='og:title') or soup.find('h1')
    author_tag = soup.find('meta', property='og:novel:author')
    status_tag = soup.find('meta', property='og:novel:status')
    description_tag = soup.find('meta', property='og:description')
    cover_image_tag = soup.select_one('#fmimg img') # Selector for the cover image
    # cover_image_tag = soup.find('meta', property='og:image') # Alternative if the site uses og:image

    title = title_tag['content'].strip() if title_tag and title_tag.has_attr('content') else (title_tag.text.strip() if title_tag else "Unknown Title")
    author = author_tag['content'].strip() if author_tag else "Unknown Author"
    status = status_tag['content'].strip() if status_tag else "Unknown Status"
    description = description_tag['content'].strip() if description_tag else "No description available."
    cover_image_url = requests.compat.urljoin(book_url, cover_image_tag['src']) if cover_image_tag and cover_image_tag.get('src') else None

    # Refine author extraction if needed (sometimes it's in a <p> tag)
    if author == "Unknown Author":
        info_div = soup.find('div', id='info')
        if info_div:
            p_tags = info_div.find_all('p')
            for p in p_tags:
                 if '作    者：' in p.text: # Check for Chinese label "作者："
                     author = p.text.replace('作    者：', '').strip()
                     break

    logging.info(f"Title: {title}")
    logging.info(f"Author: {author}")
    logging.info(f"Status: {status}")
    logging.info(f"Description: {description[:100]}...") # Log first 100 chars
    logging.info(f"Cover Image URL: {cover_image_url}")
    return title, author, description, cover_image_url

def get_chapter_links(index_html, book_url):
    """Extracts chapter links and titles from the index page."""
    soup = BeautifulSoup(index_html, 'html.parser')
    chapters = []
    # Find the chapter list container (adjust selector based on website structure)
    chapter_list_container = soup.find('div', id='list') or soup.find('dl') # Try dl as fallback
    if not chapter_list_container:
        logging.error("Could not find chapter list container ('div#list' or 'dl').")
        return []

    links = chapter_list_container.find_all('a')
    seen_urls = set() # Avoid duplicate chapters if links appear multiple times
    for link in links:
        href = link.get('href')
        title = link.text.strip()
        if href and title and not href.startswith(('javascript:', '#')):
            # Construct absolute URL if relative
            full_url = requests.compat.urljoin(book_url, href)
            if full_url not in seen_urls:
                chapters.append({'title': title, 'url': full_url})
                seen_urls.add(full_url)

    # Often the first few links are not chapters, but the latest ones.
    # Heuristic: Find the first link that looks like a real chapter (e.g., contains '第...章')
    # Or assume the list starts after a certain element like <dt>
    dt_elements = chapter_list_container.find_all('dt')
    if len(dt_elements) > 1: # Check if there are multiple <dt> sections
        # Assume chapters start after the second <dt> which often labels the main list
        chapter_links_element = dt_elements[1].find_next_siblings()
        chapters = [] # Reset chapters and rebuild from the correct section
        seen_urls = set()
        for element in chapter_links_element:
            if element.name == 'dd':
                link = element.find('a')
                if link:
                    href = link.get('href')
                    title = link.text.strip()
                    if href and title and not href.startswith(('javascript:', '#')):
                        full_url = requests.compat.urljoin(book_url, href)
                        if full_url not in seen_urls:
                            chapters.append({'title': title, 'url': full_url})
                            seen_urls.add(full_url)

    logging.info(f"Found {len(chapters)} potential chapter links.")
    return chapters

def create_epub(title, author, description, chapters_data, book_url, cover_image_url):
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

    # Create output directory if it doesn't exist
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Sanitize filename
    sanitized_title = re.sub(r'[\\/*?:"<>|]',"", title) # Remove invalid characters
    sanitized_title = re.sub(r'\s+', '_', sanitized_title) # Replace spaces with underscores
    output_filename = OUTPUT_FILENAME_TEMPLATE.format(title=sanitized_title)
    output_path = os.path.join(OUTPUT_DIR, output_filename)

    # Save EPUB file
    try:
        epub.write_epub(output_path, book, {})
        logging.info(f"\nEPUB created successfully: {output_path}")
    except Exception as e:
        logging.error(f"Error writing EPUB file: {e}")

# --- Main Execution ---
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Download chapters from a bqg5.com book index page and create an EPUB.')
    parser.add_argument('url', nargs='?', default=DEFAULT_BOOK_INDEX_URL,
                        help=f'The URL of the book index page (e.g., {DEFAULT_BOOK_INDEX_URL})')
    args = parser.parse_args()
    book_index_url = args.url

    logging.info(f"Starting EPUB creation for: {book_index_url}")
    logging.info(f"Fetching book index: {book_index_url}")
    index_html = fetch_url(book_index_url)

    if index_html:
        book_title, book_author, book_description, cover_url = get_book_details(index_html, book_index_url)

        chapter_links = get_chapter_links(index_html, book_index_url)

        if chapter_links:
            chapters_content_data = []
            total_chapters = len(chapter_links)
            logging.info(f"Attempting to fetch content for {total_chapters} chapters...")

            for i, chapter_info in enumerate(chapter_links):
                logging.info(f"Processing chapter {i+1}/{total_chapters}: {chapter_info['title']} ({chapter_info['url']})")
                chapter_html_page = fetch_url(chapter_info['url'])
                if chapter_html_page:
                    soup = BeautifulSoup(chapter_html_page, 'html.parser')
                    # Find the main content div (adjust selector based on website structure)
                    # Common selectors: #content, .content, #booktxt, .read-content
                    content_div = soup.find('div', id='content') or soup.find('div', class_='content') or soup.find('div', id='booktxt')

                    if content_div:
                        # Clean the content before adding
                        cleaned_content_html = clean_html_content(content_div)
                        if cleaned_content_html: # Ensure content was actually extracted
                            chapters_content_data.append({
                                'title': chapter_info['title'],
                                'content_html': cleaned_content_html
                            })
                        else:
                            logging.warning(f"Content div found but no text extracted for chapter: {chapter_info['title']}")
                    else:
                        logging.warning(f"Could not find content div for chapter: {chapter_info['title']} at {chapter_info['url']}")
                else:
                    logging.warning(f"Skipping chapter due to fetch error: {chapter_info['title']}")

            if chapters_content_data:
                logging.info(f"\nCollected content for {len(chapters_content_data)} chapters. Creating EPUB...")
                create_epub(book_title, book_author, book_description, chapters_content_data, book_index_url, cover_url)
            else:
                logging.error("No chapter content collected. EPUB creation aborted.")
        else:
            logging.error("No chapter links found. Aborting.")
    else:
        logging.error("Failed to fetch book index. Aborting.")

    logging.info("Script finished.")