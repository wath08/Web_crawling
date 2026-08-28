# ដំណើរការការងារប្រព័ន្ធប្រមូលទិន្នន័យ NCDD សម្រាប់ KHMER LLM (WORKFLOW.MD)

ឯកសារនេះរៀបរាប់អំពីដំណើរការការងារពេញលេញ (End-to-End Workflow) នៃប្រព័ន្ធទាញយកឯកសារច្បាប់ពីរដ្ឋបាល NCDD Library (https://library.ncdd.gov.kh/) និងបម្លែងជា File អត្ថបទខ្មែរ (.txt) មួយៗដាច់ដោយឡែកក្នុង Folder extracted_texts/ សម្រាប់យកទៅប្រើប្រាស់ក្នុងការបង្វឹក (Train) Khmer LLM។

---

## ១. ដ្យាក្រាមដំណើរការការងារ (Workflow Diagram)

```mermaid
flowchart TD
    Start([ចាប់ផ្តើមដំណើរការ]) --> CheckCheckpoint{តើ ID នេះធ្លាប់បានធ្វើរួចហើយឬនៅ?}
    
    CheckCheckpoint -->|ធ្លាប់ធ្វើរួច| SkipDoc[រំលងទៅ ID បន្ទាប់]
    CheckCheckpoint -->|មិនទាន់ធ្វើ| ScrapeMeta[១. Scrape ព័ត៌មានឯកសារ: ចំណងជើង ប្រភេទ ឆ្នាំ Link PDF]
    
    ScrapeMeta --> DownloadPDF[២. Download File PDF ទៅកាន់ downloads/ID.pdf]
    DownloadPDF --> ReadPages[៣. បើកមើលគ្រប់ទំព័រក្នុង PDF]
    
    ReadPages --> CheckDigital{តើមាន Digital Khmer Text ស្រាប់ទេ?}
    
    CheckDigital -->|មាន| DirectExtract[ស្រង់យកអក្សរផ្ទាល់<br>ឥតគិតថ្លៃ លឿន និងត្រឹមត្រូវ ១០០%]
    CheckDigital -->|គ្មាន| CheckBlank{តើជាទំព័រទទេ Blank Page ទេ?}
    
    CheckBlank -->|ទំព័រទទេ| SkipPage[រំលងទំព័រទទេ មិនចំណាយ Token]
    CheckBlank -->|ក្រដាសស្កេន| GeminiOCR[ផ្ញើទៅកាន់ Gemini Flash API<br>សាកល្បងយ៉ាងច្រើន ២ ដង ផ្អាក ៦០ វិបើ Error]
    
    DirectExtract --> Combine[បូកបញ្ចូលអត្ថបទគ្រប់ទំព័រនៃឯកសារ]
    GeminiOCR --> Combine
    
    Combine --> SaveTXT[៤. រក្សាទុកជា File ដាច់ដោយឡែក extracted_texts/ID.txt]
    SaveTXT --> MarkDone[៥. កត់ត្រា ID ចូល processed_ids.txt]
    MarkDone --> NextDoc[បន្តទៅកាន់ Document ID បន្ទាប់]
```

---

## ២. ដំណាក់កាលលម្អិតទាំង ៥ (Detailed Stages)

### ដំណាក់កាលទី ១៖ ការត្រួតពិនិត្យ Checkpoint
* ប្រព័ន្ធនឹងពិនិត្យមើលបញ្ជី ID ក្នុង File `processed_ids.txt` និង File ដែលមានស្រាប់ក្នុង `extracted_texts/`។
* ប្រសិនបើ ID ណាត្រូវបានធ្វើរួចហើយ វានឹងរំលងចោលភ្លាមៗ ដោយមិនទាញយក ឬចំណាយ Token ជាន់គ្នាឡើយ។

### ដំណាក់កាលទី ២៖ ការ Scrape ព័ត៌មាន និង Download PDF
* កូដចូលទៅកាន់ `https://library.ncdd.gov.kh/detail/{id}`។
* ស្រង់យកព័ត៌មាន៖ ចំណងជើង (Title), ប្រភេទឯកសារ (Category), ឆ្នាំចេញផ្សាយ (Year), និង Link PDF។
* Download File PDF រក្សាទុកក្នុង Folder `downloads/{id}.pdf`។

### ដំណាក់កាលទី ៣៖ ការស្រង់យកអត្ថបទខ្មែរ (Smart Extraction)
សម្រាប់ទំព័រនីមួយៗនៃ PDF៖
* **ពិនិត្យ Digital Text**៖ បើជា PDF ដែល Export ចេញពី Word មានអក្សរខ្មែរស្រាប់ វានឹងស្រង់យកផ្ទាល់ភ្លាមៗក្នុងរយៈពេល ០.១ វិនាទី (Free)។
* **ពិនិត្យទំព័រទទេ**៖ បើជាទំព័រទទេ វានឹងរំលងចោលភ្លាម (០ Token)។
* **ក្រដាសស្កេនរូបភាព**៖ វានឹងបញ្ជូនរូបភាពទំព័រទៅកាន់ **Gemini Flash API** ដើម្បីអានជើងអក្សរ និងតារាងឱ្យបានត្រឹមត្រូវ ១០០% (សាកល្បងយ៉ាងច្រើន ២ ដង និងផ្អាក ៦០ វិនាទីបើមាន Error)។

### ដំណាក់កាលទី ៤៖ ការរក្សាទុកជា File ដាច់ដោយឡែក (Individual .txt Storage)
* រាល់អត្ថបទដែលស្រង់បាននៃឯកសារនីមួយៗ នឹងត្រូវរក្សាទុកក្នុង File មួយដាច់ដោយឡែក៖ **`extracted_texts/{id}.txt`**។
* ក្នុង File នីមួយៗមានក្បាលព័ត៌មានច្បាស់លាស់៖
  * Document ID
  * Title (ចំណងជើង)
  * Category (ប្រភេទ)
  * Year (ឆ្នាំ)
  * Source URL (ប្រភព Link)
  * Content (ខ្លឹមសារអត្ថបទខ្មែរពេញលេញ)

### ដំណាក់កាលទី ៥៖ ការកត់ត្រា Checkpoint និងបន្តទៅមុខ
* កត់ត្រាលេខ ID ចូលក្នុង `processed_ids.txt`។
* ដំណើរការរត់ស្វ័យប្រវត្តិតាម Loop ទៅកាន់ ID បន្ទាប់រហូតដល់ចប់។

---

## ៣. រចនាសម្ព័ន្ធ Folder (Directory Structure)

```text
khmer_llm_pipeline/
├── downloads/                   [កន្លែងផ្ទុកបណ្ដោះអាសន្ន] File PDF ដើមពី NCDD
│   ├── 17235.pdf
│   ├── 17236.pdf
│   └── 17237.pdf
│
├── extracted_texts/             [កន្លែងផ្ទុកលទ្ធផលចុងក្រោយ] File .txt មួយៗដាច់ដោយឡែក
│   ├── 17235.txt
│   ├── 17236.txt
│   └── 17237.txt
│
├── pipeline.py                  Script ស្វ័យប្រវត្តិកម្មចម្បង
├── requirements.txt             បញ្ជី Libraries
├── run.sh                       Script សម្រាប់ដំណើរការ venv ដោយស្វ័យប្រវត្តិ
├── WORKFLOW.md                  ឯកសារដំណើរការការងារនេះ
├── processed_ids.txt            File កត់ត្រា Checkpoint
└── skipped_errors.log           File កត់ត្រាកំហុស
```

---

## ៤. របៀបដំណើរការក្នុង VS Code Terminal

```bash
cd /Users/user/Downloads/khmer_llm_pipeline
./run.sh
```

ឬដំណើរការដោយដៃ៖
```bash
source venv/bin/activate
export GEMINI_API_KEY="YOUR_ACTUAL_GEMINI_API_KEY"
python pipeline.py
```
