import pytest
from pathlib import Path
from scripts.extractor import _tripla_soglia, estrai_metadati


def test_tripla_soglia_scan():
    # Short tokens with many non-alpha chars: avg_len < 3.5, ratio_alf < 0.4, parole < 100
    garbage = "a12 b34 c56 d78 e90 " * 15
    is_scan, metrics = _tripla_soglia(garbage)
    assert is_scan is True
    assert metrics["sotto_soglia"] >= 2


def test_tripla_soglia_real_text():
    text = """Il Seicento rappresenta un periodo di straordinaria fioritura per il teatro musicale. 
    Venezia diventa il centro indiscusso della produzione operistica, con l'apertura del primo 
    teatro pubblico a pagamento, il Teatro San Cassiano, nel 1637. Claudio Monteverdi, 
    già affermato compositore mantovano, si trasferisce nella città lagunare e contribuisce 
    in modo determinante allo sviluppo del nuovo genere."""
    is_scan, metrics = _tripla_soglia(text)
    assert is_scan is False


def test_estrai_metadati_nonexistent():
    title, author = estrai_metadati("nonexistent.pdf")
    assert "nonexistent.pdf" in title
    assert author == "Autore sconosciuto"


def test_tripla_soglia_empty():
    is_scan, metrics = _tripla_soglia("")
    assert is_scan is True
    assert metrics["sotto_soglia"] == 3


def test_tripla_soglia_whitespace():
    is_scan, metrics = _tripla_soglia("   \n\n   ")
    assert is_scan is True
    assert metrics["sotto_soglia"] == 3


def test_tripla_soglia_short_text():
    """Very short text should trigger scan detection (soglia_a: parole < 100)."""
    text = "Ciao mondo. Questo è un test breve."
    is_scan, metrics = _tripla_soglia(text)
    # parole < 100 → True, but rapporto_alf should be high, media_parola should be > 3.5
    # So only 1/3 under threshold → not a scan
    assert metrics["parole"] < 100  # confirm soglia_a triggers
    assert metrics["rapporto_alf"] > 0.4  # soglia_b should NOT trigger
    assert is_scan is False  # only 1/3


def test_tripla_soglia_metrics_structure():
    text = "Some reasonable text with enough words to check metrics."
    is_scan, metrics = _tripla_soglia(text)
    assert "parole" in metrics
    assert "rapporto_alf" in metrics
    assert "media_parola" in metrics
    assert "sotto_soglia" in metrics
    assert 0 <= metrics["sotto_soglia"] <= 3
