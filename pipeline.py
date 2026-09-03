import os
import sys
import time
import json
import re
import html
import glob
import unicodedata
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# ==============================================================================
# 1. GOVERNMENT CRAWLER CONFIGURATION (MEF - ក្រសួងសេដ្ឋកិច្ច និងហិរញ្ញវត្ថុ / MINISTRIES)
# ==============================================================================

INSTITUTION_NAME = "ក្រសួងសេដ្ឋកិច្ច និងហិរញ្ញវត្ថុ"
BASE_URL = "https://mef.gov.kh"
LIST_URL_PATTERN = "https://mef.gov.kh/news/page/{page}/"

# Start Page (1 = អត្ថបទថ្មីបំផុត ខែកញ្ញា ឆ្នាំ២០២៦)
START_PAGE = 1

# ⚡ កំណត់ទាញយកម្ដង 50 ទំព័រក្នុង ១ ជុំ (50 Pages = 500 អត្ថបទក្នុង ១ ជុំ)
PAGES_PER_RUN = 50

# ចំនួនទំព័រអតិបរមា (72 ទំព័រ = ~720 អត្ថបទម៉ាក្រូសេដ្ឋកិច្ចលើ MEF)
MAX_PAGES = 72

# ចំនួនអត្ថបទដែលត្រូវប្រមូល (1000 អត្ថបទ គ្របដណ្ដប់គ្រប់អត្ថបទទាំងអស់)
MAX_ARTICLES = 10

# រយៈពេលរង់ចាំរវាងអត្ថបទ (០.២ វិនាទី)
REQUEST_DELAY = 0.2

# ==============================================================================
# 2. DIRECTORY SETTINGS (MINISTRIES FOLDER)
# ==============================================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_ROOT_DIR = os.path.join(BASE_DIR, "KhmerLLM-Dataset")
GOV_MINISTRIES_DIR = os.path.join(DATASET_ROOT_DIR, "04_government", "ministries")
RECORD_DIR = os.path.join(BASE_DIR, "record")

os.makedirs(RECORD_DIR, exist_ok=True)
os.makedirs(GOV_MINISTRIES_DIR, exist_ok=True)

CHECKPOINT_FILE = os.path.join(RECORD_DIR, "processed_urls_mef.txt")
ERROR_LOG_FILE = os.path.join(RECORD_DIR, "skipped_errors_mef.log")
JSONL_OUTPUT_FILE = os.path.join(GOV_MINISTRIES_DIR, "gov_mef.jsonl")

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

    # 1. Unescape HTML entities
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

def load_processed_urls() -> set:
    """Loads all previously crawled article URLs."""
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
                        if "url" in item:
                            processed.add(str(item["url"]))
        except Exception:
            pass

    return processed

def save_single_record(record: dict):
    """Saves clean record directly to JSONL file and checkpoint."""
    with open(JSONL_OUTPUT_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    with open(CHECKPOINT_FILE, "a", encoding="utf-8") as f:
        f.write(f"{record['url']}\n")

# ==============================================================================
# 5. FETCHER ENGINE
# ==============================================================================

def wait_for_cloudflare(page, max_wait=15):
    """Waits until Cloudflare verification completes."""
    for _ in range(max_wait):
        t = page.title()
        if "Just a moment" not in t and "mef.gov.kh" not in t and "Security" not in t and "verification" not in t.lower():
            return True
        time.sleep(1.0)
    return False

def fetch_mef_article(page, article_url: str) -> dict:
    """Fetches and parses a single MEF news article using the browser session."""
    for attempt in range(1, 4):
        try:
            page.goto(article_url, wait_until="domcontentloaded", timeout=25000)
            wait_for_cloudflare(page, max_wait=10)
            time.sleep(1.0)

            html_content = page.content()
            soup = BeautifulSoup(html_content, "html.parser")

            # 1. Extract Title
            title_clean = ""
            breadcrumb = soup.find("div", class_="breadcrumbs")
            if breadcrumb:
                b_text = breadcrumb.get_text(strip=True)
                if "›" in b_text:
                    title_clean = b_text.split("›")[-1].strip()

            if not title_clean:
                h_el = soup.find("h2") or soup.find("h1")
                if h_el and "ព័ត៌មាន" not in h_el.get_text(strip=True):
                    title_clean = h_el.get_text(strip=True)

            title_clean = clean_khmer_text(title_clean)
            if not title_clean:
                title_clean = "ព័ត៌មានក្រសួងសេដ្ឋកិច្ច និងហិរញ្ញវត្ថុ"

            # 2. Extract Date
            date_el = soup.find(string=re.compile(r"\d+\s*(?:មករា|កុម្ភៈ|មីនា|មេសា|ឧសភា|មិថុនា|កក្កដា|សីហា|កញ្ញា|តុលា|វិច្ឆិកា|ធ្នូ)\s*\d{4}"))
            date_str = clean_khmer_text(date_el.strip()) if date_el else ""

            # 3. Extract Body Content
            body_div = soup.find("div", class_=lambda c: c and any(k in c for k in ["entry-content", "post-content", "article-content", "single-content", "main-content"]))
            if not body_div:
                body_div = soup

            # Remove navigation, headers, scripts
            for unwanted in body_div.find_all(["script", "style", "nav", "header", "footer"]):
                unwanted.decompose()

            ps = body_div.find_all("p")
            raw_text = " ".join(p.get_text(" ", strip=True) for p in ps if len(p.get_text(strip=True)) > 20) if ps else body_div.get_text(" ", strip=True)
            content_clean = clean_khmer_text(raw_text)

            if len(content_clean) < 120:
                return {"skip": f"Content too short ({len(content_clean)} chars)"}

            khmer_char_count = len(re.findall(r"[\u1780-\u17ff]", content_clean))
            if khmer_char_count < 80:
                return {"skip": "Non-Khmer document"}

            # Derive ID from URL slug
            slug = article_url.strip("/").split("/")[-1]

            return {
                "id": slug,
                "institution": INSTITUTION_NAME,
                "category": "សេដ្ឋកិច្ច និងហិរញ្ញវត្ថុ",
                "title": title_clean,
                "date": date_str,
                "url": article_url,
                "text": content_clean
            }
        except Exception as e:
            if attempt == 3:
                return {"error": str(e)}
            time.sleep(1.0)

    return {"error": "Connection timed out"}

# ==============================================================================
# 6. MAIN CONTROLLER
# ==============================================================================

def cleanup_stale_locks(profile_dir: str):
    """Safely cleans up stale lock files from previous runs."""
    if os.path.exists(profile_dir):
        for lock in glob.glob(os.path.join(profile_dir, "*Lock*")):
            try:
                os.remove(lock)
            except Exception:
                pass

def main():
    print("=" * 75)
    print("KHMER LLM DATASET CRAWLER - MEF (ក្រសួងសេដ្ឋកិច្ច និងហិរញ្ញវត្ថុ / MINISTRIES)")
    print("⚡ DIRECT REAL-TIME STREAMING (UP TO 50 PAGES PER RUN)")
    print("=" * 75)

    processed_urls = load_processed_urls()
    print(f"[CHECKPOINT] Previously processed articles: {len(processed_urls)}")
    print(f"[TARGET] Collecting up to {MAX_ARTICLES} articles starting from Page {START_PAGE}")
    print(f"[OUTPUT] Destination file: {JSONL_OUTPUT_FILE}")
    print("-" * 75)

    user_data_dir = os.path.expanduser("~/.cache/playwright_mef_profile")
    cleanup_stale_locks(user_data_dir)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            channel="chrome",
            headless=True,
            viewport={"width": 1280, "height": 800},
            args=["--disable-blink-features=AutomationControlled"]
        )
        page = context.new_page()

        current_page = START_PAGE
        total_saved = 0
        start_time = time.time()

        while total_saved < MAX_ARTICLES and current_page <= MAX_PAGES:
            list_url = f"{BASE_URL}/news/" if current_page == 1 else LIST_URL_PATTERN.format(page=current_page)
            print(f"\n⚡ [PAGE {current_page}/{MAX_PAGES}] Requesting: {list_url} ...")

            try:
                page.goto(list_url, wait_until="domcontentloaded", timeout=25000)
                wait_for_cloudflare(page, max_wait=12)
                time.sleep(1.0)

                soup_list = BeautifulSoup(page.content(), "html.parser")
                article_links = []
                seen = set()
                for a in soup_list.find_all("a", href=True):
                    h = a["href"]
                    if "/news/" in h and h != f"{BASE_URL}/news/" and not re.search(r"/page/\d+/?", h):
                        if h not in processed_urls and h not in seen:
                            seen.add(h)
                            article_links.append(h)

                if not article_links:
                    print(f"[DONE] No new articles found on page {current_page}.")
                    current_page += 1
                    continue

                print(f"   -> Found {len(article_links)} new articles on Page {current_page}. Downloading now...")
                page_saved = 0
                page_start = time.time()

                for art_url in article_links:
                    record = fetch_mef_article(page, art_url)
                    if "skip" in record:
                        processed_urls.add(art_url)
                        continue
                    if "error" in record:
                        print(f"   [ERROR] ({art_url}) {record['error']}")
                        continue

                    save_single_record(record)
                    processed_urls.add(art_url)
                    page_saved += 1
                    total_saved += 1

                    print(f"   [SUCCESS] Title: {record['title'][:48]}...")
                    print(f"      Details: {len(record['text'])} chars | Date: {record['date']}")

                    if total_saved >= MAX_ARTICLES:
                        break

                    time.sleep(REQUEST_DELAY)

                page_time = round(time.time() - page_start, 2)
                print(f"--> Page {current_page} completed: {page_saved} new articles saved in {page_time}s (Total: {total_saved}/{MAX_ARTICLES})")

                current_page += 1

            except Exception as e:
                print(f"[ERROR] Error on page {current_page}: {e}")
                time.sleep(2)
                continue

        context.close()

    duration = round(time.time() - start_time, 2)
    print("\n" + "=" * 75)
    print(f"[DONE] Crawl completed: {total_saved} total articles extracted ({duration}s)")
    print(f"[OUTPUT] JSONL dataset: {JSONL_OUTPUT_FILE}")
    print("=" * 75)

if __name__ == "__main__":
    main()
