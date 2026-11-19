"""Tailor the master resume for one Job Case, audit it, and export DOCX + PDF.

Usage: python3 tailor_resume.py <case_config.json>

Only reorders / rephrases content that already exists in the master resume.
The audit step rejects the output if employers, titles, dates or education change,
or if any blocked (unverified) technology term appears.
"""
import copy, json, subprocess, sys, tempfile, pathlib, re
import docx

ROOT = pathlib.Path(__file__).resolve().parents[2]
MASTER = ROOT / "Resume" / "Master" / "Pranav_Data_Engineer_MASTER.docx"
OUT_DIR = ROOT / "Resume"

# Paragraph indexes in the master template
HEADLINE, SUMMARY = 1, 4
SECTIONS = {"dxc": list(range(10, 19)), "icici": list(range(23, 31)), "allstate": list(range(35, 39))}
FIXED = [0, 2, 7, 8, 9, 20, 21, 22, 32, 33, 34, 40, 41, 46]  # names, contact, employers, roles, dates, education

# Technologies NOT in the verified profile; must never appear in a tailored resume
BLOCKED = ["Fivetran", "Lakeflow", "Datadog", "GitHub Actions", "Microsoft Fabric", "Key Vault", "Structured Streaming",
           "Terraform", "Bedrock", "Textract", "LangChain", "pgvector", "SSIS", "Data Vault", "TensorFlow", "PyTorch",
           "Photon", "Lambda", "Step Functions", "Informatica", "certified", "Certification"]


def set_text(p, text):
    runs = p.runs
    runs[0].text = text
    for r in runs[1:]:
        r.text = ""


def all_text(d):
    t = [p.text for p in d.paragraphs]
    for row in d.tables[0].rows:
        t.append(" | ".join(c.text for c in row.cells))
    return "\n".join(t)


def tailor(cfg):
    d = docx.Document(MASTER)
    P = d.paragraphs
    changes = []
    set_text(P[HEADLINE], cfg["headline"]); changes.append("Headline retargeted to JD title/keywords.")
    set_text(P[SUMMARY], cfg["summary"]); changes.append("Summary rewritten around JD requirements using verified facts only.")
    for sec, order in cfg.get("bullet_order", {}).items():
        idx = SECTIONS[sec]
        texts = [P[i].text for i in idx]
        assert sorted(order) == list(range(len(idx))), f"bad order for {sec}"
        for slot, src in zip(idx, order):
            set_text(P[slot], texts[src])
        changes.append(f"{sec.upper()} bullets reordered to lead with JD-relevant work: {order}.")
    for key, new in cfg.get("rewrites", {}).items():
        sec, n = key.split(":")
        slot = SECTIONS[sec][int(n)]  # position AFTER reordering
        changes.append(f"Reworded {sec.upper()} bullet {n}: '{P[slot].text[:60]}...' -> '{new[:60]}...'")
        set_text(P[slot], new)
    if "skill_order" in cfg:
        rows = d.tables[0].rows
        vals = [[c.text for c in r.cells] for r in rows]
        for r, src in zip(rows, cfg["skill_order"]):
            for c, v in zip(r.cells, vals[src]):
                set_text(c.paragraphs[0], v)
        changes.append(f"Skills table reprioritized: {[vals[i][0] for i in cfg['skill_order'][:4]]} first.")
    return d, changes


def audit(d, cfg):
    master = docx.Document(MASTER)
    issues = []
    for i in FIXED:
        if d.paragraphs[i].text != master.paragraphs[i].text:
            issues.append(f"Fixed line changed: {master.paragraphs[i].text!r}")
    txt = all_text(d)
    for term in BLOCKED:
        if re.search(re.escape(term), txt, re.I) and not re.search(re.escape(term), all_text(master), re.I):
            issues.append(f"Unverified term present: {term}")
    # every number in the tailored resume must exist in the master (no invented metrics)
    mnums = set(re.findall(r"\d+%?", all_text(master)))
    for n in set(re.findall(r"\d+%?", txt)) - mnums:
        if n not in {"4"}:  # '4+ years' comes from the verified profile (May 2021-present minus study gap)
            issues.append(f"Number not in master: {n}")
    # personal-project tools must stay labeled as personal
    if "(Personal)" not in txt:
        issues.append("Personal-project labels missing")
    # duplicate bullets
    paras = [p.text for p in d.paragraphs if len(p.text) > 40]
    if len(paras) != len(set(paras)):
        issues.append("Duplicate bullet detected")
    kw = cfg.get("jd_keywords", [])
    hit = [k for k in kw if re.search(re.escape(k), txt, re.I)]
    miss = [k for k in kw if k not in hit]
    return issues, hit, miss


def export_pdf(docx_path):
    """High-fidelity PDF needs LibreOffice (brew install --cask libreoffice) or Word. textutil+Chrome
    was tested and rejected: it breaks the template (strikethrough headings, all-bold text)."""
    import shutil
    soffice = shutil.which("soffice") or "/Applications/LibreOffice.app/Contents/MacOS/soffice"
    if not pathlib.Path(soffice).exists():
        raise RuntimeError("LibreOffice not installed; DOCX only")
    subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", str(docx_path.parent), str(docx_path)],
                   check=True, capture_output=True, timeout=120)
    return docx_path.with_suffix(".pdf")


def main(cfg_path):
    cfg = json.loads(pathlib.Path(cfg_path).read_text())
    d, changes = tailor(cfg)
    issues, hit, miss = audit(d, cfg)
    report = {"file": None, "issues": issues, "keywords_covered": hit, "keywords_missing_not_claimed": miss, "changes": changes}
    if issues:
        report["status"] = "REJECTED"
    else:
        out = OUT_DIR / f"{cfg['file_stem']}.docx"
        d.save(out)
        try:
            export_pdf(out); report["pdf"] = str(out.with_suffix('.pdf'))
        except Exception as e:  # PDF is best-effort
            report["pdf_error"] = str(e)
        report["file"] = str(out); report["status"] = "PASSED"
    pathlib.Path(cfg["audit_out"]).write_text(json.dumps(report, indent=2))
    print(json.dumps({k: report[k] for k in ("status", "file", "issues")}, indent=1), "missing:", miss)


if __name__ == "__main__":
    main(sys.argv[1])
