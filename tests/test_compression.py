import pytest
from scripts.llm_engine import measure_density, calculate_compression_target
from scripts.config import Settings


def test_dense_text():
    """History text with many unique proper nouns should have high density."""
    text = (
        "Monteverdi nel 1607 compose Orfeo per il Teatro Gonzaga di Mantova. "
        "Rossi nel 1642 compose Ulisse per il Teatro Vendramin di Venezia. "
        "Vivaldi nel 1713 compose Ottone per il Teatro Sant'Angelo di Venezia. "
        "Handel nel 1724 compose Giulio Cesare per il Teatro Haymarket di Londra. "
        "Mozart nel 1786 compose Figaro per il Teatro Nazionale di Praga. "
        "Wagner nel 1876 compose Anello per il Teatro Festspielhaus di Bayreuth. "
        "Verdi nel 1851 compose Rigoletto per il Teatro Fenice di Venezia. "
        "Puccini nel 1900 compose Tosca per il Teatro Costanzi di Roma. "
        "Stravinsky nel 1913 compose Sagra per il Teatro Champs-Elysees di Parigi. "
        "Britten nel 1945 compose Peter Grimes per il Teatro Sadler Wells di Londra. "
    )
    density = measure_density(text)
    assert density > 0.3


def test_sparse_text():
    """Generic narrative should have lower density."""
    text = "Il libro parla di molte cose interessanti e importanti. " * 20
    density = measure_density(text)
    assert density < 0.3


def test_compression_small_book():
    text = "Contenuto. " * 500
    settings = Settings()
    target = calculate_compression_target(text, 2, settings)
    assert target >= 3 * 2500


def test_compression_large_book():
    text = "Contenuto. " * 50000
    settings = Settings()
    target = calculate_compression_target(text, 200, settings)
    assert target <= 50 * 2500


def test_empty_text():
    density = measure_density("")
    assert density == 0.5
