# Databricks notebook source
# MAGIC %md
# MAGIC # Upload Sample Oncology PDF to UC Volumes
# MAGIC 
# MAGIC This notebook uploads a sample oncology report PDF to Unity Catalog Volumes for testing.
# MAGIC 
# MAGIC **Run this ONCE to set up test data**

# COMMAND ----------

# Sample PDF content (embedded for portability)
# In production, you would upload actual PDFs via UI or API

sample_pdf_content = """
ONCOLOGY CONSULTATION REPORT
=============================

PATIENT INFORMATION
-------------------
Patient ID: P-2024-001
Age: 58 years
Gender: Female
Date of Report: November 3, 2025
Attending Physician: Dr. Sarah Johnson, MD Oncology

DIAGNOSIS
---------
Primary Diagnosis: Invasive Ductal Carcinoma, Stage IIA (T2N0M0)
Tumor Location: Right breast, upper outer quadrant
Histology: Invasive ductal carcinoma, grade 2/3
Tumor Size: 2.8 cm in greatest dimension
Lymph Nodes: Negative (0/3 sentinel lymph nodes examined)
Distant Metastases: None detected on staging CT scan

BIOMARKER STATUS
----------------
Estrogen Receptor (ER): Positive (90% nuclear staining)
Progesterone Receptor (PR): Positive (75% nuclear staining)
HER2: Negative (IHC 1+, FISH not required)
Ki-67 Proliferation Index: Intermediate (25%)

RECOMMENDED TREATMENT PLAN
---------------------------
1. Neoadjuvant Chemotherapy (Pre-operative)
   Protocol: AC-T (Adriamycin-Cytoxan followed by Taxol)
   - 4 cycles of AC (Adriamycin 60 mg/m² + Cytoxan 600 mg/m²) every 21 days
   - Followed by 4 cycles of Taxol (Paclitaxel 175 mg/m²) every 21 days
   - Total duration: Approximately 24 weeks

2. Surgical Intervention
   - Lumpectomy with sentinel lymph node biopsy
   - To be performed 3-4 weeks after completion of chemotherapy

3. Adjuvant Radiation Therapy
   - Whole breast radiation (50 Gy in 25 fractions)
   - Tumor bed boost (10-16 Gy in 5-8 fractions)
   - To begin 4-6 weeks post-surgery

4. Endocrine Therapy
   - Tamoxifen 20 mg daily for 5-10 years
   - To begin after completion of radiation therapy

CLINICAL NOTES
--------------
The patient was informed of the diagnosis and treatment plan. She expressed 
understanding and agreement to proceed with neoadjuvant chemotherapy. 

Baseline cardiac function assessment (MUGA scan) shows normal left ventricular 
ejection fraction (LVEF 62%), appropriate for anthracycline-based chemotherapy.

Baseline Laboratory Values:
- WBC: 6.8 K/µL (normal range)
- Hemoglobin: 13.2 g/dL (normal range)
- Platelets: 245 K/µL (normal range)
- Creatinine: 0.9 mg/dL (normal range)
- AST/ALT: Within normal limits

Patient counseled on expected side effects including alopecia, nausea, fatigue, 
myelosuppression, and peripheral neuropathy. Prophylactic anti-emetics and growth 
factor support to be provided as needed.

FOLLOW-UP SCHEDULE
------------------
- Week 1: Chemotherapy initiation (Cycle 1, Day 1)
- Week 2: CBC monitoring, symptom management
- Week 3: Pre-treatment assessment for Cycle 2
- Weeks 4-24: Continue chemotherapy per protocol
- Week 28: Post-chemotherapy surgical evaluation
- Week 32-38: Radiation therapy (daily treatments)
- Month 12: Surveillance imaging (mammography, potential MRI)

PROGNOSIS
---------
Stage IIA hormone receptor-positive, HER2-negative breast cancer has a favorable 
prognosis with appropriate treatment. With the recommended multimodal therapy 
approach, the 5-year disease-free survival rate is estimated at 85-90%, and the 
10-year overall survival rate is approximately 80-85%.

Prognostic factors in this case are favorable:
- Tumor size < 3 cm
- Node-negative disease
- Hormone receptor-positive status
- HER2-negative
- Good performance status and cardiac function

_________________________________________________________________
Dr. Sarah Johnson, MD
Board Certified Medical Oncology
License #: MED-98765
"""

# COMMAND ----------

# Configuration
dbutils.widgets.text("catalog_name", "sselvan_banner", "Catalog Name")
dbutils.widgets.text("schema_name", "oncology", "Schema Name")

catalog_name = dbutils.widgets.get("catalog_name")
schema_name = dbutils.widgets.get("schema_name")

filename = "patient_001_oncology_report.txt"
uc_path = f"/Volumes/{catalog_name}/{schema_name}/source_pdfs/{filename}"

print(f"Writing sample PDF to: {uc_path}")

# COMMAND ----------

# Write to UC Volume (using text for simplicity - in production you'd use actual PDF)
with open(uc_path, 'w') as f:
    f.write(sample_pdf_content)

print(f"✅ Sample oncology report uploaded!")
print(f"")
print(f"📊 File Details:")
print(f"   Path: {uc_path}")
print(f"   Size: {len(sample_pdf_content)} characters")
print(f"   Format: Plain text (simulating PDF for demo)")
print(f"")
print(f"🧪 Test Command for Agent:")
print(f'   "Extract {uc_path}"')
print(f"")
print(f"📝 Note: In production, this would be a real PDF file")
print(f"   For this demo, we use plain text to avoid PDF library dependencies")

# COMMAND ----------

# Verify file exists
import os
if os.path.exists(uc_path):
    file_size = os.path.getsize(uc_path)
    print(f"✅ Verification successful!")
    print(f"   File exists at: {uc_path}")
    print(f"   File size: {file_size} bytes")
else:
    print(f"❌ File not found at: {uc_path}")

# COMMAND ----------

# Return success
import json
dbutils.notebook.exit(json.dumps({
    "status": "SUCCESS",
    "file_path": uc_path,
    "file_size": len(sample_pdf_content)
}))

