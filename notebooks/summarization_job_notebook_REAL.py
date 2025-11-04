# Databricks notebook source
# MAGIC %md
# MAGIC # Summarization Job - REAL LLM VERSION
# MAGIC 
# MAGIC **This version calls REAL Foundation Model APIs!**
# MAGIC 
# MAGIC Changes from demo version:
# MAGIC - ✅ Calls REAL Databricks Foundation Model API
# MAGIC - ✅ Uses actual LLM (Llama 3.1 70B Instruct)
# MAGIC - ✅ Generates REAL clinical summaries
# MAGIC - ✅ No fake/simulated text!

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

from datetime import datetime
import traceback
import json

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
# MAGIC ## Generate Summary with REAL LLM
# MAGIC 
# MAGIC **REAL PROCESSING:** Calls Databricks Foundation Model API (Llama 3.1 70B Instruct)
# MAGIC 
# MAGIC This is NOT simulated - it makes an actual API call to the LLM!

import json
from databricks.sdk import WorkspaceClient

try:
    print(f"🤖 Generating clinical summary with REAL LLM...")
    print(f"   Model: databricks-meta-llama-3-1-70b-instruct")
    print(f"   Input length: {len(extracted_text)} characters")
    
    # Initialize Workspace Client
    # Uses automatic passthrough authentication (no credentials needed!)
    w = WorkspaceClient()
    
    # ✅ REAL LLM API CALL (not fake!)
    response = w.serving_endpoints.query(
        name="databricks-meta-llama-3-1-70b-instruct",
        messages=[
            {
                "role": "system",
                "content": """You are a medical AI assistant specializing in oncology. 
Summarize the following oncology document in a structured clinical format. 

Your summary should include:
1. **Patient Demographics** (if available)
2. **Diagnosis** with staging
3. **Biomarker Status**
4. **Treatment Recommendations**
5. **Prognosis**
6. **Key Clinical Notes**

Format your response as a professional clinical summary suitable for medical records."""
            },
            {
                "role": "user",
                "content": f"Please summarize this oncology report:\n\n{extracted_text}"
            }
        ],
        max_tokens=1500,
        temperature=0.3  # Lower temperature for factual medical content
    )
    
    # Extract summary from LLM response
    summary_text = response.choices[0].message.content
    
    print(f"✅ Generated REAL LLM summary ({len(summary_text)} characters)")
    print(f"")
    print(f"📝 Summary Preview (first 500 chars):")
    print(summary_text[:500])
    print(f"...")
    
    # Prepare metadata
    metadata = {
        "document_path": document_path,
        "extraction_run_id": extraction_run_id,
        "pages_summarized": page_count,
        "original_length": len(extracted_text),
        "summary_length": len(summary_text),
        "compression_ratio": round(len(extracted_text) / len(summary_text), 2),
        "model_used": "databricks-meta-llama-3-1-70b-instruct",
        "real_llm": True  # ✅ Flag to show this was real!
    }
    
    print(f"")
    print(f"📊 Summary Stats:")
    print(f"   Model: {metadata['model_used']}")
    print(f"   Original: {metadata['original_length']} chars")
    print(f"   Summary: {metadata['summary_length']} chars")
    print(f"   Compression: {metadata['compression_ratio']}:1")
    
except Exception as e:
    print(f"❌ Summary generation failed: {e}")
    traceback.print_exc()
    raise

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write to Staging Table
# MAGIC 
# MAGIC **Security Note:** Only SUMMARIZATION_SP has write access to staging.summaries

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
        "summary_text": summary_text,  # ✅ REAL LLM-generated summary!
        "document_metadata": json.dumps(metadata),
        "summarized_at": datetime.now(),
        "summarized_by": "SUMMARIZATION_SP"  # Record which SP performed summarization
    }])
    
    # Write to staging table
    summary_data.write \
        .mode("append") \
        .saveAsTable(f"{catalog_name}.staging.summaries")
    
    print(f"✅ Wrote REAL LLM summary to {catalog_name}.staging.summaries")
    
except Exception as e:
    print(f"❌ Failed to write to staging: {e}")
    traceback.print_exc()
    raise

# COMMAND ----------

# MAGIC %md
# MAGIC ## Self-Report to CQRS Event Store

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
        "model_used": metadata['model_used'],
        "sp_used": "SUMMARIZATION_SP",
        "summary_id": f"summary_{run_id}",
        "real_llm": True  # ✅ Flag to show this was real!
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

print("\n" + "="*80)
print("✅ REAL LLM SUMMARIZATION COMPLETE")
print("="*80)
print(f"\nExtraction Run ID: {extraction_run_id}")
print(f"Summarization Run ID: {run_id}")
print(f"Document: {document_path}")
print(f"Model: {metadata['model_used']}")
print(f"Original length: {len(extracted_text)} characters")
print(f"Summary length: {len(summary_text)} characters")
print(f"Compression ratio: {metadata['compression_ratio']}:1")
print(f"Summarized by: SUMMARIZATION_SP")
print(f"Triggered by: {triggered_by}")
print(f"\n✨ This was REAL LLM summarization (not simulated)!")
print(f"📊 Data written to: {catalog_name}.staging.summaries")
print(f"📊 Event logged to: {catalog_name}.{schema_name}.job_events")
print(f"\n🔄 Next step: FileStorageAgent will store summary to UC Volumes")
print("="*80)

# COMMAND ----------

# Return success
dbutils.notebook.exit(json.dumps({
    "status": "SUCCESS",
    "run_id": int(run_id),
    "summary_id": f"summary_{run_id}",
    "extraction_run_id": extraction_run_id,
    "model_used": metadata['model_used'],
    "real_llm": True
}))

