# Databricks notebook source
# MAGIC %md
# MAGIC # PDF Extraction Job
# MAGIC 
# MAGIC **Triggered by:** ExtractionAgent (uses EXTRACTION_SP credentials)
# MAGIC 
# MAGIC **This job:**
# MAGIC - Reads PDF from source location
# MAGIC - Extracts text using PyPDF
# MAGIC - Writes to staging.extracted_documents
# MAGIC - Self-reports completion to CQRS event store
# MAGIC 
# MAGIC **Security:** Runs with EXTRACTION_SP permissions only

# COMMAND ----------

# MAGIC %pip install pypdf --quiet
dbutils.library.restartPython()

# COMMAND ----------

# Parameters (passed by ExtractionAgent)
dbutils.widgets.text("document_path", "/source_pdfs/test.pdf", "Document Path")
dbutils.widgets.text("triggered_by", "user", "Triggered By")
dbutils.widgets.text("catalog_name", "sselvan_banner", "Catalog Name")
dbutils.widgets.text("schema_name", "oncology", "Schema Name")

document_path = dbutils.widgets.get("document_path")
triggered_by = dbutils.widgets.get("triggered_by")
catalog_name = dbutils.widgets.get("catalog_name")
schema_name = dbutils.widgets.get("schema_name")

print(f"📄 Extracting PDF: {document_path}")
print(f"👤 Triggered by: {triggered_by}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Extract PDF Content

# COMMAND ----------

from pypdf import PdfReader
from datetime import datetime
import traceback

try:
    print(f"📖 Reading PDF from: {document_path}")
    
    # Read PDF file
    # In production, this would read from actual storage location
    # For demo, we'll simulate extraction
    
    # Simulated extraction (replace with actual PDF reading in production)
    extracted_text = f"""
ONCOLOGY DOCUMENT EXTRACT
=========================

Document: {document_path}
Extracted at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

PATIENT INFORMATION
Patient ID: P-12345
Age: 58
Diagnosis: Stage II Breast Cancer

TREATMENT PROTOCOL
Chemotherapy regimen: AC-T protocol
Start date: 2024-01-15
Expected duration: 18 weeks

CLINICAL NOTES
Patient responding well to initial treatment cycle.
White blood cell count within normal range.
No significant adverse effects reported.

NEXT STEPS
- Follow-up appointment: 2024-02-15
- Lab work scheduled: 2024-02-10
- Continue current treatment protocol

[Additional clinical details would follow...]
    """
    
    page_count = 3  # Simulated
    
    print(f"✅ Extracted {len(extracted_text)} characters from {page_count} pages")
    
except Exception as e:
    print(f"❌ PDF extraction failed: {e}")
    traceback.print_exc()
    raise

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write to Staging Table
# MAGIC 
# MAGIC **Security Note:** Only EXTRACTION_SP has write access to staging.extracted_documents

# COMMAND ----------

from pyspark.sql import functions as F

try:
    # Get current run ID from Databricks context
    run_id = dbutils.notebook.entry_point.getDbutils() \
        .notebook().getContext().currentRunId().get()
    
    print(f"📝 Writing extraction to staging table (Run ID: {run_id})")
    
    # Create DataFrame with extracted data
    extraction_data = spark.createDataFrame([{
        "extraction_id": f"extract_{run_id}",
        "extraction_run_id": int(run_id),
        "document_path": document_path,
        "extracted_text": extracted_text,
        "page_count": page_count,
        "extracted_at": datetime.now(),
        "extracted_by": "EXTRACTION_SP"  # Record which SP performed extraction
    }])
    
    # Write to staging table
    extraction_data.write \
        .mode("append") \
        .saveAsTable("staging.default.extracted_documents")
    
    print(f"✅ Wrote extraction data to staging.extracted_documents")
    
except Exception as e:
    print(f"❌ Failed to write to staging: {e}")
    traceback.print_exc()
    raise

# COMMAND ----------

# MAGIC %md
# MAGIC ## Self-Report to CQRS Event Store
# MAGIC 
# MAGIC **Critical for async pattern:** Job writes completion event to Delta
# MAGIC so agent can check status without polling Jobs API

# COMMAND ----------

import json

try:
    # Get run ID
    run_id = dbutils.notebook.entry_point.getDbutils() \
        .notebook().getContext().currentRunId().get()
    
    print(f"📊 Writing completion event to CQRS (Run ID: {run_id})")
    
    # Prepare event details
    details = {
        "document_path": document_path,
        "pages_extracted": page_count,
        "characters_extracted": len(extracted_text),
        "sp_used": "EXTRACTION_SP",
        "extraction_id": f"extract_{run_id}"
    }
    details_json = json.dumps(details).replace("'", "''")
    
    # Write "ExtractionJobCompleted" event
    spark.sql(f"""
        INSERT INTO {catalog_name}.{schema_name}.job_events
        (event_id, event_type, run_id, agent, sp_used, triggered_by, 
         timestamp, status, details)
        VALUES (
            uuid(),
            'ExtractionJobCompleted',
            {run_id},
            'extraction_agent',
            'EXTRACTION_SP',
            '{triggered_by}',
            current_timestamp(),
            'SUCCESS',
            '{details_json}'
        )
    """)
    
    print(f"✅ Logged ExtractionJobCompleted event")
    print(f"📊 Details: {details}")
    
except Exception as e:
    print(f"⚠️  Could not write CQRS event (non-fatal): {e}")
    # Don't fail the job if CQRS logging fails

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary

# COMMAND ----------

print("\n" + "="*80)
print("✅ PDF EXTRACTION COMPLETE")
print("="*80)
print(f"\nDocument: {document_path}")
print(f"Run ID: {run_id}")
print(f"Pages: {page_count}")
print(f"Characters: {len(extracted_text)}")
print(f"Extracted by: EXTRACTION_SP")
print(f"Triggered by: {triggered_by}")
print(f"\n📊 Data written to: {catalog_name}.staging.extracted_documents")
print(f"📊 Event logged to: {catalog_name}.{schema_name}.job_events")
print(f"\n🔄 Next step: SummarizationAgent will automatically trigger summarization")
print("="*80)

# COMMAND ----------

# Return success (for job orchestration)
dbutils.notebook.exit(json.dumps({
    "status": "SUCCESS",
    "run_id": int(run_id),
    "extraction_id": f"extract_{run_id}",
    "pages": page_count
}))

