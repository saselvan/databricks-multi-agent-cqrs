# Future Enhancements

This reference implementation currently focuses on **authentication patterns** and **async job execution with CQRS**. 

Below are planned enhancements for a production-ready system.

---

## 🛡️ Guardrails (Not Yet Implemented)

### What They Are
Safety mechanisms to prevent harmful outputs, protect sensitive data, and ensure compliance.

### Planned Implementation

**Content Filtering:**
```python
from databricks.guardrails import ContentFilter

# Example guardrail configuration
guardrails = ContentFilter(
    block_pii=True,
    block_profanity=True,
    block_medical_advice=True,  # For healthcare use cases
    custom_filters=["ssn", "credit_card"]
)

# Apply during agent response
filtered_response = guardrails.filter(agent_response)
```

**Input Validation:**
- Max query length
- Rate limiting per user
- Allowed file types
- Max file size

**Output Validation:**
- PII detection and redaction
- Confidence thresholds
- Citation requirements
- Factuality checks

### Integration Point
Would be added in the `CoordinatorAgent.predict()` method before returning responses.

---

## 📋 Prompt Governance (Not Yet Implemented)

### What It Is
Version control, approval workflows, and monitoring for agent prompts.

### Planned Implementation

**Prompt Versioning:**
```python
# Store prompts in Unity Catalog as managed tables
CREATE TABLE catalog.governance.prompts (
    prompt_id STRING,
    version INT,
    content STRING,
    approved_by STRING,
    approved_at TIMESTAMP,
    active BOOLEAN
);

# Load prompt in agent
approved_prompt = spark.table("catalog.governance.prompts")\
    .filter("active = true AND prompt_id = 'extraction_prompt'")\
    .orderBy("version", ascending=False)\
    .first()["content"]
```

**Approval Workflow:**
1. Prompt proposed in Delta table (`status='pending'`)
2. Review by governance team
3. Approval updates status to `'approved'` and `active=true`
4. Agents automatically use latest approved version

**Monitoring:**
- Track prompt performance (accuracy, user ratings)
- A/B testing of prompt variants
- Drift detection (output quality degradation)

### Integration Point
Would replace hardcoded prompts in agent code with dynamic lookups from governance tables.

---

## 🤖 Agent Governance (Not Yet Implemented)

### What It Is
Centralized monitoring, access control, and policy enforcement for all agents.

### Planned Implementation

**Agent Registry:**
```python
# Track all deployed agents
CREATE TABLE catalog.governance.agent_registry (
    agent_id STRING,
    agent_name STRING,
    version STRING,
    owner STRING,
    deployed_at TIMESTAMP,
    status STRING,  -- active, deprecated, disabled
    permissions ARRAY<STRING>
);
```

**Usage Tracking:**
```python
# Log every agent invocation
CREATE TABLE catalog.governance.agent_usage (
    invocation_id STRING,
    agent_id STRING,
    user_id STRING,
    timestamp TIMESTAMP,
    input_tokens INT,
    output_tokens INT,
    cost DECIMAL(10,4),
    latency_ms INT,
    success BOOLEAN
);
```

**Policy Enforcement:**
- Rate limits per user/agent
- Cost budgets per agent
- Allowed data sources per agent
- Required guardrails per agent type

**Alerting:**
- Cost threshold exceeded
- Error rate spike
- Unusual usage patterns
- Policy violations

### Integration Point
Would be added as middleware in the agent framework, logging before/after each invocation.

---

## 🗄️ Lakebase Integration (Not Yet Implemented)

### What It Is
Databricks' serverless PostgreSQL for low-latency conversation memory and state management.

### Why Lakebase

**Current**: Delta tables for conversation state
- ✅ Good for CQRS event logging (append-only)
- ❌ Slower for point lookups (need to scan)
- ❌ Not ideal for high-frequency state updates

**With Lakebase**: Serverless PostgreSQL
- ✅ <20ms latency for state lookups
- ✅ Optimized for transactional workloads
- ✅ Auto-scaling, serverless
- ✅ Full SQL support
- ✅ Auto-rotating credentials (future: HIPAA-compliant)

### Planned Architecture

```
┌─────────────────────────────────────┐
│   Agent Request                      │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│   Coordinator Agent                  │
│   • Reads conversation state         │
│     from Lakebase (fast lookup)     │
└──────────────┬──────────────────────┘
               │
               ├─► Trigger Jobs (CQRS events → Delta)
               │   
               └─► Update conversation state (Lakebase)
                   • User session
                   • Pending jobs
                   • Last interaction
```

### Schema Design

```sql
-- Lakebase schema for conversation memory
CREATE TABLE conversation_state (
    session_id UUID PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    current_stage VARCHAR(50),
    pending_run_id BIGINT,
    last_message TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user_id (user_id),
    INDEX idx_updated_at (updated_at)
);

-- Delta table for CQRS events (unchanged)
CREATE TABLE job_events (
    event_id STRING,
    event_type STRING,
    run_id BIGINT,
    ...
);
```

### Implementation Pattern

```python
import psycopg

class CoordinatorAgent:
    def __init__(self):
        # Lakebase connection (auto-rotating credentials)
        self.db = psycopg.connect(
            host=os.environ["LAKEBASE_HOST"],
            database=os.environ["LAKEBASE_DB"],
            user=os.environ["LAKEBASE_USER"],
            password=os.environ["LAKEBASE_PASSWORD"]
        )
    
    def handle_message(self, session_id: str, message: str):
        # Fast lookup from Lakebase (<20ms)
        with self.db.cursor() as cur:
            cur.execute(
                "SELECT current_stage, pending_run_id FROM conversation_state WHERE session_id = %s",
                (session_id,)
            )
            state = cur.fetchone()
        
        # Process message...
        
        # Update state in Lakebase
        with self.db.cursor() as cur:
            cur.execute(
                "UPDATE conversation_state SET current_stage = %s, updated_at = NOW() WHERE session_id = %s",
                (new_stage, session_id)
            )
            self.db.commit()
        
        # Log event to Delta (CQRS audit trail)
        spark.sql(f"INSERT INTO job_events VALUES (...)")
```

### Hybrid Pattern

**Lakebase**: Hot state (current conversations, active jobs)  
**Delta**: Cold audit trail (all events, historical analysis)

This gives you:
- Fast state lookups (Lakebase)
- Complete audit trail (Delta)
- Cost-efficient (hot vs cold storage)

### Integration Point
Would replace Delta table reads/writes in `CoordinatorAgent._get_pending_refresh()` and `_update_conversation_state()` methods.

---

## 🔄 LangGraph Integration (Not Yet Implemented)

### What It Is
State machine for complex agent workflows with conditional branching.

### Why LangGraph

Current implementation: Simple sequential flow  
With LangGraph: Complex workflows with:
- Conditional branching
- Parallel execution
- Error recovery
- State persistence (in Lakebase)

### Example Workflow

```python
from langgraph.graph import StateGraph, END

# Define workflow
workflow = StateGraph()

workflow.add_node("extract", extraction_node)
workflow.add_node("summarize", summarization_node)
workflow.add_node("validate", validation_node)
workflow.add_node("retry_extraction", retry_node)

# Conditional edges
workflow.add_conditional_edges(
    "extract",
    lambda state: "summarize" if state["extracted"] else "retry_extraction"
)

workflow.add_edge("summarize", "validate")
workflow.add_conditional_edges(
    "validate",
    lambda state: END if state["valid"] else "summarize"
)
```

---

## 📊 Monitoring Dashboard (Not Yet Implemented)

### Planned Metrics

**Operational:**
- Request volume (per hour/day)
- Latency (p50, p95, p99)
- Error rates (by type)
- Cost per request

**Business:**
- Documents processed
- Extraction accuracy
- User satisfaction ratings
- Most common queries

**Security:**
- Failed auth attempts
- Policy violations
- Unusual access patterns
- PII detection events

### Implementation
Databricks SQL dashboard querying CQRS events and usage logs.

---

## Implementation Priority

### Phase 1 (Current)
✅ Dual authentication patterns  
✅ Async job execution  
✅ CQRS event logging  
✅ Basic audit trail

### Phase 2 (Next)
🔄 Guardrails (content filtering, input validation)  
🔄 Lakebase integration (conversation memory)  
🔄 Basic monitoring (error rates, latency)

### Phase 3 (Future)
📋 Prompt governance (versioning, approval)  
📋 Agent governance (registry, policies)  
📋 LangGraph workflows  
📋 Advanced monitoring dashboard

---

## Contributing

Want to implement one of these enhancements? 

1. Fork the repository
2. Create a feature branch (`feature/guardrails`, `feature/lakebase`, etc.)
3. Implement with tests
4. Submit a pull request

---

**This is a living document.** As new Databricks features become available (especially Lakebase HIPAA compliance), this list will be updated.

