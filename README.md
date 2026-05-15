# OCR Document Service

FastAPI microservice for extracting structured data from Tunisian document images
(permis de conduire, CIN, carte grise, assurance) using PaddleOCR.

## Setup

```bash
cd ocr-service

# 1. Create and activate a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment variables
cp .env.example .env
# Edit .env and set API_KEY and ALLOWED_ORIGIN

# 4. Start the server
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

> **Note:** The first run will automatically download PaddleOCR models (~500 MB).
> Subsequent starts reuse the cached models.

## Endpoints

### `GET /health`
Returns service status.

```json
{ "status": "ok", "model": "paddleocr", "langs": ["ar", "fr"] }
```

### `POST /ocr/extract`

**Headers**
| Header | Value |
|--------|-------|
| `x-api-key` | Your API key (must match `API_KEY` in `.env`) |
| `Content-Type` | `multipart/form-data` |

**Form fields**
| Field | Type | Description |
|-------|------|-------------|
| `file` | File | Image — jpg, png, or webp |
| `doc_type` | string | `permis` \| `cin` \| `carte_grise` \| `assurance` |

**Response**
```json
{
  "doc_type": "permis",
  "confidence": 91.4,
  "status": "ok",
  "data": {
    "nom": "BEN ALI",
    "prenom": "Mohamed",
    "numero": "12345678",
    "date_naissance": "22/07/1990",
    "date_expiration": "15/03/2028",
    "categories": ["A", "B"],
    "raw_text": "full extracted text here"
  },
  "processing_time_ms": 340
}
```

**Status codes**
| Confidence | Status |
|------------|--------|
| ≥ 78 | `ok` |
| 55 – 77 | `review` |
| < 55 | `failed` |

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `API_KEY` | _(empty — open)_ | Shared secret between Node backend and this service |
| `ALLOWED_ORIGIN` | `http://localhost:3000` | CORS allowed origin |

## Supported document types

| `doc_type` | Extracted fields |
|------------|-----------------|
| `permis` | nom, prenom, numero, date_naissance, date_expiration, categories |
| `cin` | nom, prenom, numero_cin, date_naissance, gouvernorat |
| `carte_grise` | immatriculation, vin, marque, annee |
| `assurance` | numero_police, date_debut, date_fin, compagnie |

## Example with curl

```bash
curl -X POST http://localhost:8000/ocr/extract \
  -H "x-api-key: your_secret_api_key_here" \
  -F "file=@document.jpg" \
  -F "doc_type=permis"
```

## Project structure

```
ocr-service/
├── main.py                  # FastAPI app, routes, OCR orchestration
├── requirements.txt
├── .env.example
├── models/                  # PaddleOCR downloads models here automatically
│   └── .gitkeep
└── utils/
    ├── __init__.py
    ├── image_processor.py   # Grayscale, resize, contrast enhancement
    └── parser.py            # Regex-based field extraction per doc_type
```
