# CQRS Chaining Pattern - How Agents Coordinate

## 🔄 The CQRS Event Flow

```
┌─────────────────────────────────────────────────────────────────┐
│ USER: "Extract /source_pdfs/patient_123.pdf"                    │
└─────────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│ COORDINATOR: Routes to ExtractionAgent                          │
└─────────────────────────────────────────────────────────────────┘
                           ↓
╔═════════════════════════════════════════════════════════════════╗
║ COMMAND SIDE (Write - Triggers Action)                          ║
╚═════════════════════════════════════════════════════════════════╝
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│ ExtractionAgent.trigger_extraction()                            │
│                                                                  │
│ 1. Triggers job with EXTRACTION_SP:                             │
│    run = w.jobs.run_now(job_id=extraction_job_id)               │
│                                                                  │
│ 2. Writes COMMAND event to Delta:                               │
│    INSERT INTO job_events VALUES (                              │
│      'ExtractionJobStarted',                                    │
│      run_id=12345,                                              │
│      agent='extraction_agent',                                  │
│      sp_used='EXTRACTION_SP'                                    │
│    )                                                             │
│                                                                  │
│ 3. Stores conversation state:                                   │
│    INSERT INTO conversation_state VALUES (                      │
│      user_id='user123',                                         │
│      extraction_run_id=12345,                                   │
│      current_stage='extracting'                                 │
│    )                                                             │
│                                                                  │
│ 4. Returns IMMEDIATELY (no blocking!):                          │
│    return {"run_id": 12345, "message": "Started!"}              │
└─────────────────────────────────────────────────────────────────┘
                           ↓
╔═════════════════════════════════════════════════════════════════╗
║ EVENT SIDE (Self-Reporting - Job Writes Completion)             ║
╚═════════════════════════════════════════════════════════════════╝
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│ Extraction Job (runs independently for 30 min)                  │
│                                                                  │
│ [30 minutes of PDF extraction...]                               │
│                                                                  │
│ On completion, job writes EVENT to Delta:                       │
│   INSERT INTO job_events VALUES (                               │
│     'ExtractionJobCompleted',                                   │
│     run_id=12345,                                               │
│     agent='extraction_agent',                                   │
│     sp_used='EXTRACTION_SP',                                    │
│     status='SUCCESS',                                           │
│     details='{"pages": 50}'                                     │
│   )                                                              │
└─────────────────────────────────────────────────────────────────┘
                           ↓
╔═════════════════════════════════════════════════════════════════╗
║ QUERY SIDE (Read - Coordinator Checks Status)                   ║
╚═════════════════════════════════════════════════════════════════╝
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│ USER: "What's the status?" (or any message)                     │
└─────────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│ Coordinator.handle_user_message()                               │
│                                                                  │
│ 1. Check for pending workflow:                                  │
│    SELECT extraction_run_id, current_stage                      │
│    FROM conversation_state                                      │
│    WHERE user_id='user123' AND status='in_progress'             │
│    → Returns: extraction_run_id=12345, stage='extracting'       │
│                                                                  │
│ 2. Check job status from Delta (NO API call!):                  │
│    SELECT event_type, status                                    │
│    FROM job_events                                              │
│    WHERE run_id=12345                                           │
│    ORDER BY timestamp DESC LIMIT 1                              │
│    → Returns: 'ExtractionJobCompleted', status='SUCCESS'        │
│                                                                  │
│ 3. Extraction complete! AUTO-ADVANCE TO NEXT STAGE:             │
│    result = summarization_agent.trigger_summarization(          │
│      extraction_run_id=12345                                    │
│    )                                                             │
└─────────────────────────────────────────────────────────────────┘
                           ↓
╔═════════════════════════════════════════════════════════════════╗
║ COMMAND SIDE (Write - Triggers Next Action)                     ║
╚═════════════════════════════════════════════════════════════════╝
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│ SummarizationAgent.trigger_summarization()                      │
│                                                                  │
│ 1. Verify extraction completed (reads from Delta):              │
│    SELECT event_type FROM job_events                            │
│    WHERE run_id=12345 AND agent='extraction_agent'              │
│    → Must be 'ExtractionJobCompleted'                           │
│                                                                  │
│ 2. Triggers job with SUMMARIZATION_SP:                          │
│    run = w.jobs.run_now(job_id=summarization_job_id)            │
│                                                                  │
│ 3. Writes COMMAND event to Delta:                               │
│    INSERT INTO job_events VALUES (                              │
│      'SummarizationJobStarted',                                 │
│      run_id=67890,                                              │
│      agent='summarization_agent',                               │
│      sp_used='SUMMARIZATION_SP'                                 │
│    )                                                             │
│                                                                  │
│ 4. Updates conversation state:                                  │
│    UPDATE conversation_state SET                                │
│      summarization_run_id=67890,                                │
│      current_stage='summarizing'                                │
│    WHERE user_id='user123'                                      │
│                                                                  │
│ 5. Returns to user:                                             │
│    return "✅ Extraction done! 📝 Summarization started!"       │
└─────────────────────────────────────────────────────────────────┘
                           ↓
╔═════════════════════════════════════════════════════════════════╗
║ EVENT SIDE (Self-Reporting - Job Writes Completion)             ║
╚═════════════════════════════════════════════════════════════════╝
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│ Summarization Job (runs independently for 10 min)               │
│                                                                  │
│ [10 minutes of summarization...]                                │
│                                                                  │
│ On completion, job writes EVENT to Delta:                       │
│   INSERT INTO job_events VALUES (                               │
│     'SummarizationJobCompleted',                                │
│     run_id=67890,                                               │
│     agent='summarization_agent',                                │
│     sp_used='SUMMARIZATION_SP',                                 │
│     status='SUCCESS'                                            │
│   )                                                              │
└─────────────────────────────────────────────────────────────────┘
                           ↓
╔═════════════════════════════════════════════════════════════════╗
║ QUERY SIDE (Read - Coordinator Checks Status)                   ║
╚═════════════════════════════════════════════════════════════════╝
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│ USER: "What's the status?" (or any message)                     │
└─────────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│ Coordinator.handle_user_message()                               │
│                                                                  │
│ 1. Check for pending workflow:                                  │
│    SELECT summarization_run_id, current_stage                   │
│    FROM conversation_state                                      │
│    WHERE user_id='user123' AND status='in_progress'             │
│    → Returns: summarization_run_id=67890, stage='summarizing'   │
│                                                                  │
│ 2. Check job status from Delta:                                 │
│    SELECT event_type, status                                    │
│    FROM job_events                                              │
│    WHERE run_id=67890                                           │
│    ORDER BY timestamp DESC LIMIT 1                              │
│    → Returns: 'SummarizationJobCompleted', status='SUCCESS'     │
│                                                                  │
│ 3. Summarization complete! AUTO-ADVANCE TO NEXT STAGE:          │
│    result = sharepoint_agent.upload_to_sharepoint(              │
│      summarization_run_id=67890                                 │
│    )                                                             │
└─────────────────────────────────────────────────────────────────┘
                           ↓
╔═════════════════════════════════════════════════════════════════╗
║ COMMAND SIDE (Write - Triggers Final Action)                    ║
╚═════════════════════════════════════════════════════════════════╝
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│ SharePointAgent.upload_to_sharepoint()                          │
│                                                                  │
│ 1. Verify summarization completed (reads from Delta):           │
│    SELECT event_type FROM job_events                            │
│    WHERE run_id=67890 AND agent='summarization_agent'           │
│    → Must be 'SummarizationJobCompleted'                        │
│                                                                  │
│ 2. Get summary content:                                         │
│    SELECT summary_text FROM staging.summaries                   │
│    WHERE summarization_run_id=67890                             │
│                                                                  │
│ 3. Upload to SharePoint with SHAREPOINT_SP:                     │
│    upload_response = sharepoint_api.upload(...)                 │
│                                                                  │
│ 4. Writes COMPLETION event to Delta:                            │
│    INSERT INTO job_events VALUES (                              │
│      'SharePointUploadCompleted',                               │
│      agent='sharepoint_agent',                                  │
│      sp_used='SHAREPOINT_SP',                                   │
│      status='SUCCESS',                                          │
│      details='{"url": "https://sharepoint.com/doc.pdf"}'        │
│    )                                                             │
│                                                                  │
│ 5. Updates conversation state to completed:                     │
│    UPDATE conversation_state SET                                │
│      current_stage='completed',                                 │
│      status='completed'                                         │
│    WHERE user_id='user123'                                      │
│                                                                  │
│ 6. Returns to user:                                             │
│    return "🎉 Workflow complete! URL: https://..."              │
└─────────────────────────────────────────────────────────────────┘
                           ↓
╔═════════════════════════════════════════════════════════════════╗
║ WORKFLOW COMPLETE                                                ║
╚═════════════════════════════════════════════════════════════════╝
```

---

## 🔑 Key CQRS Chaining Mechanisms

### 1. Command-Event Separation

**Commands (Write):** Agents trigger actions and write "Started" events
```python
# ExtractionAgent writes command
INSERT INTO job_events ('ExtractionJobStarted', run_id=12345, sp_used='EXTRACTION_SP')
```

**Events (Write):** Jobs self-report completion
```python
# Job writes event when done
INSERT INTO job_events ('ExtractionJobCompleted', run_id=12345, status='SUCCESS')
```

**Queries (Read):** Coordinator checks status
```python
# Coordinator reads latest event
SELECT event_type FROM job_events WHERE run_id=12345 ORDER BY timestamp DESC LIMIT 1
```

---

### 2. Conversation State (Workflow Tracking)

**Stores current stage per user:**
```sql
CREATE TABLE conversation_state (
  user_id STRING,
  extraction_run_id BIGINT,
  summarization_run_id BIGINT,
  current_stage STRING,  -- 'extracting', 'summarizing', 'uploading', 'completed'
  status STRING          -- 'in_progress', 'completed'
)
```

**Allows coordinator to:**
1. Remember what each user is waiting for
2. Know which stage to check
3. Know which agent to trigger next

---

### 3. Auto-Advancement Logic

**Implemented in Coordinator:**

```python
# coordinator_agent.py (_handle_pending_workflow)

def _handle_pending_workflow(self, workflow_state, user_message, user_id):
    stage = workflow_state['current_stage']
    
    if stage == "extracting":
        # Check extraction status from Delta
        status = self.extraction_agent.check_extraction_status(
            workflow_state['extraction_run_id']
        )
        
        if status['status'] == 'COMPLETED':
            # ✅ CHAIN TO NEXT STAGE
            result = self.summarization_agent.trigger_summarization(
                extraction_run_id=workflow_state['extraction_run_id'],
                user_id=user_id
            )
            
            # Update workflow state
            self._update_workflow_stage(
                user_id=user_id,
                stage="summarizing",
                summarization_run_id=result['run_id']
            )
            
            return "✅ Extraction complete! 📝 Summarization started!"
    
    elif stage == "summarizing":
        # Check summarization status from Delta
        status = self.summarization_agent.check_summarization_status(
            workflow_state['summarization_run_id']
        )
        
        if status['status'] == 'COMPLETED':
            # ✅ CHAIN TO NEXT STAGE
            result = self.sharepoint_agent.upload_to_sharepoint(
                summarization_run_id=workflow_state['summarization_run_id'],
                user_id=user_id
            )
            
            # Mark workflow complete
            self._update_workflow_stage(
                user_id=user_id,
                stage="completed"
            )
            
            return f"🎉 Complete! URL: {result['sharepoint_url']}"
    
    elif stage == "uploading":
        # Final stage - just inform user
        return "Uploading to SharePoint..."
```

**Key insight:** Coordinator checks status on EVERY user message, so when a stage completes, the NEXT user message automatically triggers the next stage.

---

### 4. Zero-Polling Pattern

**Traditional (Expensive):**
```python
# ❌ BAD: Continuous polling
while True:
    status = w.jobs.get_run(run_id).state
    if status == 'COMPLETED':
        break
    time.sleep(60)  # Poll every minute
# Cost: Hundreds of API calls
```

**CQRS (Cheap):**
```python
# ✅ GOOD: Query Delta (no API calls)
result = spark.sql(f"""
    SELECT event_type 
    FROM job_events 
    WHERE run_id = {run_id}
    ORDER BY timestamp DESC LIMIT 1
""").collect()

# Cost: Delta query (~$0.0001)
# Jobs self-report when done, no need to poll!
```

---

## 📊 Data Flow Through Tables

### Job Events Table (Event Store)

```sql
SELECT * FROM oncology_cqrs.job_events 
WHERE user_id = 'user123' 
ORDER BY timestamp;
```

**Example sequence:**
```
timestamp           | event_type                  | run_id | agent                 | sp_used
--------------------+-----------------------------+--------+-----------------------+------------------
2025-11-02 10:00:00 | ExtractionJobStarted        | 12345  | extraction_agent      | EXTRACTION_SP
2025-11-02 10:30:00 | ExtractionJobCompleted      | 12345  | extraction_agent      | EXTRACTION_SP
2025-11-02 10:30:05 | SummarizationJobStarted     | 67890  | summarization_agent   | SUMMARIZATION_SP
2025-11-02 10:40:00 | SummarizationJobCompleted   | 67890  | summarization_agent   | SUMMARIZATION_SP
2025-11-02 10:40:05 | SharePointUploadCompleted   | 0      | sharepoint_agent      | SHAREPOINT_SP
```

**Immutable audit trail** showing:
- When each stage started/completed
- Which agent performed each action
- Which SP was used (security audit)

---

### Conversation State Table (Workflow Tracking)

```sql
SELECT * FROM oncology_cqrs.conversation_state 
WHERE user_id = 'user123';
```

**Example progression:**
```
Time: 10:00 (User triggers extraction)
user_id  | extraction_run_id | summarization_run_id | current_stage | status
---------+-------------------+----------------------+---------------+-----------
user123  | 12345             | NULL                 | extracting    | in_progress

Time: 10:30 (Extraction completes, summarization starts)
user_id  | extraction_run_id | summarization_run_id | current_stage | status
---------+-------------------+----------------------+---------------+-----------
user123  | 12345             | 67890                | summarizing   | in_progress

Time: 10:40 (Summarization completes, SharePoint starts)
user_id  | extraction_run_id | summarization_run_id | current_stage | status
---------+-------------------+----------------------+---------------+-----------
user123  | 12345             | 67890                | completed     | completed
```

---

### Staging Tables (Data Flow)

**1. staging.extracted_documents** (EXTRACTION_SP writes, SUMMARIZATION_SP reads)
```sql
extraction_id | extraction_run_id | document_path       | extracted_text | extracted_by
--------------+-------------------+---------------------+----------------+---------------
extract_12345 | 12345             | /pdfs/patient_1.pdf | "ONCOLOGY..." | EXTRACTION_SP
```

**2. staging.summaries** (SUMMARIZATION_SP writes, SHAREPOINT_SP reads)
```sql
summary_id    | summarization_run_id | extraction_run_id | summary_text       | summarized_by
--------------+----------------------+-------------------+--------------------+------------------
summary_67890 | 67890                | 12345             | "CLINICAL SUMM..." | SUMMARIZATION_SP
```

**Security isolation:** Each SP can only access its designated tables!

---

## 🔄 The CQRS Loop

```
┌──────────────────────────────────────────────────────────────┐
│                                                               │
│  User Message → Coordinator checks conversation_state        │
│                                                               │
│  ↓                                                            │
│  Has pending workflow?                                        │
│  ↓                                                            │
│  YES → Query job_events for latest status                    │
│  ↓                                                            │
│  Stage complete?                                              │
│  ↓                                                            │
│  YES → Trigger next agent                                    │
│  ↓                                                            │
│  Next agent writes "Started" event to job_events             │
│  ↓                                                            │
│  Next agent updates conversation_state with new stage        │
│  ↓                                                            │
│  Return to user: "Stage X complete! Stage Y started!"        │
│  ↓                                                            │
│  [Wait for next user message]                                │
│  ↓                                                            │
│  User Message → Coordinator checks conversation_state ───────┘
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

**No background processes, no polling, no cron jobs!**

Just:
1. User sends message
2. Coordinator checks Delta
3. If stage complete, triggers next agent
4. Waits for next user message

---

## 💡 Why This Pattern Works

### 1. No Timeouts
Jobs run independently, don't hold agent session open

### 2. No Polling Costs
Read from Delta instead of continuous API calls to Jobs service

### 3. Complete Audit Trail
Every action logged with which SP was used

### 4. Auto-Advancing
User doesn't need to explicitly ask "is it done?" - any message checks status

### 5. Stateful Conversations
Agent remembers what each user is waiting for

### 6. Security Isolation
Each agent uses different SP, logged in CQRS events

---

## 🎯 Key Takeaways

**CQRS Chaining = Command + Event + Query**

**Command:** Agent triggers job, writes "Started" event  
**Event:** Job self-reports completion to Delta  
**Query:** Coordinator reads completion from Delta  
**Chain:** Coordinator triggers next agent when stage completes  

**Result:** Multi-stage async workflow with zero polling and complete audit trail!

---

**This is how Customer's oncology workflow is orchestrated with CQRS!** 🚀

