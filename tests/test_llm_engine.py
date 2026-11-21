"""
Tests for the unified LLM engine module.
"""

import pytest
from scripts.llm_engine import (
    _deduplica_testo,
    _verifica_citazioni,
    boldify_intelligente,
    _contiene_skip,
    _parse_entities,
    estimate_tokens,
    build_glossary,
    reduce_results,
)
from scripts.models import EntitySet, MapResult
from scripts.config import Settings


# ─────────────────────────────────────────────
#  _contiene_skip
# ─────────────────────────────────────────────

class TestContieneSkip:
    def test_none(self):
        assert _contiene_skip(None) is True

    def test_empty(self):
        assert _contiene_skip("") is True

    def test_skip_marker(self):
        assert _contiene_skip("[SKIP] some text") is True

    def test_nessun_contenuto(self):
        assert _contiene_skip("[NESSUN CONTENUTO UTILE]") is True

    def test_normal_text(self):
        assert _contiene_skip("Testo normale") is False


# ─────────────────────────────────────────────
#  _parse_entities
# ─────────────────────────────────────────────

class TestParseEntities:
    def test_italian(self):
        content = """Riassunto del testo.

===ENTITA===
PERSONE: Monteverdi | Rossi
DATE: 1607 | 1642
OPERE/EVENTI: Orfeo | Ritorno di Ulisse
===FINE ENTITA==="""
        clean, entities = _parse_entities(content, lang="it")
        assert "Riassunto del testo." in clean
        assert entities.persone == ["Monteverdi", "Rossi"]
        assert entities.date == ["1607", "1642"]
        assert entities.opere == ["Orfeo", "Ritorno di Ulisse"]

    def test_english(self):
        content = """Summary text.

===ENTITIES===
PEOPLE: Monteverdi | Rossi
DATES: 1607 | 1642
WORKS: Orfeo | Return of Ulysses
===END ENTITIES==="""
        clean, entities = _parse_entities(content, lang="en")
        assert "Summary text." in clean
        assert entities.persone == ["Monteverdi", "Rossi"]
        assert entities.date == ["1607", "1642"]
        assert entities.opere == ["Orfeo", "Return of Ulysses"]

    def test_no_entity_block(self):
        content = "Solo testo senza entità."
        clean, entities = _parse_entities(content, lang="it")
        assert clean == "Solo testo senza entità."
        assert entities.persone == []
        assert entities.date == []
        assert entities.opere == []


# ─────────────────────────────────────────────
#  estimate_tokens
# ─────────────────────────────────────────────

class TestEstimateTokens:
    def test_empty(self):
        assert estimate_tokens("") == 0

    def test_rough_estimate(self):
        # 100 chars / 4 = 25 tokens
        assert estimate_tokens("a" * 100) == 25


# ─────────────────────────────────────────────
#  _deduplica_testo
# ─────────────────────────────────────────────

class TestDedup:
    def test_dedup_paragraph(self):
        text = "Paragrafo uno.\n\nParagrafo uno.\n\nParagrafo due."
        result = _deduplica_testo(text)
        assert result.count("Paragrafo uno") == 1

    def test_dedup_sentence_opening(self):
        text = "Il Seicento rappresenta un periodo importante. Il Seicento rappresenta un periodo di grandi cambiamenti."
        result = _deduplica_testo(text)
        assert "Il Seicento rappresenta" in result

    def test_dedup_word_repetition(self):
        text = "Questo è un esempio esempio di ripetizione."
        result = _deduplica_testo(text)
        assert "esempio esempio" not in result

    def test_empty(self):
        assert _deduplica_testo("") == ""

    def test_none(self):
        assert _deduplica_testo(None) == ""

    def test_no_duplicates(self):
        text = "Monteverdi nacque a Cremona.\n\nL'opera buffa napoletana fiorì nel Settecento.\n\nVenezia aveva sedici teatri."
        result = _deduplica_testo(text)
        # All three distinct paragraphs are preserved
        assert "Monteverdi nacque a Cremona" in result
        assert "opera buffa napoletana" in result
        assert "Venezia aveva sedici teatri" in result


# ─────────────────────────────────────────────
#  _verifica_citazioni
# ─────────────────────────────────────────────

class TestVerificaCitazioni:
    def test_ok(self):
        text = "Testo con [Fonte: Blocco 1] citazione."
        report = _verifica_citazioni(text)
        assert report["ok"] == 1
        assert report["rosso"] == 0

    def test_multiple_ok(self):
        text = "Prima [Fonte: Blocco 1] e seconda [Fonte: Blocco 2]."
        report = _verifica_citazioni(text)
        assert report["ok"] == 2
        assert report["rosso"] == 0

    def test_missing(self):
        text = "Testo senza citazioni."
        report = _verifica_citazioni(text)
        assert report["ok"] == 0
        assert report["rosso"] == 0

    def test_none(self):
        report = _verifica_citazioni(None)
        assert report["ok"] == 0
        assert report["rosso"] == 0

    def test_empty(self):
        report = _verifica_citazioni("")
        assert report["ok"] == 0
        assert report["rosso"] == 0

    def test_malformed(self):
        """A citation reference that doesn't match the expected format."""
        text = "Testo con [Fonte: Blocco X]"
        report = _verifica_citazioni(text)
        # "X" is not a digit, so re.findall won't match it
        assert report["ok"] == 0
        assert report["rosso"] == 0


# ─────────────────────────────────────────────
#  boldify_intelligente
# ─────────────────────────────────────────────

class TestBoldify:
    def test_simple(self):
        essay = "Monteverdi compose l'Orfeo."
        entities = EntitySet(persone=["Monteverdi"], opere=["Orfeo"])
        result = boldify_intelligente(essay, entities)
        assert "**Monteverdi**" in result
        assert "**Orfeo**" in result

    def test_skip_headings(self):
        essay = "### Introduzione\n\nMonteverdi compose l'Orfeo."
        entities = EntitySet(persone=["Monteverdi"])
        result = boldify_intelligente(essay, entities)
        assert "### Introduzione" in result
        assert "**Monteverdi**" in result

    def test_skip_already_bold(self):
        essay = "**Monteverdi** compose l'Orfeo."
        entities = EntitySet(persone=["Monteverdi"])
        result = boldify_intelligente(essay, entities)
        # Should not double-bold
        assert result.count("**Monteverdi**") == 1

    def test_first_occurrence_only(self):
        essay = "Monteverdi scrisse l'Orfeo. Monteverdi era un compositore."
        entities = EntitySet(persone=["Monteverdi"])
        result = boldify_intelligente(essay, entities)
        assert result.count("**Monteverdi**") == 1

    def test_skip_short_words(self):
        essay = "Il re andò a Roma."
        entities = EntitySet(persone=["re"])
        result = boldify_intelligente(essay, entities)
        assert "**re**" not in result  # too short

    def test_skip_common_words(self):
        essay = "Nella città di Venezia."
        entities = EntitySet(persone=["nella"])
        result = boldify_intelligente(essay, entities)
        assert "**nella**" not in result  # in SKIP_WORDS

    def test_date_bold(self):
        essay = "Nel 1637 aprì il primo teatro."
        entities = EntitySet(date=["1637"])
        result = boldify_intelligente(essay, entities)
        assert "**1637**" in result

    def test_empty_entities(self):
        essay = "Testo senza entità."
        entities = EntitySet()
        result = boldify_intelligente(essay, entities)
        assert result == essay

    def test_skip_concetto_line(self):
        essay = "Concetto: Monteverdi - compositore importante.\n\nTesto normale."
        entities = EntitySet(persone=["Monteverdi"])
        result = boldify_intelligente(essay, entities)
        # "Concetto:" line should be skipped entirely
        assert "**Monteverdi**" not in essay.split("\n")[0]


# ─────────────────────────────────────────────
#  build_glossary
# ─────────────────────────────────────────────

class TestBuildGlossary:
    def test_basic(self):
        results = [
            MapResult(
                chunk_id=0,
                summary="Test",
                entities=EntitySet(
                    persone=["Monteverdi", "Rossi"],
                    date=["1607"],
                    opere=["Orfeo"],
                ),
                token_count=10,
            ),
            MapResult(
                chunk_id=1,
                summary="Test 2",
                entities=EntitySet(
                    persone=["Monteverdi"],
                    date=["1642"],
                    opere=["Ritorno di Ulisse"],
                ),
                token_count=10,
            ),
        ]
        glossary = build_glossary(results)
        assert "Monteverdi" in glossary
        assert "Rossi" in glossary
        assert "1607" in glossary
        assert "1642" in glossary
        assert "Orfeo" in glossary
        assert "Ritorno di Ulisse" in glossary

    def test_empty(self):
        glossary = build_glossary([])
        assert "PERSONE:" in glossary
        assert "DATE:" in glossary
        assert "OPERE/EVENTI:" in glossary


# ─────────────────────────────────────────────
#  reduce_results
# ─────────────────────────────────────────────

class TestReduceResults:
    def test_basic(self):
        results = [
            MapResult(chunk_id=0, summary="Primo chunk.", entities=EntitySet(), token_count=5),
            MapResult(chunk_id=1, summary="Secondo chunk.", entities=EntitySet(), token_count=5),
        ]
        essay = reduce_results(results)
        assert "Primo chunk." in essay
        assert "Secondo chunk." in essay

    def test_preserves_citations(self):
        """CRITICAL: [Fonte: Blocco N] must NOT be stripped."""
        results = [
            MapResult(
                chunk_id=0,
                summary="Testo con [Fonte: Blocco 1] citazione.",
                entities=EntitySet(),
                token_count=10,
            ),
        ]
        essay = reduce_results(results)
        assert "[Fonte: Blocco 1]" in essay, "Citations must be preserved!"

    def test_prose_mode_adds_no_synthetic_heading(self):
        """Prose mode must not inject "### Sezione": repeated label headings are
        exactly what turned the essay into an outline."""
        results = [
            MapResult(chunk_id=0, summary="Testo senza heading.", entities=EntitySet(), token_count=5),
        ]
        essay = reduce_results(results, Settings(style="prose"))
        assert "### Sezione" not in essay
        assert "[[BLOCCO 1]]" in essay

    def test_notes_mode_keeps_heading(self):
        results = [
            MapResult(chunk_id=0, summary="Testo senza heading.", entities=EntitySet(), token_count=5),
        ]
        essay = reduce_results(results, Settings(style="notes"))
        assert "### Sezione" in essay

    def test_strips_per_chunk_extras(self):
        """Sections emitted by a chunk must not reach the merged essay."""
        results = [
            MapResult(
                chunk_id=0,
                summary=(
                    "Prosa sul mercato dell'opera. [Fonte: Blocco 1]\n\n"
                    "### Da Ricordare\n**Teatro** — spazio pagante.\n\n"
                    "### Glossario\n**Libretto** — testo dell'opera."
                ),
                entities=EntitySet(),
                token_count=20,
            ),
        ]
        essay = reduce_results(results, Settings(style="prose"))
        assert "Prosa sul mercato dell'opera." in essay
        assert "Da Ricordare" not in essay
        assert "Glossario" not in essay
        assert "[Fonte: Blocco 1]" in essay

    def test_merges_repeated_headings(self):
        results = [
            MapResult(chunk_id=0, summary="### Venezia\nPrima parte.", entities=EntitySet(), token_count=5),
            MapResult(chunk_id=1, summary="### Venezia\nSeconda parte.", entities=EntitySet(), token_count=5),
        ]
        essay = reduce_results(results, Settings(style="prose"))
        assert essay.count("### Venezia") == 1
        assert "Prima parte." in essay and "Seconda parte." in essay

    def test_deduplicates(self):
        results = [
            MapResult(chunk_id=0, summary="Stesso testo.\n\nStesso testo.", entities=EntitySet(), token_count=10),
        ]
        essay = reduce_results(results)
        assert essay.count("Stesso testo") == 1
