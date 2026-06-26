"""
Generates a LABELED TEST SET of synthetic ABA treatment plan PDFs for extraction evaluation.
Now includes a Fuzzing Engine for randomized permutations and "Nightmare Tier" structural edge cases.
"""
import os
import json
import shutil
import random
from datetime import datetime, timedelta

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, PageBreak
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

# ── Styles ──────────────────────────────────────────────────────────────────

def _styles():
    return {
        "header": ParagraphStyle("header", fontSize=16, fontName="Helvetica-Bold", textColor=colors.HexColor("#1a3f6f"), spaceAfter=4),
        "subheader": ParagraphStyle("subheader", fontSize=10, fontName="Helvetica", textColor=colors.HexColor("#6b7e91"), spaceAfter=16),
        "section": ParagraphStyle("section", fontSize=11, fontName="Helvetica-Bold", textColor=colors.HexColor("#1a3f6f"), spaceBefore=16, spaceAfter=6, borderPad=4),
        "body": ParagraphStyle("body", fontSize=10, fontName="Helvetica", leading=15, textColor=colors.HexColor("#1a2e3b"), spaceAfter=6),
        "mono": ParagraphStyle("mono", fontSize=10, fontName="Courier", leading=14, spaceAfter=6),
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

# ── Layout Builders ─────────────────────────────────────────────────────────────

def _build_rich_story(doc, st):
    """Generates the flowable story for a single rich document. (Abstracted for merging)"""
    story = []
    story.append(Paragraph("APPLIED BEHAVIOR ANALYSIS (ABA) TREATMENT PLAN", st["header"]))
    story.append(Paragraph("Behavioral Health Services — Prior Authorization Support Document", st["subheader"]))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#d0d9e4")))
    story.append(Spacer(1, 14))

    info_data = [
        ["PATIENT INFORMATION", "", "PROVIDER INFORMATION", ""],
        ["Patient Name:", doc["patient_name"], "Treating Provider:", doc["provider_name"]],
        ["Date of Birth:", doc["dob_display"], "Provider NPI:", doc["provider_npi_display"]],
        ["Member ID:", doc.get("member_id", "12345"), "Clinic Name:", doc.get("clinic", "Clinic")],
        ["Insurance:", doc["insurance_display"], "Tax ID:", doc.get("tax_id", "00-0000000")],
    ]
    info_table = Table(info_data, colWidths=[1.4 * inch, 2.2 * inch, 1.6 * inch, 2.1 * inch])
    info_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f4f8")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#d0d9e4")),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e8eef4")),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 14))

    # Optional: Force a page break before services to test Orphaned Tables
    if doc.get("force_orphan_break"):
        story.append(Spacer(1, 5 * inch)) 

    story.append(Paragraph("1. REQUESTED SERVICES", st["section"]))
    svc_data = [["CPT Code", "Service Description", "Requested Units", "Frequency", "Auth Period"]] + doc["services"]
    svc_table = Table(svc_data, colWidths=[0.85 * inch, 2.4 * inch, 1.3 * inch, 1.1 * inch, 1.0 * inch])
    svc_table.setStyle(_grid_table_style())
    story.append(svc_table)

    story.append(Paragraph("2. MEDICAL NECESSITY", st["section"]))
    story.append(Paragraph(doc["necessity"], st["body"]))

    if doc.get("addendum"):
        story.append(Spacer(1, 20))
        story.append(Paragraph(f"<b>CLINICAL ADDENDUM:</b> {doc['addendum']}", st["body"]))

    return story

def build_rich_pdf(doc, path):
    pdf = SimpleDocTemplate(path, pagesize=letter, rightMargin=0.85*inch, leftMargin=0.85*inch, topMargin=0.9*inch, bottomMargin=0.9*inch)
    pdf.build(_build_rich_story(doc, _styles()))

def build_merged_pdf(docs, path):
    """Takes a list of document dicts and merges them into one PDF separated by page breaks."""
    pdf = SimpleDocTemplate(path, pagesize=letter, rightMargin=0.85*inch, leftMargin=0.85*inch, topMargin=0.9*inch, bottomMargin=0.9*inch)
    st = _styles()
    full_story = []
    for i, doc in enumerate(docs):
        full_story.extend(_build_rich_story(doc, st))
        if i < len(docs) - 1:
            full_story.append(PageBreak())
    pdf.build(full_story)

def build_whitespace_pdf(doc, path):
    """Destroys bounding boxes by formatting tables as tab-spaced raw text strings."""
    pdf = SimpleDocTemplate(path, pagesize=letter, rightMargin=1*inch, leftMargin=1*inch)
    st = _styles()
    story = [Paragraph("TREATMENT PLAN REQUEST", st["header"]), Spacer(1, 12)]
    
    # 1. Identity & Payer
    story.append(Paragraph(f"Patient: {doc['patient_name']}    DOB: {doc['dob_display']}", st["mono"]))
    story.append(Paragraph(f"Provider: {doc['provider_name']}    NPI: {doc['provider_npi_display']}", st["mono"]))
    story.append(Paragraph(f"Payer: {doc.get('insurance_display', 'Unknown')}", st["mono"]))
    story.append(Spacer(1, 15))
    
    # 2. Diagnosis
    story.append(Paragraph("DIAGNOSIS CODES:", st["mono"]))
    for dx in doc.get("diagnoses", []):
        story.append(Paragraph(f"{dx[0]} &nbsp;&nbsp;&nbsp;&nbsp; {dx[1]} &nbsp;&nbsp;&nbsp;&nbsp; {dx[2]}", st["mono"]))
    story.append(Spacer(1, 15))
    
    # 3. Services
    story.append(Paragraph("SERVICES REQUESTED (CPT | DESC | UNITS | AUTH PERIOD):", st["mono"]))
    for svc in doc["services"]:
        story.append(Paragraph(f"{svc[0]} &nbsp;&nbsp; {svc[1][:15]}... &nbsp;&nbsp; {svc[2]} &nbsp;&nbsp; {svc[4]}", st["mono"]))
    story.append(Spacer(1, 15))
    
    # 4. Summary & Goals
    story.append(Paragraph("MEDICAL NECESSITY SUMMARY:", st["mono"]))
    story.append(Paragraph(doc.get("necessity", "N/A"), st["mono"]))
    story.append(Spacer(1, 10))
    if doc.get("goals"):
        story.append(Paragraph("PRIMARY GOAL: " + doc["goals"][0], st["mono"]))
        
    pdf.build(story)
    
# ── Data Helpers & Base Documents ───────────────────────────────────────────────

def _derive(base_doc, **overrides):
    new = dict(base_doc)
    for key in ("diagnoses", "services", "goals"):
        if key in base_doc:
            new[key] = [list(row) if isinstance(row, list) else row for row in base_doc[key]]
    new.update(overrides)
    return new

def _expected(base_expected, **overrides):
    new = dict(base_expected)
    new.update(overrides)
    return new

MARCUS_NECESSITY = """
Marcus Thompson is a 6-year-old male presenting with Autism Spectrum Disorder (ASD), Level 2,
characterized by significant deficits in social communication, restricted and repetitive behaviors,
and sensory sensitivities that substantially impair daily functioning across home, school, and
community settings. A comprehensive evaluation conducted at Bright Horizons ABA Center on
January 12, 2026 confirmed the diagnosis and established baseline functioning across adaptive
behavior domains using the Vineland Adaptive Behavior Scales, Third Edition (Vineland-3).
<br/><br/>
He exhibits frequent maladaptive behaviors including self-injurious behavior (head-banging,
hand-biting) occurring at an average rate of 12 times per day, and elopement behaviors occurring
3–5 times per school day. These behaviors represent a safety risk and significantly limit his
ability to access educational programming.
<br/><br/>
Applied Behavior Analysis therapy delivered at the requested intensity (120 units/month) is
medically necessary and consistent with Aetna Clinical Policy Bulletin #0473 for ASD.
"""

MARCUS_GOALS = [
    "Reduce self-injurious behavior (head-banging, hand-biting) from 12/day to ≤3/day as measured by direct observation data.",
    "Increase functional communication using PECS or AAC device to make 10+ independent requests per session.",
]

MARCUS = {
    "patient_name": "Marcus J. Thompson",
    "dob_display": "March 14, 2018",
    "member_id": "AET-00291847",
    "insurance_display": "Aetna Commercial PPO",
    "plan_id": "AET-PPO-NY-2024",
    "provider_name": "Dr. Sarah K. Nguyen, BCBA-D",
    "provider_npi_display": "1437892056",
    "clinic": "Bright Horizons ABA Center",
    "tax_id": "82-4910273",
    "phone": "(212) 555-0174",
    "diagnoses": [
        ["F84.0", "Autism Spectrum Disorder", "Level 2", "June 3, 2021"],
    ],
    "services": [
        ["97153", "ABA Therapy — Technician-Delivered", "120 units/month", "5x per week", "6 months"],
        ["97155", "ABA Therapy — Supervision (BCBA)", "16 units/month", "As needed", "6 months"],
    ],
    "necessity": MARCUS_NECESSITY,
    "goals": MARCUS_GOALS,
    "plan_date": "January 30, 2026",
    "review_date": "July 30, 2026",
    "license": "NY-BCBA-004821",
}

MARCUS_EXPECTED = {
    "patient_name": "Marcus J. Thompson",
    "dob": "2018-03-14",
    "diagnosis_code": "F84.0",
    "diagnosis_description": "Autism Spectrum Disorder",
    "cpt_code": "97153",
    "requested_units": "120 units/month",
    "provider_name": "Dr. Sarah K. Nguyen, BCBA-D",
    "provider_npi": "1437892056",
    "payer": "Aetna Commercial PPO",
    "auth_period": "6 months",
    "medical_necessity_summary": (
        "Marcus is a 6-year-old with Autism Spectrum Disorder Level 2 exhibiting self-injurious "
        "behavior (~12x/day) and elopement (3–5x/day) that pose safety risks and impair functioning. "
        "ABA at the requested intensity is medically necessary and the evidence-based standard for "
        "reducing these behaviors, consistent with Aetna CPB #0473."
    ),
    "primary_treatment_goal": MARCUS_GOALS[0],
}

# ── The Fuzzing Engine ──────────────────────────────────────────────────────────

def generate_fuzzed_cases(base_doc, base_expected, count=5):
    """Generates random permutations of a base document to aggressively test bounds."""
    fuzzed_cases = []
    first_names = ["Jackson", "Aria", "Mateo", "Chloe", "Leo"]
    last_names = ["Smith", "Rodriguez", "Patel", "Kim", "O'Connor"]
    
    for i in range(count):
        # 1. Randomize Identity
        f_name = f"{random.choice(first_names)} {random.choice(last_names)}"
        
        # 2. Randomize Date (Between 2010 and 2022)
        start_date = datetime(2010, 1, 1)
        rand_days = random.randint(0, 4000)
        rand_dob = start_date + timedelta(days=rand_days)
        dob_display = rand_dob.strftime("%B %d, %Y")
        dob_iso = rand_dob.strftime("%Y-%m-%d")
        
        # 3. Randomize NPI (Valid 10 digits)
        f_npi = str(random.randint(1000000000, 9999999999))
        
        # 4. Randomize Units
        f_units = random.randint(40, 200)
        f_unit_str = f"{f_units} units/month"
        
        mutated_doc = _derive(base_doc, 
            patient_name=f_name, 
            dob_display=dob_display,
            provider_npi_display=f_npi,
            services=[["97153", "ABA Therapy", f_unit_str, "5x/week", "6 months"]]
        )
        
        mutated_expected = _expected(base_expected,
            patient_name=f_name,
            dob=dob_iso,
            provider_npi=f_npi,
            requested_units=f_unit_str
        )
        
        fuzzed_cases.append({
            "case_id": f"fuzz_var_{i+1}",
            "description": f"Randomized extraction target #{i+1}",
            "layout": "rich",
            "doc": mutated_doc,
            "expected": mutated_expected,
            "match_types": DEFAULT_MATCH_TYPES,
            "notes": "Tests model resilience against memorization by ensuring it tracks dynamic permutations.",
        })
        
    return fuzzed_cases

# ── Case Registry ───────────────────────────────────────────────────────────────

CASES = [
    {
        "case_id": "baseline",
        "description": "Clean, complete document.",
        "layout": "rich",
        "doc": MARCUS,
        "expected": MARCUS_EXPECTED,
        "match_types": DEFAULT_MATCH_TYPES,
        "notes": "Establishes the accuracy ceiling.",
    },
    {
        "case_id": "clinical_addendum",
        "description": "Base table says 120 units, but an addendum overrides it to 90.",
        "layout": "rich",
        "doc": _derive(MARCUS, addendum="Effective immediately, requested units for 97153 are reduced to 90 units/month due to staffing limits."),
        "expected": _expected(MARCUS_EXPECTED, requested_units="90 units/month"),
        "match_types": DEFAULT_MATCH_TYPES,
        "notes": "Tests temporal contradiction. The model must override the cleanly formatted table with narrative text.",
    },
    {
        "case_id": "whitespace_hell",
        "description": "Gridless table relying solely on erratic spacing.",
        "layout": "whitespace",
        "doc": MARCUS,
        "expected": MARCUS_EXPECTED,
        "match_types": DEFAULT_MATCH_TYPES,
        "notes": "Destroys bounding box logic, forcing the model to rely purely on token adjacency.",
    },
    {
        "case_id": "page_break_orphan",
        "description": "Table breaks across pages, separating headers from the unit rows.",
        "layout": "rich",
        "doc": _derive(MARCUS, force_orphan_break=True),
        "expected": MARCUS_EXPECTED,
        "match_types": DEFAULT_MATCH_TYPES,
        "notes": "Tests spatial stitching across page breaks.",
    },
    {
        "case_id": "merged_fax_poisoning",
        "description": "Two distinct patients in one PDF file.",
        "layout": "merged",
        "doc": [MARCUS, _derive(MARCUS, patient_name="Ava Lin Chen", dob_display="August 2, 2019")],
        "expected": MARCUS_EXPECTED, # It should extract the PRIMARY (first) patient
        "match_types": DEFAULT_MATCH_TYPES,
        "notes": "Context poisoning. Model must isolate entities to Document 1 and ignore the conflicting data in Document 2.",
    }
]

# Inject 5 randomized fuzzer cases into the testing suite
CASES.extend(generate_fuzzed_cases(MARCUS, MARCUS_EXPECTED, count=5))

# ── Execution ───────────────────────────────────────────────────────────────────

_BUILDERS = {
    "rich": build_rich_pdf,
    "whitespace": build_whitespace_pdf,
    "merged": lambda doc, path: build_merged_pdf(doc, path) # Wrapper for the list-based doc
}

def main():
    os.makedirs(CASES_DIR, exist_ok=True)
    manifest_cases = []

    print("\n── Generating labeled extraction test set ───────────────────")
    for case in CASES:
        pdf_name = f"{case['case_id']}.pdf"
        pdf_path = os.path.join(CASES_DIR, pdf_name)
        
        # Build the specific layout
        _BUILDERS[case["layout"]](case["doc"], pdf_path)

        truth_name = f"{case['case_id']}.truth.json"
        truth_path = os.path.join(CASES_DIR, truth_name)
        
        truth = {k: v for k, v in case.items() if k != "doc"}
        truth["source_file"] = pdf_name
        
        with open(truth_path, "w") as f:
            json.dump(truth, f, indent=2)

        manifest_cases.append(truth)
        print(f"  ✓ {case['case_id']:<25} {case['layout']:<10} → {pdf_name}")

    with open(os.path.join(CASES_DIR, "manifest.json"), "w") as f:
        json.dump({"cases": manifest_cases}, f, indent=2)
    
    print(f"\n  ✓ Generated {len(manifest_cases)} total test cases (Including {sum(1 for c in CASES if 'fuzz' in c['case_id'])} fuzzed permutations).")

if __name__ == "__main__":
    main()