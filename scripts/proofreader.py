"""
Proofreading module — quality check pass for generated essays.
"""

from typing import Optional
import re
from loguru import logger
from scripts.config import Settings
from scripts.models import ProofreadResult, PipelineResult
from scripts.llm_engine import call_ollama
from scripts.style import analyse_style

PROOFREAD_PROMPT = """Verifica la qualità del seguente saggio riassuntivo.

Criteri di valutazione (0-100 ciascuno):
1. COERENZA: Il testo è logicamente coerente? Le transizioni sono fluide?
2. COMPLETEZZA: Tutti i concetti principali del testo originale sono coperti?
3. CHIAREZZA: Il linguaggio è semplice e comprensibile?
4. ERRORI: Ci sono errori fattuali, contraddizioni o refusi?
5. STRUTTURA: I titoli e le sezioni sono ben organizzati?

Rispondi nel formato:
COERENZA: X/100
COMPLETEZZA: X/100
CHIAREZZA: X/100
ERRORI: X/100 (più alto = meno errori)
STRUTTURA: X/100
PUNTEGGIO_TOTALE: X/100
ISSUES: elenco separato da |
SUGGESTIONS: elenco separato da |

SAGGIO:
{essay}"""


def proofread(essay: str, settings: Settings) -> ProofreadResult:
    """Run proofreading pass on the essay.
    
    Returns ProofreadResult with score, issues, and suggestions.
    """
    prompt = PROOFREAD_PROMPT.replace("{essay}", essay[:8000])
    
    content = call_ollama(
        settings.model_proofread,
        prompt,
        settings,
        num_ctx=16384,
        temperature=0.1,
        timeout=120,
    )
    
    if not content:
        return ProofreadResult(score=100)    
    score_match = re.search(r"PUNTEGGIO_TOTALE:\s*(\d+)", content)
    score = int(score_match.group(1)) if score_match else 100
    
    issues_match = re.search(r"ISSUES:\s*(.*)", content)
    issues = [i.strip() for i in issues_match.group(1).split("|") if i.strip()] if issues_match else []
    
    suggestions_match = re.search(r"SUGGESTIONS:\s*(.*)", content)
    suggestions = [s.strip() for s in suggestions_match.group(1).split("|") if s.strip()] if suggestions_match else []
    
    return ProofreadResult(score=score, issues=issues, suggestions=suggestions)


def auto_critique(result: PipelineResult, settings: Settings) -> ProofreadResult:
    """Full auto-critique: LLM proofread + deterministic style gate + coverage.

    The style gate is measured, not judged by the model: a document that is
    structurally an outline cannot score above 40, whatever the prose says.
    """
    proof = proofread(result.essay, settings)

    style = getattr(settings, "style", "prose")
    stats = analyse_style(result.essay)
    proof.style = stats.as_dict()

    total_entities = (len(result.entities.persone) +
                      len(result.entities.date) +
                      len(result.entities.opere))

    has_sections = all(marker in result.essay for marker in
                       ["### Da Ricordare", "### Scheda Riassuntiva", "### Domande di Verifica"])

    if not has_sections:
        proof.issues.append("Mancano sezioni obbligatorie (Da Ricordare, Scheda, Domande)")

    if total_entities < 5:
        proof.issues.append(f"Poche entità estratte ({total_entities})")

    if style == "prose":
        if stats.is_bullet_dump():
            proof.must_rewrite = True
            proof.score = min(proof.score, 40)
            proof.issues.append(
                "Bullet dump: "
                f"{stats.bullet_lines}/{stats.lines} righe di elenco "
                f"({stats.bullet_ratio:.1%}), {stats.lists} elenchi "
                f"({stats.lists_per_1000_words:.1f} ogni 1000 parole). "
                "Serve una riscrittura in prosa (max 40/100)."
            )
        if stats.label_headings:
            proof.score = min(proof.score, 70)
            proof.issues.append(
                f"{stats.label_headings} titoli-etichetta da eliminare "
                "(### Introduzione, ### Concetti chiave, ### Esempi)"
            )
        if stats.bibliographic > 3:
            proof.score = min(proof.score, 75)
            proof.issues.append(
                f"{stats.bibliographic} metadati bibliografici trascritti "
                "(ISSN/DOI/ISBN/pagine): i contenuti vanno raccontati, non citati"
            )
        if stats.paragraphs and stats.short_paragraphs > max(3, stats.paragraphs // 5):
            proof.score = min(proof.score, 80)
            proof.issues.append(
                f"{stats.short_paragraphs} paragrafi sotto le 25 parole: "
                "il contratto chiede 3-6 frasi per paragrafo"
            )

    return proof
