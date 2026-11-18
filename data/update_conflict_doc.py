"""Update conflict document with strong letter signals and high-risk PII."""

import json
from pathlib import Path
from data.synthetic_generator import render_pdf_document

SPECIAL_DIR = Path("data/dataset/special")

conflict_text = """
============================================================
              FORMAL LETTER OF CORRESPONDENCE
============================================================
From: Corporate Communications Division, Global Enterprise Inc.
To: Valued Stakeholder Johnathan Doe
Date: 2026-03-01
Subject: Formal Stakeholder Letter Regarding Annual Corporate Policies

Dear Valued Stakeholder,

We are writing to officially provide you with this formal letter of correspondence
regarding our updated annual enterprise policies and shareholder governance guidelines.

Please review the attached terms and keep this letter for your correspondence records.
For identity verification under corporate compliance requirements:
Primary SSN on Record: 987-65-4321
Passport Identifier: P88776655
Medical License Reference: MD-445566

Should you have any questions regarding this correspondence, please reply to this letter.

Sincerely,
Corporate Secretarial Office
Global Enterprise Inc.
"""

pdf_bytes = render_pdf_document(conflict_text)
with open(SPECIAL_DIR / "special_conflict_document.pdf", "wb") as f:
    f.write(pdf_bytes)

print("Updated special_conflict_document.pdf with high-confidence letter text and high-risk PII.")
