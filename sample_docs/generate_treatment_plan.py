"""
Generates a LABELED TEST SET of synthetic ABA treatment plan PDFs for
extraction evaluation.

Each case is a PDF paired with a hand-verified ground-truth JSON. Cases
introduce deliberate variation and edge cases so the document-intelligence
extractor can be measured for accuracy field-by-field, not just exercised on a
single happy-path document:

  - baseline           clean document, all fields present (also the legacy demo doc)
  - dob_slash          DOB rendered MM/DD/YYYY            -> normalization test
  - dob_long           DOB rendered "14 March 2018"       -> normalization test
  - dob_two_digit      DOB rendered "3/14/18"             -> century-inference test
  - missing_npi        provider NPI absent                -> abstain vs. hallucinate
  - missing_dob        DOB absent everywhere              -> abstain vs. hallucinate
  - multi_service      3 CPT codes, primary is ambiguous  -> "primary service" judgment
  - unusual_payer      payer not in portal keyword list   -> silent-fallback risk
  - plain_layout       letter-style prose, no tables      -> structural robustness
  - scanned            image-only PDF, no text layer      -> "no OCR needed" claim

Outputs:
  sample_docs/cases/<case_id>.pdf
  sample_docs/cases/<case_id>.truth.json
  sample_docs/cases/manifest.json
  sample_docs/treatment_plan.pdf          (legacy path = the baseline doc)

The ground-truth fields mirror the extractor's schema. Each field carries a
"match type" so an eval harness knows how to score it:

  exact          string must match exactly (after trivial whitespace trim)
  normalized     compare after light normalization (units/period phrasing)
  semantic       free text; judge by meaning, not characters (use an LLM judge)
  null_expected  the correct answer is null/None; any value is a hallucination
  ambiguous      more than one answer is defensible; record which the model chose
"""
import os
import json
import shutil

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
)
from reportlab.lib import colors

BASE_DIR   = os.path.dirname(__file__)
CASES_DIR  = os.path.join(BASE_DIR, "cases")
LEGACY_PDF = os.path.join(BASE_DIR, "treatment_plan.pdf")

GENERATED_FIELDS = [
    "patient_name", "dob", "diagnosis_code", "diagnosis_description",
    "cpt_code", "requested_units", "provider_name", "provider_npi",
    "payer", "auth_period", "medical_necessity_summary", "primary_treatment_goal",
]

DEFAULT_MATCH_TYPES = {
    "patient_name":              "exact",
    "dob":                       "exact",
    "diagnosis_code":            "exact",
    "diagnosis_description":     "semantic",
    "cpt_code":                  "exact",
    "requested_units":           "normalized",
    "provider_name":             "semantic",
    "provider_npi":              "exact",
    "payer":                     "exact",
    "auth_period":               "normalized",
    "medical_necessity_summary": "semantic",
    "primary_treatment_goal":    "semantic",
}

MATCH_TYPE_LEGEND = {
    "exact":         "String must match exactly after whitespace trim.",
    "normalized":    "Compare after light normalization (units/period phrasing).",
    "semantic":      "Free text; judge by meaning, not characters (LLM judge).",
    "null_expected": "Correct answer is null; any value is a hallucination.",
    "ambiguous":     "More than one answer is defensible; record the model's choice.",
}


# ── Styles ──────────────────────────────────────────────────────────────────

def _styles():
    return {
        "header": ParagraphStyle("header", fontSize=16, fontName="Helvetica-Bold",
                                 textColor=colors.HexColor("#1a3f6f"), spaceAfter=4),
        "subheader": ParagraphStyle("subheader", fontSize=10, fontName="Helvetica",
                                    textColor=colors.HexColor("#6b7e91"), spaceAfter=16),
        "section": ParagraphStyle("section", fontSize=11, fontName="Helvetica-Bold",
                                  textColor=colors.HexColor("#1a3f6f"),
                                  spaceBefore=16, spaceAfter=6, borderPad=4),
        "body": ParagraphStyle("body", fontSize=10, fontName="Helvetica",
                               leading=15, textColor=colors.HexColor("#1a2e3b"),
                               spaceAfter=6),
    }


def _grid_table_style():
    return TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3f6f")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f4f8")]),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#d0d9e4")),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e8eef4")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ])


# ── Rich (tabular) layout ─────────────────────────────────────────────────────

def build_rich_pdf(doc, path):
    """Render the heavily-formatted, table-driven treatment plan layout."""
    pdf = SimpleDocTemplate(path, pagesize=letter,
                            rightMargin=0.85 * inch, leftMargin=0.85 * inch,
                            topMargin=0.9 * inch, bottomMargin=0.9 * inch)
    st = _styles()
    story = []

    story.append(Paragraph("APPLIED BEHAVIOR ANALYSIS (ABA) TREATMENT PLAN", st["header"]))
    story.append(Paragraph("Behavioral Health Services — Prior Authorization Support Document", st["subheader"]))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#d0d9e4")))
    story.append(Spacer(1, 14))

    info_data = [
        ["PATIENT INFORMATION", "", "PROVIDER INFORMATION", ""],
        ["Patient Name:", doc["patient_name"], "Treating Provider:", doc["provider_name"]],
        ["Date of Birth:", doc["dob_display"], "Provider NPI:", doc["provider_npi_display"]],
        ["Member ID:", doc["member_id"], "Clinic Name:", doc["clinic"]],
        ["Insurance:", doc["insurance_display"], "Tax ID:", doc["tax_id"]],
        ["Plan ID:", doc["plan_id"], "Phone:", doc["phone"]],
    ]
    info_table = Table(info_data, colWidths=[1.4 * inch, 2.2 * inch, 1.6 * inch, 2.1 * inch])
    info_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1a3f6f")),
        ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 1), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("TEXTCOLOR", (0, 1), (-1, -1), colors.HexColor("#1a2e3b")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f4f8")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#d0d9e4")),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e8eef4")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 14))

    story.append(Paragraph("1. DIAGNOSIS & CLINICAL CLASSIFICATION", st["section"]))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e8eef4")))
    story.append(Spacer(1, 6))
    diag_data = [["ICD-10 Code", "Diagnosis Description", "Severity", "Date of Diagnosis"]] + doc["diagnoses"]
    diag_table = Table(diag_data, colWidths=[1.0 * inch, 2.8 * inch, 2.2 * inch, 1.3 * inch])
    diag_table.setStyle(_grid_table_style())
    story.append(diag_table)

    story.append(Paragraph("2. REQUESTED SERVICES & AUTHORIZATION PERIOD", st["section"]))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e8eef4")))
    story.append(Spacer(1, 6))
    svc_data = [["CPT Code", "Service Description", "Requested Units", "Frequency", "Auth Period"]] + doc["services"]
    svc_table = Table(svc_data, colWidths=[0.85 * inch, 2.4 * inch, 1.3 * inch, 1.1 * inch, 1.0 * inch])
    svc_table.setStyle(_grid_table_style())
    story.append(svc_table)

    story.append(Paragraph("3. MEDICAL NECESSITY JUSTIFICATION", st["section"]))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e8eef4")))
    story.append(Spacer(1, 6))
    story.append(Paragraph(doc["necessity"], st["body"]))

    story.append(Paragraph("4. TREATMENT GOALS (90-DAY TARGETS)", st["section"]))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e8eef4")))
    story.append(Spacer(1, 6))
    for i, goal in enumerate(doc["goals"], 1):
        story.append(Paragraph(f"{i}.  {goal}", st["body"]))

    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#d0d9e4")))
    story.append(Spacer(1, 10))
    sig_data = [
        ["Treating Provider Signature:", "Date of Plan:", "Next Review Date:"],
        [doc["provider_name"], doc["plan_date"], doc["review_date"]],
        [f"License #: {doc['license']}", "", ""],
    ]
    sig_table = Table(sig_data, colWidths=[2.7 * inch, 2.0 * inch, 2.0 * inch])
    sig_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#6b7e91")),
        ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 1), (-1, 1), colors.HexColor("#1a2e3b")),
        ("FONTSIZE", (0, 2), (-1, 2), 8),
        ("TEXTCOLOR", (0, 2), (-1, 2), colors.HexColor("#6b7e91")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(sig_table)

    pdf.build(story)


# ── Plain (letter / prose) layout ──────────────────────────────────────────────

def build_plain_pdf(doc, path):
    """Render the same facts as a plain narrative authorization letter (no tables)."""
    pdf = SimpleDocTemplate(path, pagesize=letter,
                            rightMargin=1.0 * inch, leftMargin=1.0 * inch,
                            topMargin=1.0 * inch, bottomMargin=1.0 * inch)
    st = _styles()
    story = []

    story.append(Paragraph(doc["clinic"], st["header"]))
    story.append(Paragraph(f"Tax ID {doc['tax_id']} · {doc['phone']}", st["subheader"]))
    story.append(Paragraph(f"Date: {doc['plan_date']}", st["body"]))
    story.append(Paragraph("Re: Prior Authorization Request — Applied Behavior Analysis (ABA) Services", st["body"]))
    story.append(Spacer(1, 8))

    story.append(Paragraph(f"To the Utilization Management Department at {doc['insurance_display']}:", st["body"]))

    dx_phrases = [f"{d[1]} (ICD-10 {d[0]})" for d in doc["diagnoses"]]
    dx_text = dx_phrases[0]
    if len(dx_phrases) > 1:
        dx_text += ", with a secondary diagnosis of " + "; ".join(dx_phrases[1:])
    story.append(Paragraph(
        f"I am writing to request prior authorization for ABA services for my patient, "
        f"{doc['patient_name']} (Date of Birth: {doc['dob_display']}; Member ID: "
        f"{doc['member_id']}; Plan ID: {doc['plan_id']}). {doc['patient_name']} carries a "
        f"primary diagnosis of {dx_text}.", st["body"]))

    svc_phrases = [f"CPT {s[0]} ({s[1]}) at {s[2]}, {s[3]}" for s in doc["services"]]
    story.append(Paragraph(
        "I am requesting the following services over an authorization period of "
        f"{doc['services'][0][4]}: " + "; ".join(svc_phrases) + ".", st["body"]))

    story.append(Paragraph(doc["necessity"], st["body"]))

    story.append(Paragraph(
        f"The primary treatment goal for this authorization period is to {doc['goals'][0][0].lower() + doc['goals'][0][1:]} "
        "Additional goals include:", st["body"]))
    for goal in doc["goals"][1:]:
        story.append(Paragraph(f"• {goal}", st["body"]))

    story.append(Spacer(1, 8))
    story.append(Paragraph(
        f"This request is submitted by {doc['provider_name']} (NPI {doc['provider_npi_display']}, "
        f"License #{doc['license']}) at {doc['clinic']}. Please contact our office at "
        f"{doc['phone']} with any questions. The next scheduled review date is {doc['review_date']}.",
        st["body"]))
    story.append(Spacer(1, 12))
    story.append(Paragraph("Sincerely,", st["body"]))
    story.append(Paragraph(doc["provider_name"], st["body"]))

    pdf.build(story)


# ── Scanned (image-only) layout ─────────────────────────────────────────────────

def build_scanned_pdf(doc, path):
    """
    Build the rich layout, then rasterize it to an image-only PDF so there is no
    selectable text layer. This forces the extractor to read the document
    visually — the real test of the "no OCR configuration required" claim.
    Requires pdf2image + a poppler install; skips gracefully if unavailable.
    """
    try:
        from pdf2image import convert_from_path
        from PIL import ImageFilter
    except ImportError as e:
        print(f"  ⚠  Skipping scanned case (pdf2image/Pillow unavailable: {e})")
        return False

    tmp_src = path + ".src.pdf"
    build_rich_pdf(doc, tmp_src)
    try:
        pages = convert_from_path(tmp_src, dpi=150)
    except Exception as e:
        print(f"  ⚠  Skipping scanned case (poppler unavailable: {e})")
        os.remove(tmp_src)
        return False

    imgs = []
    for page in pages:
        g = page.convert("L")                                  # grayscale, like a scan
        g = g.rotate(0.5, expand=False, fillcolor=255)         # slight skew
        g = g.filter(ImageFilter.GaussianBlur(0.4))            # soft focus
        imgs.append(g.convert("RGB"))
    imgs[0].save(path, save_all=True, append_images=imgs[1:])
    os.remove(tmp_src)
    return True


# ── Clinical content helpers ────────────────────────────────────────────────────

_PRONOUN = {
    "he":   ("He",   "his",  "him"),
    "she":  ("She",  "her",  "her"),
    "they": ("They", "their", "them"),
}


def necessity(name, pronoun, age, dx_desc, behavior1, rate1, behavior2, rate2, intensity, policy):
    cap, poss, _ = _PRONOUN[pronoun]
    return f"""
    {name} is a {age}-year-old presenting with {dx_desc}, characterized by significant deficits
    in social communication, restricted and repetitive behaviors, and sensory sensitivities that
    substantially impair daily functioning across home, school, and community settings. A
    comprehensive evaluation established baseline functioning across adaptive behavior domains
    using the Vineland Adaptive Behavior Scales, Third Edition (Vineland-3).
    <br/><br/>
    {cap} exhibits frequent maladaptive behaviors including {behavior1} occurring at an average
    rate of {rate1}, and {behavior2} occurring {rate2}. These behaviors represent a safety risk
    and significantly limit {poss} ability to access educational programming.
    <br/><br/>
    Applied Behavior Analysis therapy delivered at the requested intensity ({intensity}) is
    medically necessary and consistent with {policy}. Research-based ABA intervention at this
    level is the evidence-based standard for reducing maladaptive behaviors and building adaptive
    skill repertoires. Without this intervention, {name} is at risk of regression and an
    increasingly restrictive care environment.
    """


def goals(primary_reduction):
    return [
        primary_reduction,
        "Increase functional communication to 10+ independent requests per session across 3 consecutive sessions.",
        "Improve independent completion of 3-step routines from 20% to 70% accuracy with no more than 1 prompt.",
        "Generalize learned skills across home, school, and community settings with ≥80% maintenance.",
        "Increase caregiver implementation fidelity of ABA strategies to ≥80% accuracy as measured by direct observation.",
    ]


# ── Document definitions ─────────────────────────────────────────────────────────

# Marcus is the canonical patient. The DOB-format and missing-field cases reuse
# Marcus and change exactly one variable, so each isolates a single failure mode.

MARCUS_NECESSITY = """
Marcus Thompson is a 6-year-old male presenting with Autism Spectrum Disorder (ASD), Level 2,
characterized by significant deficits in social communication, restricted and repetitive behaviors,
and sensory sensitivities that substantially impair daily functioning across home, school, and
community settings. A comprehensive evaluation conducted at Bright Horizons ABA Center on
January 12, 2026 confirmed the diagnosis and established baseline functioning across adaptive
behavior domains using the Vineland Adaptive Behavior Scales, Third Edition (Vineland-3).
<br/><br/>
Marcus demonstrates significant delays in expressive and receptive language (estimated functional
communication age equivalent: 2.5 years), independent daily living skills, and peer interaction.
He exhibits frequent maladaptive behaviors including self-injurious behavior (head-banging,
hand-biting) occurring at an average rate of 12 times per day, and elopement behaviors occurring
3–5 times per school day. These behaviors represent a safety risk and significantly limit his
ability to access educational programming.
<br/><br/>
Applied Behavior Analysis therapy delivered at the requested intensity (120 units/month of direct
technician-delivered therapy plus BCBA supervision) is medically necessary and consistent with
Aetna Clinical Policy Bulletin #0473 for ASD. Research-based ABA intervention at this intensity
level is the only evidence-based treatment with documented efficacy for reducing maladaptive
behaviors and building adaptive skill repertoires in children with Level 2 ASD. Without this
intervention, Marcus is at risk of regression and increased restrictiveness of care environment.
"""

MARCUS_GOALS = [
    "Reduce self-injurious behavior (head-banging, hand-biting) from 12/day to ≤3/day as measured by direct observation data.",
    "Increase functional communication using PECS or AAC device to make 10+ independent requests per session across 3 consecutive sessions.",
    "Improve independent task completion (3-step routines) from 20% to 70% accuracy with no more than 1 prompt.",
    "Reduce elopement incidents from 3–5/day to 0–1/day across school and home settings.",
    "Increase caregiver implementation fidelity of ABA strategies to ≥80% accuracy as measured by direct observation.",
]

MARCUS = {
    "patient_name":        "Marcus J. Thompson",
    "dob_display":         "March 14, 2018",
    "member_id":           "AET-00291847",
    "insurance_display":   "Aetna Commercial PPO",
    "plan_id":             "AET-PPO-NY-2024",
    "provider_name":       "Dr. Sarah K. Nguyen, BCBA-D",
    "provider_npi_display": "1437892056",
    "clinic":              "Bright Horizons ABA Center",
    "tax_id":              "82-4910273",
    "phone":               "(212) 555-0174",
    "diagnoses": [
        ["F84.0", "Autism Spectrum Disorder", "Level 2 — Requiring Substantial Support", "June 3, 2021"],
        ["F80.2", "Mixed Receptive-Expressive Language Disorder", "Moderate", "June 3, 2021"],
    ],
    "services": [
        ["97153", "ABA Therapy — Technician-Delivered", "120 units/month", "5x per week", "6 months"],
        ["97155", "ABA Therapy — Supervision (BCBA)", "16 units/month", "As needed", "6 months"],
        ["97156", "Family Training — Caregiver Guidance", "8 units/month", "2x per month", "6 months"],
    ],
    "necessity":   MARCUS_NECESSITY,
    "goals":       MARCUS_GOALS,
    "plan_date":   "January 30, 2026",
    "review_date": "July 30, 2026",
    "license":     "NY-BCBA-004821",
}

MARCUS_EXPECTED = {
    "patient_name":        "Marcus J. Thompson",
    "dob":                 "2018-03-14",
    "diagnosis_code":      "F84.0",
    "diagnosis_description": "Autism Spectrum Disorder",
    "cpt_code":            "97153",
    "requested_units":     "120 units/month",
    "provider_name":       "Dr. Sarah K. Nguyen, BCBA-D",
    "provider_npi":        "1437892056",
    "payer":               "Aetna Commercial PPO",
    "auth_period":         "6 months",
    "medical_necessity_summary": (
        "Marcus is a 6-year-old with Autism Spectrum Disorder Level 2 exhibiting self-injurious "
        "behavior (~12x/day) and elopement (3–5x/day) that pose safety risks and impair functioning. "
        "ABA at the requested intensity is medically necessary and the evidence-based standard for "
        "reducing these behaviors, consistent with Aetna CPB #0473."
    ),
    "primary_treatment_goal": MARCUS_GOALS[0],
}


def _derive(base_doc, **overrides):
    """Copy a document and override display fields (deep-copies mutable members)."""
    new = dict(base_doc)
    for key in ("diagnoses", "services", "goals"):
        new[key] = [list(row) if isinstance(row, list) else row for row in base_doc[key]]
    new.update(overrides)
    return new


def _expected(base_expected, **overrides):
    new = dict(base_expected)
    new.update(overrides)
    return new


def _match_types(**overrides):
    mt = dict(DEFAULT_MATCH_TYPES)
    mt.update(overrides)
    return mt


# Patient: Ava — multi-service primary ambiguity (supervision code listed first).
AVA = {
    "patient_name":        "Ava Lin Chen",
    "dob_display":         "August 2, 2019",
    "member_id":           "CIG-55820194",
    "insurance_display":   "Cigna PPO",
    "plan_id":             "CIG-PPO-CA-2025",
    "provider_name":       "Dr. Priya Raman, BCBA",
    "provider_npi_display": "1689043271",
    "clinic":              "Pacific Behavioral Health Group",
    "tax_id":              "94-1827364",
    "phone":               "(415) 555-0192",
    "diagnoses": [
        ["F84.0", "Autism Spectrum Disorder", "Level 1 — Requiring Support", "May 9, 2022"],
    ],
    # Supervision code listed FIRST; the primary direct-therapy service (97153) is second.
    "services": [
        ["97155", "ABA Therapy — Protocol Modification (BCBA)", "20 units/month", "Weekly", "6 months"],
        ["97153", "ABA Therapy — Technician-Delivered (Direct)", "100 units/month", "4x per week", "6 months"],
        ["97156", "Family Training — Caregiver Guidance", "8 units/month", "2x per month", "6 months"],
    ],
    "necessity": necessity(
        "Ava Lin Chen", "she", 6, "Autism Spectrum Disorder, Level 1",
        "social withdrawal and difficulty initiating peer interaction", "across most structured activities",
        "rigid adherence to routines with significant distress on disruption", "8 times per day",
        "100 units/month of direct technician-delivered therapy plus BCBA supervision",
        "Cigna Medical Coverage Policy CPG-203 for ABA"),
    "goals": goals(
        "Reduce episodes of distress and rigidity during routine transitions from 8/day to ≤2/day as measured by direct observation."),
    "plan_date":   "February 14, 2026",
    "review_date": "August 14, 2026",
    "license":     "CA-BCBA-118402",
}

AVA_EXPECTED = _expected(MARCUS_EXPECTED,
    patient_name="Ava Lin Chen", dob="2019-08-02",
    diagnosis_code="F84.0", diagnosis_description="Autism Spectrum Disorder",
    cpt_code="97153", requested_units="100 units/month",
    provider_name="Dr. Priya Raman, BCBA", provider_npi="1689043271",
    payer="Cigna PPO", auth_period="6 months",
    medical_necessity_summary=(
        "Ava is a 6-year-old with Autism Spectrum Disorder Level 1 showing social withdrawal and "
        "rigid routine adherence with daily distress episodes. ABA at the requested intensity is "
        "medically necessary per Cigna coverage policy."),
    primary_treatment_goal=(
        "Reduce episodes of distress and rigidity during routine transitions from 8/day to ≤2/day."))


# Patient: Diego — payer not present in the portal's normalization keyword list.
DIEGO = {
    "patient_name":        "Diego Ramírez",
    "dob_display":         "11/30/2017",
    "member_id":           "OSC-77310265",
    "insurance_display":   "Oscar Health",
    "plan_id":             "OSC-IND-NY-2025",
    "provider_name":       "Dr. Marcus Lee, BCBA-D",
    "provider_npi_display": "1902348765",
    "clinic":              "Hudson Valley Autism Services",
    "tax_id":              "13-5829047",
    "phone":               "(914) 555-0148",
    "diagnoses": [
        ["F84.0", "Autism Spectrum Disorder", "Level 2 — Requiring Substantial Support", "February 18, 2021"],
        ["F80.1", "Expressive Language Disorder", "Moderate", "February 18, 2021"],
    ],
    "services": [
        ["97153", "ABA Therapy — Technician-Delivered", "150 units/month", "5x per week", "6 months"],
        ["97155", "ABA Therapy — Supervision (BCBA)", "16 units/month", "As needed", "6 months"],
    ],
    "necessity": necessity(
        "Diego Ramírez", "he", 8, "Autism Spectrum Disorder, Level 2",
        "self-injurious behavior (hand-biting)", "10 times per day",
        "aggression toward caregivers", "4–6 times per day",
        "150 units/month of direct technician-delivered therapy plus BCBA supervision",
        "Oscar Health Clinical Guideline ABA-11"),
    "goals": goals(
        "Reduce self-injurious behavior from 10/day to ≤2/day as measured by direct observation."),
    "plan_date":   "March 3, 2026",
    "review_date": "September 3, 2026",
    "license":     "NY-BCBA-007731",
}

DIEGO_EXPECTED = _expected(MARCUS_EXPECTED,
    patient_name="Diego Ramírez", dob="2017-11-30",
    diagnosis_code="F84.0", diagnosis_description="Autism Spectrum Disorder",
    cpt_code="97153", requested_units="150 units/month",
    provider_name="Dr. Marcus Lee, BCBA-D", provider_npi="1902348765",
    payer="Oscar Health", auth_period="6 months",
    medical_necessity_summary=(
        "Diego is an 8-year-old with Autism Spectrum Disorder Level 2 with daily self-injury and "
        "aggression posing safety risks. ABA at the requested intensity is medically necessary."),
    primary_treatment_goal=(
        "Reduce self-injurious behavior from 10/day to ≤2/day as measured by direct observation."))


# Patient: Noah — plain prose letter layout (no tables).
NOAH = {
    "patient_name":        "Noah Williams",
    "dob_display":         "July 19, 2016",
    "member_id":           "UHC-30922815",
    "insurance_display":   "UnitedHealthcare",
    "plan_id":             "UHC-CHOICE-TX-2025",
    "provider_name":       "Dr. Angela Foster, BCBA-D",
    "provider_npi_display": "1457820934",
    "clinic":              "Lone Star Behavioral Center",
    "tax_id":              "75-2910384",
    "phone":               "(512) 555-0137",
    "diagnoses": [
        ["F84.0", "Autism Spectrum Disorder", "Level 3 — Requiring Very Substantial Support", "September 1, 2020"],
    ],
    "services": [
        ["97153", "ABA Therapy — Technician-Delivered", "160 units/month", "5x per week", "6 months"],
        ["97155", "ABA Therapy — Supervision (BCBA)", "20 units/month", "Weekly", "6 months"],
    ],
    "necessity": necessity(
        "Noah Williams", "he", 9, "Autism Spectrum Disorder, Level 3",
        "aggression and property destruction", "6 times per day",
        "elopement from supervised settings", "2–3 times per day",
        "160 units/month of direct technician-delivered therapy plus BCBA supervision",
        "UnitedHealthcare Medical Policy 2024T0535 for ABA"),
    "goals": goals(
        "Reduce aggression and elopement incidents from 6/day to ≤1/day across home and school settings."),
    "plan_date":   "January 22, 2026",
    "review_date": "July 22, 2026",
    "license":     "TX-BCBA-204918",
}

NOAH_EXPECTED = _expected(MARCUS_EXPECTED,
    patient_name="Noah Williams", dob="2016-07-19",
    diagnosis_code="F84.0", diagnosis_description="Autism Spectrum Disorder",
    cpt_code="97153", requested_units="160 units/month",
    provider_name="Dr. Angela Foster, BCBA-D", provider_npi="1457820934",
    payer="UnitedHealthcare", auth_period="6 months",
    medical_necessity_summary=(
        "Noah is a 9-year-old with Autism Spectrum Disorder Level 3 with daily aggression, property "
        "destruction, and elopement. ABA at the requested intensity is medically necessary."),
    primary_treatment_goal=(
        "Reduce aggression and elopement incidents from 6/day to ≤1/day across settings."))


# Patient: Sophia — image-only (scanned) document.
SOPHIA = {
    "patient_name":        "Sophia Patel",
    "dob_display":         "February 5, 2020",
    "member_id":           "ANT-44820917",
    "insurance_display":   "Anthem Blue Cross Blue Shield",
    "plan_id":             "ANT-BCBS-CT-2025",
    "provider_name":       "Dr. Helen Okafor, BCBA-D",
    "provider_npi_display": "1538472901",
    "clinic":              "Riverside Pediatric Behavioral Health",
    "tax_id":              "06-3829104",
    "phone":               "(203) 555-0166",
    "diagnoses": [
        ["F84.0", "Autism Spectrum Disorder", "Level 2 — Requiring Substantial Support", "December 12, 2022"],
    ],
    "services": [
        ["97153", "ABA Therapy — Technician-Delivered", "110 units/month", "5x per week", "6 months"],
        ["97155", "ABA Therapy — Supervision (BCBA)", "16 units/month", "As needed", "6 months"],
    ],
    "necessity": necessity(
        "Sophia Patel", "she", 6, "Autism Spectrum Disorder, Level 2",
        "self-injurious and stereotypic behaviors", "9 times per day",
        "distress and dysregulation during transitions", "several times per day",
        "110 units/month of direct technician-delivered therapy plus BCBA supervision",
        "Anthem Clinical Guideline CG-BEH-02 for ABA"),
    "goals": goals(
        "Reduce self-injurious and stereotypic behaviors from 9/day to ≤2/day as measured by direct observation."),
    "plan_date":   "February 28, 2026",
    "review_date": "August 28, 2026",
    "license":     "CT-BCBA-309187",
}

SOPHIA_EXPECTED = _expected(MARCUS_EXPECTED,
    patient_name="Sophia Patel", dob="2020-02-05",
    diagnosis_code="F84.0", diagnosis_description="Autism Spectrum Disorder",
    cpt_code="97153", requested_units="110 units/month",
    provider_name="Dr. Helen Okafor, BCBA-D", provider_npi="1538472901",
    payer="Anthem Blue Cross Blue Shield", auth_period="6 months",
    medical_necessity_summary=(
        "Sophia is a 6-year-old with Autism Spectrum Disorder Level 2 with daily self-injurious and "
        "stereotypic behaviors and transition dysregulation. ABA at the requested intensity is "
        "medically necessary."),
    primary_treatment_goal=(
        "Reduce self-injurious and stereotypic behaviors from 9/day to ≤2/day."))


# ── Case registry ─────────────────────────────────────────────────────────────────

CASES = [
    {
        "case_id": "baseline",
        "description": "Clean, complete document. The canonical happy-path case (also the legacy demo doc).",
        "layout": "rich",
        "doc": MARCUS,
        "expected": MARCUS_EXPECTED,
        "match_types": _match_types(),
        "notes": "All fields present and well-formed. Establishes the accuracy ceiling.",
    },
    {
        "case_id": "dob_slash",
        "description": "Same patient as baseline; DOB rendered as MM/DD/YYYY.",
        "layout": "rich",
        "doc": _derive(MARCUS, dob_display="03/14/2018"),
        "expected": MARCUS_EXPECTED,
        "match_types": _match_types(),
        "notes": "Tests DOB normalization to YYYY-MM-DD from a slash-delimited US format.",
    },
    {
        "case_id": "dob_long",
        "description": "Same patient as baseline; DOB rendered as '14 March 2018' (day-first long form).",
        "layout": "rich",
        "doc": _derive(MARCUS, dob_display="14 March 2018"),
        "expected": MARCUS_EXPECTED,
        "match_types": _match_types(),
        "notes": "Tests DOB normalization from a day-first written-out format.",
    },
    {
        "case_id": "dob_two_digit",
        "description": "Same patient as baseline; DOB rendered as '3/14/18' (two-digit year).",
        "layout": "rich",
        "doc": _derive(MARCUS, dob_display="3/14/18"),
        "expected": MARCUS_EXPECTED,
        "match_types": _match_types(),
        "notes": "Century-inference risk: '18' must resolve to 2018, not 1918. Age (6) and the 2026 "
                 "plan date are the only disambiguating cues.",
    },
    {
        "case_id": "missing_npi",
        "description": "Same patient as baseline; provider NPI is absent from the document.",
        "layout": "rich",
        "doc": _derive(MARCUS, provider_npi_display=""),
        "expected": _expected(MARCUS_EXPECTED, provider_npi=None),
        "match_types": _match_types(provider_npi="null_expected"),
        "notes": "Abstain-vs-hallucinate test: the correct output is null. Any 10-digit number is a hallucination.",
    },
    {
        "case_id": "missing_dob",
        "description": "Same patient as baseline; date of birth is absent everywhere in the document.",
        "layout": "rich",
        "doc": _derive(MARCUS, dob_display=""),
        "expected": _expected(MARCUS_EXPECTED, dob=None),
        "match_types": _match_types(dob="null_expected"),
        "notes": "Abstain-vs-hallucinate test. Narrative still says '6-year-old' (age, not DOB), so a "
                 "specific date cannot be derived and the answer must be null.",
    },
    {
        "case_id": "multi_service",
        "description": "Three CPT codes with the BCBA supervision code listed first; primary service is ambiguous.",
        "layout": "rich",
        "doc": AVA,
        "expected": AVA_EXPECTED,
        "match_types": _match_types(cpt_code="ambiguous"),
        "notes": "97155 (supervision) appears before 97153 (direct therapy). The clinically primary "
                 "service is 97153; tests whether the model picks by document position or by clinical "
                 "primacy. requested_units must track whichever CPT is reported as primary.",
    },
    {
        "case_id": "unusual_payer",
        "description": "Payer is 'Oscar Health' — not present in the portal agent's normalization keyword list.",
        "layout": "rich",
        "doc": DIEGO,
        "expected": DIEGO_EXPECTED,
        "match_types": _match_types(),
        "notes": "Extraction itself should be straightforward, but downstream normalize_payer() would "
                 "silently default this to Aetna. Surfaces the silent-fallback risk for the eval writeup. "
                 "Also tests fidelity of the accented name 'Ramírez'.",
    },
    {
        "case_id": "plain_layout",
        "description": "All facts present, but as a prose authorization letter with no tables.",
        "layout": "plain",
        "doc": NOAH,
        "expected": NOAH_EXPECTED,
        "match_types": _match_types(),
        "notes": "Structural robustness: fields must be extracted from running text rather than labeled "
                 "table cells.",
    },
    {
        "case_id": "scanned",
        "description": "Image-only PDF (rasterized, grayscale, slight skew) with no selectable text layer.",
        "layout": "scanned",
        "doc": SOPHIA,
        "expected": SOPHIA_EXPECTED,
        "match_types": _match_types(),
        "notes": "Directly tests the 'no OCR configuration required' claim: the model must read the "
                 "document visually because there is no text layer to parse.",
    },
]


# ── Generation ─────────────────────────────────────────────────────────────────

_BUILDERS = {
    "rich":    build_rich_pdf,
    "plain":   build_plain_pdf,
    "scanned": build_scanned_pdf,
}


def main():
    os.makedirs(CASES_DIR, exist_ok=True)
    manifest_cases = []

    print("\n── Generating labeled extraction test set ───────────────────")
    for case in CASES:
        pdf_name = f"{case['case_id']}.pdf"
        pdf_path = os.path.join(CASES_DIR, pdf_name)
        builder = _BUILDERS[case["layout"]]

        built = builder(case["doc"], pdf_path)
        if built is False:               # scanned case skipped (missing dependency)
            continue

        truth_name = f"{case['case_id']}.truth.json"
        truth_path = os.path.join(CASES_DIR, truth_name)
        truth = {
            "case_id":     case["case_id"],
            "description": case["description"],
            "layout":      case["layout"],
            "source_file": pdf_name,
            "expected":    case["expected"],
            "match_types": case["match_types"],
            "notes":       case["notes"],
        }
        with open(truth_path, "w") as f:
            json.dump(truth, f, indent=2, ensure_ascii=False)

        manifest_cases.append({
            "case_id":     case["case_id"],
            "pdf":         pdf_name,
            "truth":       truth_name,
            "layout":      case["layout"],
            "description": case["description"],
            "notes":       case["notes"],
        })
        print(f"  ✓ {case['case_id']:<14} {case['layout']:<8} → {pdf_name} + {truth_name}")

    manifest = {
        "generated_fields_schema": GENERATED_FIELDS,
        "match_type_legend":       MATCH_TYPE_LEGEND,
        "cases":                   manifest_cases,
    }
    manifest_path = os.path.join(CASES_DIR, "manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(f"  ✓ manifest      → cases/manifest.json ({len(manifest_cases)} cases)")

    # Keep the legacy single-document path working: it is the baseline case.
    baseline_pdf = os.path.join(CASES_DIR, "baseline.pdf")
    shutil.copyfile(baseline_pdf, LEGACY_PDF)
    print(f"  ✓ legacy doc    → treatment_plan.pdf (= baseline)")
    print("──────────────────────────────────────────────────────────────\n")


if __name__ == "__main__":
    main()
