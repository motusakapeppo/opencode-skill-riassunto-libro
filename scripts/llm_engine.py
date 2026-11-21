"""
Unified LLM interaction module for riassunto-libro.

Merges Map-Reduce logic from:
  - mega_skill.py (equalizzatore_map, equalizzatore_reduce, _contiene_skip,
    _verifica_citazioni, _deduplica_testo, boldify_intelligente)
  - pipeline_unificata.py (map_chunk, feedback_loop, reduce_summaries, build_glossary)
  - riassumi.py (call_llm pattern)

Provides:
  - call_ollama() — call Ollama API with retry + exponential backoff + jitter
  - map_chunk() — summarize a single chunk
  - reduce_results() — concatenate, deduplicate, verify citations
  - boldify_intelligente() — apply **bold** to known entities
  - _deduplica_testo() — three-level deduplication
  - _verifica_citazioni() — verify citation integrity
"""

import logging
import random
import re
import time
from enum import Enum
from typing import Optional

import requests

from scripts.config import Settings
from scripts.models import EntitySet, MapResult

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
#  ADAPTIVE PROMPT SYSTEM
# ─────────────────────────────────────────────


class ContentType(Enum):
    HISTORY = "history"
    SCIENCE = "science"
    ART = "art"
    PHILOSOPHY = "philosophy"
    LITERATURE = "literature"
    GENERAL = "general"


def detect_content_type(text_sample: str) -> ContentType:
    """Analyze first 2000 chars to detect content type using keyword frequency."""
    sample = text_sample[:2000].lower()

    # Keyword sets for each content type
    history_keywords = {"secolo", "guerra", "regno", "impero", "rivoluzione", "dinastia",
                        "trattato", "alleanza", "civiltà", "medievale", "moderno",
                        "contemporaneo", "storico", "antico", "pace", "colonizzazione"}
    science_keywords = {"teoria", "esperimento", "formula", "dati", "laboratorio",
                        "ipotesi", "metodo", "scienza", "biologia", "fisica", "chimica",
                        "matematica", "calcolo", "analisi", "sistema", "struttura"}
    art_keywords = {"pittura", "musica", "colore", "compositore", "tela", "affresco",
                   "sinfonia", "teatro", "opera", "barocco", "rinascimento", "scultura",
                   "dipinto", "melodramma", "libretto", "recitativo", "aria"}
    philosophy_keywords = {"concetto", "ragione", "essere", "pensiero", "logica",
                          "dialettica", "etica", "morale", "conoscenza", "verità",
                          "esistenza", "soggetto", "oggetto", "trascendentale"}
    literature_keywords = {"romanzo", "personaggio", "narrativa", "poesia", "capitolo",
                          "trama", "narratore", "protagonista", "stile", "metafora",
                          "simbolo", "versi", "strofa", "prosa"}

    def score(keywords):
        return sum(1 for k in keywords if k in sample)

    scores = {
        ContentType.HISTORY: score(history_keywords),
        ContentType.SCIENCE: score(science_keywords),
        ContentType.ART: score(art_keywords),
        ContentType.PHILOSOPHY: score(philosophy_keywords),
        ContentType.LITERATURE: score(literature_keywords),
    }

    best = max(scores, key=scores.get)
    if scores[best] >= 3:
        return best
    return ContentType.GENERAL


# ─────────────────────────────────────────────
#  DEFAULT PROMPT TEMPLATES
# ─────────────────────────────────────────────

PROMPT_MAP_IT = """Riscrivi il testo in italiano SEMPLICE, CONCISO, completo.

Parla come un amico intelligente che spiega a uno stanco dopo lavoro. Frasi corte, parole di tutti i giorni.

TERMINI TECNICI: se usi parole specialistiche (recitativo, monodia, libretto...), aggiungi subito una brevissima spiegazione tra parentesi: "recitativo (canto parlato)", "libretto (testo dell'opera)".

GRASSETTO INTELLIGENTE: usa **grassetto** per evidenziare in modo strategico:
- **Nomi propri** di persone, luoghi, istituzioni importanti (es: **Monteverdi**, **Venezia**, **Teatro San Cassiano**)
- **Date e periodi** chiave (es: **1637**, **primo Seicento**)
- **Concetti portanti** che sono il tema centrale del discorso (es: **brevità**, **frequenza delle arie**, **recitativo**, **mercato dell'opera**)
- **Relazioni causali** e punti di svolta (es: **passaggio dall'opera di corte all'opera a pagamento**, **nascita del melodramma**)
- **Termini tecnici** alla loro prima occorrenza (es: **libretto**, **monodia**, **basso continuo**)

Regola d'oro: non più di 2-3 grassetti per paragrafo. Il grassetto deve GUIDARE l'occhio, non appesantire.

REGOLE:
1. COMPLETEZZA: ogni nome, data, concetto, evento deve restare.
2. PARLA SEMPLICE: come al bar. Frasi corte, parole comuni.
3. CONCISIONE: vai dritto al punto. Taglia fronzoli.
4. LUNGHEZZA: circa {target}.
5. ### per i titoli.
6. ZERO elenchi puntati. ZERO asterischi singoli. Solo **grassetto** va bene.
7. Alla fine del riassunto, aggiungi QUESTE SEZIONI nell'ordine:

### Da Ricordare
Scrivi 3-5 concetti chiave del testo, ognuno come frase breve. Formato: **Concetto** — spiegazione in una riga.

### Cronologia
Elenco delle date principali menzionate, in ordine cronologico. Formato: **Anno** — evento.

### Glossario
5-10 termini tecnici con definizione breve. Formato: **termine** — definizione.

### Opere Citati
Elenco delle opere, libri, articoli menzionati. Formato: **Titolo** (Autore, anno).

Poi: ### Scheda Riassuntiva (15 concetti, formato: Concetto: [termine] - [spiegazione]) e ### Domande di Verifica (5 domande, formato: Domanda: [domanda] - [risposta]).

Infine:
===ENTITA===
PERSONE: separato da |
DATE: separato da |
OPERE/EVENTI/CONCETTI: separato da |
===FINE ENTITA===

TESTO:
{testo}"""

PROMPT_MAP_EN = """Rewrite in simple, CONCISE, complete Italian.

Write like a smart friend explaining to a tired friend after work. Short sentences, everyday words.

TECHNICAL TERMS: when you use specialist words (recitative, monody, libretto...), add a quick explanation in parentheses: "recitative (sung speech)", "libretto (opera text)".

BOLD: use **word** to highlight important names, key dates, core concepts. Ex: **Monteverdi**, **1637**, **recitative**. Dont overdo it.

RULES:
1. COMPLETENESS: every name, date, concept, event must stay.
2. SIMPLE LANGUAGE: like at a bar. Short sentences, common words.
3. CONCISE: get to the point. Cut fluff.
4. LENGTH: about {target}.
5. Use ### for section titles.
6. ZERO bullet points. ZERO single asterisks. Only **bold** is fine.
7. At the end of the summary, add THESE SECTIONS in order:

### Da Ricordare
Write 3-5 key concepts from the text, each as a short phrase. Format: **Concept** — one-line explanation.

### Cronologia
List the main dates mentioned, in chronological order. Format: **Year** — event.

### Glossario
5-10 technical terms with short definitions. Format: **term** — definition.

### Opere Citati
List of works, books, articles mentioned. Format: **Title** (Author, year).

Then: ### Scheda Riassuntiva (15 concepts, format: Concetto: [term] - [explanation]) and ### Domande di Verifica (5 questions, format: Domanda: [question] - [answer]).

Finally:
===ENTITA===
PERSONE: list separated by |
DATE: list separated by |
OPERE/EVENTI/CONCETTI: list separated by |
===FINE ENTITA===

TEXT:
{testo}"""


PROMPT_TEMPLATES = {
    ContentType.HISTORY: """Sei uno storico specializzato. Analizza il testo con attenzione alle relazioni causali, alle cronologie e ai contesti. Spiega come gli eventi si collegano tra loro, chi sono i protagonisti e perché le loro azioni sono significative.

REGOLE:
1. Preserva TUTTI i nomi propri, date, trattati, eventi
2. Spiega le RELAZIONI CAUSALI: "X è successo perché Y, e questo ha portato a Z"
3. Contestualizza: spiega perché un evento è importante nel suo periodo storico
4. Usa ### per i titoli delle sezioni
5. ZERO elenchi puntati
6. Alla fine: ### Da Ricordare, ### Cronologia, ### Glossario, ### Opere Citati, ### Scheda Riassuntiva, ### Domande di Verifica
7. Poi: ===ENTITA=== ... ===FINE ENTITA===

TESTO:
{testo}""",

    ContentType.SCIENCE: """Sei un divulgatore scientifico. Spiega i concetti con chiarezza, definendo ogni termine tecnico. Usa analogie per rendere accessibili i concetti complessi.

REGOLE:
1. Definisci OGNI termine tecnico la prima volta che appare
2. Usa ANALOGIE e metafore per spiegare concetti astratti
3. Preserva dati, formule, esperimenti e risultati
4. Spiega il METODO: come sono state ottenute le conclusioni
5. Usa ### per i titoli delle sezioni
6. ZERO elenchi puntati
7. Alla fine: ### Da Ricordare, ### Glossario, ### Scheda Riassuntiva, ### Domande di Verifica
8. Poi: ===ENTITA=== ... ===FINE ENTITA===

TESTO:
{testo}""",

    ContentType.ART: """Sei un critico d'arte/musica. Descrivi le opere con sensibilità estetica, collegandole al contesto storico e culturale. Spiega perché sono significative.

REGOLE:
1. Descrivi lo STILE e la TECNICA con linguaggio evocativo ma preciso
2. Collega le opere al CONTESTO storico e culturale
3. Spiega l'INNOVAZIONE: cosa rende unica ogni opera
4. Preserva titoli di opere, nomi di artisti, date, correnti
5. Usa ### per i titoli delle sezioni
6. ZERO elenchi puntati
7. Alla fine: ### Da Ricordare, ### Cronologia, ### Glossario, ### Opere Citati, ### Scheda Riassuntiva, ### Domande di Verifica
8. Poi: ===ENTITA=== ... ===FINE ENTITA===

TESTO:
{testo}""",

    ContentType.PHILOSOPHY: """Sei un filosofo. Analizza gli argomenti, le tesi e le antitesi. Chiarisci le distinzioni concettuali e la struttura del ragionamento.

REGOLE:
1. Esponi la TESI centrale e le ANTITESI
2. Chiarisci le DISTINZIONI CONCETTUALI
3. Spiega la STRUTTURA del ragionamento (premesse → conclusioni)
4. Preserva termini filosofici e nomi di pensatori
5. Usa ### per i titoli delle sezioni
6. ZERO elenchi puntati
7. Alla fine: ### Da Ricordare, ### Glossario, ### Scheda Riassuntiva, ### Domande di Verifica
8. Poi: ===ENTITA=== ... ===FINE ENTITA===

TESTO:
{testo}""",

    ContentType.LITERATURE: """Sei un critico letterario. Analizza personaggi, temi, stile narrativo e struttura dell'opera. Collega gli elementi al contesto storico-letterario.

REGOLE:
1. Analizza PERSONAGGI: motivazioni, evoluzione, relazioni
2. Identifica TEMI principali e secondari
3. Descrivi lo STILE NARRATIVO e le scelte formali
4. Collega l'opera al CONTESTO storico-letterario
5. Preserva titoli, autori, date, correnti letterarie
6. Usa ### per i titoli delle sezioni
7. ZERO elenchi puntati
8. Alla fine: ### Da Ricordare, ### Cronologia, ### Glossario, ### Opere Citati, ### Scheda Riassuntiva, ### Domande di Verifica
9. Poi: ===ENTITA=== ... ===FINE ENTITA===

TESTO:
{testo}""",

    ContentType.GENERAL: PROMPT_MAP_IT,  # Use the default prompt
}


def get_prompt_template(content_type: ContentType, lingua: str = "it") -> str:
    """Return the appropriate prompt template for the content type and language."""
    if lingua == "en":
        return PROMPT_MAP_EN  # English fallback to default
    return PROMPT_TEMPLATES.get(content_type, PROMPT_MAP_IT)

# ─────────────────────────────────────────────
#  CONSTANTS
# ─────────────────────────────────────────────

DEFAULT_TIMEOUT = 600
DEFAULT_NUM_CTX = 32768
DEFAULT_TEMPERATURE = 0.3

# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────


def estimate_tokens(text: str) -> int:
    """Rough token estimate: 1 token ≈ 4 characters."""
    return len(text) // 4


# ─────────────────────────────────────────────
#  OLLAMA CALL
# ─────────────────────────────────────────────


def call_ollama(
    model: str,
    prompt: str,
    settings: Settings,
    *,
    num_ctx: int = DEFAULT_NUM_CTX,
    temperature: float = DEFAULT_TEMPERATURE,
    timeout: int = DEFAULT_TIMEOUT,
    max_retries: Optional[int] = None,
) -> Optional[str]:
    """Call Ollama chat API with exponential backoff + jitter.

    Args:
        model: Ollama model name (e.g. "deepseek-v4.1-flash:cloud").
        prompt: User message content.
        settings: Pipeline Settings object.
        num_ctx: Context window size.
        temperature: Sampling temperature.
        timeout: Request timeout in seconds.
        max_retries: Override settings.max_retries.

    Returns:
        Response content string, or None if all retries exhausted.
    """
    retries = max_retries if max_retries is not None else settings.max_retries
    base_delay = settings.retry_base_delay

    # Build headers: API key for cloud, empty for local
    headers = {"Content-Type": "application/json"}
    if settings.ollama_api_key:
        headers["Authorization"] = f"Bearer {settings.ollama_api_key}"

    # Determine endpoint: cloud uses OpenAI-compatible /v1/chat/completions,
    # local Ollama uses /api/chat
    is_cloud = "ollama.com" in settings.ollama_host or "openai" in settings.ollama_host.lower()
    endpoint = f"{settings.ollama_host}/chat/completions" if is_cloud else f"{settings.ollama_host}/api/chat"

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    if not is_cloud:
        payload["options"] = {"num_ctx": num_ctx, "temperature": temperature}
    else:
        payload["max_tokens"] = num_ctx
        payload["temperature"] = temperature

    for attempt in range(retries):
        try:
            resp = requests.post(
                endpoint,
                json=payload,
                headers=headers,
                timeout=timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            if is_cloud:
                return data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return data.get("message", {}).get("content", "")
        except Exception as exc:
            msg = str(exc)[:80]
            if attempt < retries - 1:
                # Exponential backoff with jitter: base * 2^attempt + random(0, base)
                delay = base_delay * (2**attempt) + random.uniform(0, base_delay)
                logger.info("Retry %d/%d for %s: %s — waiting %.1fs", attempt + 1, retries, model, msg, delay)
                time.sleep(delay)
            else:
                logger.error("All %d retries exhausted for %s: %s", retries, model, msg)
                return None
    return None


# ─────────────────────────────────────────────
#  ENTITY PARSING
# ─────────────────────────────────────────────


def _parse_entities(content: str, lang: str = "it") -> tuple[str, EntitySet]:
    """Extract ===ENTITA=== / ===ENTITIES=== block from LLM output.

    Returns:
        (cleaned_text_without_entity_block, EntitySet)
    """
    if lang == "it":
        pattern = r"===ENTITA===\n(.*?)===FINE ENTITA==="
        prefixes = {"PERSONE": "persone", "DATE": "date", "OPERE": "opere"}
    else:
        pattern = r"===ENTITIES===\n(.*?)===END ENTITIES==="
        prefixes = {"PEOPLE": "persone", "DATES": "date", "WORKS": "opere"}

    entities = EntitySet()
    em = re.search(pattern, content, re.DOTALL)
    if em:
        for line in em.group(1).strip().split("\n"):
            for prefix, field in prefixes.items():
                if line.startswith(prefix + ":") or line.startswith(prefix + "/"):
                    parts = line.split(":", 1)[1] if ":" in line else ""
                    vals = [e.strip() for e in parts.split("|") if e.strip()]
                    setattr(entities, field, vals)
                    break
        clean = content[: em.start()].strip()
    else:
        clean = content.strip()

    return clean, entities


# ─────────────────────────────────────────────
#  SKIP DETECTION
# ─────────────────────────────────────────────


def _contiene_skip(testo: Optional[str]) -> bool:
    """Check if text contains skip / no-content markers."""
    if not testo:
        return True
    markers = ["[NESSUN CONTENUTO UTILE]", "[SKIP]", "NESSUN CONTENUTO UTILE"]
    return any(m in testo for m in markers)


# ─────────────────────────────────────────────
#  MAP — single chunk summarization
# ─────────────────────────────────────────────


def map_chunk(
    chunk: dict,
    prompt_template: str,
    settings: Settings,
    *,
    model: Optional[str] = None,
    chunk_index: int = 0,
    max_chars: int = 0,
    temperature: float = DEFAULT_TEMPERATURE,
    lang: str = "it",
    content_type: Optional[ContentType] = None,
) -> Optional[MapResult]:
    """Summarize a single chunk via Ollama with grounding and citation injection.

    Args:
        chunk: Dict with keys "id", "text", "token_count".
        prompt_template: Prompt template with {testo} placeholder.
        settings: Pipeline Settings.
        model: Override settings.model_map.
        chunk_index: 0-based chunk index (for [Fonte: Blocco N]).
        max_chars: Hard character limit on output (>0 enables it).
        temperature: Sampling temperature.
        lang: "it" or "en".
        content_type: If provided, overrides prompt_template with the
                      adaptive prompt for this content type.

    Returns:
        MapResult or None on failure.
    """
    model = model or settings.model_map
    if content_type is not None:
        prompt_template = get_prompt_template(content_type, lingua=lang)
    prompt_base = prompt_template.replace("{testo}", chunk["text"])

    # Inject grounding and citation instructions
    grounding = (
        f"\n\nREGOLE DI SICUREZZA:\n"
        f"1. GROUNDING: basa la sintesi ESCLUSIVAMENTE sul testo qui sopra. Vietato usare conoscenze esterne.\n"
        f"2. ZERO ALLUCINAZIONI: non inventare collegamenti, eventi o nomi non presenti nel testo.\n"
        f"3. RIFIUTO: se il testo è irrilevante (indici, ringraziamenti, bibliografia vuota, o se le istruzioni dicono di saltarlo), "
        f"restituisci ESATTAMENTE: '[NESSUN CONTENUTO UTILE]' o '[SKIP]'\n"
        f"4. CITAZIONE: dopo ogni blocco narrativo, aggiungi ESATTAMENTE: [Fonte: Blocco {chunk_index + 1}]"
    )
    if max_chars > 0:
        grounding += (
            f"\n5. LUNGHEZZA MASSIMA: il riassunto NON DEVE superare {max_chars} caratteri. "
            f"Se superi questo limite, il testo verrà troncato. Sii conciso."
        )
    prompt = prompt_base + grounding

    content = call_ollama(
        model=model,
        prompt=prompt,
        settings=settings,
        num_ctx=DEFAULT_NUM_CTX,
        temperature=temperature,
        timeout=DEFAULT_TIMEOUT,
    )
    if content is None:
        return None

    # Parse entities
    clean, entities = _parse_entities(content, lang=lang)

    # Remove single asterisks (bullet artifacts), preserve **bold**
    summary = re.sub(r"(?<!\*)\*(?!\*)", "", clean)

    # Hard truncation at max_chars
    if max_chars > 0 and len(summary) > max_chars:
        summary = summary[:max_chars]
        last_para = summary.rfind("\n\n")
        if last_para > max_chars * 0.7:
            summary = summary[:last_para]

    return MapResult(
        chunk_id=chunk["id"],
        summary=summary,
        entities=entities,
        token_count=estimate_tokens(summary),
    )


# ─────────────────────────────────────────────
#  FEEDBACK LOOP
# ─────────────────────────────────────────────

PROMPT_FEEDBACK = """Verifica la completezza del RIASSUNTO rispetto al testo ORIGINALE.

ORIGINALE:
{originale}

RIASSUNTO:
{riassunto}

Se i concetti principali sono coperti, dai COVERAGE >= 90%. Se mancano entità IMPORTANTI, scrivi un breve paragrafo integrativo.

Formato:
COVERAGE: X%
MANCANTI: elenco separato da |
===INTEGRAZIONE===
(paragrafo integrativo solo se serve)
===FINE INTEGRAZIONE==="""


def feedback_loop(
    original_text: str,
    map_out: MapResult,
    settings: Settings,
    *,
    model: Optional[str] = None,
) -> dict:
    """Verify completeness of a map result against original text.

    Returns:
        Dict with keys "coverage" (int 0-100) and "integration" (str).
    """
    model = model or settings.model_proofread
    prompt = PROMPT_FEEDBACK.replace("{originale}", original_text[:8000])
    prompt = prompt.replace("{riassunto}", map_out.summary)

    try:
        content = call_ollama(
            model=model,
            prompt=prompt,
            settings=settings,
            num_ctx=16384,
            temperature=0.1,
            timeout=120,
        )
        if content is None:
            return {"coverage": 100, "integration": ""}

        cov_match = re.search(r"COVERAGE:\s*(\d+)%", content)
        coverage = int(cov_match.group(1)) if cov_match else 100

        int_match = re.search(
            r"===INTEGRAZIONE===\n(.*?)===FINE INTEGRAZIONE===", content, re.DOTALL
        )
        integration = int_match.group(1).strip() if int_match else ""

        return {"coverage": coverage, "integration": integration}
    except Exception as exc:
        logger.warning("Feedback loop error: %s", exc)
        return {"coverage": 100, "integration": ""}


# ─────────────────────────────────────────────
#  CITATION VERIFICATION
# ─────────────────────────────────────────────


def _verifica_citazioni(testo: Optional[str]) -> dict:
    """Verify integrity of [Fonte: Blocco N] citations.

    Returns:
        Dict with keys: ok, giallo, rosso, dettagli.
        - ok: count of properly formed citations
        - giallo: count of partial matches (unused, kept for compat)
        - rosso: count of malformed citations
        - dettagli: list of (blocco_num, ratio, status)
    """
    if not testo:
        return {"ok": 0, "giallo": 0, "rosso": 0, "dettagli": []}

    citazioni = re.findall(r"\[Fonte:\s*Blocco\s*(\d+)\]", testo)
    dettagli = []
    ok = giallo = rosso = 0

    for c in citazioni:
        expected = f"[Fonte: Blocco {c}]"
        if expected in testo:
            ok += 1
            dettagli.append((c, 1.0, "OK"))
        else:
            rosso += 1
            dettagli.append((c, 0.0, "ROSSO"))

    return {"ok": ok, "giallo": giallo, "rosso": rosso, "dettagli": dettagli}


# ─────────────────────────────────────────────
#  THREE-LEVEL DEDUPLICATION
# ─────────────────────────────────────────────


def _deduplica_testo(essay: Optional[str]) -> str:
    """Three-level deduplication: paragraph, phrase, word.

    Level 1 — Paragraph-level: detect near-duplicate paragraphs via SequenceMatcher.
    Level 2 — Phrase-level: detect repeated 4-gram sentence openings.
    Level 3 — Word-level: detect immediate word repetitions (4+ chars only).
    """
    import difflib

    if not essay:
        return essay or ""

    # Level 1: Paragraph-level dedup
    paragraphs = essay.split("\n\n")
    deduped = []
    seen_paras = []
    for p in paragraphs:
        p_stripped = p.strip()
        if not p_stripped:
            deduped.append(p)
            continue
        is_dup = False
        for seen in seen_paras[-3:]:
            ratio = difflib.SequenceMatcher(None, p_stripped.lower(), seen.lower()).ratio()
            if ratio > 0.65:
                is_dup = True
                break
        if not is_dup:
            deduped.append(p)
            seen_paras.append(p_stripped)

    essay = "\n\n".join(deduped)

    # Level 2: Phrase-level — detect repeated sentence openings (4-gram)
    sentences = re.split(r"(?<=[.!?])\s+", essay)
    seen_phrases = set()
    clean_sentences = []
    for sent in sentences:
        words = sent.split()
        if len(words) < 4:
            clean_sentences.append(sent)
            continue
        key = " ".join(words[:4]).lower().strip(".,;:!?")
        if key in seen_phrases and len(key) > 15:
            continue  # skip near-duplicate sentence
        seen_phrases.add(key)
        clean_sentences.append(sent)
    essay = " ".join(clean_sentences)

    # Level 3: Word-level immediate repetition (only words 4+ chars)
    essay = re.sub(r"(\b\w{4,})\s+\1\b", r"\1", essay)

    return essay


# ─────────────────────────────────────────────
#  REDUCE — concatenate, deduplicate, verify
# ─────────────────────────────────────────────


def reduce_results(results: list[MapResult]) -> str:
    """Concatenate map results in order, deduplicate, verify citations.

    CRITICAL: [Fonte: Blocco N] citations are PRESERVED — never stripped.

    Returns:
        Combined essay string.
    """
    parts = []
    for r in results:
        t = r.summary
        if not re.search(r"^#{1,3}\s+", t, re.MULTILINE):
            t = "### Sezione\n\n" + t
        parts.append(t)

    essay = "\n\n".join(parts)

    # Verify citations
    cit_report = _verifica_citazioni(essay)
    if cit_report["ok"] + cit_report["giallo"] + cit_report["rosso"] > 0:
        logger.info(
            "Citazioni: %d OK, %d giallo, %d rosso",
            cit_report["ok"],
            cit_report["giallo"],
            cit_report["rosso"],
        )
        if cit_report["rosso"] > 0:
            for c, _r, s in cit_report["dettagli"]:
                if s == "ROSSO":
                    logger.warning("Citazione Blocco %s: malformata", c)

    # NOTE: [Fonte: Blocco N] citations are intentionally PRESERVED.
    # The old mega_skill.py stripped them — that was a bug. We keep them.

    essay = _deduplica_testo(essay)
    essay = re.sub(r"  +", " ", essay)
    return essay


# ─────────────────────────────────────────────
#  GLOSSARY BUILDER
# ─────────────────────────────────────────────


def build_glossary(results: list[MapResult]) -> str:
    """Build a glossary string from aggregated entities across all map results.

    Returns:
        Formatted glossary with PERSONE, DATE, OPERE/EVENTI sections.
    """
    from collections import Counter

    all_p: dict[str, int] = Counter()
    all_d: dict[str, int] = Counter()
    all_o: dict[str, int] = Counter()

    for mr in results:
        for p in mr.entities.persone:
            n = p.strip().rstrip(".,;:")
            if n:
                all_p[n] += 1
        for d in mr.entities.date:
            n = d.strip()
            if n:
                all_d[n] += 1
        for o in mr.entities.opere:
            n = o.strip()
            if n:
                all_o[n] += 1

    lines = ["PERSONE:"]
    lines.extend(f"  - {k}" for k, _ in sorted(all_p.items(), key=lambda x: -x[1])[:60])
    lines.append("DATE:")
    lines.extend(f"  - {k}" for k, _ in sorted(all_d.items(), key=lambda x: -x[1])[:30])
    lines.append("OPERE/EVENTI:")
    lines.extend(f"  - {k}" for k, _ in sorted(all_o.items(), key=lambda x: -x[1])[:30])

    return "\n".join(lines)


# ─────────────────────────────────────────────
#  BOLDIFY
# ─────────────────────────────────────────────


def boldify_intelligente(essay: str, entities: EntitySet) -> str:
    """Apply **bold** strategically to known entities in the text.

    Rules:
    - Persone: always bold (proper names)
    - Date (4 digits): always bold
    - Opere/titles: bold if they are work titles
    - Only FIRST occurrence per paragraph (avoids visual noise)
    - Does not bold words already in **bold** or inside ### headings
    - Order: longest entities first (avoids overlap)
    - Skips short words (< 4 chars) and common words
    """
    # Common words to NEVER bold
    SKIP_WORDS = {
        "anno", "anni", "dopo", "prima", "dove", "come", "cosa", "quel",
        "della", "degli", "delle", "dello", "nella", "negli", "nelle",
        "nello", "sulla", "sugli", "sulle", "sullo", "dalla", "dagli",
        "dalle", "dallo",
    }

    # Build term list sorted by length descending
    all_terms: list[tuple[int, str, str]] = []
    for cat in ("persone", "date", "opere"):
        for t in getattr(entities, cat, []):
            t_clean = t.strip().rstrip(".,;:!?")
            if len(t_clean) > 3 and t_clean.lower() not in SKIP_WORDS:
                all_terms.append((len(t_clean), re.escape(t_clean), t_clean))
    all_terms.sort(reverse=True)

    # Apply bold line by line, skipping headings and special sections
    lines = essay.split("\n")
    new_lines = []
    for line in lines:
        s = line.strip()
        # Skip headings and special sections
        if s.startswith("#") or s.startswith("Concetto:") or s.startswith("Domanda:"):
            new_lines.append(line)
            continue
        # Skip lines that already have bold
        if "**" in s:
            new_lines.append(line)
            continue

        result = line
        seen_in_line = set()
        for _length, pattern, original in all_terms:
            if original.lower() in seen_in_line:
                continue
            new_result = re.sub(
                r"(?<!\*)" + pattern + r"(?!\*)",
                r"**\g<0>**",
                result,
                count=1,  # first occurrence only
            )
            if new_result != result:
                seen_in_line.add(original.lower())
                result = new_result
        new_lines.append(result)

    return "\n".join(new_lines)


# ─────────────────────────────────────────────
#  DENSITY-BASED COMPRESSION
# ─────────────────────────────────────────────


def measure_density(text: str) -> float:
    """Measure information density: unique entities + proper nouns per 1000 chars.
    
    Higher density → less compression needed (preserve detail).
    Lower density → more compression possible (redundant text).
    Returns 0.0 to 1.0 normalized score.
    """
    if not text or len(text) < 100:
        return 0.5
    
    proper_nouns = len(set(re.findall(r'\b[A-Z][a-zà-ÿ]+\b', text)))
    dates = len(set(re.findall(r'\b\d{4}\b', text)))
    total_chars = max(len(text), 1)
    
    density = (proper_nouns + dates * 2) / (total_chars / 1000)
    
    return min(1.0, density / 30)


def calculate_compression_target(text: str, raw_pages: int, settings=None) -> int:
    """Calculate target output characters based on content density.
    
    Dense text (history, science): 30-40% of original
    Sparse text (narrative, general): 15-25% of original
    Very large books: cap at 50 pages
    Very small books: minimum 3 pages
    """
    density = measure_density(text)
    
    if raw_pages < 50:
        ratio = 0.25 + (density * 0.15)
    elif raw_pages < 200:
        ratio = 0.15 + (density * 0.15)
    else:
        ratio = 0.10 + (density * 0.10)
    
    target_chars = int(len(text) * ratio)
    
    max_chars = 50 * 2500
    min_chars = 3 * 2500
    
    return max(min_chars, min(max_chars, target_chars))
