import os
import sys
import time
import json
import re
import urllib.parse
import unicodedata
import requests
from bs4 import BeautifulSoup
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==============================================================================
# 1. CRAWLER CONFIGURATION
# ==============================================================================

# Target website base URL
BASE_URL = "https://btv.com.kh"

# Starting Article ID (where the crawler begins)
START_ID = 114468

# "DOWN" : Count backwards (114468 -> 114467 -> 114466...) to scrape existing/older articles
CRAWL_DIRECTION = "DOWN"

# How many articles to crawl in this batch (set to None for continuous unlimited crawl)
MAX_ARTICLES = 30000


# Number of concurrent workers for multi-threading (2 workers = fast & stable without rate limits)
NUM_WORKERS = 2

# Delay between requests in seconds to keep scraping stable
REQUEST_DELAY = 0.2


# ==============================================================================
# 2. DIRECTORY SETTINGS & THREAD LOCK
# ==============================================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EXTRACTED_DIR = os.path.join(BASE_DIR, "extracted_texts")
CHECKPOINT_FILE = os.path.join(BASE_DIR, "processed_ids.txt")
ERROR_LOG_FILE = os.path.join(BASE_DIR, "skipped_errors.log")
JSONL_OUTPUT_FILE = os.path.join(EXTRACTED_DIR, "khmer_articles_corpus.jsonl")

os.makedirs(EXTRACTED_DIR, exist_ok=True)
FILE_LOCK = threading.Lock()


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "km,en-US,en;q=0.9",
}

# ==============================================================================
# 3. KHMER UNICODE CHARACTER SET & NORMALIZER
# ==============================================================================

KHMER_CONSONANTS = "កខគឃងចឆជឈញដឋឌឍណតថទធនបផពភមយរលវសហឡអ"
KHMER_INDEPENDENT_VOWELS = "ឣឤឥឦឧឨឩឪឫឬឭឮឯឰឱឲឳ"
KHMER_DEPENDENT_VOWELS = "ាិីឹឺុូួើឿៀេែៃោៅ"
KHMER_DIACRITICS = ["ំ", "ះ", "ៈ", "៉", "៊", "់", "៌", "៍", "៎", "៏", "័", "៑", "្", "៓", "៝"]
KHMER_DIGITS = "០១២៣៤៥៦៧៨៩"
KHMER_SYMBOLS = "។៕៖ៗ៘៙៚៛ៜ៝"
UNIVERSAL_PUNCTUATION = "«»“”‘’()[]{}<>%‰$+-=/*_.,:;?!~\"'#@ "

ALL_KHMER_CHARS = set(
    KHMER_CONSONANTS
    + KHMER_INDEPENDENT_VOWELS
    + KHMER_DEPENDENT_VOWELS
    + "".join(KHMER_DIACRITICS)
    + KHMER_DIGITS
    + KHMER_SYMBOLS
    + UNIVERSAL_PUNCTUATION
)

VALID_KHMER_STREAM_REGEX = re.compile(r"[^\u1780-\u17ff\u19e0-\u19ff0-9a-zA-Z\s.,;:()/%«»“”\"\'\-?!\n#@+=<>]")

def clean_khmer_text(text: str) -> str:
    """
    Cleans and normalizes Khmer text according to Unicode (NFC) standards.
    Strips corrupt legacy glyphs, handles broken ligatures, deduplicates vowels,
    and formats spacing cleanly.
    """
    if not text:
        return ""

    # 1. Remove non-Khmer font shadow glyphs and corrupted artifacts
    cleaned = VALID_KHMER_STREAM_REGEX.sub("", text)

    # 2. Re-join words split across newlines
    cleaned = re.sub(r"([\u1780-\u17d3])\n([\u1780-\u17d3])", r"\1\2", cleaned)

    # 3. Deduplicate consecutive duplicate vowels and diacritics
    all_vowels_and_signs = list(KHMER_DEPENDENT_VOWELS) + KHMER_DIACRITICS
    for d in all_vowels_and_signs:
        cleaned = re.sub(f"{d}+", d, cleaned)

    # 4. Deduplicate repeated consonants when not preceded by Coeng (\u17d2)
    for c in KHMER_CONSONANTS:
        cleaned = re.sub(f"(?<!\u17d2){c}{{2,}}", c, cleaned)

    # 5. Fix common broken words and misplaced characters
    cleaned = re.sub(r"ដែ\s*ល", "ដែល", cleaned)
    cleaned = re.sub(r"ក្នុ\s*ង", "ក្នុង", cleaned)
    cleaned = re.sub(r"ឡើ\s*ើង", "ឡើង", cleaned)
    cleaned = re.sub(r"ខ្លួ\s*ន", "ខ្លួន", cleaned)
    cleaned = re.sub(r"ឱ្យ\s*យ", "ឱ្យ", cleaned)
    cleaned = re.sub(r"រដ្ឋឋបាល", "រដ្ឋបាល", cleaned)
    cleaned = re.sub(r"\u17d2+", "\u17d2", cleaned)

    # 6. Format whitespace and remove all newline breaks (\n\n, \n, \r)
    cleaned = re.sub(r"[\r\n\t]+", " ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)

    return unicodedata.normalize("NFC", cleaned).strip()


# ==============================================================================
# 4. CHECKPOINT & ERROR LOGGING
# ==============================================================================

def load_processed_ids() -> set:
    """Loads all previously crawled article IDs from checkpoint file and existing JSONL corpus."""
    processed = set()
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
            processed = set(line.strip() for line in f if line.strip())

    if os.path.exists(JSONL_OUTPUT_FILE):
        try:
            with open(JSONL_OUTPUT_FILE, "r", encoding="utf-8") as f_jsonl:
                for line in f_jsonl:
                    line = line.strip()
                    if line:
                        item = json.loads(line)
                        if "id" in item:
                            processed.add(str(item["id"]))
        except Exception:
            pass

    return processed

def mark_id_processed(article_id: str):
    """Appends an article ID to the checkpoint file to avoid duplicate crawls."""
    with FILE_LOCK:
        with open(CHECKPOINT_FILE, "a", encoding="utf-8") as f:
            f.write(f"{article_id}\n")

def log_error(article_id: str, reason: str):
    """Logs crawling or parsing errors to the error log file."""
    with FILE_LOCK:
        with open(ERROR_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"ID: {article_id} | Reason: {reason} | Time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")


# ==============================================================================
# 5. HTML SCRAPER & PARSER FOR BTV NEWS
# ==============================================================================

def parse_btv_article_html(html_text: str, article_url: str) -> dict:
    """
    Extracts structured fields from BTV News HTML:
    - Title: <h4 class="h4 color"> or <h1>
    - Date/Time: <div class="group-date-share">
    - Category: Breadcrumb item
    - Content: <div class="font-size-detail textview">
    """
    soup = BeautifulSoup(html_text, "html.parser")

    # 1. Extract Title
    title = ""
    title_el = soup.find("h4", class_=lambda c: c and "h4" in c and "color" in c)
    if not title_el:
        title_el = soup.find("h1") or soup.find("h2") or soup.find("h4")
    if title_el:
        title = title_el.get_text(strip=True)

    # 2. Extract Publish Date & Time
    pub_date = ""
    date_el = soup.find("div", class_=lambda c: c and "group-date-share" in c)
    if date_el:
        raw_date_text = date_el.get_text(" ", strip=True)
        date_match = re.search(r"(\d{4}[/-]\d{1,2}[/-]\d{1,2}\s+\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm|AM|PM)?)", raw_date_text)
        if date_match:
            pub_date = date_match.group(1).strip()
        else:
            pub_date = re.sub(r"(Facebook|Telegram|Linkedin|Linkin|\d+\s*$)", "", raw_date_text).strip()
    else:
        meta_date = soup.find("meta", property="article:published_time")
        if meta_date and meta_date.get("content"):
            pub_date = meta_date["content"]

    # 3. Extract Category
    category = ""
    breadcrumb = soup.find("ul", class_=lambda c: c and "breadcrumb" in c)
    if breadcrumb:
        items = [li.get_text(strip=True) for li in breadcrumb.find_all("li")]
        if len(items) > 1:
            category = items[-1]

    # 4. Extract Article Content
    content_el = soup.find("div", class_=lambda c: c and "font-size-detail" in c and "textview" in c)
    if not content_el:
        content_el = soup.find("div", class_=lambda c: c and "detail-content" in c) or soup.find("article")

    content_text = ""
    if content_el:
        # Remove advertisements, scripts, styling tags, and share buttons
        for unwanted in content_el.find_all(["script", "style", "iframe", "button"]):
            unwanted.decompose()
        for ad in content_el.find_all("div", class_=lambda c: c and ("ads" in str(c).lower() or "view_ads" in str(c).lower())):
            ad.decompose()

        # Collect paragraphs cleanly
        paragraphs = []
        for p in content_el.find_all(["p", "div", "h2", "h3", "h4", "h5", "blockquote"]):
            p_text = p.get_text(strip=True)
            if p_text and len(p_text) > 10 and p_text not in paragraphs:
                paragraphs.append(p_text)

        if paragraphs:
            content_text = " ".join(paragraphs)
        else:
            content_text = content_el.get_text(" ", strip=True)


    # Fallback to meta description if content element is empty
    if not content_text:
        meta_desc = soup.find("meta", property="og:description") or soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            content_text = meta_desc["content"]

    # Clean text via Khmer Unicode normalizer
    title_clean = clean_khmer_text(title)
    content_clean = clean_khmer_text(content_text)

    id_match = re.search(r"/article/(\d+)", article_url)
    article_id = id_match.group(1) if id_match else str(int(time.time()))

    return {
        "id": article_id,
        "title": title_clean,
        "date": pub_date.strip(),
        "category": category.strip(),
        "url": article_url,
        "content": content_clean,
    }

# ==============================================================================
# 6. CRAWLER & SCRAPER ENGINE
# ==============================================================================

def fetch_single_article(article_url: str) -> dict:
    """Fetches HTML and parses a single article using isolated thread-safe HTTP request."""
    try:
        with requests.Session() as s:
            s.headers.update(HEADERS)
            resp = s.get(article_url, timeout=3.5)
            if resp.status_code == 200:
                return parse_btv_article_html(resp.text, article_url)
            else:
                return {"error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"error": str(e)}



def save_article_result(data: dict):
    """Directly saves and streams the clean article into the JSONL corpus file with thread safety."""
    article_id = data["id"]
    json_record = {
        "id": article_id,
        "title": data["title"],
        "date": data["date"],
        "category": data["category"],
        "url": data["url"],
        "text": data["content"]
    }

    with FILE_LOCK:
        with open(JSONL_OUTPUT_FILE, "a", encoding="utf-8") as f_jsonl:
            f_jsonl.write(json.dumps(json_record, ensure_ascii=False) + "\n")

    mark_id_processed(article_id)


def discover_articles_from_site(base_url: str, limit: int = 50) -> list:
    """Discovers latest article URLs by finding all article IDs on homepage and category pages."""
    print(f"[CRAWLER] Discovering articles from homepage: {base_url} ...")
    found_article_ids = set()

    def extract_article_ids_from_soup(soup):
        for a in soup.find_all("a", href=True):
            href = a["href"]
            matches = re.findall(r"article(?:/|%2F|=)(\d+)", href)
            for aid in matches:
                found_article_ids.add(aid)

    try:
        resp = requests.get(base_url, headers=HEADERS, timeout=15)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            extract_article_ids_from_soup(soup)

            # Discover via category navigation
            category_links = set([
                f"{base_url}/category/1",
                f"{base_url}/category/2",
                f"{base_url}/category/3",
                f"{base_url}/category/4",
                f"{base_url}/category/5",
                f"{base_url}/category/6",
            ])
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "/category/" in href or "/news/" in href or "cat=" in href:
                    category_links.add(urllib.parse.urljoin(base_url, href))

            for cat in list(category_links):
                if limit and len(found_article_ids) >= limit * 2:
                    break
                try:
                    c_resp = requests.get(cat, headers=HEADERS, timeout=10)
                    if c_resp.status_code == 200:
                        c_soup = BeautifulSoup(c_resp.text, "html.parser")
                        extract_article_ids_from_soup(c_soup)
                except Exception:
                    pass
    except Exception as e:
        print(f"[WARN] Unable to reach {base_url}: {e}")


    # Construct clean URLs (https://btv.com.kh/article/{id}) sorted ascending (20, 21, 22...)
    sorted_ids = sorted(list(found_article_ids), key=lambda x: int(x))
    clean_urls = [f"{base_url}/article/{aid}" for aid in sorted_ids]
    return clean_urls[:limit] if limit else clean_urls


def process_single_url(url: str, idx: int, total: int) -> bool:
    """Worker function to process one URL."""
    id_match = re.search(r"/article/(\d+)", url)
    a_id = id_match.group(1) if id_match else f"item_{idx}"

    print(f"[{idx}/{total}] Scraping: {url} ...")
    article_data = fetch_single_article(url)

    if "error" in article_data:
        err = article_data["error"]
        if "timed out" in err.lower() or "500" in err or "404" in err:
            print(f"   [NOT FOUND] (ID: {a_id}) No article published at this ID (Skipped)")
            log_error(a_id, "No article published at this ID on server")
        else:
            print(f"   [ERROR] (ID: {a_id}) Connection issue: {err}")
            log_error(a_id, err)
        mark_id_processed(a_id)
        return False

    if not article_data.get("content") or len(article_data["content"]) < 20:
        print(f"   [SKIP] (ID: {a_id}) Article content is empty or not found")
        log_error(a_id, "Empty or too short content")
        mark_id_processed(a_id)
        return False

    save_article_result(article_data)
    print(f"   [SUCCESS] (ID: {a_id}) Title: {article_data['title'][:55]}...")
    print(f"      Details: {len(article_data['content'])} chars | Date: {article_data['date']}")
    return True



# ==============================================================================
# 7. MAIN CONTROLLER
# ==============================================================================

def main():
    print("=" * 75)
    print("KHMER LLM DATASET CRAWLER (100% PURE WEB SCRAPING)")
    print("=" * 75)

    processed_ids = load_processed_ids()
    print(f"[CHECKPOINT] Previously processed articles: {len(processed_ids)}")

    urls_to_crawl = []

    # 1. Generate URLs to crawl based on START_ID and CRAWL_DIRECTION
    dir_text = "downwards (-1)" if CRAWL_DIRECTION == "DOWN" else "upwards (+1)"
    print(f"[CRAWLER] Starting crawl from ID {START_ID} {dir_text}...")
    
    current_id = START_ID
    limit = MAX_ARTICLES if MAX_ARTICLES is not None else 1000000
    
    while len(urls_to_crawl) < limit and current_id > 0:
        if str(current_id) not in processed_ids:
            urls_to_crawl.append(f"{BASE_URL}/article/{current_id}")
        
        if CRAWL_DIRECTION == "DOWN":
            current_id -= 1
        else:
            current_id += 1

    print(f"[QUEUE] {len(urls_to_crawl)} articles queued for processing (Workers: {NUM_WORKERS})")
    print(f"[OUTPUT] Files will be stored in: {EXTRACTED_DIR}/")
    print("-" * 75)


    if not urls_to_crawl:
        print("[INFO] No new articles to crawl (all items in queue already processed).")
        return

    success_count = 0
    start_time = time.time()
    total_urls = len(urls_to_crawl)

    if NUM_WORKERS > 1:
        # Multi-threaded concurrent crawling
        with ThreadPoolExecutor(max_workers=NUM_WORKERS) as executor:
            futures = {
                executor.submit(process_single_url, url, idx, total_urls): url
                for idx, url in enumerate(urls_to_crawl, 1)
            }
            for future in as_completed(futures):
                try:
                    if future.result():
                        success_count += 1
                except Exception as e:
                    print(f"   [ERROR] Worker failed: {e}")
    else:
        # Sequential single-threaded crawling
        for idx, url in enumerate(urls_to_crawl, 1):
            if process_single_url(url, idx, total_urls):
                success_count += 1
            time.sleep(REQUEST_DELAY)

    duration = round(time.time() - start_time, 2)
    print("\n" + "=" * 75)
    print(f"[DONE] Crawl completed: {success_count}/{len(urls_to_crawl)} articles extracted ({duration}s)")
    print(f"[OUTPUT] JSONL corpus dataset: {JSONL_OUTPUT_FILE}")
    print("=" * 75)


if __name__ == "__main__":
    main()