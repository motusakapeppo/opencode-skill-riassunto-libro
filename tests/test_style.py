"""Style contract tests: the essay must be measurable prose, not an outline."""

import pytest

from scripts.config import Settings
from scripts.models import EntitySet, PipelineResult, ProofreadResult
from scripts.style import (
    StyleViolation,
    analyse_style,
    enforce_prose,
    strip_bullet_markup,
)

PROSE = (
    "Il mercato dell'opera nasce a Venezia nel 1637, quando il Teatro San Cassiano "
    "apre le porte a un pubblico pagante. Per questo i compositori cominciano a "
    "scrivere per un gusto condiviso, non per una corte. Di conseguenza la brevita' "
    "delle arie diventa una necessita' economica oltre che estetica. "
    "Allo stesso tempo il libretto si professionalizza e nasce una figura nuova, "
    "quella del poeta stipendiato dall'impresario.\n\n"
    "Piu' avanti il modello veneziano si diffonde in tutta Europa. "
    "Le compagnie viaggiano, i cantanti diventano star, e ogni citta' adatta il "
    "repertorio al proprio pubblico.\n\n"
    "### Da Ricordare\n"
    "**Teatro San Cassiano** — primo teatro pubblico a pagamento.\n\n"
    "### Scheda Riassuntiva\n"
    "Concetto: mercato dell'opera - la musica diventa impresa commerciale.\n\n"
    "### Domande di Verifica\n"
    "Domanda: perche' nasce a Venezia? - perche' c'e' un pubblico pagante.\n"
)

BULLET_DUMP = "\n".join(
    [
        "### Introduzione",
        "- il mercato dell'opera nasce nel 1637",
        "- il teatro San Cassiano e' il primo pubblico",
        "- Monteverdi si trasferisce a Venezia",
        "### Concetti chiave",
        "- brevita' delle arie",
        "- frequenza dei cambi di scena",
        "1. il libretto si professionalizza",
        "2. nasce la figura dell'impresario",
    ] * 3
)


def test_prose_passes_the_gate():
    stats = analyse_style(PROSE)
    assert not stats.is_bullet_dump()
    assert stats.paragraphs >= 2
    assert stats.label_headings == 0


def test_bullet_dump_is_detected():
    stats = analyse_style(BULLET_DUMP)
    assert stats.bullet_lines >= 20
    assert stats.is_bullet_dump()
    assert stats.lists >= 3
    assert stats.label_headings >= 2


def test_label_headings_and_bibliography():
    text = (
        "### Introduzione\n"
        "Un paragrafo qualsiasi con abbastanza parole per contare come prosa vera "
        "e non come riga isolata di un elenco.\n\n"
        "Rivista di musicologia, ISSN 1234-5678, pp. 44-51, vol. II.\n"
        "DOI 10.1234/abc.\n"
    )
    stats = analyse_style(text)
    assert stats.label_headings == 1
    assert stats.bibliographic >= 3


def test_minor_list_is_converted_not_rejected():
    text = "Un paragrafo introduttivo abbastanza lungo da non sembrare un elenco.\n\n- primo punto\n- secondo punto\n"
    out, stats = enforce_prose(text, Settings(style="prose"))
    assert stats.bullet_lines == 2
    assert "- " not in out
    assert "primo punto." in out and "secondo punto." in out


def test_dump_raises_style_violation():
    with pytest.raises(StyleViolation) as exc:
        enforce_prose(BULLET_DUMP, Settings(style="prose"))
    assert "elenco" in str(exc.value)


def test_notes_mode_is_left_alone():
    out, _stats = enforce_prose(BULLET_DUMP, Settings(style="notes"))
    assert out == BULLET_DUMP


def test_strip_bullet_markup_keeps_numbered_items():
    out = strip_bullet_markup("1. primo\n2. secondo\n")
    assert "1." not in out
    assert out.strip() == "primo. secondo."


def test_auto_critique_caps_score_on_bullet_dump(monkeypatch):
    from scripts.proofreader import auto_critique

    monkeypatch.setattr(
        "scripts.proofreader.proofread",
        lambda essay, settings: ProofreadResult(score=95),
    )
    result = PipelineResult(
        essay=BULLET_DUMP,
        entities=EntitySet(persone=["a", "b", "c"], date=["1", "2"], opere=["x"]),
        total_chunks=1,
        processed_chunks=1,
        coverage=100,
    )
    proof = auto_critique(result, Settings(style="prose"))

    assert proof.must_rewrite is True
    assert proof.score <= 40
    assert any("Bullet dump" in i for i in proof.issues)
    assert proof.style["bullet_ratio"] > 0.03


def test_auto_critique_keeps_score_on_prose(monkeypatch):
    from scripts.proofreader import auto_critique

    monkeypatch.setattr(
        "scripts.proofreader.proofread",
        lambda essay, settings: ProofreadResult(score=88),
    )
    result = PipelineResult(
        essay=PROSE,
        entities=EntitySet(persone=["a", "b", "c"], date=["1", "2"], opere=["x"]),
        total_chunks=1,
        processed_chunks=1,
        coverage=100,
    )
    proof = auto_critique(result, Settings(style="prose"))
    assert proof.must_rewrite is False
    assert proof.score == 88


def test_render_refuses_bullet_dump():
    from scripts.renderer import render_pdf
    from scripts.design_system import DesignSpec

    with pytest.raises(StyleViolation):
        render_pdf(BULLET_DUMP, "unused.pdf", DesignSpec(), Settings(style="prose"))
