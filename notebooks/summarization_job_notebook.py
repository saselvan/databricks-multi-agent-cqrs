# Databricks notebook source
# MAGIC %md
# MAGIC # Summarization Job
# MAGIC 
# MAGIC **Triggered by:** SummarizationAgent (uses SUMMARIZATION_SP credentials)
# MAGIC 
# MAGIC **This job:**
# MAGIC - Reads extracted text from staging.extracted_documents
# MAGIC - Generates clinical summary using LLM
# MAGIC - Writes to staging.summaries
# MAGIC - Self-reports completion to CQRS event store
# MAGIC 
# MAGIC **Security:** Runs with SUMMARIZATION_SP permissions only

# COMMAND ----------

# Parameters (passed by SummarizationAgent)
dbutils.widgets.text("extraction_run_id", "0", "Extraction Run ID")
dbutils.widgets.text("triggered_by", "user", "Triggered By")
dbutils.widgets.text("catalog_name", "sselvan_banner", "Catalog Name")
dbutils.widgets.text("schema_name", "oncology", "Schema Name")

extraction_run_id = int(dbutils.widgets.get("extraction_run_id"))
triggered_by = dbutils.widgets.get("triggered_by")
catalog_name = dbutils.widgets.get("catalog_name")
schema_name = dbutils.widgets.get("schema_name")

print(f"📝 Summarizing extraction run: {extraction_run_id}")
print(f"👤 Triggered by: {triggered_by}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Read Extracted Document
# MAGIC 
# MAGIC **Security Note:** Only SUMMARIZATION_SP has read access to staging.extracted_documents

# COMMAND ----------

from datetime import datetime
import traceback

try:
    print(f"📖 Reading extraction data for run_id: {extraction_run_id}")
    
    # Read from staging table
    extraction_df = spark.sql(f"""
        SELECT 
            extraction_id,
            document_path,
            extracted_text,
            page_count,
            extracted_at
        FROM {catalog_name}.staging.extracted_documents
        WHERE extraction_run_id = {extraction_run_id}
        ORDER BY extracted_at DESC
        LIMIT 1
    """)
    
    if extraction_df.count() == 0:
        raise ValueError(f"No extraction found for run_id: {extraction_run_id}")
    
    extraction = extraction_df.collect()[0]
    document_path = extraction.document_path
    extracted_text = extraction.extracted_text
    page_count = extraction.page_count
    
    print(f"✅ Retrieved extraction: {extraction.extraction_id}")
    print(f"   Document: {document_path}")
    print(f"   Pages: {page_count}")
    print(f"   Text length: {len(extracted_text)} characters")
    
except Exception as e:
    print(f"❌ Failed to read extraction data: {e}")
    traceback.print_exc()
    raise

# COMMAND ----------

# MAGIC %md
# MAGIC ## Generate Summary
# MAGIC 
# MAGIC In production, this would use a Foundation Model API to generate the summary.
# MAGIC For demo, we'll create a structured summary.

# COMMAND ----------

import json

try:
    print(f"🤖 Generating clinical summary...")
    
    # In production, this would call Foundation Model API:
    # summary = ai_generate_summary(extracted_text, model="llama-3.1-70b")
    
    # For demo, create structured summary
    summary_text = f"""
CLINICAL SUMMARY
================

Document Source: {document_path}
Summarized: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Pages Analyzed: {page_count}

EXECUTIVE SUMMARY
-----------------
Patient presents with Stage II Breast Cancer, currently undergoing AC-T chemotherapy protocol.
Treatment initiated 2024-01-15 with expected 18-week duration. Patient showing positive
response to initial treatment cycle with minimal adverse effects.

KEY CLINICAL FINDINGS
--------------------
• Diagnosis: Stage II Breast Cancer
• Current Treatment: AC-T chemotherapy protocol
• Treatment Start: 2024-01-15
• Treatment Duration: 18 weeks
• Patient Response: Positive
• Adverse Effects: Minimal
• Lab Results: White blood cell count within normal range

TREATMENT PROTOCOL
------------------
The patient is following the standard AC-T (Adriamycin-Cytoxan-Taxol) protocol for 
Stage II breast cancer. This regimen has shown high efficacy rates and the patient's
initial response is encouraging.

RECOMMENDATIONS
--------------
1. Continue current chemotherapy protocol as scheduled
2. Monitor white blood cell count weekly
3. Schedule follow-up appointment: 2024-02-15
4. Complete lab work: 2024-02-10
5. Patient education on managing treatment side effects

PROGNOSIS
---------
Favorable prognosis given early stage diagnosis and positive initial treatment response.
Continued monitoring and adherence to treatment protocol recommended.

Next Review: 2024-02-15
Summarized by: SUMMARIZATION_SP
    """
    
    # Prepare metadata
    metadata = {
        "document_path": document_path,
        "extraction_run_id": extraction_run_id,
        "pages_summarized": page_count,
        "original_length": len(extracted_text),
        "summary_length": len(summary_text),
        "compression_ratio": round(len(summary_text) / len(extracted_text), 2)
    }
    
    print(f"✅ Generated summary ({len(summary_text)} characters)")
    print(f"   Compression ratio: {metadata['compression_ratio']}:1")
    
except Exception as e:
    print(f"❌ Summary generation failed: {e}")
    traceback.print_exc()
    raise

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write to Staging Table
# MAGIC 
# MAGIC **Security Note:** Only SUMMARIZATION_SP has write access to staging.summaries

# COMMAND ----------

try:
    # Get current run ID
    run_id = dbutils.notebook.entry_point.getDbutils() \
        .notebook().getContext().currentRunId().get()
    
    print(f"📝 Writing summary to staging table (Run ID: {run_id})")
    
    # Create DataFrame with summary data
    summary_data = spark.createDataFrame([{
        "summary_id": f"summary_{run_id}",
        "summarization_run_id": int(run_id),
        "extraction_run_id": extraction_run_id,
        "summary_text": summary_text,
        "document_metadata": json.dumps(metadata),
        "summarized_at": datetime.now(),
        "summarized_by": "SUMMARIZATION_SP"  # Record which SP performed summarization
    }])
    
    # Write to staging table
    summary_data.write \
        .mode("append") \
        .saveAsTable("staging.default.summaries")
    
    print(f"✅ Wrote summary to staging.summaries")
    
except Exception as e:
    print(f"❌ Failed to write to staging: {e}")
    traceback.print_exc()
    raise

# COMMAND ----------

# MAGIC %md
# MAGIC ## Self-Report to CQRS Event Store

# COMMAND ----------

try:
    # Get run ID
    run_id = dbutils.notebook.entry_point.getDbutils() \
        .notebook().getContext().currentRunId().get()
    
    print(f"📊 Writing completion event to CQRS (Run ID: {run_id})")
    
    # Prepare event details
    details = {
        "extraction_run_id": extraction_run_id,
        "summary_length": len(summary_text),
        "compression_ratio": metadata['compression_ratio'],
        "sp_used": "SUMMARIZATION_SP",
        "summary_id": f"summary_{run_id}"
    }
    details_json = json.dumps(details).replace("'", "''")
    
    # Write "SummarizationJobCompleted" event
    spark.sql(f"""
        INSERT INTO {catalog_name}.{schema_name}.job_events
        (event_id, event_type, run_id, agent, sp_used, triggered_by, 
         timestamp, status, details)
        VALUES (
            uuid(),
            'SummarizationJobCompleted',
            {run_id},
            'summarization_agent',
            'SUMMARIZATION_SP',
            '{triggered_by}',
            current_timestamp(),
            'SUCCESS',
            '{details_json}'
        )
    """)
    
    print(f"✅ Logged SummarizationJobCompleted event")
    print(f"📊 Details: {details}")
    
except Exception as e:
    print(f"⚠️  Could not write CQRS event (non-fatal): {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary

# COMMAND ----------

print("\n" + "="*80)
print("✅ SUMMARIZATION COMPLETE")
print("="*80)
print(f"\nExtraction Run ID: {extraction_run_id}")
print(f"Summarization Run ID: {run_id}")
print(f"Document: {document_path}")
print(f"Original length: {len(extracted_text)} characters")
print(f"Summary length: {len(summary_text)} characters")
print(f"Compression ratio: {metadata['compression_ratio']}:1")
print(f"Summarized by: SUMMARIZATION_SP")
print(f"Triggered by: {triggered_by}")
print(f"\n📊 Data written to: {catalog_name}.staging.summaries")
print(f"📊 Event logged to: {catalog_name}.{schema_name}.job_events")
print(f"\n🔄 Next step: SharePointAgent will automatically upload to SharePoint")
print("="*80)

# COMMAND ----------

# Return success
dbutils.notebook.exit(json.dumps({
    "status": "SUCCESS",
    "run_id": int(run_id),
    "summary_id": f"summary_{run_id}",
    "extraction_run_id": extraction_run_id
}))

