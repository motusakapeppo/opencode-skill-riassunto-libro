"""
PDF renderer — converts essay text to PDF via Playwright/Chromium.
Replaces WeasyPrint with browser-based rendering for better CSS support.
"""

from pathlib import Path
from typing import Optional
import html as html_mod
import re
from loguru import logger
from scripts.config import Settings
from scripts.design_system import DesignSpec, generate_cover_css, generate_header_css, generate_decor_css
from scripts.style import BULLET_RE, StyleViolation, enforce_prose


BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def html_paragraph(line: str) -> str:
    """Convert a line of text to HTML with real bold tags."""
    def replace_bold(m):
        return "<strong>" + html_mod.escape(m.group(1)) + "</strong>"
    
    if BOLD_RE.search(line):
        parts = BOLD_RE.split(line)
        result = []
        for i, part in enumerate(parts):
            if i % 2 == 0:
                result.append(html_mod.escape(part))
            else:
                result.append("<strong>" + html_mod.escape(part) + "</strong>")
        return "".join(result)
    return html_mod.escape(line)


def build_html(
    essay: str,
    design: DesignSpec,
    titolo: str,
    autore: str = "Autore sconosciuto",
    style: str = "prose",
) -> str:
    """Build complete HTML document from essay text and design spec."""
    # Build body parts
    body_parts = []
    
    # Cover
    body_parts.append('<div class="cover">')
    body_parts.append(f'<div class="cover-accent"></div>')
    body_parts.append('<div class="cover-content">')
    body_parts.append('<p class="cover-label">RIASSUNTO DI STUDIO</p>')
    titolo_esc = html_mod.escape(titolo)
    if len(titolo) > 50:
        body_parts.append(f'<h1 class="cover-title cover-title-long">{titolo_esc}</h1>')
    else:
        body_parts.append(f'<h1 class="cover-title">{titolo_esc}</h1>')
    body_parts.append(f'<div class="cover-divider"></div>')
    if autore and autore != "Autore sconosciuto":
        body_parts.append(f'<p class="cover-author">{html_mod.escape(autore)}</p>')
    body_parts.append('<p class="cover-note">Elaborazione ad alta densità narrativa per studio universitario</p>')
    body_parts.append('</div>')
    body_parts.append('</div>')
    
    # Body — parse essay line by line
    tabella_aperta = False
    in_da_ricordare = False
    in_cronologia = False
    in_glossario = False
    in_opere = False
    
    for line in essay.split("\n"):
        s = line.strip()
        if not s:
            continue

        # Lists: styled as lists only in notes mode, as prose otherwise
        if BULLET_RE.match(line):
            if style == "notes":
                body_parts.append(
                    f'<p class="list-item">{html_paragraph(BULLET_RE.sub("", line).strip())}</p>'
                )
            else:
                body_parts.append(f'<p class="body-text">{html_paragraph(s)}</p>')
            continue

        # Section headers
        if s.startswith("### Da Ricordare"):
            body_parts.append('<h2 class="section-ricordare">Da Ricordare</h2>')
            in_da_ricordare = True; in_cronologia = in_glossario = in_opere = False
            continue
        if s.startswith("### Cronologia"):
            body_parts.append('<h2 class="section-cronologia">Cronologia</h2>')
            in_cronologia = True; in_da_ricordare = in_glossario = in_opere = False
            continue
        if s.startswith("### Glossario"):
            body_parts.append('<h2 class="section-glossario">Glossario</h2>')
            in_glossario = True; in_da_ricordare = in_cronologia = in_opere = False
            continue
        if s.startswith("### Opere Citati"):
            body_parts.append('<h2 class="section-opere">Opere Citati</h2>')
            in_opere = True; in_da_ricordare = in_cronologia = in_glossario = False
            continue
        if s.startswith("### Scheda Riassuntiva"):
            body_parts.append('<h2 class="section-scheda">Scheda Riassuntiva</h2>')
            in_da_ricordare = in_cronologia = in_glossario = in_opere = False
            continue
        if s.startswith("### Domande di Verifica"):
            body_parts.append('<h2 class="section-domande">Domande di Verifica</h2>')
            in_da_ricordare = in_cronologia = in_glossario = in_opere = False
            continue
        
        # Da Ricordare items
        if in_da_ricordare:
            if s.startswith("**") and "—" in s:
                parts = s.split("—", 1)
                termine = parts[0].strip(" *")
                spiegazione = parts[1].strip()
                body_parts.append(
                    f'<div class="box-key"><p><strong>{html_mod.escape(termine)}</strong> — {html_paragraph(spiegazione)}</p></div>'
                )
            else:
                body_parts.append(f'<p class="body-text">{html_paragraph(s)}</p>')
            continue
        
        # Cronologia items
        if in_cronologia:
            if s.startswith("**") and "—" in s:
                parts = s.split("—", 1)
                anno = parts[0].strip(" *")
                evento = parts[1].strip()
                body_parts.append(
                    f'<p class="cronologia-item"><span class="cronologia-anno">{html_mod.escape(anno)}</span> — {html_paragraph(evento)}</p>'
                )
            else:
                body_parts.append(f'<p class="body-text">{html_paragraph(s)}</p>')
            continue
        
        # Glossario items
        if in_glossario:
            if s.startswith("**") and "—" in s:
                parts = s.split("—", 1)
                termine = parts[0].strip(" *")
                definizione = parts[1].strip()
                body_parts.append(
                    f'<p class="glossario-item"><strong class="glossario-termine">{html_mod.escape(termine)}</strong> — {html_paragraph(definizione)}</p>'
                )
            else:
                body_parts.append(f'<p class="body-text">{html_paragraph(s)}</p>')
            continue
        
        # Opere items
        if in_opere:
            if s.startswith("**") and "(" in s:
                body_parts.append(f'<p class="opere-item">{html_paragraph(s)}</p>')
            else:
                body_parts.append(f'<p class="body-text">{html_paragraph(s)}</p>')
            continue
        
        # Concetti → table
        if s.startswith("Concetto:"):
            clean = s.replace("Concetto:", "").strip()
            if "-" in clean:
                termine, spiegazione = clean.split("-", 1)
                if not tabella_aperta:
                    body_parts.append('<table class="concept-table">')
                    body_parts.append("<tr><th>Concetto</th><th>Spiegazione</th></tr>")
                    tabella_aperta = True
                body_parts.append(
                    f"<tr><td><strong>{html_mod.escape(termine.strip())}</strong></td><td>{html_paragraph(spiegazione.strip())}</td></tr>"
                )
            else:
                body_parts.append(f"<p>{html_paragraph(clean)}</p>")
            continue
        
        if tabella_aperta and not s.startswith("Concetto:"):
            body_parts.append("</table>")
            tabella_aperta = False
        
        # Domande
        if s.startswith("Domanda:"):
            clean = s.replace("Domanda:", "").strip()
            if "-" in clean:
                quesito, risposta = clean.split("-", 1)
                body_parts.append('<div class="qa-block">')
                body_parts.append(f'<p class="question"><strong>{html_mod.escape(quesito.strip())}</strong></p>')
                body_parts.append(f'<p class="answer">{html_paragraph(risposta.strip())}</p>')
                body_parts.append('</div>')
            else:
                body_parts.append(f"<p>{html_paragraph(clean)}</p>")
            continue
        
        # Headings
        if s.startswith("### "):
            body_parts.append(f"<h3>{html_mod.escape(s[4:])}</h3>")
        elif s.startswith("## "):
            body_parts.append(f"<h2>{html_mod.escape(s[3:])}</h2>")
        elif s.startswith("# "):
            body_parts.append(f"<h1>{html_mod.escape(s[2:])}</h1>")
        else:
            body_parts.append(f'<p class="body-text">{html_paragraph(s)}</p>')
    
    if tabella_aperta:
        body_parts.append("</table>")
    
    # CSS
    cover_css = generate_cover_css(design)
    header_css = generate_header_css(design)
    decor_css = generate_decor_css(design)
    
    base_css = f"""
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
    p.list-item {{
        text-indent: 0;
        margin: 0.15em 0 0.15em 1.2em;
    }}
    """
    
    css = base_css + cover_css + header_css + decor_css
    
    # Google Fonts link
    google_fonts_link = ""
    if design.google_fonts_url:
        google_fonts_link = f'<link href="{design.google_fonts_url}" rel="stylesheet">'
    
    html_doc = f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="utf-8">
<title>{html_mod.escape(titolo)} — Riassunto</title>
{google_fonts_link}
<style>{css}</style>
</head>
<body>
{chr(10).join(body_parts)}
</body>
</html>"""
    
    return html_doc


def render_pdf(
    essay: str,
    output_path: str,
    design: DesignSpec,
    settings: Settings,
    titolo: str = "Riassunto",
    autore: str = "Autore sconosciuto",
) -> str:
    """Render essay to PDF via Playwright/Chromium.
    
    Steps:
    1. Build HTML from essay + design
    2. Save HTML to temp file
    3. Launch Playwright browser
    4. Load HTML, wait for fonts
    5. Generate PDF with proper page settings
    6. Save to output_path
    7. Clean up temp HTML
    
    Returns output_path.
    """
    # The PDF is the point of no return: refuse to typeset a list dump as an
    # essay. Minor lists are converted, a full outline raises StyleViolation.
    essay, stats = enforce_prose(essay, settings)
    if stats.bullet_lines and getattr(settings, "style", "prose") == "prose":
        logger.warning(
            "Style: %d list lines converted to paragraphs before rendering", stats.bullet_lines
        )

    html_content = build_html(essay, design, titolo, autore, style=getattr(settings, "style", "prose"))
    
    html_path = Path(output_path).with_suffix(".html")
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html_content, encoding="utf-8")
    
    try:
        from playwright.sync_api import sync_playwright
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=settings.playwright_headless)
            page = browser.new_page()
            page.goto(f"file://{html_path.resolve()}")
            page.wait_for_load_state("networkidle")
            
            page.pdf(
                path=output_path,
                format="A4",
                margin={
                    "top": f"{design.margin_top}cm",
                    "bottom": f"{design.margin_bottom}cm",
                    "left": f"{design.margin_left}cm",
                    "right": f"{design.margin_right}cm",
                },
                print_background=True,
            )
            browser.close()
        
        pdf_size = Path(output_path).stat().st_size / 1024
        logger.info(f"PDF saved: {Path(output_path).name} ({pdf_size:.0f} KB)")
    except ImportError:
        logger.warning("Playwright not installed. Install with: playwright install chromium")
        logger.info(f"HTML saved instead: {html_path}")
    finally:
        if html_path.exists():
            html_path.unlink()
    
    return output_path
