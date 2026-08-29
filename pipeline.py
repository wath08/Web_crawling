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



#  1. SET YOUR TARGET URL / SPECIFIC FILE HERE

# Option A: Paste a single specific detail URL link to test directly:
TARGET_URL = "https://library.ncdd.gov.kh/detail/17235"

# Option B: Put specific document IDs to test (e.g. [17235, 17236]):
SPECIFIC_IDS = []

# Option C: Crawl starting from Main Website Homepage
MAIN_URL = "https://library.ncdd.gov.kh/"

# Run Mode when crawling from MAIN_URL
TEST_MODE = True
TEST_LIMIT = 1

# Gemini API Key (Loaded automatically from .env or system environment)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY_HERE")
if os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")):
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"), "r", encoding="utf-8") as f_env:
        for line in f_env:
            if line.strip().startswith("GEMINI_API_KEY="):
                GEMINI_API_KEY = line.strip().split("=", 1)[1].strip("\"' ")

# ==============================================================================
# DIRECTORY SETTINGS
# ==============================================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
EXTRACTED_DIR = os.path.join(BASE_DIR, "extracted_texts")
CHECKPOINT_FILE = os.path.join(BASE_DIR, "processed_ids.txt")
ERROR_LOG_FILE = os.path.join(BASE_DIR, "skipped_errors.log")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(EXTRACTED_DIR, exist_ok=True)

# ==============================================================================
# COMPLETE KHMER UNICODE CHARACTER SET & INDICES (U+1780 - U+17FF & U+19E0 - U+19FF)
# ==============================================================================

# 1. (Khmer Consonants: 33 letters)
KHMER_CONSONANTS = "កខគឃងចឆជឈញដឋឌឍណតថទធនបផពភមយរលវសហឡអ"

# 2.  (Khmer Independent Vowels)
KHMER_INDEPENDENT_VOWELS = "ឣឤឥឦឧឨឩឪឫឬឭឮឯឰឱឲឳ"

# 3. (Khmer Dependent Vowel Signs)
KHMER_DEPENDENT_VOWELS = "ាិីឹឺុូួើឿៀេែៃោៅ"

KHMER_DIACRITICS = [
    "ំ",   # Nikkahit (និគ្គហិត)
    "ះ",   # Reahmukh (រះមុខ)
    "ៈ",   # Yuukaleapintu (យុគលពិន្ទុ)
    "៉",   # Muusikoatoan (មូសិកទន្ត/ធ្មេញកណ្តុរ)
    "៊",   # Triisap (ត្រីស័ព្ទ)
    "់",   # Bantoc (បន្តក់)
    "៌",   # Robat (របាទ)
    "៍",   # Toandakhiat (ទណ្ឌឃាត)
    "៎",   # Kakabat (កាកបាទ)
    "៏",   # Ahsda (អស្តា)
    "័",   # Samyok Sannya (សំយោគសញ្ញា)
    "៑",   # Viriam (វិរាម)
    "្",   # Sign Coeng (ជើងអក្សរ)
    "៓",   # Bathamasat (បឋមាសាឍ)
    "៝",   # Atirek (អតិរេកសញ្ញា)
]

# 5. (Khmer Digits: 0-9)
KHMER_DIGITS = "០១២៣៤៥៦៧៨៩"

# 6. (Khmer Punctuation & Symbols)
KHMER_SYMBOLS = "។៕៖ៗ៘៙៚៛ៜ៝"

# 7.  (Universal Punctuation & Quotes)
UNIVERSAL_PUNCTUATION = "«»“”‘’()[]{}<>%‰$+-=/*_.,:;?!~\"'#@ "

# 8.  (Complete Valid Characters)
ALL_KHMER_CHARS = (
    KHMER_CONSONANTS
    + KHMER_INDEPENDENT_VOWELS
    + KHMER_DEPENDENT_VOWELS
    + "".join(KHMER_DIACRITICS)
    + KHMER_DIGITS
    + KHMER_SYMBOLS
    + UNIVERSAL_PUNCTUATION
)

# Legacy non-Unicode shadow/font artifact glyphs to strip
LEGACY_JUNK_CHARS = set("{}÷þǮÌÚŒƒŽšǝ±Â”ǞæØ‰Đǫ`^|\\ù\ufffd")

GEMINI_OCR_PROMPT = """Extract and transcribe all the text from this document image with 100% strict fidelity and accuracy.
- Transcribe EXACTLY word-for-word as written in the original document. Do NOT summarize, rephrase, interpret, or add any extra words.
- Preserve all structural formatting, titles, legal articles (មាត្រា), bullet points, and tables in clean Markdown.
- Ensure correct Khmer Unicode characters, vowel ordering, and subscripts (ជើងអក្សរ).
- Do NOT include repetitive running headers, running footers, page numbers (e.g. ទំព័រ ១/៤), or circular ink stamp texts.
- Output ONLY the verbatim extracted clean text without any introductory or concluding conversational reply.
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
else:
    print("\n" + "!" * 75)
    print("[WARNING] GEMINI_API_KEY is not set or empty!")
    print("[WARNING] To get your 100% FREE Gemini API Key, please visit:")
    print("          👉 https://aistudio.google.com/api-keys")
    print("[INFO] Falling back to free local Khmer OCR (Tesseract) for scanned pages.")
    print("!" * 75 + "\n")

# ==============================================================================
# COMPREHENSIVE KHMER UNICODE NORMALIZER & CLEANER
# ==============================================================================

VALID_KHMER_STREAM_REGEX = re.compile(r"[^\u1780-\u17ff\u19e0-\u19ff0-9a-zA-Z\s.,;:()/%«»“”\"\'\-?!\n#@+=<>]")

def clean_khmer_text(text):
    if not text:
        return ""

    # 1. Strip all non-Khmer Western Latin-1 shadow font junk glyphs (InDesign artifacts)
    cleaned = VALID_KHMER_STREAM_REGEX.sub("", text)

    # 2. Merge broken mid-word linebreaks (Khmer word split across newlines)
    cleaned = re.sub(r"([\u1780-\u17d3])\n([\u1780-\u17d3])", r"\1\2", cleaned)

    # 3. Deduplicate Khmer vowels and diacritics
    all_vowels_and_signs = list(KHMER_DEPENDENT_VOWELS) + KHMER_DIACRITICS
    for d in all_vowels_and_signs:
        cleaned = re.sub(f"{d}+", d, cleaned)

    # 4. Deduplicate repeated bold consonants (when not preceded by Coeng \u17d2)
    for c in KHMER_CONSONANTS:
        cleaned = re.sub(f"(?<!\u17d2){c}{{2,}}", c, cleaned)

    # 5. Fix common Adobe InDesign broken ligature & typography artifacts
    cleaned = re.sub(r"ក្រោ្រោម|ក្រោប្រោម", "ក្រោម", cleaned)
    cleaned = re.sub(r"ដែ\s*ល", "ដែល", cleaned)
    cleaned = re.sub(r"អ្ន\s*នក|អ្ននក", "អ្នក", cleaned)
    cleaned = re.sub(r"ប្រព័ន្ធធ", "ប្រព័ន្ធ", cleaned)
    cleaned = re.sub(r"ឡើ\s*ើង", "ឡើង", cleaned)
    cleaned = re.sub(r"ក្នុ\s*ង", "ក្នុង", cleaned)
    cleaned = re.sub(r"ខ្លួ\s*ន", "ខ្លួន", cleaned)
    cleaned = re.sub(r"ផែ\s*នការ", "ផែនការ", cleaned)
    cleaned = re.sub(r"ផ្សេ\s*ង", "ផ្សេង", cleaned)
    cleaned = re.sub(r"បន្ថែ\s*ម", "បន្ថែម", cleaned)
    cleaned = re.sub(r"ផ្អែ\s*ក", "ផ្អែក", cleaned)
    cleaned = re.sub(r"ចាប់ផ្តើ\s*ម", "ចាប់ផ្តើម", cleaned)
    cleaned = re.sub(r"កាត់បន្ថ\s*យ", "កាត់បន្ថយ", cleaned)
    cleaned = re.sub(r"ឆ្លើ\s*ើយ", "ឆ្លើយ", cleaned)
    cleaned = re.sub(r"ឱ្យ\s*យ", "ឱ្យ", cleaned)
    cleaned = re.sub(r"ជួប្រទះ", "ជួបប្រទះ", cleaned)
    cleaned = re.sub(r"រដ្ឋឋបាល", "រដ្ឋបាល", cleaned)
    cleaned = re.sub(r"សន្ទទស្សសន៍", "សន្ទស្សន៍", cleaned)
    cleaned = re.sub(r"សីតុណ្ហហភាព", "សីតុណ្ហភាព", cleaned)
    cleaned = re.sub(r"ខ្យយល់", "ខ្យល់", cleaned)
    cleaned = re.sub(r"អារម្មមណ៍", "អារម្មណ៍", cleaned)
    cleaned = re.sub(r"ខ្ពពស់", "ខ្ពស់", cleaned)
    cleaned = re.sub(r"បន្តត", "បន្ត", cleaned)
    cleaned = re.sub(r"ទួល", "ទទួល", cleaned)
    cleaned = re.sub(r"សង្ខ\s*ខេប", "សង្ខេប", cleaned)
    cleaned = re.sub(r"ក្ន\s*ង", "ក្នុង", cleaned)

    cleaned = re.sub(r"\u17d2+", "\u17d2", cleaned)
    cleaned = re.sub(r"[ ]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    
    return unicodedata.normalize("NFC", cleaned).strip()

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
# CRAWLER & DOWNLOADER
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
# OCR ENGINES (GEMINI FLASH VISION & LOCAL TESSERACT KHMER)
# ==============================================================================

def extract_text_via_gemini(pil_image, doc_id, page_num, max_retries=2):
    if not client:
        print(f"      [WARNING] [Page {page_num}] Gemini API Key is missing or empty!")
        print(f"      [SKIP] [Page {page_num}] Cannot transcribe scanned image without Gemini API Key.")
        log_error(doc_id, page_num, "Gemini API Key Missing - visit https://aistudio.google.com/api-keys")
        return ""

    for attempt in range(1, max_retries + 1):
        try:
            from google.genai import types
            img_byte_arr = io.BytesIO()
            pil_image.save(img_byte_arr, format='JPEG', quality=90)
            img_bytes = img_byte_arr.getvalue()
            
            image_part = types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")

            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=[
                    GEMINI_OCR_PROMPT,
                    image_part
                ]
            )

            text_result = response.text.strip() if response.text else ""
            return text_result

        except Exception as e:
            err_msg = str(e)
            print(f"      [WARN] [Page {page_num}] Attempt {attempt}/{max_retries} failed: {err_msg[:80]}...")

            if attempt < max_retries:
                print("      [PAUSE] Pausing 5 seconds before retry...")
                time.sleep(5)
            else:
                print(f"      [SKIP] [Page {page_num}] Failed twice. Skipping to save tokens.")
                log_error(doc_id, page_num, f"Gemini failed twice: {err_msg}")
                return ""

    return ""

# ==============================================================================
# PROCESS DOCUMENT AND SAVE
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

        # 1. Check for digital selectable text
        raw_text = page.get_text().strip()
        cleaned_text = clean_khmer_text(raw_text)
        khmer_chars = [c for c in cleaned_text if c in ALL_KHMER_CHARS]

        if len(khmer_chars) >= 25:
            print(f"      [TYPE: DIGITAL PDF] [Page {page_num}/{total_pages}] Extracted selectable text via PyMuPDF ({len(khmer_chars)} chars).")
            extracted_pages.append(cleaned_text)
            continue

        # 2. Render page to image (Scanned Page)
        print(f"      [TYPE: SCANNED PDF] [Page {page_num}/{total_pages}] Detected scanned image/photo page.")
        pix = page.get_pixmap(dpi=200)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        # 3. Check for blank page
        if is_page_blank(img):
            print(f"      [BLANK PAGE] [Page {page_num}/{total_pages}] Blank paper detected -> Skipped to save quota.")
            continue

        # 4. OCR Processing via Gemini Vision
        ocr_text = ""
        if client:
            print(f"      [GEMINI FLASH] [Page {page_num}/{total_pages}] Reading scanned image with Gemini Vision AI...")
            ocr_text = extract_text_via_gemini(img, doc_id, page_num, max_retries=2)
        else:
            print(f"      [WARNING] [Page {page_num}/{total_pages}] Scanned image requires Gemini API Key!")
            print(f"      👉 Please get your FREE Gemini API Key from: https://aistudio.google.com/api-keys")
            print(f"      [SKIP] [Page {page_num}/{total_pages}] Page skipped due to missing API Key.")
            log_error(doc_id, page_num, "Missing Gemini API Key - Get key at https://aistudio.google.com/api-keys")

        if ocr_text:
            cleaned_ocr = clean_khmer_text(ocr_text)
            extracted_pages.append(cleaned_ocr)
            print(f"      [SUCCESS] [Page {page_num}/{total_pages}] Clean text extracted ({len(cleaned_ocr)} chars).")
        else:
            print(f"      [WARN] [Page {page_num}/{total_pages}] No text extracted.")
        
        time.sleep(0.5)

    pdf_doc.close()

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
    print("=" * 75)

    processed_ids = load_processed_ids()
    print(f"[CHECKPOINT] Previously processed documents: {len(processed_ids)}")

    # 1. Single target URL provided
    if TARGET_URL and TARGET_URL.strip():
        full_target = urllib.parse.urljoin(MAIN_URL, TARGET_URL.strip())
        print(f"[TARGET URL] Processing single target link: {full_target}")
        target_links = [full_target]
    # 2. Specific IDs configured
    elif SPECIFIC_IDS:
        print(f"[TARGET IDS] Processing {len(SPECIFIC_IDS)} specific document IDs: {SPECIFIC_IDS}")
        target_links = [urllib.parse.urljoin(MAIN_URL, f"detail/{doc_id}") for doc_id in SPECIFIC_IDS]
    # 3. Automatic crawl from main website
    else:
        limit = TEST_LIMIT if TEST_MODE else None
        print(f"[START] Discovering documents starting from {MAIN_URL}...")
        document_links = discover_document_links(MAIN_URL, limit=limit)
        target_links = []
        for link in document_links:
            id_match = re.search(r"/detail/(\d+)", link)
            doc_id = id_match.group(1) if id_match else None
            if doc_id and doc_id not in processed_ids:
                target_links.append(link)

    print(f"[FOUND] Found {len(target_links)} documents to process.")
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