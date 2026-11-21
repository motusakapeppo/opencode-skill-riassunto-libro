"""
Tests for the adaptive prompt system (ContentType detection and templates).
"""

import pytest
from scripts.llm_engine import detect_content_type, ContentType, get_prompt_template


class TestDetectContentType:
    def test_detect_history(self):
        text = "Il Seicento fu un secolo di guerre e rivoluzioni. Il regno di Luigi XIV rappresenta un periodo storico di grande importanza per la civiltà europea."
        assert detect_content_type(text) == ContentType.HISTORY

    def test_detect_science(self):
        text = "La teoria della relatività si basa su esperimenti e formule matematiche. I dati raccolti in laboratorio confermano l'ipotesi iniziale."
        assert detect_content_type(text) == ContentType.SCIENCE

    def test_detect_art(self):
        text = "La pittura barocca si caratterizza per l'uso drammatico del colore e della luce. Compositori come Monteverdi rivoluzionarono la musica."
        assert detect_content_type(text) == ContentType.ART

    def test_detect_philosophy(self):
        text = "Il concetto di ragione è centrale nella filosofia. La dialettica hegeliana analizza l'essere e il pensiero come unità."
        assert detect_content_type(text) == ContentType.PHILOSOPHY

    def test_detect_literature(self):
        text = "Il romanzo moderno si sviluppa attraverso personaggi complessi e una narrativa ricca di metafore. Il protagonista incarna i temi centrali."
        assert detect_content_type(text) == ContentType.LITERATURE

    def test_detect_general(self):
        text = "Oggi è una bella giornata. Il sole splende e gli uccelli cantano."
        assert detect_content_type(text) == ContentType.GENERAL

    def test_empty_string(self):
        assert detect_content_type("") == ContentType.GENERAL

    def test_short_text(self):
        text = "Ciao mondo."
        assert detect_content_type(text) == ContentType.GENERAL

    def test_mixed_keywords_history_wins(self):
        """When multiple types match, the one with highest score wins."""
        text = (
            "La guerra dei cent'anni fu un conflitto storico. "
            "Il regno di Francia combatté contro l'Inghilterra. "
            "Questa antica civiltà medievale firmò un trattato di pace."
        )
        # "guerra", "storico", "regno", "antico", "medievale", "trattato", "pace" → HISTORY wins
        assert detect_content_type(text) == ContentType.HISTORY


class TestGetPromptTemplate:
    def test_history_italian(self):
        template = get_prompt_template(ContentType.HISTORY, "it")
        assert "storico" in template.lower()
        assert "{testo}" in template

    def test_science_italian(self):
        template = get_prompt_template(ContentType.SCIENCE, "it")
        assert "scientifico" in template.lower()
        assert "{testo}" in template

    def test_art_italian(self):
        template = get_prompt_template(ContentType.ART, "it")
        assert "arte" in template.lower() or "critico" in template.lower()
        assert "{testo}" in template

    def test_philosophy_italian(self):
        template = get_prompt_template(ContentType.PHILOSOPHY, "it")
        assert "filosofo" in template.lower()
        assert "{testo}" in template

    def test_literature_italian(self):
        template = get_prompt_template(ContentType.LITERATURE, "it")
        assert "letterario" in template.lower()
        assert "{testo}" in template

    def test_general_italian(self):
        template = get_prompt_template(ContentType.GENERAL, "it")
        assert "Riscrivi" in template
        assert "{testo}" in template

    def test_english_fallback(self):
        template = get_prompt_template(ContentType.SCIENCE, "en")
        assert "Rewrite" in template
        assert "{testo}" in template

    def test_unknown_type_fallsback_to_general(self):
        template = get_prompt_template(ContentType.GENERAL, "it")
        assert "Riscrivi" in template
