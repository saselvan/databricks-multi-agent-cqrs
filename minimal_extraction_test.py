# Databricks notebook source
# MINIMAL TEST - Just read the file and print it

import os

# Parameters
dbutils.widgets.text("document_path", "/Volumes/sselvan_banner/oncology/source_pdfs/patient_001_oncology_report.txt", "Document Path")
document_path = dbutils.widgets.get("document_path")

print("="*80)
print("MINIMAL EXTRACTION TEST")
print("="*80)
print(f"\n1️⃣ Testing file path: {document_path}")

# Test 1: Check if path exists
print(f"\n2️⃣ Checking if file exists...")
if os.path.exists(document_path):
    print(f"   ✅ File exists!")
else:
    print(f"   ❌ File does NOT exist")
    print(f"   Listing parent directory:")
    parent_dir = os.path.dirname(document_path)
    try:
        files = os.listdir(parent_dir)
        print(f"   Files found: {files}")
    except Exception as e:
        print(f"   ❌ Cannot list directory: {e}")
    import json
    dbutils.notebook.exit(json.dumps({"status": "FAILED", "error": "File not found"}))

# Test 2: Try to read the file
print(f"\n3️⃣ Reading file...")
try:
    with open(document_path, 'r') as f:
        content = f.read()
    print(f"   ✅ Read {len(content)} characters!")
    print(f"   Preview: {content[:200]}...")
except Exception as e:
    print(f"   ❌ Failed to read: {e}")
    import traceback
    traceback.print_exc()
    import json
    dbutils.notebook.exit(json.dumps({"status": "FAILED", "error": str(e)}))

# Success!
print(f"\n" + "="*80)
print(f"✅ TEST PASSED!")
print(f"="*80)

import json
dbutils.notebook.exit(json.dumps({"status": "SUCCESS", "chars_read": len(content)}))
