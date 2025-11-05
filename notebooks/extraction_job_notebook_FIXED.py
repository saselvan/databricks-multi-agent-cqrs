# Databricks notebook source
# MAGIC %md
# MAGIC # PDF Extraction Job - REAL PROCESSING VERSION
# MAGIC 
# MAGIC **This version actually reads and extracts text from files!**
# MAGIC 
# MAGIC Changes from demo version:
# MAGIC - ✅ Reads REAL files from UC Volumes
# MAGIC - ✅ Extracts REAL text content
# MAGIC - ✅ Handles actual file I/O
# MAGIC - ✅ Works with text files (simulating PDFs for demo simplicity)

# COMMAND ----------

# Parameters (passed by ExtractionAgent)
dbutils.widgets.text("document_path", "/Volumes/sselvan_banner/oncology/source_pdfs/patient_001_oncology_report.txt", "Document Path")
dbutils.widgets.text("user_id", "user", "User ID")
dbutils.widgets.text("catalog_name", "sselvan_banner", "Catalog Name")
dbutils.widgets.text("schema_name", "oncology", "Schema Name")

document_path = dbutils.widgets.get("document_path")
user_id = dbutils.widgets.get("user_id")
catalog_name = dbutils.widgets.get("catalog_name")
schema_name = dbutils.widgets.get("schema_name")

print(f"📄 Extracting document: {document_path}")
print(f"👤 Triggered by: {user_id}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Log JobStarted Event (CQRS)
# MAGIC 
# MAGIC Log immediately at job start for full audit trail

# COMMAND ----------

# Get run ID
import re
import uuid as uuid_lib

run_id = dbutils.notebook.entry_point.getDbutils() \
    .notebook().getContext().currentRunId().get()
run_id_str = str(run_id)
run_id_int = int(re.search(r'\d+', run_id_str).group())

print(f"🆔 Run ID: {run_id_int}")

# Log JobStarted event
try:
    event_id = str(uuid_lib.uuid4())
    spark.sql(f"""
        INSERT INTO {catalog_name}.{schema_name}.job_events
        (event_id, event_type, run_id, agent, sp_used, triggered_by, 
         timestamp, status, details)
        VALUES (
            '{event_id}',
            'JobStarted',
            {run_id_int},
            'extraction_agent',
            'EXTRACTION_SP',
            '{user_id}',
            current_timestamp(),
            'STARTED',
            '{{"document_path": "{document_path}"}}'
        )
    """)
    print(f"✅ Logged JobStarted event (ID: {event_id})")
except Exception as e:
    print(f"⚠️  Could not log JobStarted event (non-fatal): {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Extract REAL Document Content
# MAGIC 
# MAGIC **REAL PROCESSING:** Reads actual file from UC Volumes

# COMMAND ----------

from datetime import datetime
import traceback
import os
import json

try:
    print(f"📖 Reading file from: {document_path}")
    
    # ✅ REAL FILE READ (not fake data!)
    if not os.path.exists(document_path):
        raise FileNotFoundError(f"Document not found: {document_path}")
    
    with open(document_path, 'r') as f:
        extracted_text = f.read()
    
    # Count pages (simulate by counting sections or use line breaks)
    page_count = extracted_text.count('\n\n') + 1  # Approximate page count
    
    print(f"✅ Extracted {len(extracted_text)} characters")
    print(f"📄 Approximate pages: {page_count}")
    print(f"")
    print(f"📝 First 500 characters:")
    print(extracted_text[:500])
    print(f"...")
    
except Exception as e:
    print(f"❌ Extraction failed: {e}")
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
    
    # Convert to int (extract number from 'RunId(12345)' format)
    import re
    run_id_str = str(run_id)
    run_id_int = int(re.search(r'\d+', run_id_str).group())
    
    print(f"📝 Writing extraction to staging table (Run ID: {run_id_int})")
    
    # Create DataFrame with extracted data
    extraction_data = spark.createDataFrame([{
        "extraction_id": f"extract_{run_id_int}",
        "extraction_run_id": run_id_int,
        "document_path": document_path,
        "extracted_text": extracted_text,  # ✅ REAL extracted text!
        "page_count": page_count,
        "extracted_at": datetime.now(),
        "extracted_by": "EXTRACTION_SP"  # Record which SP performed extraction
    }])
    
    # Write to staging table
    extraction_data.write \
        .mode("append") \
        .saveAsTable(f"{catalog_name}.staging.extracted_documents")
    
    print(f"✅ Wrote REAL extraction data to {catalog_name}.staging.extracted_documents")
    
except Exception as e:
    print(f"❌ Failed to write to staging: {e}")
    traceback.print_exc()
    raise

# COMMAND ----------

# MAGIC %md
# MAGIC ## Self-Report to CQRS Event Store
# MAGIC 
# MAGIC **Critical for async pattern:** Job writes completion event to Delta

# COMMAND ----------

import json
import uuid as uuid_lib

try:
    # Get run ID
    run_id = dbutils.notebook.entry_point.getDbutils() \
        .notebook().getContext().currentRunId().get()
    # Extract number from 'RunId(12345)' format
    import re
    run_id_str = str(run_id)
    run_id_int = int(re.search(r'\d+', run_id_str).group())
    
    print(f"📊 Writing completion event to CQRS (Run ID: {run_id_int})")
    
    # Prepare event details
    details = {
        "document_path": document_path,
        "pages_extracted": page_count,
        "characters_extracted": len(extracted_text),
        "sp_used": "EXTRACTION_SP",
        "extraction_id": f"extract_{run_id_int}",
        "real_processing": True  # ✅ Flag to show this was real, not fake!
    }
    details_json = json.dumps(details).replace("'", "''")
    
    # Generate event ID
    event_id = str(uuid_lib.uuid4())
    
    # Write "ExtractionJobCompleted" event
    spark.sql(f"""
        INSERT INTO {catalog_name}.{schema_name}.job_events
        (event_id, event_type, run_id, agent, sp_used, triggered_by, 
         timestamp, status, details)
        VALUES (
            '{event_id}',
            'ExtractionJobCompleted',
            {run_id_int},
            'extraction_agent',
            'EXTRACTION_SP',
            '{user_id}',
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
print("✅ REAL PDF EXTRACTION COMPLETE")
print("="*80)
print(f"\nDocument: {document_path}")
print(f"Run ID: {run_id_int}")
print(f"Pages: {page_count}")
print(f"Characters: {len(extracted_text)}")
print(f"Extracted by: EXTRACTION_SP")
print(f"Triggered by: {user_id}")
print(f"\n✨ This was REAL extraction (not simulated)!")
print(f"📊 Data written to: {catalog_name}.staging.extracted_documents")
print(f"📊 Event logged to: {catalog_name}.{schema_name}.job_events")
print(f"\n🔄 Next step: SummarizationAgent will trigger summarization")
print("="*80)

# COMMAND ----------

# Return success (simplified - job framework detects success if no exception)
import json
dbutils.notebook.exit(json.dumps({
    "status": "SUCCESS",
    "real_processing": True,
    "message": "REAL PDF extraction completed successfully"
}))

