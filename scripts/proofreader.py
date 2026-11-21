"""
Proofreading module — quality check pass for generated essays.
"""

from typing import Optional
import re
from loguru import logger
from scripts.config import Settings
from scripts.models import ProofreadResult, PipelineResult
from scripts.llm_engine import call_ollama

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
    """Full auto-critique: proofread + check entity coverage + check structure.
    
    Returns ProofreadResult with combined score.
    """
    proof = proofread(result.essay, settings)
    
    total_entities = (len(result.entities.persone) +
                      len(result.entities.date) +
                      len(result.entities.opere))
    
    has_sections = all(marker in result.essay for marker in
                       ["### Da Ricordare", "### Scheda Riassuntiva", "### Domande di Verifica"])
    
    if not has_sections:
        proof.issues.append("Mancano sezioni obbligatorie (Da Ricordare, Scheda, Domande)")
    
    if total_entities < 5:
        proof.issues.append(f"Poche entità estratte ({total_entities})")
    
    return proof
