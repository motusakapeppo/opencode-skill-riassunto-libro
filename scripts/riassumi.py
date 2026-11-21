#!/usr/bin/env python3
"""
Wrapper per skill riassunto-libro.
Usa i file extract.py e pipeline_unificata.py dalla stessa cartella della skill.
"""

import os, sys, subprocess, json, re, time, shutil, glob
from pathlib import Path

SKILL_DIR = Path(__file__).parent
SCRIPTS_DIR = SKILL_DIR / "scripts"
EXTRACT = SCRIPTS_DIR / "extract.py"
PIPELINE = SCRIPTS_DIR / "pipeline_unificata.py"


def main():
    if len(sys.argv) < 2:
        print("Uso: python riassumi.py <path-to-document> [lingua]")
        print("  lingua: 'it' (default per libri inglesi) o 'originale'")
        print("  Esempio: python riassumi.py D:\\Downloads\\libro.pdf")
        sys.exit(1)

    doc_path = sys.argv[1]
    lang = sys.argv[2] if len(sys.argv) > 2 else "it"

    if not os.path.exists(doc_path):
        print(f"ERRORE: File non trovato: {doc_path}")
        sys.exit(1)

    # Determina cartella output: stessa cartella del documento, sottocartella riassunti
    doc_dir = os.path.dirname(os.path.abspath(doc_path))
    out_dir = os.path.join(doc_dir, "riassunti")
    os.makedirs(out_dir, exist_ok=True)

    print(f"Documento: {doc_path}")
    print(f"Output in: {out_dir}")
    print(f"Lingua: {'italiano' if lang == 'it' else 'originale'}")

    # FASE 1: Estrai testo
    print("\n[FASE 1] Estrazione testo...")
    workdir = os.path.join(doc_dir, "_extract_work")
    shutil.rmtree(workdir, ignore_errors=True)
    os.makedirs(workdir, exist_ok=True)

    env = os.environ.copy()
    env["BOOK_SKILL_WORKDIR"] = workdir
    env["BOOK_SKILL_INSTALL_MISSING"] = "no"

    if os.path.exists(str(EXTRACT)):
        r = subprocess.run(
            [sys.executable, "-X", "utf8", str(EXTRACT), doc_path, "--mode", "text"],
            capture_output=True,
            text=True,
            timeout=300,
            env=env,
        )

    text_path = os.path.join(workdir, "full_text.txt")
    raw_text = ""
    if os.path.exists(text_path):
        raw_text = open(text_path, encoding="utf-8", errors="replace").read()

    if not raw_text or len(raw_text) < 200:
        try:
            import fitz

            doc = fitz.open(doc_path)
            raw_text = "\n\n".join([p.get_text() for p in doc])
            doc.close()
        except:
            pass

    shutil.rmtree(workdir, ignore_errors=True)
    print(f"Estratto: {len(raw_text)} car ({len(raw_text) // 4} tok)")

    if len(raw_text) < 200:
        print("ERRORE: Testo insufficiente")
        sys.exit(1)

    # FASE 2: Chunking
    print("\n[FASE 2] Chunking...")
    cl = []
    for line in raw_text.split("\n"):
        s = line.strip()
        if re.match(r"^\d+$", s) and len(s) < 5:
            continue
        cl.append(line)
    ct = "\n".join(cl)
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", ct) if p.strip()]
    chunks, current, cur_tok, ch_id = [], "", 0, 0
    for para in paragraphs:
        pt = len(para) // 4
        if pt > 24000:
            if current.strip() and len(current) // 4 > 800:
                chunks.append(
                    {"id": ch_id, "text": current, "token_count": len(current) // 4}
                )
                ch_id += 1
                current, cur_tok = "", 0
            for sent in re.split(r"(?<=[.!?])\s+", para):
                st = len(sent) // 4
                if cur_tok + st > 24000 and current:
                    chunks.append(
                        {"id": ch_id, "text": current, "token_count": cur_tok}
                    )
                    ch_id += 1
                    current, cur_tok = sent, st
                else:
                    current += " " + sent if current else sent
                    cur_tok += st
            continue
        if cur_tok + pt > 24000 and current:
            chunks.append({"id": ch_id, "text": current, "token_count": cur_tok})
            ch_id += 1
            current, cur_tok = para, pt
        else:
            current += "\n\n" + para if current else para
            cur_tok += pt
    if current.strip():
        chunks.append({"id": ch_id, "text": current, "token_count": cur_tok})
    merged = []
    for c in chunks:
        if c["token_count"] < 800 and merged:
            merged[-1]["text"] += "\n\n" + c["text"]
            merged[-1]["token_count"] += c["token_count"]
        else:
            merged.append(c)
    for i, m in enumerate(merged):
        m["id"] = i
    print(f"{len(merged)} chunk finali")

    # FASE 3: Map
    print("\n[FASE 3] Map (deepseek-v4.1-flash:cloud)...")
    import requests

    def call_llm(prompt, timeout=300):
        for attempt in range(3):
            try:
                resp = requests.post(
                    "http://127.0.0.1:11434/api/chat",
                    json={
                        "model": "deepseek-v4.1-flash:cloud",
                        "messages": [{"role": "user", "content": prompt}],
                        "options": {"num_ctx": 32768, "temperature": 0.2},
                        "stream": False,
                    },
                    timeout=timeout,
                )
                return resp.json().get("message", {}).get("content", "")
            except Exception as e:
                print(f"  Retry {attempt + 1}: {str(e)[:60]}")
                time.sleep(15)
        return None

    # Carica checkpoint
    cp_file = os.path.join(doc_dir, "_checkpoint.json")
    results = []
    if os.path.exists(cp_file):
        cp = json.load(open(cp_file, encoding="utf-8"))
        if cp.get("chunks_total") == len(merged):
            results = cp.get("results", [])
            print(f"Checkpoint caricato: {len(results)}/{len(merged)} chunk fatti")

    done_ids = {r["chunk_id"] for r in results}
    pending = [c for c in merged if c["id"] not in done_ids]
    print(f"Da fare: {len(pending)} chunk")

    for chunk in pending:
        cid = chunk["id"]
        print(f"  Chunk {cid + 1}/{len(merged)} ({chunk['token_count']} tok)...")

        if lang == "it":
            prompt = (
                "Sei uno storico specializzato. Il libro seguente e in INGLESE, "
                "ma DEVI scrivere il riassunto in ITALIANO.\n\n"
                "REGOLE:\n"
                "1. Conserva TUTTI i nomi propri, date, titoli di opere\n"
                "2. Scrivi riassunto DENSO in italiano. Paragrafi fluidi. ZERO elenchi.\n"
                "3. Copri circa il 40-60% del testo.\n"
                "4. Usa ### per titoli.\n"
                "5. Alla fine:\n"
                "===ENTITA===\nPERSONE: |\nDATE: |\nOPERE: |\n===FINE ENTITA===\n\n"
                "TESTO:\n" + chunk["text"]
            )
        else:
            prompt = (
                "You are a specialist historian. Analyze the following text exhaustively.\n\n"
                "RULES:\n"
                "1. Preserve ALL names, dates, titles\n"
                "2. Write DENSE summary. Fluid paragraphs. ZERO bullet points.\n"
                "3. Cover about 40-60% of the text.\n"
                "4. Use ### for section titles.\n"
                "5. At the end:\n"
                "===ENTITIES===\nPEOPLE: |\nDATES: |\nWORKS: |\n===END ENTITIES===\n\n"
                "TEXT:\n" + chunk["text"]
            )

        content = call_llm(prompt)
        if not content:
            continue

        entities = {"persone": [], "date": [], "opere": []}
        if lang == "it":
            em = re.search(r"===ENTITA===\n(.*?)===FINE ENTITA===", content, re.DOTALL)
        else:
            em = re.search(
                r"===ENTITIES===\n(.*?)===END ENTITIES===", content, re.DOTALL
            )
        if em:
            if lang == "it":
                for line in em.group(1).strip().split("\n"):
                    if line.startswith("PERSONE:"):
                        entities["persone"] = [
                            e.strip()
                            for e in line.replace("PERSONE:", "").split("|")
                            if e.strip()
                        ]
                    elif line.startswith("DATE:"):
                        entities["date"] = [
                            e.strip()
                            for e in line.replace("DATE:", "").split("|")
                            if e.strip()
                        ]
                    elif line.startswith("OPERE") and ":" in line:
                        entities["opere"] = [
                            e.strip()
                            for e in line.split(":", 1)[1].split("|")
                            if e.strip()
                        ]
            else:
                for line in em.group(1).strip().split("\n"):
                    if line.startswith("PEOPLE:"):
                        entities["persone"] = [
                            e.strip()
                            for e in line.replace("PEOPLE:", "").split("|")
                            if e.strip()
                        ]
                    elif line.startswith("DATES:"):
                        entities["date"] = [
                            e.strip()
                            for e in line.replace("DATES:", "").split("|")
                            if e.strip()
                        ]
                    elif line.startswith("WORKS") and ":" in line:
                        entities["opere"] = [
                            e.strip()
                            for e in line.split(":", 1)[1].split("|")
                            if e.strip()
                        ]
            clean = content[: em.start()].strip()
        else:
            clean = content.strip()

        results.append(
            {
                "chunk_id": cid,
                "summary": clean,
                "entities": entities,
                "token_count": len(clean) // 4,
            }
        )
        print(f"  Fatto: {len(clean)} car")

        # Checkpoint
        json.dump(
            {"chunks_total": len(merged), "results": results},
            open(cp_file, "w", encoding="utf-8"),
            ensure_ascii=False,
            indent=2,
        )
        time.sleep(2)

    print(f"\nCompletati {len(results)}/{len(merged)} chunk")

    # FASE 4: DOCX
    print("\n[FASE 4] Assemblaggio DOCX...")
    from docx import Document as Doc
    from docx.shared import Pt, Inches
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    parts = []
    for r in results:
        t = r.get("summary", "")
        if not re.search(r"^#{1,3}\s+", t, re.MULTILINE):
            t = "### Sezione\n\n" + t
        parts.append(t)
    essay = "\n\n".join(parts)

    doc = Doc()
    for s in doc.sections:
        s.top_margin = Inches(1)
        s.bottom_margin = Inches(1)
        s.left_margin = Inches(1.15)
        s.right_margin = Inches(1.15)
    sty = doc.styles["Normal"]
    sty.font.name = "Calibri"
    sty.font.size = Pt(11.5)
    sty.paragraph_format.line_spacing = 1.35
    sty.paragraph_format.space_after = Pt(6)
    sty.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    doc.add_heading("Riassunto - " + os.path.basename(doc_path), level=0)
    for line in essay.split("\n"):
        s = line.strip()
        if not s:
            continue
        if s.startswith("### "):
            doc.add_heading(s[4:], level=3)
        elif s.startswith("## "):
            doc.add_heading(s[3:], level=2)
        elif s.startswith("# "):
            doc.add_heading(s[2:], level=1)
        else:
            doc.add_paragraph(s)

    out_name = (
        "Riassunto_"
        + re.sub(
            r"[^a-zA-Z0-9_-]", "", os.path.basename(doc_path).replace(" ", "_")[:50]
        )
        + ".docx"
    )
    out_path = os.path.join(out_dir, out_name)
    doc.save(out_path)
    total = sum(len(p.text) for p in doc.paragraphs)
    print(f"\n{'=' * 60}")
    print(f"COMPLETATO: {out_path}")
    print(f"Caratteri: {total:,} ({total // 2500} pagine Word stimate)")
    print(f"Paragrafi: {len(doc.paragraphs)}")
    print(f"Chunk: {len(results)}/{len(merged)}")
    print(f"{'=' * 60}")

    # Pulisci checkpoint
    if os.path.exists(cp_file):
        os.remove(cp_file)


if __name__ == "__main__":
    main()
