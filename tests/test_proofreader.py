"""
Tests for the proofreader module.
"""

import pytest
from scripts.models import ProofreadResult, PipelineResult, EntitySet
from scripts.config import Settings


def test_proofread_result_defaults():
    r = ProofreadResult(score=85)
    assert r.score == 85
    assert r.issues == []
    assert r.suggestions == []


def test_proofread_result_with_issues():
    r = ProofreadResult(score=60, issues=["Manca conclusione"], suggestions=["Aggiungere conclusione"])
    assert len(r.issues) == 1
    assert "conclusione" in r.issues[0]


def test_proofread_result_with_multiple_issues():
    r = ProofreadResult(
        score=40,
        issues=["Manca conclusione", "Sezioni disordinate", "Poche entità"],
        suggestions=["Aggiungere conclusione", "Riordinare sezioni", "Estrarre più entità"],
    )
    assert r.score == 40
    assert len(r.issues) == 3
    assert len(r.suggestions) == 3


def test_proofread_result_score_bounds():
    r_low = ProofreadResult(score=0)
    r_high = ProofreadResult(score=100)
    assert r_low.score == 0
    assert r_high.score == 100


def test_auto_critique_detects_missing_sections(monkeypatch):
    """auto_critique should flag missing mandatory sections."""
    from scripts.proofreader import auto_critique

    # Mock proofread to return a clean result
    def mock_proofread(essay, settings):
        return ProofreadResult(score=90)

    monkeypatch.setattr("scripts.proofreader.proofread", mock_proofread)

    result = PipelineResult(
        essay="Testo senza sezioni obbligatorie.",
        entities=EntitySet(persone=["Rossi"], date=["1900"], opere=["Libro"]),
        total_chunks=3,
        processed_chunks=3,
        coverage=95.0,
    )
    settings = Settings()

    proof = auto_critique(result, settings)
    assert any("Mancano sezioni obbligatorie" in i for i in proof.issues)


def test_auto_critique_detects_few_entities(monkeypatch):
    """auto_critique should flag when too few entities are extracted."""
    from scripts.proofreader import auto_critique

    def mock_proofread(essay, settings):
        return ProofreadResult(score=90)

    monkeypatch.setattr("scripts.proofreader.proofread", mock_proofread)

    result = PipelineResult(
        essay="### Da Ricordare\n### Scheda Riassuntiva\n### Domande di Verifica\nTesto.",
        entities=EntitySet(persone=[], date=[], opere=[]),
        total_chunks=2,
        processed_chunks=2,
        coverage=90.0,
    )
    settings = Settings()

    proof = auto_critique(result, settings)
    assert any("Poche entità" in i for i in proof.issues)


def test_auto_critique_passes_with_good_input(monkeypatch):
    """auto_critique should return clean result when everything is fine."""
    from scripts.proofreader import auto_critique

    def mock_proofread(essay, settings):
        return ProofreadResult(score=95)

    monkeypatch.setattr("scripts.proofreader.proofread", mock_proofread)

    result = PipelineResult(
        essay="### Da Ricordare\n### Scheda Riassuntiva\n### Domande di Verifica\nTesto completo.",
        entities=EntitySet(
            persone=["Rossi", "Bianchi", "Verdi", "Neri", "Gialli"],
            date=["1900", "1920", "1950"],
            opere=["Libro A", "Libro B"],
        ),
        total_chunks=5,
        processed_chunks=5,
        coverage=98.0,
    )
    settings = Settings()

    proof = auto_critique(result, settings)
    # Should have no additional issues from auto_critique
    assert len(proof.issues) == 0
    assert proof.score == 95
