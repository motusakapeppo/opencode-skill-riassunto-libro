# Mega-Skill Riassunto Universitario

Skill per OpenCode che converte libri e documenti (PDF, EPUB, DOCX, MOBI, TXT, MD, HTML, RTF) in un **saggio discorsivo .pdf** per studio esame, con linguaggio semplice, grassetti automatici, zero elenchi, zero asterischi, e apparato didattico completo (scheda concetti + domande di verifica).

## Requisiti

1. **Ollama Pro** (abbonamento attivo) — $20/mese
   - Modello cloud: `deepseek-v4.1-flash:cloud`
   - Installazione: [ollama.com](https://ollama.com)

2. **Tesseract OCR 5.4** (per scansioni/fotocopie) — GRATIS, ora opzionale
   - Installare in `D:\tesseract\`
   - Download: [UB Mannheim Tesseract](https://github.com/UB-Mannheim/tesseract/wiki)
   - Modello lingua italiano incluso in `tessdata\`: senza `ita.traineddata` l'OCR
     italiano non funziona (la skill lo segnala e passa le pagine alla lane vision)

3. **Poppler** (opzionale) — serve solo per `pdftotext -layout` su PDF a colonne
   - Installare in `D:\poppler\`
   - Download: [poppler-windows](https://github.com/oschwartz10612/poppler-windows/releases)

4. **Playwright + Chromium** (per generazione PDF) — GRATIS
   ```powershell
   pip install playwright
   playwright install chromium
   ```

5. **Python 3.10+** con pacchetti:
   ```
   pip install requests PyMuPDF pdfplumber pypdf pytesseract pdf2image loguru pyyaml playwright python-docx ebooklib beautifulsoup4
   ```

## Installazione

1. Scompatta questa cartella in:
   ```
   C:\Users\<TUO_NOME>\.config\opencode\skill\riassunto-libro\
   ```

2. Verifica che i percorsi siano corretti:
   - `D:\tesseract\tesseract.exe` (OCR)
   - `D:\poppler\poppler-24.08.0\Library\bin\pdftotext.exe` (layout extraction)

3. Installa Playwright e Chromium:
   ```powershell
   pip install playwright
   playwright install chromium
   ```

4. Avvia Ollama e verifica che il modello cloud sia disponibile:
   ```powershell
   ollama pull deepseek-v4.1-flash:cloud
   ```

## Configurazione

Copia `config.yaml.example` in `config.yaml` per personalizzare impostazioni come modelli LLM, chunk size, percorsi tool esterni, e retry. Tutte le chiavi possono essere sovrascritte con variabili d'ambiente `RIASSUNTO_*`.

## Come usare

In qualsiasi sessione OpenCode, basta scrivere:

```
riassumi D:\percorso\del\libro.pdf
```

Oppure, se il libro e in inglese e vuoi l'output in italiano:

```
riassumi D:\percorso\libro.pdf en
```

La skill:
1. Estrae il testo con PyMuPDF pagina per pagina; solo le pagine senza text layer usabile passano dall'OCR (Tesseract, batch paralleli, escalation DPI), e le pagine che restano illeggibili vengono preparate per la lane vision
2. Lo divide in chunk con overlap semantico e rilevamento confini di sezione
3. Rileva il tipo di contenuto (storia, scienza, arte, filosofia, letteratura) e sceglie il prompt adattivo
4. Processa ogni chunk con deepseek-v4.1-flash:cloud producendo **solo prosa** (paragrafi di 3-6 frasi, connettivi, niente elenchi ne' sezioni finali)
5. Fonde i blocchi: toglie le sezioni ripetute, deduplica i titoli, marca i confini e genera in un unico passaggio finale il saggio con Da Ricordare, Cronologia, Glossario, Opere Citati, Scheda e Domande
6. Applica compressione a densita variabile (10-40% in base a densita informativa)
7. Esegue proofreading automatico con punteggio 0-100 e un gate di stile misurato (bullet dump → max 40, una riscrittura)
8. Genera PDF via Playwright/Chromium con copertina, heading nativi (indice navigabile), grassetti, scheda concetti, domande di verifica, tema adattivo

## Output

Nella cartella `riassunti/` accanto al file originale:
- `Riassunto_NomeLibro.pdf` — saggio discorsivo con copertina, indice navigabile, tema adattivo
- `Riassunto_NomeLibro_entities.json` — entita estratte (persone, date, opere)

## Architettura (7 Moduli)

```
Extractor     → Estrazione universale (PDF/EPUB/DOCX/HTML/RTF/TXT/MOBI)
Chunker       → Chunking semantico con overlap e contesto precedente
LLM Engine    → Adaptive prompts, map-reduce, compressione densita variabile, boldify
Proofreader   → Controllo qualita automatico (5 criteri, punteggio 0-100)
Design System → Spettro generativo (6 palette + regolazioni dinamiche)
Renderer      → HTML+CSS → PDF via Playwright/Chromium
Config/CLI    → Config YAML + env var override + CLI entry point
```

Ogni modulo e un file separato in `scripts/`:

| File | Cosa fa |
|------|---------|
| `SKILL.md` | Istruzioni per OpenCode (trigger: "riassumi", "riassunto", ecc.) |
| `config.yaml.example` | Template di configurazione YAML |
| `scripts/cli.py` | Entry point CLI |
| `scripts/pipeline.py` | Orchestratore pipeline (extract → chunk → map → reduce → proofread) |
| `scripts/extractor.py` | Estrattore universale con routing OCR per pagina, cache e handoff vision |
| `scripts/chunker.py` | Chunking semantico con overlap e checkpoint |
| `scripts/llm_engine.py` | LLM interaction: map in prosa, merge, sintesi finale, boldify, compressione |
| `scripts/proofreader.py` | Controllo qualità automatico + gate di stile misurato |
| `scripts/style.py` | Contratto di stile: metriche di prosa, conversione elenchi, StyleViolation |
| `scripts/renderer.py` | PDF generation via Playwright/Chromium |
| `scripts/design_system.py` | Generative design spectrum (6 palette + regolazioni dinamiche) |
| `scripts/config.py` | Configurazione da YAML + env var override |
| `scripts/models.py` | Data models condivisi (Chunk, EntitySet, MapResult, PipelineResult) |

## Note

- I checkpoint automatici salvano lo stato dopo ogni chunk: se la pipeline si interrompe (crash, timeout), basta rilanciarla e riprende da dove era rimasta.
- La compressione a densita variabile calcola automaticamente il target in base alla densita informativa del testo (entita uniche per 1000 caratteri).
- I grassetti vengono applicati a nomi propri, date, secoli e concetti chiave (prima occorrenza per paragrafo).
- I termini tecnici (recitativo, monodia, libretto...) vengono spiegati tra parentesi la prima volta che compaiono.
- Il proofreading automatico verifica 5 criteri (coerenza, completezza, chiarezza, errori, struttura) e assegna un punteggio 0-100.
- I prompt si adattano automaticamente al tipo di contenuto rilevato (storia, scienza, arte, filosofia, letteratura, generale).

## Temi Disponibili

La skill rileva automaticamente il tema piu adatto in base al nome del file e al contenuto del testo:

| Tema | Colore | Adatto per |
|------|--------|------------|
| `classic` | Blu scuro (#1a2744) | Storia, eventi, default |
| `forest` | Verde (#2d6a4f) | Natura, ecologia, Bianconi |
| `royal` | Viola (#6b2d5a) | Arte, musica, teatro, Rosand |
| `sunset` | Arancio (#c45a2a) | Mediterraneo, calore |
| `ocean` | Teal (#1a6b8a) | Mare, navigazione |
| `monochrome` | Grigio (#555555) | Filosofia, scienza |

Ogni tema include regolazioni dinamiche di font, margini e interlinea in base alla densita del contenuto.
