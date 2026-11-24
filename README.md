# Document Reader

An AI document reading application with ZERO DEFAULTS:
- Reads documents from scratch with high-resolution image rendering and OpenCV deskew/denoise.
- Extracts document type, header title, and all physical fields with vision AI and OCR cross-check.
- Exact value preservation: casing, commas, and suffixes (e.g. `PhD`, `DDS`, `Jr.`) are strictly preserved.
- Dynamic table columns generated on the fly from the union of extracted field labels per document group.
- Real duplicate check: detects same content (SHA-256) while reading again from scratch with duplicate note.
- Check and edit split screen: preview original document page side-by-side with extracted details, confidence scores, and edit/add/remove capabilities.
- Learning: persists user corrections to continuously improve future extraction.
- ZIP export: downloads original files, dynamic CSV, and multi-sheet Excel (.xlsx) workbooks.

---

## 1. Prerequisites & Installation

### Python & Node.js
- Python 3.11+
- Node.js 18+ and npm

Install Python dependencies:
```bash
pip install -r requirements.txt
pip install anthropic openpyxl bcrypt
```

Install Frontend dependencies:
```bash
cd frontend
npm install
```

### Tesseract OCR Installation
- **Windows**: Install using winget or the official installer:
  ```powershell
  winget install UB-Mannheim.TesseractOCR
  ```
  Add `C:\Program Files\Tesseract-OCR` to your system `PATH`.
- **macOS**:
  ```bash
  brew install tesseract
  ```
- **Linux (Ubuntu/Debian)**:
  ```bash
  sudo apt-get install -y tesseract-ocr
  ```

---

## 2. Environment Configuration

Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Configure `ANTHROPIC_API_KEY`:
```ini
ANTHROPIC_API_KEY=your_anthropic_api_key_here
MODEL_NAME=claude-sonnet-5-5
JWT_SECRET=your_secure_secret_key
DATABASE_URL=sqlite:///./data/ecm_pipeline.db
```

*Note: If `ANTHROPIC_API_KEY` is not provided or invalid, the app reports honest `Failed` status with the exact error and stores zero placeholder values.*

---

## 3. Running the App

### Start Backend
In the root directory:
```bash
python -m uvicorn app.api.app:app --host 127.0.0.1 --port 8000
```

### Start Frontend
In `frontend/`:
```bash
cd frontend
npm run dev
```

Open your browser at `http://localhost:5173`.
All requests to `/api` are automatically proxied to `http://127.0.0.1:8000`.

---

## 4. Architecture & Workflow

1. **Sign in / Register**: Secure authentication with bcrypt password hashing and HS256 JWT tokens. No seeded or hard-coded default accounts.
2. **Upload**: Drag-and-drop or select multiple documents. Real duplicate detection compares SHA-256 hashes against previous uploads and reads every upload again from scratch.
3. **Reading**: Live stage progression (`Waiting` -> `Reading` -> `Extracting` -> `Done` / `Failed`). Computes visual page condition (`clean`, `slightly skewed`, `speckled background`) from image contours and noise variance.
4. **Results**: Groups documents by detected type. Columns are dynamically generated only from the fields present in that group. High confidence values mark `Done`; values with confidence < 85% mark `Done, check`.
5. **Check and edit**: Split screen displays the high-resolution original document on the left and editable field values with confidence metrics on the right. User edits are persisted in the database and logged to the `corrections` table for learning.
6. **Download all as ZIP**: Packages the batch with original documents, `results.csv`, and `results.xlsx` (with one sheet per document type).
