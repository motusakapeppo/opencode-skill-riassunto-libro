"""Synthesis pass: folding, marker handling, fallbacks — no API calls."""

from scripts.config import Settings
from scripts import llm_engine
from scripts.llm_engine import (
    BLOCK_MARKER,
    _split_blocks,
    synthesize_essay,
    repair_prose,
    strip_block_markers,
    strip_extra_sections,
)


def test_strip_block_markers():
    text = f"{BLOCK_MARKER.format(n=1)}\n\nPrimo.\n\n{BLOCK_MARKER.format(n=2)}\n\nSecondo."
    assert strip_block_markers(text) == "Primo.\n\nSecondo."


def test_split_blocks_respects_budget():
    text = "\n\n".join(
        f"{BLOCK_MARKER.format(n=i)}\n\n" + ("parola " * 200) for i in range(1, 7)
    )
    groups = _split_blocks(text, 100)          # 200 words ≈ 300 tokens per block
    assert len(groups) == 6
    for g in groups:
        assert g.count("[[BLOCCO") == 1


def test_split_blocks_groups_small_ones():
    text = "\n\n".join(f"{BLOCK_MARKER.format(n=i)}\n\nbreve" for i in range(1, 5))
    groups = _split_blocks(text, 10_000)
    assert len(groups) == 1


def test_concat_mode_just_strips_markers():
    settings = Settings(reduce_mode="concat")
    draft = f"{BLOCK_MARKER.format(n=1)}\n\nProsa uno.\n\n{BLOCK_MARKER.format(n=2)}\n\nProsa due."
    out = synthesize_essay(draft, settings)
    assert "[[BLOCCO" not in out
    assert "Prosa uno." in out and "Prosa due." in out


def test_llm_mode_calls_final_prompt_and_strips_markers(monkeypatch):
    calls = []

    def fake_reduce_call(template, draft, settings, target):
        calls.append(template[:40])
        return f"{BLOCK_MARKER.format(n=1)}\n\nSaggio riscritto in prosa."

    monkeypatch.setattr(llm_engine, "_reduce_call", fake_reduce_call)
    out = synthesize_essay("bozza", Settings(reduce_mode="llm"))

    assert out == "Saggio riscritto in prosa."
    assert len(calls) == 1                    # short draft: one final pass
    assert "{stile}" in llm_engine.PROMPT_REDUCE_FINAL_IT
    assert "CONTRATTO DI STILE" in llm_engine.STILE_COMUNE_IT


def test_llm_mode_falls_back_to_draft(monkeypatch):
    monkeypatch.setattr(llm_engine, "_reduce_call", lambda *a, **k: None)
    out = synthesize_essay(f"{BLOCK_MARKER.format(n=1)}\n\nBozza salvata.", Settings())
    assert out == "Bozza salvata."


def test_repair_prose_returns_none_on_empty(monkeypatch):
    monkeypatch.setattr(llm_engine, "_reduce_call", lambda *a, **k: "")
    assert repair_prose("testo", Settings()) is None


def test_strip_extra_sections_is_case_insensitive():
    text = "Prosa.\n\n### da ricordare\n**A** — b.\n\n### Glossario\n**C** — d."
    assert strip_extra_sections(text) == "Prosa."
