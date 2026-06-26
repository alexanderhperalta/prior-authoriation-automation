"""
Document Intelligence Module
Extracts structured PA fields from an ABA treatment plan PDF using Claude API.
"""
import asyncio, base64, json, os, time
from anthropic import AsyncAnthropic
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"), max_retries=5)

EXTRACTION_PROMPT = """You are a healthcare document intelligence system specializing in 
prior authorization workflows. Extract the following structured fields from this ABA 
treatment plan document.

Return ONLY a valid JSON object matching the exact keys below. If a field is not found, return 
null. Do not include markdown formatting, code fences, or explanations.

{"patient_name": "Full legal name of the patient",
  # Normalize to YYYY-MM-DD regardless of how the date appears in the document
  "dob": "Date of birth in YYYY-MM-DD format",
  "diagnosis_code": "Primary ICD-10 diagnosis code only (e.g. F84.0)",
  "diagnosis_description": "Return only the diagnosis name",
  "cpt_code": "Primary CPT procedure code for the main service requested",
  "requested_amount": "Units requested for the primary service",
  "requested_unit_type": "Unit of measurement associated with requested_amount (e.g., units/month)",
  "provider_name": "Full name and credentials of the treating provider",
  "provider_npi": "10-digit NPI number",
  "payer": "Insurance payer name",
  "auth_period": "Requested authorization period",
  "medical_necessity_summary": "2-3 sentence summary of the medical necessity justification",
  "primary_treatment_goal": "The single most important 90-day treatment goal"}

Return only the JSON object. No markdown, no explanation, no code fences."""

extraction_tool = {
    "name": "record_extracted_fields",
    "description": "Record the structured fields extracted from the Prior Authorization PDF. Use null if a field is missing.",
    "input_schema": {
        "type": "object",
        "properties": {
            "patient_name": {"type": ["string", "null"], "description": "Full legal name of the patient"},
            "dob": {"type": ["string", "null"], "description": "Date of birth in YYYY-MM-DD format"},
            "diagnosis_code": {"type": ["string", "null"], "description": "Primary ICD-10 diagnosis code only (e.g. F84.0)"},
            "diagnosis_description": {"type": ["string", "null"], "description": "Include only the diagnosis name"},
            "cpt_code": {"type": ["string", "null"], "description": "Primary CPT procedure code for the main service requested"},
            "requested_amount": {"type": ["number", "string", "null"], "description": "Number only. The raw amount of units or hours requested (e.g., 160)"},
            "requested_unit_type": {"type": ["string", "null"], "description": "MUST NOT BE NULL if amount is found. Choose from: 'units/month', 'hours/week', 'units', 'hours', or exact document wording."},
            "provider_name": {"type": ["string", "null"], "description": "Full name and credentials of the treating provider"},
            "provider_npi": {"type": ["string", "null"], "description": "10-digit NPI number"},
            "payer": {"type": ["string", "null"], "description": "Insurance payer name"},
            "auth_period": {"type": ["string", "null"], "description": "Requested authorization period"},
            "medical_necessity_summary": {"type": ["string", "null"], "description": "2-3 sentence summary of the medical necessity justification"},
            "primary_treatment_goal": {"type": ["string", "null"], "description": "The single most important 90-day treatment goal"}},
        "required": [
            "patient_name", "dob", "diagnosis_code", "diagnosis_description", "cpt_code",
            "requested_amount", "requested_unit_type", "provider_name", "provider_npi",
            "payer", "auth_period", "medical_necessity_summary", "primary_treatment_goal"]}}

# Load in the pdf as unstructured text to be extracted
def load_pdf_as_base64(pdf_path: str) -> str:
    with open(pdf_path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


# Uses the Messages API to extract fields from a pdf
async def extract_fields(pdf_path: str) -> dict:
    """Send PDF to Claude 4.6+ and extract structured PA fields using tool calling."""
    start = time.time()
    
    # Assuming load_pdf_as_base64 is defined elsewhere in your file
    pdf_data = load_pdf_as_base64(pdf_path)
    
    strict_prompt = "Extract the structured fields from this ABA treatment plan document. You must return the data by calling the 'record_extracted_fields' tool."

    response = await client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1024,
        temperature=0, 
        tools=[extraction_tool],
        tool_choice={"type": "tool", "name": "record_extracted_fields"},
        messages=[{"role": "user", "content": [{"type": "document", 
                    "source": {"type": "base64",
                                "media_type": "application/pdf", 
                                "data": pdf_data}},
                    {"type": "text", "text": strict_prompt}]}])

    extracted = {}
    
    # Parse the forced tool call directly into our dictionary
    for content_block in response.content:
        if content_block.type == "tool_use" and content_block.name == "record_extracted_fields":
            extracted = content_block.input
            break

    # Construct the final result payload
    result = {
        "extracted_fields": extracted,
        "metadata": {
            "source_file": Path(pdf_path).name,
            "model": response.model,
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "elapsed_seconds": round(time.time() - start, 2),},}

    return result

def map_to_portal_fields(result: dict) -> dict:
    """Map extracted fields to the exact form field IDs used by the portal."""
    f = result.get("extracted_fields", {})

    amount = str(f.get("requested_amount", "") or "").strip()
    unit = str(f.get("requested_unit_type", "") or "").strip()
    portal_units = f"{amount} {unit}".strip()

    return {
        "pdf_name":         result["metadata"]["source_file"],
        "patient_name":     f.get("patient_name", ""),
        "dob":              f.get("dob", ""),
        "diagnosis_code":   f.get("diagnosis_code", ""),
        "cpt_code":         f.get("cpt_code", ""),
        "provider_npi":     f.get("provider_npi", ""),
        "requested_units":  portal_units,
        "payer":            f.get("payer", ""),
        "notes":            f.get("medical_necessity_summary", ""),
    }

async def main():
    cases_dir = Path(__file__).parent.parent / "sample_docs" / "cases"
    pdf_paths = sorted(cases_dir.glob("*.pdf"))

    sem = asyncio.Semaphore(5)                       # cap concurrency / respect rate limits
    async def extract_one(p):
        async with sem:
            return await extract_fields(str(p))

    # return_exceptions=True so one bad PDF doesn't kill the whole run
    results = await asyncio.gather(*(extract_one(p) for p in pdf_paths),
                                    return_exceptions=True)

    # Create a list to hold only the successful data
    valid_results = []

    for p, r in zip(pdf_paths, results):
        if isinstance(r, Exception):
            print(f"  ✗ {p.name}: {r}")
            continue
        
        # Print the mapped fields for the console
        print(f"  ✓ {p.name}: {json.dumps(map_to_portal_fields(r))}")
        
        # Append only the successful, raw results to our new list
        valid_results.append(r)
    
    # Save the filtered list, safely avoiding any Exception objects
    with open("data.json", "w") as file:
        json.dump(valid_results, file, indent=4)

if __name__ == "__main__":
    asyncio.run(main())