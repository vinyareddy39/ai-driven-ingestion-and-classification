"""Full Audit Pipeline Runner:
1. Runs all 30 files in audit_inputs/ through GeneralizedPipeline.
2. Saves raw output JSONs to audit_outputs/.
3. Evaluates extracted fields against audit_inputs/*.expected.json.
4. Generates self-contained extraction_audit.html with side-by-side previews,
   top-of-section metadata, and a comprehensive summary.
5. Exports extraction_audit.csv.
"""

import os
import sys
import glob
import json
import base64
import csv
import re
from io import BytesIO
from collections import defaultdict, Counter
from typing import Dict, List, Any

sys.path.insert(0, os.path.abspath("."))
import fitz  # PyMuPDF
from PIL import Image
from app.core.generalized_pipeline import GeneralizedDocumentPipeline

INPUT_DIR = "audit_inputs"
OUTPUT_DIR = "audit_outputs"
PREVIEWS_DIR = os.path.join(OUTPUT_DIR, "previews")
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(PREVIEWS_DIR, exist_ok=True)

pipeline = GeneralizedDocumentPipeline()

def normalize_val(val: Any) -> str:
    if val is None:
        return ""
    s = str(val).lower()
    # remove punctuation, dollar signs, commas, extra whitespace
    s = re.sub(r"[\$,\-_/\\\(\):]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def render_preview_b64(file_path: str) -> List[str]:
    """Render preview images of all pages and return base64 data URIs."""
    ext = os.path.splitext(file_path)[1].lower()
    previews = []
    try:
        if ext == ".pdf":
            doc = fitz.open(file_path)
            for p_num in range(len(doc)):
                page = doc[p_num]
                pix = page.get_pixmap(dpi=110)
                png_bytes = pix.tobytes("png")
                b64 = base64.b64encode(png_bytes).decode("ascii")
                previews.append(f"data:image/png;base64,{b64}")
            doc.close()
        elif ext in [".png", ".jpg", ".jpeg"]:
            with Image.open(file_path) as im:
                buf = BytesIO()
                im.save(buf, format="JPEG", quality=85)
                b64 = base64.b64encode(buf.getvalue()).decode("ascii")
                previews.append(f"data:image/jpeg;base64,{b64}")
    except Exception as e:
        print(f"Error rendering preview for {file_path}: {e}")
    return previews

# Discover document files (excluding .expected.json)
doc_files = sorted([
    f for f in glob.glob(os.path.join(INPUT_DIR, "*"))
    if not f.endswith(".expected.json") and os.path.isfile(f)
])

print(f"Found {len(doc_files)} audit document files in {INPUT_DIR}.")

all_audit_results = []
csv_rows = []

# Global Summary accumulators
type_label_stats = defaultdict(lambda: defaultdict(lambda: {"count": 0, "conf_sum": 0.0, "match_yes": 0, "match_no": 0, "not_in_exp": 0, "doc_set": set()}))
type_doc_counts = Counter()
type_expected_fields = defaultdict(lambda: Counter())
extracted_expected_matches = defaultdict(lambda: Counter())
confidence_histogram = Counter()
total_fields_count = 0
unlabelled_fields_count = 0
paragraph_fields = []

for doc_path in doc_files:
    base_name = os.path.splitext(os.path.basename(doc_path))[0]
    expected_path = os.path.join(INPUT_DIR, f"{base_name}.expected.json")
    expected_data = {}
    if os.path.exists(expected_path):
        with open(expected_path, "r", encoding="utf-8") as f:
            expected_data = json.load(f)

    exp_kind = expected_data.get("document_kind", "unknown")
    exp_key_values = expected_data.get("key_values", {})
    type_doc_counts[exp_kind] += 1
    for k in exp_key_values.keys():
        type_expected_fields[exp_kind][k] += 1

    print(f"--> Processing {os.path.basename(doc_path)} ({exp_kind})...")
    output_json = pipeline.process_file(doc_path)

    # Save raw output JSON in audit_outputs
    out_json_path = os.path.join(OUTPUT_DIR, f"{base_name}.json")
    with open(out_json_path, "w", encoding="utf-8") as f:
        json.dump(output_json, f, indent=2)

    # Previews
    previews = render_preview_b64(doc_path)

    # Evaluate fields
    extracted_fields = output_json.get("fields", [])
    evaluated_fields = []
    
    # Pre-compute normalized expected values
    norm_expected = {k: normalize_val(v) for k, v in exp_key_values.items()}

    for fld in extracted_fields:
        lbl = str(fld.get("label", "")).strip()
        val = str(fld.get("value", "")).strip()
        conf = float(fld.get("confidence", 1.0))
        page = fld.get("page", 1)
        needs_review = bool(fld.get("needs_review", False))

        total_fields_count += 1
        confidence_histogram[round(conf, 4)] += 1
        is_missing_label = "yes" if not lbl else "no"
        if is_missing_label == "yes":
            unlabelled_fields_count += 1

        # Check for whole sentences or paragraphs stored as field
        if len(val) > 80 or (val.count(".") >= 2 and len(val) > 50):
            paragraph_fields.append({
                "file": base_name,
                "label": lbl or "(No label)",
                "length": len(val),
                "preview": val[:120] + "..." if len(val) > 120 else val,
            })

        # Match logic against expected values
        norm_v = normalize_val(val)
        matched_expected = "not in expected"
        matched_expected_key = None

        # 1. Exact or partial containment in expected values
        for exp_k, exp_v in norm_expected.items():
            if not exp_v:
                continue
            if norm_v == exp_v or (len(exp_v) > 3 and exp_v in norm_v) or (len(norm_v) > 3 and norm_v in exp_v):
                matched_expected = "yes"
                matched_expected_key = exp_k
                extracted_expected_matches[exp_kind][exp_k] += 1
                break

        # 2. If label closely matches an expected key but value differed
        if matched_expected == "not in expected":
            norm_lbl = normalize_val(lbl)
            for exp_k in norm_expected.keys():
                norm_ek = normalize_val(exp_k)
                if norm_lbl and (norm_lbl in norm_ek or norm_ek in norm_lbl):
                    matched_expected = "no"
                    break

        evaluated_fields.append({
            "label": lbl,
            "value": val,
            "confidence": conf,
            "page": page,
            "missing_label": is_missing_label,
            "matched_expected": matched_expected,
            "needs_review": needs_review,
        })

        # Update summary stats
        stat_lbl = lbl if lbl else "(Unlabelled)"
        t_stat = type_label_stats[output_json.get("type", "unknown")][stat_lbl]
        t_stat["count"] += 1
        t_stat["conf_sum"] += conf
        t_stat["doc_set"].add(base_name)
        if matched_expected == "yes":
            t_stat["match_yes"] += 1
        elif matched_expected == "no":
            t_stat["match_no"] += 1
        else:
            t_stat["not_in_exp"] += 1

        csv_rows.append({
            "file": base_name,
            "expected_type": exp_kind,
            "detected_type": output_json.get("type", "unknown"),
            "label": lbl,
            "value": val,
            "confidence": f"{conf:.4f}",
            "page": page,
            "missing_label": is_missing_label,
            "matched_expected": matched_expected,
        })

    # Sensitive findings masked
    sens_findings = output_json.get("sensitive_findings", [])
    masked_sens = []
    for s in sens_findings:
        m_val = s.get("masked_value") or s.get("value", "")
        # mask if raw
        if len(m_val) > 4:
            m_val = m_val[:2] + "*" * (len(m_val) - 4) + m_val[-2:]
        masked_sens.append(f"{s.get('detector_tag', 'PII')}: {m_val}")

    all_audit_results.append({
        "file_name": os.path.basename(doc_path),
        "base_name": base_name,
        "expected_kind": exp_kind,
        "detected_type": output_json.get("type", "unknown"),
        "type_confidence": output_json.get("type_confidence", 0.0),
        "routing": output_json.get("routing", {}),
        "sensitive_findings_masked": masked_sens,
        "total_fields": len(evaluated_fields),
        "unlabelled_count": sum(1 for f in evaluated_fields if f["missing_label"] == "yes"),
        "flagged_for_review_count": sum(1 for f in evaluated_fields if f["needs_review"] or f["confidence"] < 0.85),
        "fields": evaluated_fields,
        "previews": previews,
    })

# -----------------------------------------------------------------------------
# WRITE CSV REPORT
# -----------------------------------------------------------------------------
csv_path = "extraction_audit.csv"
with open(csv_path, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=[
        "file", "expected_type", "detected_type", "label", "value",
        "confidence", "page", "missing_label", "matched_expected"
    ])
    writer.writeheader()
    writer.writerows(csv_rows)
print(f"Exported extraction audit CSV to {csv_path} ({len(csv_rows)} rows).")

# -----------------------------------------------------------------------------
# SUMMARY CALCULATIONS
# -----------------------------------------------------------------------------
# 1. Table per document type
type_summary_tables = {}
for doc_t, labels_dict in type_label_stats.items():
    rows = []
    for lbl, st in labels_dict.items():
        doc_cnt = len(st["doc_set"])
        avg_conf = st["conf_sum"] / max(1, st["count"])
        total_eval = st["match_yes"] + st["match_no"]
        match_rate = (st["match_yes"] / total_eval * 100.0) if total_eval > 0 else 0.0
        rows.append({
            "label": lbl,
            "doc_count": doc_cnt,
            "total_extracted": st["count"],
            "avg_confidence": avg_conf,
            "match_rate": match_rate,
            "match_yes": st["match_yes"],
            "match_no": st["match_no"],
            "not_in_exp": st["not_in_exp"],
        })
    rows.sort(key=lambda r: (-r["doc_count"], -r["total_extracted"]))
    type_summary_tables[doc_t] = rows

# 2. Candidates to keep vs drop
candidates_keep = []
candidates_drop = []
for doc_t, rows in type_summary_tables.items():
    total_docs_of_t = max(1, len({res["base_name"] for res in all_audit_results if res["detected_type"] == doc_t}))
    for r in rows:
        pct_docs = (r["doc_count"] / total_docs_of_t) * 100.0
        if r["label"] == "(Unlabelled)":
            candidates_drop.append({
                "type": doc_t,
                "label": r["label"],
                "reason": f"Unlabelled noise ({r['total_extracted']} instances)",
            })
        elif pct_docs >= 60.0 and r["avg_confidence"] >= 0.85:
            candidates_keep.append({
                "type": doc_t,
                "label": r["label"],
                "frequency": f"{r['doc_count']}/{total_docs_of_t} docs ({pct_docs:.0f}%)",
                "avg_conf": f"{r['avg_confidence']:.2f}",
                "matches": r["match_yes"],
            })
        elif r["doc_count"] <= 1 and (r["avg_confidence"] < 0.85 or r["match_no"] > r["match_yes"]):
            candidates_drop.append({
                "type": doc_t,
                "label": r["label"],
                "reason": f"Low frequency ({r['doc_count']} doc) and low match rate",
            })

# 3. Missing expected fields
missing_fields_by_type = []
for doc_t, exp_counts in type_expected_fields.items():
    for fld_name, total_expected in exp_counts.items():
        extracted_cnt = extracted_expected_matches[doc_t].get(fld_name, 0)
        if extracted_cnt == 0:
            missing_fields_by_type.append({
                "type": doc_t,
                "expected_field": fld_name,
                "expected_count": total_expected,
                "extracted_count": 0,
            })

# 4. Totals
avg_fields_per_doc = total_fields_count / max(1, len(all_audit_results))
pct_unlabelled = (unlabelled_fields_count / max(1, total_fields_count)) * 100.0

# Identical confidence values
most_common_confs = confidence_histogram.most_common(5)
pct_identical_conf = (most_common_confs[0][1] / max(1, total_fields_count)) * 100.0 if most_common_confs else 0.0

# -----------------------------------------------------------------------------
# GENERATE HTML REPORT
# -----------------------------------------------------------------------------
html_path = "extraction_audit.html"

html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Document Extraction Audit Report (30 Documents)</title>
<style>
  :root {{
    --bg: #0f172a;
    --card-bg: #1e293b;
    --border: #334155;
    --text: #f8fafc;
    --sub: #94a3b8;
    --pri: #38bdf8;
    --success: #4ade80;
    --warn: #fbbf24;
    --err: #f87171;
  }}
  body {{
    margin: 0;
    padding: 24px;
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    line-height: 1.5;
  }}
  h1, h2, h3, h4 {{ color: #ffffff; margin-top: 0; }}
  .container {{ max-width: 1400px; margin: 0 auto; }}
  .summary-card {{
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 24px;
    margin-bottom: 32px;
  }}
  .metrics-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
    margin: 20px 0;
  }}
  .metric-box {{
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    text-align: center;
  }}
  .metric-val {{ font-size: 28px; font-weight: 700; color: var(--pri); margin: 6px 0; }}
  .metric-lbl {{ font-size: 13px; color: var(--sub); text-transform: uppercase; letter-spacing: 0.5px; }}
  
  table {{
    width: 100%;
    border-collapse: collapse;
    margin: 14px 0;
    font-size: 13px;
  }}
  th, td {{
    padding: 10px 12px;
    border: 1px solid var(--border);
    text-align: left;
    vertical-align: top;
  }}
  th {{ background: #0b1120; color: var(--sub); font-weight: 600; }}
  tr:nth-child(even) {{ background: rgba(255, 255, 255, 0.02); }}
  
  .badge {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 600;
  }}
  .badge-yes {{ background: #14532d; color: #86efac; }}
  .badge-no {{ background: #7f1d1d; color: #fca5a5; }}
  .badge-neutral {{ background: #374151; color: #d1d5db; }}
  .badge-warn {{ background: #78350f; color: #fde68a; }}
  
  .doc-section {{
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 20px;
    margin-bottom: 28px;
  }}
  .doc-header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid var(--border);
    padding-bottom: 12px;
    margin-bottom: 16px;
    flex-wrap: wrap;
    gap: 10px;
  }}
  .doc-meta-pills {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; }}
  .meta-pill {{
    background: #0b1120;
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 6px 12px;
    font-size: 12px;
  }}
  .meta-pill strong {{ color: var(--pri); }}
  
  .side-by-side {{
    display: grid;
    grid-template-columns: 420px 1fr;
    gap: 20px;
  }}
  @media (max-width: 1024px) {{
    .side-by-side {{ grid-template-columns: 1fr; }}
  }}
  .preview-col {{
    background: #020617;
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 12px;
    text-align: center;
    max-height: 800px;
    overflow-y: auto;
  }}
  .preview-col img {{
    max-width: 100%;
    border-radius: 4px;
    margin-bottom: 12px;
    box-shadow: 0 4px 6px rgba(0,0,0,0.3);
  }}
  .table-col {{
    overflow-x: auto;
  }}
</style>
</head>
<body>
<div class="container">
  <h1>Document Ingestion & Extraction Audit Report</h1>
  <p style="color: var(--sub);">Comprehensive evaluation of 30 synthetic business documents across 12 categories, testing layout-aware field extraction, holistic classification, and confidence calibration.</p>

  <!-- SUMMARY SECTION -->
  <div class="summary-card">
    <h2>Audit Executive Summary & Totals</h2>
    <div class="metrics-grid">
      <div class="metric-box">
        <div class="metric-val">{len(all_audit_results)}</div>
        <div class="metric-lbl">Total Documents</div>
      </div>
      <div class="metric-box">
        <div class="metric-val">{total_fields_count}</div>
        <div class="metric-lbl">Total Extracted Fields</div>
      </div>
      <div class="metric-box">
        <div class="metric-val">{avg_fields_per_doc:.1f}</div>
        <div class="metric-lbl">Avg Fields / Document</div>
      </div>
      <div class="metric-box">
        <div class="metric-val">{pct_unlabelled:.1f}%</div>
        <div class="metric-lbl">% Fields with No Label</div>
      </div>
      <div class="metric-box">
        <div class="metric-val">{pct_identical_conf:.1f}%</div>
        <div class="metric-lbl">Identical Confidence Spike</div>
      </div>
    </div>
    
    <h3>1. Field Extraction Statistics Per Document Type</h3>
"""

for doc_t, rows in type_summary_tables.items():
    html_content += f"""
    <h4>Type: <span style="color: var(--pri);">{doc_t.upper()}</span></h4>
    <table>
      <thead>
        <tr>
          <th>Distinct Label</th>
          <th>Doc Frequency</th>
          <th>Total Extractions</th>
          <th>Avg Confidence</th>
          <th>Matched Expected</th>
          <th>Not in Expected</th>
        </tr>
      </thead>
      <tbody>
    """
    for r in rows:
        conf_color = "var(--success)" if r["avg_confidence"] >= 0.85 else "var(--warn)"
        html_content += f"""
        <tr>
          <td><strong>{r['label']}</strong></td>
          <td>{r['doc_count']} docs</td>
          <td>{r['total_extracted']}</td>
          <td style="color: {conf_color};">{r['avg_confidence']:.2f}</td>
          <td><span class="badge badge-yes">{r['match_yes']} yes</span> / <span class="badge badge-no">{r['match_no']} no</span></td>
          <td><span class="badge badge-neutral">{r['not_in_exp']}</span></td>
        </tr>
        """
    html_content += """
      </tbody>
    </table>
    """

html_content += """
    <h3>2. Candidate Fields to Keep vs Drop</h3>
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
      <div>
        <h4 style="color: var(--success);">Keep Candidates (Reliable, High Frequency)</h4>
        <table>
          <thead>
            <tr><th>Type</th><th>Field</th><th>Doc Frequency</th><th>Avg Conf</th></tr>
          </thead>
          <tbody>
"""
for ck in candidates_keep:
    html_content += f"""
            <tr>
              <td>{ck['type']}</td>
              <td><strong>{ck['label']}</strong></td>
              <td>{ck['frequency']}</td>
              <td>{ck['avg_conf']}</td>
            </tr>
    """
html_content += """
          </tbody>
        </table>
      </div>
      <div>
        <h4 style="color: var(--err);">Drop Candidates (Noise, Low Frequency / Unlabelled)</h4>
        <table>
          <thead>
            <tr><th>Type</th><th>Label</th><th>Reason</th></tr>
          </thead>
          <tbody>
"""
for cd in candidates_drop:
    html_content += f"""
            <tr>
              <td>{cd['type']}</td>
              <td><strong>{cd['label']}</strong></td>
              <td>{cd['reason']}</td>
            </tr>
    """
html_content += """
          </tbody>
        </table>
      </div>
    </div>

    <h3>3. Missing Expected Fields</h3>
    <p style="color: var(--sub);">Fields present in expected.json that the application failed to extract:</p>
    <table>
      <thead>
        <tr><th>Type</th><th>Expected Field</th><th>Expected In # Docs</th><th>Extracted Count</th></tr>
      </thead>
      <tbody>
"""
if not missing_fields_by_type:
    html_content += "<tr><td colspan='4' style='text-align:center;'>Zero missing fields. All expected field keys were captured.</td></tr>"
else:
    for mf in missing_fields_by_type:
        html_content += f"""
        <tr>
          <td>{mf['type']}</td>
          <td><strong>{mf['expected_field']}</strong></td>
          <td>{mf['expected_count']}</td>
          <td><span class="badge badge-no">{mf['extracted_count']}</span></td>
        </tr>
        """
html_content += """
      </tbody>
    </table>

    <h3>4. Paragraphs Stored as Fields (Extraction Noise)</h3>
    <p style="color: var(--sub);">Long text blocks or sentences extracted into single field value boxes instead of raw page body:</p>
    <table>
      <thead>
        <tr><th>Document</th><th>Label</th><th>Char Length</th><th>Value Preview</th></tr>
      </thead>
      <tbody>
"""
if not paragraph_fields:
    html_content += "<tr><td colspan='4' style='text-align:center;'>No whole paragraphs stored as fields.</td></tr>"
else:
    for pf in paragraph_fields:
        html_content += f"""
        <tr>
          <td>{pf['file']}</td>
          <td>{pf['label']}</td>
          <td>{pf['length']} chars</td>
          <td><code>{pf['preview']}</code></td>
        </tr>
        """
html_content += """
      </tbody>
    </table>
  </div>

  <!-- INDIVIDUAL DOCUMENT SECTIONS -->
  <h2>Individual Document Results (30 Documents)</h2>
"""

for res in all_audit_results:
    type_badge = "badge-yes" if res["detected_type"] != "unknown" else "badge-neutral"
    review_badge = "badge-warn" if res["flagged_for_review_count"] > 0 else "badge-yes"
    routing_dest = res["routing"].get("destination", "MANUAL_TRIAGE_QUEUE")
    is_restr = res["routing"].get("is_restricted", False)
    sens_findings_str = ", ".join(res["sensitive_findings_masked"]) if res["sensitive_findings_masked"] else "None detected"

    html_content += f"""
  <div class="doc-section" id="{res['base_name']}">
    <div class="doc-header">
      <div>
        <h3 style="margin: 0;">{res['file_name']}</h3>
        <span style="font-size: 13px; color: var(--sub);">Expected: <strong>{res['expected_kind']}</strong> &bull; Detected: <span class="badge {type_badge}">{res['detected_type']} ({res['type_confidence']:.2f})</span></span>
      </div>
      <div>
        <span class="badge {review_badge}">{res['flagged_for_review_count']} Flagged for Review</span>
      </div>
    </div>

    <div class="doc-meta-pills">
      <div class="meta-pill">Routing: <strong>{routing_dest}</strong> {'(RESTRICTED)' if is_restr else ''}</div>
      <div class="meta-pill">Sensitive Findings: <strong>{sens_findings_str}</strong></div>
      <div class="meta-pill">Extracted Fields: <strong>{res['total_fields']}</strong></div>
      <div class="meta-pill">Unlabelled Fields: <strong>{res['unlabelled_count']}</strong></div>
    </div>

    <div class="side-by-side">
      <div class="preview-col">
        <h4 style="color: var(--sub); font-size: 13px; margin-bottom: 8px;">Document Preview</h4>
    """
    for p_b64 in res["previews"]:
        html_content += f'<img src="{p_b64}" alt="Page preview" />'
    
    html_content += """
      </div>
      <div class="table-col">
        <table>
          <thead>
            <tr>
              <th>Label</th>
              <th>Value</th>
              <th>Confidence</th>
              <th>Page</th>
              <th>Missing Label?</th>
              <th>Matches Expected?</th>
            </tr>
          </thead>
          <tbody>
    """
    for fld in res["fields"]:
        lbl_display = fld["label"] if fld["label"] else "<em style='color: var(--warn);'>(No label)</em>"
        miss_badge = "<span class='badge badge-warn'>Yes</span>" if fld["missing_label"] == "yes" else "<span class='badge badge-neutral'>No</span>"
        if fld["matched_expected"] == "yes":
            match_badge = "<span class='badge badge-yes'>yes</span>"
        elif fld["matched_expected"] == "no":
            match_badge = "<span class='badge badge-no'>no</span>"
        else:
            match_badge = "<span class='badge badge-neutral'>not in expected</span>"
        
        conf_display = f"{fld['confidence']:.2f}"
        if fld["confidence"] < 0.85:
            conf_display = f"<span style='color: var(--err); font-weight:600;'>{conf_display}</span>"

        html_content += f"""
            <tr>
              <td>{lbl_display}</td>
              <td><code>{fld['value']}</code></td>
              <td>{conf_display}</td>
              <td>{fld['page']}</td>
              <td>{miss_badge}</td>
              <td>{match_badge}</td>
            </tr>
        """
    html_content += """
          </tbody>
        </table>
      </div>
    </div>
  </div>
    """

html_content += """
</div>
</body>
</html>
"""

with open(html_path, "w", encoding="utf-8") as f:
    f.write(html_content)

print(f"Generated standalone extraction audit HTML report: {html_path}")
print("Audit pipeline complete!")
