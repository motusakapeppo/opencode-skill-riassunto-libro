---
name: riassunto-libro
description: "Converte libri e documenti (PDF, EPUB, DOCX, MOBI, TXT, MD, HTML, RTF) in un saggio discorsivo .pdf per studio universitario. Architettura modulare a 7 componenti: Extractor, Chunker, LLM Engine, Proofreader, Renderer, Design System, Config/CLI. Adaptive prompts per tipo di contenuto, compressione a densità variabile, chunking semantico, proofreading automatico. Linguaggio semplice, zero elenchi, zero asterischi, citazioni fonte."
triggers: riassumi, riassunto, fai un riassunto, riassunto libro, riassunto pdf, summary, summarize book, studiare, prepara esame, sintesi libro, book summary, mega skill, mega-skill
argument-hint: <path-to-document> [lingua=it|en]
---

# Mega-Skill Riassunto Universitario

Converte qualsiasi libro/articolo/documento in un **saggio discorsivo .pdf** per studio esame, con linguaggio semplice, zero allucinazioni, e apparato didattico completo.

## Architettura (7 Moduli)

```
DOCUMENTO (PDF/EPUB/DOCX/MOBI/TXT/MD/HTML/RTF)
  │
  ├─ [1/7] EXTRACTOR (L'Occhio) — Estrazione universale, routing per pagina
  │     ├─ PDF: PyMuPDF per pagina → pdftotext -layout (solo se batte PyMuPDF su colonne)
  │     ├─ Routing OCR: SOLO le pagine senza text layer usabile (non piu' tutto il libro)
  │     ├─ OCR: Tesseract, batch da 2xCPU, DPI 200 → escalation 300 sulle pagine illeggibili
  │     ├─ Gate qualita' per pagina (vuota / poche lettere / testo garbled)
  │     ├─ Lane vision: pagine che falliscono il gate → PNG 300 DPI + manifest per l'agente
  │     ├─ Cache estrazione (hash path+size+mtime): i re-run non ri-OCR-ano nulla
  │     ├─ EPUB: ebooklib + BeautifulSoup → zipfile fallback
  │     ├─ DOCX: python-docx → zipfile/XML fallback
  │     ├─ HTML: BeautifulSoup → stdlib parser fallback
  │     ├─ RTF: striprtf → regex fallback
  │     ├─ TXT/MD/RST: encoding fallback chain (utf-8-sig, cp1252, latin-1)
  │     └─ MOBI/AZW: Calibre ebook-convert fallback
  │
  ├─ [2/7] CHUNKER (Il Chirurgo) — Chunking semantico
  │     ├─ Rilevamento confini di sezione (capitoli, heading, pagine)
  │     ├─ 24K token per chunk, overlap 2 paragrafi
  │     ├─ Contesto precedente iniettato (riassunto del chunk prima)
  │     ├─ Split oversized: sezioni → paragrafi → frasi
  │     └─ Merge chunk piccoli (< 800 token)
  │
  ├─ [3/7] LLM ENGINE (L'Equalizzatore) — Map-Reduce adattivo
  │     ├─ Adaptive prompts: rileva tipo contenuto (storia/scienza/arte/filosofia/letteratura)
  │     ├─ Grounding: zero allucinazioni, solo dal testo fornito
  │     ├─ Filtro rumore: scarta indici/bibliografie ([SKIP], [NESSUN CONTENUTO UTILE])
  │     ├─ Citazioni: [Fonte: Blocco N] per ogni concetto
  │     ├─ Checkpoint incrementale: riprende da crash
  │     ├─ Feedback loop: verifica completezza vs originale
  │     ├─ Compressione a densità variabile (10-40% in base a densità informativa)
  │     ├─ Dedup a 3 livelli: paragrafo, frase, parola
  │     ├─ Boldify intelligente: entità in grassetto (prima occorrenza per paragrafo)
  │     ├─ Scheda Riassuntiva: 15 concetti chiave in tabella
  │     └─ Domande d'Esame: 5 probabili domande del professore
  │
  ├─ [4/7] PROOFREADER (Il Revisore) — Controllo qualità
  │     ├─ Punteggio 0-100 su 5 criteri (coerenza, completezza, chiarezza, errori, struttura)
  │     ├─ Verifica sezioni obbligatorie (Da Ricordare, Scheda, Domande)
  │     ├─ Controllo copertura entità estratte
  │     └─ Segnalazione issue e suggerimenti
  │
  ├─ [5/7] DESIGN SYSTEM (Il Designer) — Spettro generativo
  │     ├─ 6 palette base (classic, forest, royal, sunset, ocean, monochrome)
  │     ├─ Rilevamento automatico da filename e contenuto (parole chiave)
  │     ├─ Regolazioni dinamiche: font, margini, interlinea in base a densità
  │     └─ Copertina con metadati (titolo + autore)
  │
  ├─ [6/7] RENDERER (L'Impaginatore) — Export .pdf via Playwright
  │     ├─ HTML+CSS → PDF via Chromium (Playwright)
  │     ├─ Copertina con metadati (titolo + autore)
  │     ├─ Heading nativi → indice navigabile PDF
  │     ├─ Tabella concetti (Termine / Definizione)
  │     ├─ Domande in grassetto
  │     ├─ Citazioni in grigio corsivo [Fonte: Blocco N]
  │     ├─ Zero asterischi, zero elenchi
  │     └─ Drop cap con initial-letter, dedup multi-livello
  │
  └─ [7/7] CONFIG/CLI (Il Direttore) — Configurazione e entry point
        ├─ Config YAML (config.yaml) con override via env var RIASSUNTO_*
        ├─ CLI: python -m scripts.cli <file> [lingua] [--deep-scan] [--stats] [--no-pdf]
        │        [--ocr-dpi N] [--workers N] [--no-cache] [--no-vision]
        │        [--vision-first] [--vision-transcript PATH]
        └─ Pipeline orchestrator: extract → chunk → map → reduce → proofread → render
```

## Output generato

- `Riassunto_NomeLibro.pdf` — saggio discorsivo con copertina, indice navigabile, scheda concetti, domande esame, tema adattivo automatico (6 palette rilevate da filename/contenuto)
- `Riassunto_NomeLibro_entities.json` — entità estratte (persone, date, opere)

## Come usare

```
riassumi D:\percorso\libro.pdf
riassumi D:\percorso\libro.epub in italiano
riassumi D:\Downloads\liber.pdf en      ← se il libro e in inglese
```

Oppure allega il file e scrivi "riassumi questo libro"

## Requisiti

- Ollama Pro (deepseek-v4.1-flash:cloud)
- PyMuPDF (obbligatorio per i PDF: estrazione e rendering pagine)
- Tesseract 5.4 in D:\tesseract (opzionale: senza Tesseract le pagine scansionate
  finiscono tutte nella lane vision invece di fallire)
- Playwright + Chromium: `playwright install chromium`
- Poppler non e' piu' richiesto: il rendering delle pagine usa PyMuPDF

## Lane vision (pagine illeggibili)

Il lato Python non puo' chiamare un modello vision, quindi prepara il lavoro e
lo passa all'agente. Non blocca mai: se il transcript manca, la pipeline procede
con il testo OCR disponibile.

1. La pipeline scrive le pagine che falliscono il gate qualita' in
   `<output_dir>/.vision/<libro>/page-NNNN.png` + `manifest.json`, e stampa:
   `VISION_REQUIRED:<path manifest> pages=12,47`
2. L'agente legge le immagini del manifest (a batch, senza riassumerle) e
   trascrive il testo fedele di ogni pagina.
3. Scrive `transcript.json` accanto al manifest:
   `{"pages": {"12": "testo trascritto...", "47": "..."}}`
4. Rilancia la pipeline: il transcript viene unito alle pagine per numero e la
   cache fa il resto (nessun nuovo OCR).

Solo le pagine rotte passano di qui: su un libro normale sono zero. Cap di
default 40 pagine per run (`vision_max_pages`).

## Scripts

- `scripts/cli.py` — entry point CLI
- `scripts/pipeline.py` — orchestratore pipeline (extract → chunk → map → reduce → proofread)
- `scripts/extractor.py` — estrattore universale con routing OCR per pagina e handoff vision
- `scripts/chunker.py` — chunking semantico con overlap
- `scripts/llm_engine.py` — LLM interaction, adaptive prompts, map-reduce, boldify, compression
- `scripts/proofreader.py` — controllo qualità automatico
- `scripts/renderer.py` — PDF generation via Playwright/Chromium
- `scripts/design_system.py` — generative design spectrum (6 palette + regolazioni dinamiche)
- `scripts/config.py` — configurazione da YAML + env var override
- `scripts/models.py` — data models condivisi (Chunk, EntitySet, MapResult, PipelineResult)
- `scripts/css_templates.py` — template CSS (legacy, integrato in design_system.py)

## Configurazione

Copia `config.yaml.example` in `config.yaml` per personalizzare:

```yaml
# Ollama API endpoint
ollama_host: "http://127.0.0.1:11434"

# LLM models (map, reduce, proofread)
model_map: "deepseek-v4.1-flash:cloud"
model_reduce: "deepseek-v4.1-flash:cloud"
model_proofread: "deepseek-v4.1-flash:cloud"

# Chunking settings
chunk_max_tokens: 24000
chunk_overlap_paragraphs: 2
chunk_min_tokens: 800

# OCR (routing per pagina, batch paralleli, escalation DPI)
ocr_dpi: 200
ocr_dpi_max: 300
ocr_workers: 0            # 0 = numero di CPU
ocr_lang: null            # null = derivato dalla lingua di output
ocr_preprocess: true

# Cache estrazione (i re-run non rifanno OCR)
cache_enabled: true

# Lane vision
vision_enabled: true
vision_first: false       # manda tutto il libro alla vision (doc brevi)
vision_max_pages: 40

# Output directory (relative to input file location)
output_dir: "riassunti"

# External tool paths (auto-detected if on PATH)
tesseract_path: null
poppler_path: null

# Playwright settings
playwright_headless: true

# Retry settings for Ollama API calls
max_retries: 5
retry_base_delay: 30
```

Tutte le chiavi possono essere sovrascritte con variabili d'ambiente `RIASSUNTO_*` (es. `RIASSUNTO_MODEL_MAP`).
