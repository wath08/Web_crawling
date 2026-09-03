import os
import sys
import time
import json
import re
import html
import urllib.parse
import unicodedata
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
import threading
from concurrent.futures import ThreadPoolExecutor

# ==============================================================================
# 1. GOVERNMENT CRAWLER CONFIGURATION (GDT - អគ្គនាយកដ្ឋានពន្ធដារ / ECONOMY)
# ==============================================================================

INSTITUTION_NAME = "អគ្គនាយកដ្ឋានពន្ធដារ"
BASE_URL = "https://www.tax.gov.kh"
LIST_URL_PATTERN = "https://www.tax.gov.kh/kh/event?p={page}"

# Start Page (1 = អត្ថបទថ្មីបំផុត Bq5cun30264204244W1)
START_PAGE = 1

# ចំនួនទំព័រអតិបរមា (50 ទំព័រ)
MAX_PAGES = 50

# ចំនួនអត្ថបទដែលត្រូវប្រមូល (1000 អត្ថបទ)
MAX_ARTICLES = 1000

# ចំនួន Threads ស្របគ្នា (4 Workers)
NUM_WORKERS = 4

# រយៈពេលរង់ចាំរវាង Request (០.២ វិនាទី)
REQUEST_DELAY = 0.2

# ==============================================================================
# 2. DIRECTORY SETTINGS (ECONOMY FOLDER)
# ==============================================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_ROOT_DIR = os.path.join(BASE_DIR, "KhmerLLM-Dataset")
GOV_ECONOMY_DIR = os.path.join(DATASET_ROOT_DIR, "04_government", "economy")
RECORD_DIR = os.path.join(BASE_DIR, "record")

os.makedirs(RECORD_DIR, exist_ok=True)
os.makedirs(GOV_ECONOMY_DIR, exist_ok=True)

CHECKPOINT_FILE = os.path.join(RECORD_DIR, "processed_keys_gdt.txt")
ERROR_LOG_FILE = os.path.join(RECORD_DIR, "skipped_errors_gdt.log")
JSONL_OUTPUT_FILE = os.path.join(GOV_ECONOMY_DIR, "economy_gdt.jsonl")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "km,en-US,en;q=0.9",
    "Referer": "https://www.tax.gov.kh/kh/event"
}

def create_robust_session():
    session = requests.Session()
    session.headers.update(HEADERS)
    retries = Retry(total=5, backoff_factor=1.0, status_forcelist=[500, 502, 503, 504, 429])
    adapter = HTTPAdapter(pool_connections=50, pool_maxsize=50, max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

# ==============================================================================
# 3. KHMER UNICODE CHARACTER SET & BOILERPLATE REMOVER
# ==============================================================================

KHMER_CONSONANTS = "កខគឃងចឆជឈញដឋឌឍណតថទធនបផពភមយរលវសហឡអ"
KHMER_INDEPENDENT_VOWELS = "ឣឤឥឦឧឨឩឪឫឬឭឮឯឰឱឲឳ"
KHMER_DEPENDENT_VOWELS = "ាិីឹឺុូួើឿៀេែៃោៅ"
KHMER_DIACRITICS = ["ំ", "ះ", "ៈ", "៉", "៊", "់", "៌", "៍", "៎", "៏", "័", "៑", "្", "៓", "៝"]

VALID_KHMER_STREAM_REGEX = re.compile(r"[^\u1780-\u17ff\u19e0-\u19ff0-9a-zA-Z\s.,;:()/%«»“”\"\'\-?!\n#@+=<>]")

BOILERPLATE_PATTERNS = [
    r"https?://[^\s]+",
    r"[-–—•*]*\s*តេឡេក្រាម\s*[^.។៕\n]*",
    r"[-–—•*]*\s*គេហទំព័រ\s*[^.។៕\n]*",
    r"[-–—•*]*\s*ទិកតុក\s*[^.។៕\n]*",
    r"[-–—•*]*\s*អិច\s*[^.។៕\n]*",
    r"[-–—•*]*\s*យូ\s*ធូប\s*[^.។៕\n]*",
    r"[-–—•*]*\s*យូធូប\s*[^.។៕\n]*",
    r"[-–—•*]*\s*ហ្វេសប៊ុក\s*[^.។៕\n]*",
    r"[-–—•*]*\s*ឆាណែល\s*តេឡេក្រាម\s*[^.។៕\n]*",
    r"[-–—•*]*\s*ទំព័រ\s*ហ្វេសប៊ុក\s*[^.។៕\n]*",
    r"[-–—•*]*\s*បណ្ដាញ\s*សង្គម\s*ផ្លូវការ\s*[^.។៕\n]*",
    r"[-–—•*]*\s*ផ្សាយ\s*បន្ត\s*ដោយ\s*[^.។៕\n]*",
    r"[-–—•*]*\s*ចែករំលែក\s*:\s*[^.។៕\n]*",
    r"[-–—•*]*\s*ចុច\s*Link\s*[^.។៕\n]*",
    r"[-–—•*]*\s*ចុច\s*ទីនេះ\s*[^.។៕\n]*",
    r"[-–—•*]*\s*អាន\s*ព័ត៌មាន\s*បន្ថែម\s*[^.។៕\n]*",
    r"[-–—•*]*\s*ទូរស័ព្ទ\s*លេខ\s*:\s*[\d\s/\-]+",
    r"[-–—•*]*\s*(?:Email|អ៊ីមែល|សារអេឡិចត្រូនិច)\s*:\s*[^\s]+"
]

def clean_khmer_text(text: str) -> str:
    """Cleans, normalizes, and converts ASCII escaped quotes into standard Khmer quotes «...» with zero backslashes."""
    if not text:
        return ""

    # 1. Unescape HTML entities (&quot;, &nbsp;, &mdash;, &amp;, etc.)
    cleaned = html.unescape(text)

    # 2. Strip boilerplate patterns
    for pat in BOILERPLATE_PATTERNS:
        cleaned = re.sub(pat, " ", cleaned, flags=re.IGNORECASE)

    # 3. Clean literal backslashes
    cleaned = re.sub(r"\\+", "", cleaned)

    # 4. Filter corrupted characters
    cleaned = VALID_KHMER_STREAM_REGEX.sub("", cleaned)

    # 5. Convert straight quotes "..." to formal Khmer quotes «...» (eliminates \" in JSON!)
    parts = cleaned.split('"')
    if len(parts) > 1:
        new_parts = []
        for i, part in enumerate(parts):
            if i % 2 == 1:
                new_parts.append(f"«{part}»")
            else:
                new_parts.append(part)
        cleaned = "".join(new_parts)

    # 6. Deduplicate consecutive identical vowels and signs (NOT consonants!)
    all_vowels_and_signs = list(KHMER_DEPENDENT_VOWELS) + KHMER_DIACRITICS
    for d in all_vowels_and_signs:
        cleaned = re.sub(f"{d}+", d, cleaned)

    # 7. Fix common broken words and restore legitimate compound consonants
    cleaned = re.sub(r"ដែ\s*ល", "ដែល", cleaned)
    cleaned = re.sub(r"ក្នុ\s*ង", "ក្នុង", cleaned)
    cleaned = re.sub(r"ឡើ\s*ើង", "ឡើង", cleaned)
    cleaned = re.sub(r"ខ្លួ\s*ន", "ខ្លួន", cleaned)
    cleaned = re.sub(r"ឱ្យ\s*យ", "ឱ្យ", cleaned)
    cleaned = re.sub(r"រដ្ឋឋបាល", "រដ្ឋបាល", cleaned)
    cleaned = re.sub(r"ផ្នែកម្មន្តសាល", "ផ្នែកកម្មន្តសាល", cleaned)
    cleaned = re.sub(r"ផ្នែកម្មសិទ្ធិ", "ផ្នែកកម្មសិទ្ធិ", cleaned)
    cleaned = re.sub(r"(?<![ក-អ])ក្កដា", "កក្កដា", cleaned)
    cleaned = re.sub(r"\u17d2+", "\u17d2", cleaned)

    # 8. Remove download badges (KH, EN, Download, ទាញយក)
    cleaned = re.sub(r"\s+(?:KH|EN|PDF|Download|ទាញយក)$", "", cleaned.strip(), flags=re.IGNORECASE)

    # 9. Format whitespace and remove all newlines
    cleaned = re.sub(r"[\r\n\t]+", " ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)

    # 10. Normalize NFC
    cleaned = unicodedata.normalize("NFC", cleaned).strip()

    # 11. Clean trailing symbols
    cleaned = re.sub(r"\s+([។៕៖ៗ])$", r"\1", cleaned)
    return cleaned

# ==============================================================================
# 4. CHECKPOINT & STORAGE
# ==============================================================================

def load_processed_keys() -> set:
    """Loads all previously crawled article keys."""
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

def save_single_record(record: dict):
    """Saves clean record directly to JSONL file and checkpoint."""
    with open(JSONL_OUTPUT_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    with open(CHECKPOINT_FILE, "a", encoding="utf-8") as f:
        f.write(f"{record['id']}\n")

# ==============================================================================
# 5. FETCHER ENGINE
# ==============================================================================

def fetch_page_article_keys(session, page_num: int) -> list:
    """Fetches article keys from event page in exact visual order."""
    page_url = LIST_URL_PATTERN.format(page=page_num)
    for attempt in range(1, 4):
        try:
            resp = session.get(page_url, timeout=30)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                keys = []
                seen = set()
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    match = re.search(r"/kh/article\?key=([a-zA-Z0-9_-]+)", href)
                    if match:
                        k = match.group(1)
                        if k not in seen and len(k) > 4:
                            seen.add(k)
                            keys.append(k)
                return keys
        except Exception:
            time.sleep(1)
    return []

def fetch_gdt_article(session, article_key: str) -> dict:
    """Fetches and parses a single GDT news article by key, filtering out PDF-only 1-line placeholders."""
    article_url = f"{BASE_URL}/kh/article?key={article_key}"

    for attempt in range(1, 4):
        try:
            resp = session.get(article_url, timeout=30)
            if resp.status_code == 404:
                return {"skip": "Article not found (404)"}
            if resp.status_code != 200:
                time.sleep(0.5)
                continue

            soup = BeautifulSoup(resp.text, "html.parser")

            content_div = soup.find("div", id="content_detail") or soup.find("div", class_="article-container")
            if not content_div:
                return {"skip": "No content container found"}

            raw_text = content_div.get_text(" ", strip=True)

            # Strip headers: អគ្គនាយកដ្ឋានពន្ធដារ, Date header, \d+ថ្ងៃមុន
            cleaned_body = re.sub(r"^អគ្គនាយកដ្ឋានពន្ធដារ\s*", "", raw_text)
            cleaned_body = re.sub(r"^ថ្ងៃ[^\n]+ឆ្នាំ\s*\d{4}\s*", "", cleaned_body)
            cleaned_body = re.sub(r"^\d+\s*(?:ថ្ងៃ|ម៉ោង|នាទី)\s*មុន\s*", "", cleaned_body)
            cleaned_body = clean_khmer_text(cleaned_body)

            # 🛑 SKIP 1-LINE PDF PLACEHOLDERS
            if len(cleaned_body) < 120:
                return {"skip": f"PDF placeholder or too short ({len(cleaned_body)} chars)"}

            khmer_char_count = len(re.findall(r"[\u1780-\u17ff]", cleaned_body))
            if khmer_char_count < 80:
                return {"skip": "Non-Khmer content"}

            # Date
            date_el = soup.find(string=re.compile(r"ថ្ងៃ[^\n]+ខែ[^\n]+ឆ្នាំ"))
            date_str = clean_khmer_text(date_el.strip()) if date_el else ""

            # Title
            title = cleaned_body[:90]
            if "។" in cleaned_body:
                first_sent = cleaned_body.split("។")[0] + "។"
                if 10 <= len(first_sent) <= 150:
                    title = first_sent
                else:
                    title = cleaned_body[:90] + "..."

            if cleaned_body == title:
                return {"skip": "Title identical to body (placeholder banner)"}

            return {
                "id": str(article_key),
                "institution": INSTITUTION_NAME,
                "category": "ពន្ធដារ និងហិរញ្ញវត្ថុ",
                "title": title,
                "date": date_str,
                "url": article_url,
                "text": cleaned_body
            }
        except Exception as e:
            if attempt == 3:
                return {"error": str(e)}
            time.sleep(1.0)

    return {"error": "Connection timed out"}

# ==============================================================================
# 6. MAIN CONTROLLER
# ==============================================================================

def main():
    print("=" * 75)
    print("KHMER LLM DATASET CRAWLER - GDT (អគ្គនាយកដ្ឋានពន្ធដារ / ECONOMY)")
    print("⚡ STRICT QUALITY FILTER: ONLY FULL-TEXT NEWS ARTICLES (PDF PLACEHOLDERS SKIPPED)")
    print("=" * 75)

    processed_keys = load_processed_keys()
    print(f"[CHECKPOINT] Previously processed articles: {len(processed_keys)}")
    print(f"[TARGET] Collecting up to {MAX_ARTICLES} articles starting from Page {START_PAGE}")
    print(f"[OUTPUT] Destination file: {JSONL_OUTPUT_FILE}")
    print("-" * 75)

    session = create_robust_session()

    current_page = START_PAGE
    total_saved = 0
    start_time = time.time()

    while total_saved < MAX_ARTICLES and current_page <= MAX_PAGES:
        print(f"\n⚡ [PAGE {current_page}] Requesting: {LIST_URL_PATTERN.format(page=current_page)} ...")

        try:
            keys = fetch_page_article_keys(session, current_page)
            if not keys:
                print(f"[DONE] No more articles available at page {current_page - 1}.")
                break

            unprocessed_keys = [k for k in keys if k not in processed_keys]
            if not unprocessed_keys:
                print(f"--> Page {current_page}: All {len(keys)} articles already processed.")
                current_page += 1
                continue

            page_saved = 0
            page_start = time.time()

            # Concurrently fetch in pool preserving page order
            with ThreadPoolExecutor(max_workers=NUM_WORKERS) as executor:
                results = list(executor.map(lambda k: (k, fetch_gdt_article(session, k)), unprocessed_keys))

            for k, record in results:
                if str(k) in processed_keys:
                    continue
                if "skip" in record:
                    processed_keys.add(str(k))
                    continue
                if "error" in record:
                    print(f"   [ERROR] (Key: {k}) {record['error']}")
                    continue

                save_single_record(record)
                processed_keys.add(str(k))
                page_saved += 1
                total_saved += 1

                print(f"   [SUCCESS] (Key: {record['id']}) Title: {record['title'][:48]}...")
                print(f"      Details: {len(record['text'])} chars | Date: {record['date']}")

                if total_saved >= MAX_ARTICLES:
                    break

            page_time = round(time.time() - page_start, 2)
            print(f"--> Page {current_page} completed: {page_saved} new articles saved in {page_time}s (Total: {total_saved}/{MAX_ARTICLES})")

            current_page += 1
            time.sleep(REQUEST_DELAY)

        except Exception as e:
            print(f"[ERROR] Error on page {current_page}: {e}")
            time.sleep(2)
            continue

    duration = round(time.time() - start_time, 2)
    print("\n" + "=" * 75)
    print(f"[DONE] Crawl completed: {total_saved} total articles extracted ({duration}s)")
    print(f"[OUTPUT] JSONL dataset: {JSONL_OUTPUT_FILE}")
    print("=" * 75)

if __name__ == "__main__":
    main()
