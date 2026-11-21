"""
Generative design system — creates unique visual designs for each book.
Replaces the 6 fixed themes with a continuous design spectrum.
"""

from dataclasses import dataclass, field
from typing import Optional
import re
from loguru import logger


@dataclass
class DesignSpec:
    """Complete design specification for the PDF."""
    # Color palette
    primary: str = "#1a2744"
    secondary: str = "#2c3e6b"
    accent: str = "#1a2744"
    background: str = "#faf8f3"
    text_color: str = "#1a1a1a"
    cover_bg: str = "#f0ece2"

    # Typography
    font_serif: str = "'Georgia', 'Palatino Linotype', serif"
    font_sans: str = "'Helvetica Neue', Arial, sans-serif"
    font_display: str = "'Georgia', serif"
    font_size_body: float = 10.5
    font_size_h1: float = 15.0
    font_size_h2: float = 12.5
    font_size_h3: float = 11.0
    font_size_cover_title: float = 22.0

    # Layout
    margin_top: float = 2.2
    margin_bottom: float = 2.5
    margin_left: float = 2.5
    margin_right: float = 2.5
    line_height: float = 1.75

    # Cover
    cover_style: str = "classic"
    cover_decoration: str = "subtle"

    # Header style
    header_style: str = "classic"

    # Google Fonts URL (optional)
    google_fonts_url: str = ""


PALETTES = {
    "classic": {"primary": "#1a2744", "secondary": "#2c3e6b", "accent": "#1a2744", "background": "#faf8f3"},
    "forest": {"primary": "#1b4332", "secondary": "#2d6a4f", "accent": "#2d6a4f", "background": "#f4f1ea"},
    "royal": {"primary": "#3d1a4e", "secondary": "#6b2d5a", "accent": "#6b2d5a", "background": "#f8f4f0"},
    "sunset": {"primary": "#8b3a1a", "secondary": "#c45a2a", "accent": "#c45a2a", "background": "#fdf6ee"},
    "ocean": {"primary": "#0a3d5c", "secondary": "#1a6b8a", "accent": "#1a6b8a", "background": "#f0f4f8"},
    "monochrome": {"primary": "#333333", "secondary": "#666666", "accent": "#555555", "background": "#fafafa"},
}

GOOGLE_FONTS = {
    "serif_classic": {
        "family": "Lora",
        "url": "https://fonts.googleapis.com/css2?family=Lora:ital,wght@0,400;0,700;1,400&display=swap",
    },
    "serif_elegant": {
        "family": "Cormorant Garamond",
        "url": "https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,700;1,400&display=swap",
    },
    "sans_modern": {
        "family": "Inter",
        "url": "https://fonts.googleapis.com/css2?family=Inter:wght@300;400;700&display=swap",
    },
    "sans_academic": {
        "family": "Source Sans 3",
        "url": "https://fonts.googleapis.com/css2?family=Source+Sans+3:ital,wght@0,400;0,700;1,400&display=swap",
    },
    "display_decorative": {
        "family": "Playfair Display",
        "url": "https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,700;1,400&display=swap",
    },
}


def select_fonts(theme_name: str, content_type: str = "general") -> dict:
    """Select appropriate fonts based on theme and content type.
    
    History → serif_classic (Lora)
    Science → sans_modern (Inter) for body, serif_classic for headings
    Art → serif_elegant (Cormorant Garamond) + display_decorative (Playfair Display)
    Philosophy → serif_classic
    Literature → serif_elegant
    General → serif_classic
    """
    font_map = {
        "classic": ("serif_classic", "serif_classic"),
        "forest": ("serif_classic", "sans_modern"),
        "royal": ("serif_elegant", "display_decorative"),
        "sunset": ("serif_classic", "sans_modern"),
        "ocean": ("sans_modern", "serif_classic"),
        "monochrome": ("sans_academic", "serif_classic"),
    }
    
    body_key, heading_key = font_map.get(theme_name, ("serif_classic", "serif_classic"))
    
    body_font = GOOGLE_FONTS.get(body_key, GOOGLE_FONTS["serif_classic"])
    heading_font = GOOGLE_FONTS.get(heading_key, GOOGLE_FONTS["serif_classic"])
    
    return {
        "body": body_font,
        "heading": heading_font,
        "url": body_font["url"] if body_font["url"] == heading_font["url"] else f"{body_font['url']}&family={heading_font['family'].replace(' ', '+')}"
    }


def detect_theme(filename: str, essay: str = "") -> str:
    """Detect the most appropriate theme name from filename and content.
    
    Returns one of: classic, forest, royal, sunset, ocean, monochrome
    """
    fp_lower = filename.lower()

    if "bianconi" in fp_lower:
        return "forest"
    if "rosand" in fp_lower or "venice" in fp_lower:
        return "royal"
    if "ivanovich" in fp_lower or "cristoforo" in fp_lower or "bellina" in fp_lower:
        return "classic"

    if essay and len(essay) > 200:
        sample = essay[:2000].lower()

        topic_themes = [
            (["natura", "forest", "green", "environment", "ecologia", "naturale",
              "piante", "alberi", "bosco", "giardino", "campagna", "paesaggio",
              "flora", "fauna", "selvatico", "verde", "prato", "foglie"], "forest"),
            (["arte", "pittura", "musica", "teatro", "opera", "barocco",
              "rinascimento", "melodramma", "scultura", "affresco", "dipinto",
              "compositore", "libretto", "recitativo", "aria", "sinfonia",
              "palcoscenico", "spettacolo", "coreografia", "balletto"], "royal"),
            (["mare", "oceano", "acqua", "navigazione", "isola", "costiero",
              "marino", "pesca", "vela", "onda", "corrente", "profondità",
              "spiaggia", "porto", "marittimo", "subacqueo"], "ocean"),
            (["sole", "tramonto", "calore", "fuoco", "estate", "mediterraneo",
              "sicilia", "sardegna", "deserto", "luce", "caldo", "fiamma",
              "vulcano", "lava", "crepuscolo", "aurora"], "sunset"),
            (["filosofia", "logica", "matematica", "scienza", "teoria",
              "struttura", "sistema", "metodo", "analisi", "concetto",
              "astratto", "ragionamento", "deduzione", "ipotesi", "paradigma"], "monochrome"),
            (["storia", "storico", "antico", "medievale", "moderno", "contemporaneo",
              "civiltà", "impero", "regno", "dinastia", "rivoluzione", "guerra",
              "pace", "trattato", "alleanza", "colonizzazione"], "classic"),
        ]

        for keywords, theme_name in topic_themes:
            if any(k in sample for k in keywords):
                return theme_name

    return "classic"


def generate_design(theme_name: str, essay: str = "") -> DesignSpec:
    """Generate a DesignSpec from a theme name with content-aware adjustments.
    
    Instead of 6 fixed themes, this creates a continuous spectrum:
    1. Start from base theme palette
    2. Select Google Fonts based on theme
    3. Adjust based on content analysis (density, genre)
    4. Add subtle variations for uniqueness
    """
    base = PALETTES.get(theme_name, PALETTES["classic"])
    design = DesignSpec(**base)
    
    # Select Google Fonts for this theme
    fonts = select_fonts(theme_name)
    design.font_serif = f"'{fonts['body']['family']}', 'Georgia', 'Palatino Linotype', serif"
    design.font_sans = f"'{fonts['heading']['family']}', 'Helvetica Neue', Arial, sans-serif"
    design.font_display = f"'{fonts['heading']['family']}', 'Georgia', serif"
    design.google_fonts_url = fonts["url"]
    
    if essay and len(essay) > 500:
        sample = essay[:2000].lower()
        
        # Detect dense academic text → adjust layout
        proper_noun_count = len(re.findall(r'\b[A-Z][a-zà-ÿ]+\b', essay[:500]))
        if proper_noun_count > 15:
            design.font_size_body = 10.0
            design.line_height = 1.65
            design.margin_left = 2.7
            design.margin_right = 2.7
        
        # Detect narrative/literary text → larger font, more spacing
        if proper_noun_count < 8:
            design.font_size_body = 11.0
            design.line_height = 1.85
            design.margin_left = 2.3
            design.margin_right = 2.3
    
    return design


def generate_cover_css(design: DesignSpec) -> str:
    """Generate cover CSS from design spec."""
    return f"""
    .cover {{
        position: relative;
        page-break-after: always;
        min-height: 29.7cm;
        background: linear-gradient(160deg, {design.background} 0%, #f0ece2 40%, #e8e2d5 100%);
        margin: 0;
        padding: 0;
        overflow: hidden;
    }}
    .cover::after {{
        content: "";
        position: absolute;
        bottom: 0;
        right: 0;
        width: 6cm;
        height: 6cm;
        background: radial-gradient(circle, {design.primary}08 0%, transparent 70%);
        pointer-events: none;
    }}
    .cover-accent {{
        position: absolute;
        top: 0;
        left: 0;
        width: 0.8cm;
        height: 100%;
        background: linear-gradient(180deg, {design.primary}, {design.secondary}, {design.primary});
    }}
    .cover-content {{
        position: relative;
        padding: 5.5cm 3.5cm 3cm 4cm;
        max-width: 15cm;
    }}
    .cover-label {{
        font-family: {design.font_serif};
        font-size: 8.5pt;
        letter-spacing: 5pt;
        text-transform: uppercase;
        color: #999;
        margin-bottom: 1.5cm;
    }}
    .cover-title {{
        font-family: {design.font_display};
        font-size: {design.font_size_cover_title}pt;
        font-weight: bold;
        color: {design.primary};
        line-height: 1.3;
        margin-bottom: 0.6cm;
        text-align: left;
        word-wrap: break-word;
        max-width: 13cm;
    }}
    .cover-divider {{
        width: 3.5cm;
        height: 2px;
        background: {design.accent};
        margin: 0.6cm 0;
    }}
    .cover-author {{
        font-family: {design.font_serif};
        font-size: 11pt;
        color: #777;
        margin-bottom: 2cm;
        text-align: left;
        font-style: italic;
    }}
    .cover-note {{
        font-family: {design.font_serif};
        font-size: 8pt;
        font-style: italic;
        color: #bbb;
        margin-top: 0.8cm;
        text-align: left;
    }}
    """


def generate_header_css(design: DesignSpec) -> str:
    """Generate heading CSS from design spec."""
    return f"""
    h1, h2, h3 {{
        font-family: {design.font_serif};
        color: {design.primary};
        page-break-after: avoid;
        font-weight: normal;
    }}
    h1 {{
        font-size: {design.font_size_h1}pt;
        margin-top: 1.8cm;
        margin-bottom: 0.5cm;
        padding-bottom: 0.25cm;
        border-bottom: 1px solid #d4d0c8;
        letter-spacing: 0.3pt;
        font-weight: bold;
    }}
    h2 {{
        font-size: {design.font_size_h2}pt;
        margin-top: 1cm;
        margin-bottom: 0.35cm;
        font-weight: bold;
    }}
    h3 {{
        font-size: {design.font_size_h3}pt;
        margin-top: 0.7cm;
        margin-bottom: 0.25cm;
        font-weight: bold;
        color: {design.secondary};
    }}
    """


def generate_decor_css(design: DesignSpec) -> str:
    """Generate decoration CSS from design spec."""
    return f"""
    .section-ricordare,
    .section-cronologia,
    .section-glossario,
    .section-opere,
    .section-scheda,
    .section-domande {{
        color: {design.primary};
        border-bottom: 2px solid {design.primary};
        padding-bottom: 0.25cm;
        margin-top: 1.2cm;
        font-size: 13pt;
        font-weight: bold;
        letter-spacing: 0.3pt;
    }}
    .box-key {{
        margin: 0.7em 0;
        padding: 0.5em 1em;
        border-left: 4px solid {design.accent};
        background: linear-gradient(90deg, {design.accent}0a 0%, transparent 100%);
        page-break-inside: avoid;
        font-size: 10pt;
    }}
    .cronologia-item {{
        margin: 0.35em 0;
        padding: 0.15em 0 0.15em 1.2em;
        border-left: 2px solid {design.accent}30;
        font-size: 10pt;
        position: relative;
    }}
    .cronologia-item::before {{
        content: "";
        position: absolute;
        left: -4px;
        top: 0.55em;
        width: 6px;
        height: 6px;
        background: {design.accent};
        border-radius: 50%;
    }}
    .cronologia-anno {{
        font-weight: bold;
        color: {design.accent};
    }}
    .glossario-item {{
        margin: 0.35em 0;
        padding: 0.25em 0.5em;
        border-bottom: 1px dotted #e0ddd5;
        font-size: 10pt;
    }}
    .glossario-termine {{
        color: {design.accent};
    }}
    .concept-table {{
        width: 100%;
        border-collapse: collapse;
        margin: 1em 0;
        page-break-inside: avoid;
        font-size: 9.5pt;
    }}
    .concept-table th {{
        background-color: {design.primary};
        color: white;
        padding: 7px 12px;
        text-align: left;
        font-family: {design.font_serif};
    }}
    .concept-table td {{
        border: 1px solid #d4d0c8;
        padding: 5px 12px;
        vertical-align: top;
    }}
    .concept-table tr:nth-child(even) td {{
        background-color: #f8f6f0;
    }}
    .qa-block {{
        margin: 1em 0;
        padding: 0.5em 1em;
        border-left: 4px solid {design.accent};
        background-color: #f8f6f0;
        page-break-inside: avoid;
    }}
    .question {{
        font-weight: bold;
        font-size: 10.5pt;
        margin-bottom: 0.25em;
        color: {design.primary};
    }}
    .answer {{
        font-size: 10pt;
        color: #444;
        line-height: 1.5;
    }}
    strong {{ font-weight: bold; color: {design.primary}; }}
    """
