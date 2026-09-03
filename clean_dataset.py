import os
import sys
import json
import re
import html
import unicodedata

# ==============================================================================
# 🎯 1. FILE & DIRECTORY CONFIGURATION
# ==============================================================================
TARGET_FILE = "economy_gdt.jsonl"
CLEANED_ROOT_DIR = "cleaned_data"

# ==============================================================================
# 2. ADVANCED BOILERPLATE & JUNK FILTER PATTERNS
# ==============================================================================

KHMER_DEPENDENT_VOWELS = "ាិីឹឺុូួើឿៀេែៃោៅ"
KHMER_DIACRITICS = ["ំ", "ះ", "ៈ", "៉", "៊", "់", "៌", "៍", "៎", "៏", "័", "៑", "្", "៓", "៝"]

VALID_KHMER_STREAM_REGEX = re.compile(r"[^\u1780-\u17ff\u19e0-\u19ff0-9a-zA-Z\s.,;:()/%«»“”\"\'\-?!\n#@+=<>]")

# Social media and boilerplate patterns to remove
BOILERPLATE_PATTERNS = [
    # 1. Remove all Web URLs
    r"https?://[^\s]+",
    r"www\.[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}[^\s]*",
    
    # 2. Social channels and keywords
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
    r"[-–—•*]*\s*រូបភាព\s*:\s*[^.។៕\n]*",
    r"[-–—•*]*\s*ប្រភព\s*:\s*[^.។៕\n]*",
    r"[-–—•*]*\s*ទូរស័ព្ទ\s*លេខ\s*:\s*[\d\s/\-]+",
    r"[-–—•*]*\s*(?:Email|អ៊ីមែល|សារអេឡិចត្រូនិច)\s*:\s*[^\s]+"
]

def clean_text(text: str) -> str:
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

def get_target_cleaned_path(input_file_path: str, cleaned_base_dir: str) -> str:
    """Computes direct clean path like cleaned_data/economy/economy_gdt.jsonl"""
    parent_folder_name = os.path.basename(os.path.dirname(input_file_path))
    file_name = os.path.basename(input_file_path)
    return os.path.join(cleaned_base_dir, parent_folder_name, file_name)

def clean_single_file(input_file_path: str, cleaned_base_dir: str):
    """Sanitizes input JSONL file, filters out PDF/empty placeholders, and saves to cleaned_data/<category>/<file_name>."""
    if not os.path.exists(input_file_path):
        print(f"[ERROR] File not found: {input_file_path}")
        return

    output_file_path = get_target_cleaned_path(input_file_path, cleaned_base_dir)
    os.makedirs(os.path.dirname(output_file_path), exist_ok=True)

    print(f"[CLEANING] Input Raw: {input_file_path}")
    print(f"   -> Output Clean File: {output_file_path}")

    cleaned_count = 0
    skipped_count = 0

    with open(input_file_path, "r", encoding="utf-8") as f_in, open(output_file_path, "w", encoding="utf-8") as f_out:
        for line in f_in:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                raw_text = item.get("text", "")
                raw_title = item.get("title", "")

                cleaned_text = clean_text(raw_text)
                cleaned_title = clean_text(raw_title)

                # 🛑 FILTER OUT PDF / 1-LINE PLACEHOLDER DOCUMENTS
                # 1. Skip if text is too short (< 120 chars)
                if len(cleaned_text) < 120:
                    skipped_count += 1
                    continue

                # 2. Skip if text is identical to title (PDF banner without body paragraph)
                if cleaned_text == cleaned_title:
                    skipped_count += 1
                    continue

                # 3. Check Khmer character density
                khmer_char_count = len(re.findall(r"[\u1780-\u17ff]", cleaned_text))
                if khmer_char_count < 80:
                    skipped_count += 1
                    continue

                item["text"] = cleaned_text
                item["title"] = cleaned_title

                f_out.write(json.dumps(item, ensure_ascii=False) + "\n")
                cleaned_count += 1
            except Exception as e:
                skipped_count += 1

    file_size_mb = round(os.path.getsize(output_file_path) / (1024 * 1024), 2)
    print(f"   -> ✅ Cleaned: {cleaned_count} high-quality articles | 🚫 Filtered {skipped_count} PDF placeholders | Size: {file_size_mb} MB\n")

def find_target_file(base_dir: str, target_name: str):
    """Finds the absolute path of a target file inside the dataset directory."""
    for root, dirs, files in os.walk(base_dir):
        if target_name in files:
            return os.path.join(root, target_name)
    return None

def main():
    print("=" * 75)
    print("KHMER LLM DATASET SANITIZER (PDF PLACEHOLDER FILTER ENABLED)")
    print("=" * 75)

    base_dir = os.path.dirname(os.path.abspath(__file__))
    raw_dataset_dir = os.path.join(base_dir, "KhmerLLM-Dataset")
    cleaned_root_dir = os.path.join(base_dir, CLEANED_ROOT_DIR)

    os.makedirs(cleaned_root_dir, exist_ok=True)

    target = ""
    if len(sys.argv) > 1:
        target = sys.argv[1].strip()
    elif TARGET_FILE.strip():
        target = TARGET_FILE.strip()

    if target:
        found_path = target if os.path.isabs(target) and os.path.exists(target) else find_target_file(raw_dataset_dir, target)
        if found_path:
            clean_single_file(found_path, cleaned_root_dir)
        else:
            print(f"[ERROR] Could not find '{target}' inside {raw_dataset_dir}!")
    else:
        jsonl_files = []
        for root, dirs, files in os.walk(raw_dataset_dir):
            for f in files:
                if f.endswith(".jsonl"):
                    jsonl_files.append(os.path.join(root, f))

        print(f"[BATCH] Cleaning all {len(jsonl_files)} files into '{cleaned_root_dir}/' ...\n")
        for f in sorted(jsonl_files):
            clean_single_file(f, cleaned_root_dir)

    print("=" * 75)
    print(f"✨ CLEANING COMPLETED! Check '{cleaned_root_dir}/' in your Explorer.")
    print("=" * 75)

if __name__ == "__main__":
    main()
