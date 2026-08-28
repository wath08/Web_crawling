import os
import sys
import time
import json
import io
import re
import urllib.parse
import requests
from bs4 import BeautifulSoup
import pymupdf
from PIL import Image, ImageStat
import unicodedata

# ==============================================================================
# CONFIGURATION
# ==============================================================================ខ

# 1. Main Website Entry URL
MAIN_URL = "https://library.ncdd.gov.kh/"

# 2. Gemini API Key (Optional: used when Vision OCR is required)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY_HERE")

# 3. Run Mode:
#    - TEST_MODE = True  : Crawls and processes up to 5 documents from the main URL
#    - TEST_MODE = False : Crawls and processes all documents across all categories
TEST_MODE = True
TEST_LIMIT = 5

# 4. Directory Structure
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
EXTRACTED_DIR = os.path.join(BASE_DIR, "extracted_texts")
CHECKPOINT_FILE = os.path.join(BASE_DIR, "processed_ids.txt")
ERROR_LOG_FILE = os.path.join(BASE_DIR, "skipped_errors.log")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(EXTRACTED_DIR, exist_ok=True)

# 5. OCR Extraction Prompt for Gemini Flash
GEMINI_OCR_PROMPT = """Extract all the Khmer text from this document image accurately.
- Preserve all titles, articles (មាត្រា), bullet points, and tables in clean Markdown.
- Fix broken Khmer unicode characters and subscripts.
- Do NOT include headers, footers, page numbers, or official stamp marks.
- Output ONLY the extracted clean Khmer text without any conversational reply.
"""

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# ==============================================================================
# GEMINI CLIENT INITIALIZATION
# ==============================================================================

client = None
if GEMINI_API_KEY and GEMINI_API_KEY != "YOUR_GEMINI_API_KEY_HERE":
    try:
        from google import genai
        client = genai.Client(api_key=GEMINI_API_KEY)
        print("[INFO] Connected to Gemini API successfully.")
    except Exception as e:
        print(f"[WARN] Failed to initialize Google GenAI client: {e}")

# ==============================================================================
# KHMER UNICODE NORMALIZER & CLEANER
# ==============================================================================

def clean_khmer_text(text):
    """
    Cleans font artifacts, double-bold characters, and non-standard Khmer encodings.
    """
    if not text:
        return ""

    text = text.replace("\ufffd", "")
    
    # Remove Latin-1 font shadow artifact characters injected by PDF export engines
    junk_chars = set("{}÷þǮÌÚŒƒŽšǝ±Â”ǞæØ‰Đǫ\"\'`~^|\\<>ù")
    cleaned = [ch for ch in text if ch not in junk_chars]
    res = "".join(cleaned)

    # 1. Deduplicate consecutive identical Khmer vowel signs & diacritics
    khmer_diacritics = [
        "\u17b6", "\u17b7", "\u17b8", "\u17b9", "\u17ba", "\u17bb", "\u17bc", "\u17bd",
        "\u17be", "\u17bf", "\u17c0", "\u17c1", "\u17c2", "\u17c3", "\u17c4", "\u17c5",
        "\u17c6", "\u17c7", "\u17c8", "\u17c9", "\u17ca", "\u17cb", "\u17cc", "\u17cd",
        "\u17ce", "\u17cf", "\u17d0", "\u17d1", "\u17d3"
    ]
    for d in khmer_diacritics:
        res = re.sub(f"{d}+", d, res)

    # 2. Deduplicate double Khmer consonants caused by PDF bold rendering
    khmer_consonants = "កខគឃងចឆជឈញដឋឌឍណតថទធនបផពភមយរលវសហឡអ"
    for c in khmer_consonants:
        res = re.sub(f"(?<!\u17d2){c}{{2,}}", c, res)

    # 3. Deduplicate Coeng \u17d2
    res = re.sub(r"\u17d2+", "\u17d2", res)

    # 4. Clean consecutive spaces and newlines
    res = re.sub(r"[ ]{2,}", " ", res)
    res = re.sub(r"\n{3,}", "\n\n", res)
    
    # 5. Unicode NFC normalization
    res = unicodedata.normalize("NFC", res)
    return res.strip()

# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def load_processed_ids():
    processed = set()
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
            processed = set(line.strip() for line in f if line.strip())
    
    if os.path.exists(EXTRACTED_DIR):
        for fname in os.listdir(EXTRACTED_DIR):
            if fname.endswith(".txt"):
                doc_id = fname.replace(".txt", "")
                processed.add(doc_id)
                
    return processed

def mark_id_processed(doc_id):
    with open(CHECKPOINT_FILE, "a", encoding="utf-8") as f:
        f.write(f"{doc_id}\n")

def log_error(doc_id, page_num, reason):
    with open(ERROR_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"ID: {doc_id} | Page: {page_num} | Reason: {reason} | Time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")

def is_page_blank(pil_image, threshold=4.5):
    try:
        gray = pil_image.convert("L")
        stat = ImageStat.Stat(gray)
        return stat.stddev[0] < threshold
    except Exception:
        return False

# ==============================================================================
# STEP 1: CRAWL MAIN WEBSITE TO DISCOVER ALL CATEGORIES & DOCUMENTS
# ==============================================================================

def discover_document_links(main_url, limit=None):
    print(f"[CRAWLER] Connecting to main website: {main_url}")
    try:
        resp = requests.get(main_url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            print(f"[ERROR] Cannot access {main_url} (HTTP {resp.status_code})")
            return []
        
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        print(f"[ERROR] Connection error: {e}")
        return []

    category_links = set()
    detail_links = set()

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        full_url = urllib.parse.urljoin(main_url, href)
        if "category=" in href:
            category_links.add(full_url)
        elif "/detail/" in href:
            detail_links.add(full_url)

    print(f"[CRAWLER] Discovered {len(category_links)} categories from homepage.")

    for cat_url in sorted(category_links):
        if limit and len(detail_links) >= limit:
            break
        print(f"[CRAWLER] Exploring category: {cat_url}")
        try:
            cat_resp = requests.get(cat_url, headers=HEADERS, timeout=15)
            if cat_resp.status_code == 200:
                cat_soup = BeautifulSoup(cat_resp.text, "html.parser")
                for a_tag in cat_soup.find_all("a", href=True):
                    href = a_tag["href"]
                    if "/detail/" in href:
                        detail_links.add(urllib.parse.urljoin(main_url, href))
                        if limit and len(detail_links) >= limit:
                            break
        except Exception as e:
            print(f"[WARN] Error reading category {cat_url}: {e}")

    ordered_links = sorted(list(detail_links), key=lambda x: [int(s) for s in re.findall(r'\d+', x)] or [0], reverse=True)
    return ordered_links[:limit] if limit else ordered_links

# ==============================================================================
# STEP 2: SCRAPE METADATA & DOWNLOAD PDF
# ==============================================================================

def fetch_document_info(detail_url):
    id_match = re.search(r"/detail/(\d+)", detail_url)
    doc_id = id_match.group(1) if id_match else "unknown"

    try:
        response = requests.get(detail_url, headers=HEADERS, timeout=15)
        if response.status_code != 200:
            return None

        soup = BeautifulSoup(response.text, "html.parser")
        
        title_el = soup.find("h4") or soup.find("h3") or soup.find("h2") or soup.find("h1")
        title = title_el.get_text(strip=True) if title_el else ""

        if not title:
            return None

        text_content = soup.get_text()
        doc_type = ""
        year = ""

        type_match = re.search(r"ប្រភេទ\s*[:：]\s*([^\n\r]+)", text_content)
        if type_match:
            doc_type = type_match.group(1).strip()

        year_match = re.search(r"ឆ្នាំ[^\d]*(\d{4})", text_content)
        if year_match:
            year = year_match.group(1).strip()

        pdf_url = None
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if ".pdf" in href.lower() or "download" in href.lower():
                pdf_url = urllib.parse.urljoin(detail_url, href)
                break

        return {
            "id": str(doc_id),
            "url": detail_url,
            "title": title,
            "category": doc_type,
            "year": year,
            "pdf_url": pdf_url
        }

    except Exception as e:
        return None

def download_pdf_file(pdf_url, save_path):
    try:
        response = requests.get(pdf_url, headers=HEADERS, timeout=30, stream=True)
        if response.status_code == 200:
            with open(save_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
        return False
    except Exception as e:
        return False

# ==============================================================================
# STEP 3: GEMINI OCR FALLBACK
# ==============================================================================

def extract_text_via_gemini(pil_image, doc_id, page_num, max_retries=2):
    if not client:
        return ""

    for attempt in range(1, max_retries + 1):
        try:
            img_byte_arr = io.BytesIO()
            pil_image.save(img_byte_arr, format='JPEG', quality=90)
            img_bytes = img_byte_arr.getvalue()

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    GEMINI_OCR_PROMPT,
                    {"mime_type": "image/jpeg", "data": img_bytes}
                ]
            )

            text_result = response.text.strip() if response.text else ""
            return text_result

        except Exception as e:
            err_msg = str(e)
            print(f"      [WARN] [Page {page_num}] Attempt {attempt}/{max_retries} failed: {err_msg[:60]}...")

            if attempt < max_retries:
                print("      [PAUSE] Pausing 60 seconds before retry...")
                time.sleep(60)
            else:
                print(f"      [SKIP] [Page {page_num}] Failed twice. Skipping to save tokens.")
                log_error(doc_id, page_num, f"Gemini failed twice: {err_msg}")
                return ""

    return ""

# ==============================================================================
# STEP 4: SMART HYBRID PDF EXTRACTION WITH AUTOMATIC NORMALIZER
# ==============================================================================

def process_pdf_document(pdf_path, doc_info):
    doc_id = doc_info["id"]
    output_txt_path = os.path.join(EXTRACTED_DIR, f"{doc_id}.txt")

    try:
        pdf_doc = pymupdf.open(pdf_path)
    except Exception as e:
        print(f"   [ERROR] Cannot open PDF file: {e}")
        log_error(doc_id, 0, "Corrupted PDF file")
        return False

    total_pages = len(pdf_doc)
    print(f"   [INFO] Total pages: {total_pages}")

    extracted_pages = []

    for page_idx in range(total_pages):
        page_num = page_idx + 1
        page = pdf_doc[page_idx]

        # 1. Try extracting and cleaning digital text
        raw_text = page.get_text().strip()
        cleaned_text = clean_khmer_text(raw_text)
        khmer_chars = [c for c in cleaned_text if '\u1780' <= c <= '\u17FF']

        if len(khmer_chars) >= 25:
            print(f"      [DIRECT CLEAN] [Page {page_num}/{total_pages}] Extracted & normalized clean Khmer text ({len(khmer_chars)} chars).")
            extracted_pages.append(cleaned_text)
            continue

        # 2. Render page to image
        pix = page.get_pixmap(dpi=150)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        # 3. Check for blank page
        if is_page_blank(img):
            print(f"      [BLANK] [Page {page_num}/{total_pages}] Blank page -> Skipped.")
            continue

        # 4. OCR fallback
        if client:
            print(f"      [OCR] [Page {page_num}/{total_pages}] Scanned image -> Transcribing with Gemini Flash...")
            ocr_text = extract_text_via_gemini(img, doc_id, page_num, max_retries=2)
            if ocr_text:
                extracted_pages.append(ocr_text)
                print(f"      [SUCCESS] [Page {page_num}/{total_pages}] Clean text extracted ({len(ocr_text)} chars).")
        else:
            print(f"      [SKIP] [Page {page_num}/{total_pages}] Scanned image (Gemini API key not set).")
        
        time.sleep(1)

    pdf_doc.close()

    # Save to individual extracted_texts/{doc_id}.txt
    if extracted_pages:
        combined_text = "\n\n".join(extracted_pages)
        
        doc_content = (
            f"======================================================================\n"
            f"Document ID : {doc_id}\n"
            f"Title       : {doc_info.get('title', '')}\n"
            f"Category    : {doc_info.get('category', '')}\n"
            f"Year        : {doc_info.get('year', '')}\n"
            f"Source URL  : {doc_info.get('url', '')}\n"
            f"======================================================================\n\n"
            f"Content:\n\n"
            f"{combined_text}\n"
        )

        with open(output_txt_path, "w", encoding="utf-8") as f_out:
            f_out.write(doc_content)

        print(f"   [SAVED] Saved clean file: extracted_texts/{doc_id}.txt ({len(combined_text)} characters)")
        mark_id_processed(doc_id)
        return True
    else:
        print(f"   [WARN] No text extracted for ID {doc_id}")
        mark_id_processed(doc_id)
        return False

# ==============================================================================
# MAIN PIPELINE CONTROLLER
# ==============================================================================

def main():
    print("=" * 75)
    print("KHMER LLM DATA INGESTION PIPELINE (NCDD LIBRARY)")
    print(f"Target Main Website: {MAIN_URL}")
    print("=" * 75)

    processed_ids = load_processed_ids()
    print(f"[CHECKPOINT] Previously processed documents: {len(processed_ids)}")

    limit = TEST_LIMIT if TEST_MODE else None
    print(f"[START] Discovering documents starting from {MAIN_URL}...")
    document_links = discover_document_links(MAIN_URL, limit=limit)

    target_links = []
    for link in document_links:
        id_match = re.search(r"/detail/(\d+)", link)
        doc_id = id_match.group(1) if id_match else None
        if doc_id and doc_id not in processed_ids:
            target_links.append(link)

    print(f"[FOUND] Found {len(target_links)} new documents to process.")
    print(f"[OUTPUT] Text files will be saved in: {EXTRACTED_DIR}/")
    print("-" * 75)

    success_count = 0
    for idx, detail_url in enumerate(target_links, 1):
        print(f"\n[{idx}/{len(target_links)}] Fetching: {detail_url}")

        doc_info = fetch_document_info(detail_url)
        if not doc_info:
            print(f"   [SKIP] Failed to parse document at {detail_url}")
            continue

        doc_id = doc_info["id"]
        print(f"   [TITLE] {doc_info['title'][:70]}...")
        print(f"   [META] Category: {doc_info['category'] or 'N/A'} | Year: {doc_info['year'] or 'N/A'}")

        if not doc_info.get("pdf_url"):
            print(f"   [SKIP] No PDF download link found for ID {doc_id}")
            mark_id_processed(doc_id)
            continue

        pdf_filename = f"{doc_id}.pdf"
        pdf_path = os.path.join(DOWNLOAD_DIR, pdf_filename)

        if not os.path.exists(pdf_path):
            print(f"   [DOWNLOAD] Downloading PDF from: {doc_info['pdf_url']}...")
            dl_ok = download_pdf_file(doc_info["pdf_url"], pdf_path)
            if not dl_ok:
                print(f"   [ERROR] Failed to download PDF. Skipping.")
                log_error(doc_id, 0, "PDF Download Failed")
                mark_id_processed(doc_id)
                continue
            print(f"   [OK] Downloaded: downloads/{pdf_filename}")
        else:
            print(f"   [EXISTING] Local PDF already exists: downloads/{pdf_filename}")

        is_success = process_pdf_document(pdf_path, doc_info)
        if is_success:
            success_count += 1

        print("-" * 75)

    print("\n" + "=" * 75)
    print(f"Completed! Successfully processed: {success_count} documents.")
    print(f"All clean text files stored in: {EXTRACTED_DIR}/")
    print("=" * 75)

if __name__ == "__main__":
    main()