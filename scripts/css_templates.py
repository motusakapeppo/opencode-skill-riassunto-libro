"""
Modular CSS template system for PDF rendering.
Each function generates a CSS section from a DesignSpec.
"""

from scripts.design_system import DesignSpec


def base_css(design: DesignSpec) -> str:
    """Base CSS: page setup, body typography, general styles."""
    return f"""
    @page {{
        size: A4;
        margin: {design.margin_top}cm {design.margin_right}cm {design.margin_bottom}cm {design.margin_left}cm;
        @bottom-center {{
            content: "— " counter(page) " —";
            font-family: {design.font_serif};
            font-size: 8pt;
            color: #ccc;
            letter-spacing: 1pt;
        }}
    }}
    @page :first {{
        @bottom-center {{ content: ""; }}
        margin: 0;
    }}
    body {{
        font-family: {design.font_serif};
        font-size: {design.font_size_body}pt;
        line-height: {design.line_height};
        color: {design.text_color};
        text-align: justify;
        hyphens: auto;
        orphans: 3;
        widows: 3;
    }}
    p.body-text {{
        text-indent: 1.5em;
        margin: 0.15em 0;
    }}
    p.body-text:first-of-type {{
        text-indent: 0;
    }}
    p.body-text:first-of-type::first-letter {{
        font-size: 2.8em;
        font-weight: bold;
        color: {design.accent};
        float: left;
        line-height: 0.8;
        margin-right: 0.15em;
        margin-top: 0.05em;
        margin-bottom: -0.15em;
        font-family: {design.font_serif};
    }}
    """


def cover_css(design: DesignSpec) -> str:
    """Cover page CSS."""
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


def headings_css(design: DesignSpec) -> str:
    """Heading hierarchy CSS."""
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


def special_sections_css(design: DesignSpec) -> str:
    """CSS for Da Ricordare, Cronologia, Glossario, etc."""
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
    .opere-item {{
        margin: 0.25em 0;
        padding-left: 1.2em;
        text-indent: -1.2em;
        font-size: 9.5pt;
        color: #555;
    }}
    """


def concept_table_css(design: DesignSpec) -> str:
    """CSS for the concept table."""
    return f"""
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
        font-size: 9.5pt;
        font-weight: normal;
        letter-spacing: 0.8pt;
    }}
    .concept-table td {{
        border: 1px solid #d4d0c8;
        padding: 5px 12px;
        vertical-align: top;
    }}
    .concept-table tr:nth-child(even) td {{
        background-color: #f8f6f0;
    }}
    """


def qa_css(design: DesignSpec) -> str:
    """CSS for Q&A blocks."""
    return f"""
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


def all_css(design: DesignSpec) -> str:
    """Combine all CSS templates into one string."""
    parts = [
        base_css(design),
        cover_css(design),
        headings_css(design),
        special_sections_css(design),
        concept_table_css(design),
        qa_css(design),
    ]
    return "\n".join(parts)
