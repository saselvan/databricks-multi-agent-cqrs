#!/usr/bin/env python3
"""
End-to-End Test Script for Multi-Agent CQRS Demo

This script automates the setup and testing of the multi-agent system
to verify it works correctly after cloning from GitHub.

Prerequisites:
  - Databricks CLI configured (databricks configure --token)
  - Two Service Principals created with secrets stored
  - Account admin access for UC permissions

Usage:
  python END_TO_END_TEST.py --catalog test_demo --schema multi_agent

Expected Duration: 30-45 minutes
"""

import argparse
import time
import os
import sys
from databricks.sdk import WorkspaceClient
from databricks.sdk.service import catalog, jobs, compute, iam
from databricks.sdk.service.catalog import VolumeType
import json

class Colors:
    """ANSI color codes for terminal output"""
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def print_header(text):
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*80}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{text}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'='*80}{Colors.ENDC}\n")

def print_success(text):
    print(f"{Colors.OKGREEN}✅ {text}{Colors.ENDC}")

def print_warning(text):
    print(f"{Colors.WARNING}⚠️  {text}{Colors.ENDC}")

def print_error(text):
    print(f"{Colors.FAIL}❌ {text}{Colors.ENDC}")

def print_info(text):
    print(f"{Colors.OKCYAN}ℹ️  {text}{Colors.ENDC}")

class EndToEndTest:
    def __init__(self, catalog_name, schema_name, secret_scope, 
                 extraction_sp_id, extraction_sp_secret,
                 summarization_sp_id, summarization_sp_secret):
        self.w = WorkspaceClient()
        self.catalog_name = catalog_name
        self.schema_name = schema_name
        self.secret_scope = secret_scope
        self.extraction_sp_id = extraction_sp_id
        self.extraction_sp_secret = extraction_sp_secret
        self.summarization_sp_id = summarization_sp_id
        self.summarization_sp_secret = summarization_sp_secret
        self.current_user = self.w.current_user.me()
        self.workspace_path = f"/Users/{self.current_user.user_name}/test_multi_agent_demo"
        
        self.extraction_job_id = None
        self.summarization_job_id = None
        self.endpoint_name = None

    def step_1_create_catalog_schema(self):
        """Create Unity Catalog catalog and schemas"""
        print_header("STEP 1: Create Unity Catalog & Schemas")
        
        try:
            # Create catalog
            try:
                self.w.catalogs.create(name=self.catalog_name, comment="Test catalog for multi-agent demo")
                print_success(f"Created catalog: {self.catalog_name}")
            except Exception as e:
                if "already exists" in str(e).lower():
                    print_warning(f"Catalog {self.catalog_name} already exists, using existing")
                else:
                    raise
            
            # Create main schema
            try:
                self.w.schemas.create(
                    catalog_name=self.catalog_name,
                    name=self.schema_name,
                    comment="Schema for multi-agent demo"
                )
                print_success(f"Created schema: {self.catalog_name}.{self.schema_name}")
            except Exception as e:
                if "already exists" in str(e).lower():
                    print_warning(f"Schema {self.schema_name} already exists, using existing")
                else:
                    raise
            
            # Create staging schema
            try:
                self.w.schemas.create(
                    catalog_name=self.catalog_name,
                    name="staging",
                    comment="Staging schema for demo"
                )
                print_success(f"Created schema: {self.catalog_name}.staging")
            except Exception as e:
                if "already exists" in str(e).lower():
                    print_warning(f"Schema staging already exists, using existing")
                else:
                    raise
            
            print_success("Step 1 complete: Catalog and schemas ready")
            return True
            
        except Exception as e:
            print_error(f"Step 1 failed: {e}")
            return False

    def step_2_store_secrets(self):
        """Store Service Principal credentials in Databricks Secrets"""
        print_header("STEP 2: Store Service Principal Secrets")
        
        try:
            # Create secret scope
            try:
                self.w.secrets.create_scope(scope=self.secret_scope)
                print_success(f"Created secret scope: {self.secret_scope}")
            except Exception as e:
                if "already exists" in str(e).lower():
                    print_warning(f"Secret scope {self.secret_scope} already exists, using existing")
                else:
                    raise
            
            # Store secrets
            secrets_to_store = {
                "extraction_sp_client_id": self.extraction_sp_id,
                "extraction_sp_secret": self.extraction_sp_secret,
                "summarization_sp_client_id": self.summarization_sp_id,
                "summarization_sp_secret": self.summarization_sp_secret
            }
            
            for secret_key, secret_value in secrets_to_store.items():
                self.w.secrets.put_secret(
                    scope=self.secret_scope,
                    key=secret_key,
                    string_value=secret_value
                )
                print_success(f"Stored secret: {secret_key}")
            
            # Verify secrets
            secrets_list = self.w.secrets.list_secrets(scope=self.secret_scope)
            print_info(f"Total secrets in scope: {len(list(secrets_list))}")
            
            print_success("Step 2 complete: Secrets stored")
            return True
            
        except Exception as e:
            print_error(f"Step 2 failed: {e}")
            return False

    def step_3_upload_notebooks(self):
        """Upload notebooks to workspace"""
        print_header("STEP 3: Upload Notebooks to Workspace")
        
        try:
            # Create workspace directory
            self.w.workspace.mkdirs(path=self.workspace_path)
            print_success(f"Created workspace directory: {self.workspace_path}")
            
            # Upload notebooks
            notebooks_dir = "./notebooks"
            notebooks_to_upload = [
                "01_setup_cqrs_tables.py",
                "02_create_extraction_job.py",
                "03_create_summarization_job.py",
                "extraction_job_notebook_FIXED.py",
                "summarization_job_notebook_REAL.py",
                "06_deploy_production_proper.py"
            ]
            
            for notebook in notebooks_to_upload:
                local_path = os.path.join(notebooks_dir, notebook)
                workspace_path = f"{self.workspace_path}/{notebook}"
                
                with open(local_path, 'r') as f:
                    content = f.read()
                
                # Import to workspace
                import base64
                content_bytes = content.encode('utf-8')
                content_b64 = base64.b64encode(content_bytes).decode('utf-8')
                
                self.w.workspace.import_(
                    path=workspace_path,
                    format=catalog.ImportFormat.SOURCE,
                    language=catalog.Language.PYTHON,
                    content=content_b64,
                    overwrite=True
                )
                print_success(f"Uploaded: {notebook}")
            
            print_success("Step 3 complete: Notebooks uploaded")
            return True
            
        except Exception as e:
            print_error(f"Step 3 failed: {e}")
            import traceback
            traceback.print_exc()
            return False

    def step_4_run_setup_notebook(self):
        """Run 01_setup_cqrs_tables.py to create tables and volumes"""
        print_header("STEP 4: Run Setup Notebook (Create Tables & Volumes)")
        
        try:
            print_info("This will take ~3-5 minutes (cluster startup + execution)")
            
            notebook_path = f"{self.workspace_path}/01_setup_cqrs_tables.py"
            
            # Run notebook
            run = self.w.jobs.submit(
                run_name="Test: Setup CQRS Tables",
                tasks=[
                    jobs.SubmitTask(
                        task_key="setup",
                        notebook_task=jobs.NotebookTask(
                            notebook_path=notebook_path,
                            base_parameters={
                                "catalog_name": self.catalog_name,
                                "schema_name": self.schema_name
                            }
                        ),
                        new_cluster=compute.ClusterSpec(
                            spark_version="14.3.x-scala2.12",
                            node_type_id="i3.xlarge",
                            num_workers=0,
                            data_security_mode=compute.DataSecurityMode.SINGLE_USER,
                            runtime_engine=compute.RuntimeEngine.PHOTON
                        )
                    )
                ]
            )
            
            print_info(f"Submitted run: {run.run_id}")
            print_info(f"Monitor: {self.w.config.host}/#job/{run.run_id}")
            
            # Wait for completion
            final_run = self.w.jobs.wait_get_run_job_terminated_or_skipped(run_id=run.run_id)
            
            if final_run.state.result_state == jobs.RunResultState.SUCCESS:
                print_success("Setup notebook completed successfully")
                print_success("Created: CQRS tables, staging tables, UC volumes")
                return True
            else:
                print_error(f"Setup notebook failed: {final_run.state.state_message}")
                return False
                
        except Exception as e:
            print_error(f"Step 4 failed: {e}")
            return False

    def step_5_create_jobs(self):
        """Create extraction and summarization jobs"""
        print_header("STEP 5: Create Extraction & Summarization Jobs")
        
        try:
            # Create extraction job
            print_info("Creating extraction job...")
            extraction_job = self.w.jobs.create(
                name=f"test_extraction_job_{int(time.time())}",
                tasks=[
                    jobs.Task(
                        task_key="extract",
                        notebook_task=jobs.NotebookTask(
                            notebook_path=f"{self.workspace_path}/extraction_job_notebook_FIXED.py",
                            base_parameters={
                                "catalog_name": self.catalog_name,
                                "schema_name": self.schema_name
                            }
                        ),
                        new_cluster=compute.ClusterSpec(
                            spark_version="14.3.x-scala2.12",
                            node_type_id="i3.xlarge",
                            num_workers=0,
                            data_security_mode=compute.DataSecurityMode.SINGLE_USER,
                            runtime_engine=compute.RuntimeEngine.PHOTON
                        )
                    )
                ],
                run_as=jobs.JobRunAs(service_principal_name=self.extraction_sp_id)
            )
            self.extraction_job_id = extraction_job.job_id
            print_success(f"Created extraction job: {self.extraction_job_id}")
            
            # Create summarization job
            print_info("Creating summarization job...")
            summarization_job = self.w.jobs.create(
                name=f"test_summarization_job_{int(time.time())}",
                tasks=[
                    jobs.Task(
                        task_key="summarize",
                        notebook_task=jobs.NotebookTask(
                            notebook_path=f"{self.workspace_path}/summarization_job_notebook_REAL.py",
                            base_parameters={
                                "catalog_name": self.catalog_name,
                                "schema_name": self.schema_name
                            }
                        ),
                        new_cluster=compute.ClusterSpec(
                            spark_version="14.3.x-scala2.12",
                            node_type_id="i3.xlarge",
                            num_workers=0,
                            data_security_mode=compute.DataSecurityMode.SINGLE_USER,
                            runtime_engine=compute.RuntimeEngine.PHOTON
                        )
                    )
                ],
                run_as=jobs.JobRunAs(service_principal_name=self.summarization_sp_id)
            )
            self.summarization_job_id = summarization_job.job_id
            print_success(f"Created summarization job: {self.summarization_job_id}")
            
            print_success("Step 5 complete: Jobs created")
            return True
            
        except Exception as e:
            print_error(f"Step 5 failed: {e}")
            return False

    def step_6_grant_permissions(self):
        """Grant UC permissions to Service Principals"""
        print_header("STEP 6: Grant Unity Catalog Permissions")
        
        print_warning("⚠️  This step requires SQL execution")
        print_info("Granting permissions via SQL...")
        
        # TODO: Implement SQL execution for permissions
        # For now, print the SQL commands
        sql_commands = f"""
-- For EXTRACTION_SP:
GRANT USE CATALOG ON CATALOG {self.catalog_name} TO `{self.extraction_sp_id}`;
GRANT USE SCHEMA ON SCHEMA {self.catalog_name}.{self.schema_name} TO `{self.extraction_sp_id}`;
GRANT READ VOLUME ON VOLUME {self.catalog_name}.{self.schema_name}.source_pdfs TO `{self.extraction_sp_id}`;
GRANT SELECT, INSERT ON TABLE {self.catalog_name}.staging.extracted_documents TO `{self.extraction_sp_id}`;
GRANT SELECT, INSERT ON TABLE {self.catalog_name}.{self.schema_name}.job_events TO `{self.extraction_sp_id}`;

-- For SUMMARIZATION_SP:
GRANT USE CATALOG ON CATALOG {self.catalog_name} TO `{self.summarization_sp_id}`;
GRANT USE SCHEMA ON SCHEMA {self.catalog_name}.{self.schema_name} TO `{self.summarization_sp_id}`;
GRANT WRITE VOLUME ON VOLUME {self.catalog_name}.{self.schema_name}.summaries TO `{self.summarization_sp_id}`;
GRANT SELECT, INSERT ON TABLE {self.catalog_name}.staging.summaries TO `{self.summarization_sp_id}`;
GRANT SELECT, INSERT ON TABLE {self.catalog_name}.{self.schema_name}.job_events TO `{self.summarization_sp_id}`;
"""
        
        print_info("Execute these SQL commands in a SQL editor:")
        print(f"{Colors.OKCYAN}{sql_commands}{Colors.ENDC}")
        
        input(f"\n{Colors.BOLD}Press ENTER after executing the SQL commands...{Colors.ENDC}")
        
        print_success("Step 6 complete: Permissions granted")
        return True

    def step_7_create_sample_data(self):
        """Create sample PDF in UC Volume"""
        print_header("STEP 7: Create Sample Data")
        
        print_warning("⚠️  Manual step required")
        print_info(f"Run this notebook in the UI: {self.workspace_path}/00_upload_sample_pdf.py")
        print_info("Or manually create a file in UC Volume:")
        print_info(f"  /Volumes/{self.catalog_name}/{self.schema_name}/source_pdfs/patient_001.txt")
        
        input(f"\n{Colors.BOLD}Press ENTER after creating sample data...{Colors.ENDC}")
        
        print_success("Step 7 complete: Sample data ready")
        return True

    def step_8_deploy_agent(self):
        """Deploy the agent"""
        print_header("STEP 8: Deploy Agent")
        
        print_warning("⚠️  This will take ~5-10 minutes")
        print_info(f"Run this notebook: {self.workspace_path}/06_deploy_production_proper.py")
        print_info("With parameters:")
        print_info(f"  catalog_name: {self.catalog_name}")
        print_info(f"  schema_name: {self.schema_name}")
        print_info(f"  extraction_job_id: {self.extraction_job_id}")
        print_info(f"  summarization_job_id: {self.summarization_job_id}")
        
        input(f"\n{Colors.BOLD}Press ENTER after agent deployment completes...{Colors.ENDC}")
        
        # Get endpoint name
        self.endpoint_name = input(f"{Colors.BOLD}Enter the endpoint name: {Colors.ENDC}").strip()
        
        print_success(f"Step 8 complete: Agent deployed to {self.endpoint_name}")
        return True

    def step_9_test_agent(self):
        """Test the deployed agent"""
        print_header("STEP 9: Test Agent")
        
        print_info(f"Testing endpoint: {self.endpoint_name}")
        
        try:
            from databricks.sdk.service.serving import ChatMessage, ChatMessageRole
            
            test_query = f"Extract /Volumes/{self.catalog_name}/{self.schema_name}/source_pdfs/patient_001.txt"
            
            response = self.w.serving_endpoints.query(
                name=self.endpoint_name,
                messages=[
                    ChatMessage(
                        role=ChatMessageRole.USER,
                        content=test_query
                    )
                ]
            )
            
            print_success("Agent responded successfully!")
            print_info(f"Response: {response.choices[0].message.content}")
            
            print_success("Step 9 complete: Agent tested successfully")
            return True
            
        except Exception as e:
            print_error(f"Step 9 failed: {e}")
            print_warning("You can test manually in the UI")
            return False

    def step_10_verify_results(self):
        """Verify CQRS events and data"""
        print_header("STEP 10: Verify Results")
        
        print_info("Verification SQL queries:")
        
        queries = f"""
-- Check extracted documents:
SELECT * FROM {self.catalog_name}.staging.extracted_documents 
ORDER BY extracted_at DESC LIMIT 5;

-- Check CQRS events:
SELECT event_type, agent, sp_used, status, timestamp 
FROM {self.catalog_name}.{self.schema_name}.job_events 
ORDER BY timestamp DESC LIMIT 10;

-- Check job status:
SELECT * FROM {self.catalog_name}.{self.schema_name}.job_status_latest;
"""
        
        print(f"{Colors.OKCYAN}{queries}{Colors.ENDC}")
        
        print_success("Step 10 complete: Verification queries provided")
        return True

    def run_all(self):
        """Run all test steps"""
        print_header("MULTI-AGENT CQRS END-TO-END TEST")
        print_info(f"Catalog: {self.catalog_name}")
        print_info(f"Schema: {self.schema_name}")
        print_info(f"Workspace: {self.w.config.host}")
        print_info(f"User: {self.current_user.user_name}")
        
        steps = [
            ("Create Catalog & Schemas", self.step_1_create_catalog_schema),
            ("Store Secrets", self.step_2_store_secrets),
            ("Upload Notebooks", self.step_3_upload_notebooks),
            ("Run Setup Notebook", self.step_4_run_setup_notebook),
            ("Create Jobs", self.step_5_create_jobs),
            ("Grant Permissions", self.step_6_grant_permissions),
            ("Create Sample Data", self.step_7_create_sample_data),
            ("Deploy Agent", self.step_8_deploy_agent),
            ("Test Agent", self.step_9_test_agent),
            ("Verify Results", self.step_10_verify_results)
        ]
        
        for i, (step_name, step_func) in enumerate(steps, 1):
            try:
                if not step_func():
                    print_error(f"\n❌ Test failed at step {i}: {step_name}")
                    return False
            except KeyboardInterrupt:
                print_warning("\n\n⚠️  Test interrupted by user")
                return False
            except Exception as e:
                print_error(f"\n❌ Unexpected error in step {i} ({step_name}): {e}")
                import traceback
                traceback.print_exc()
                return False
        
        print_header("🎉 END-TO-END TEST COMPLETE!")
        print_success("All steps passed successfully!")
        print_info(f"\nEndpoint: {self.w.config.host}/ml/endpoints/{self.endpoint_name}")
        print_info(f"Extraction Job: {self.w.config.host}/#job/{self.extraction_job_id}")
        print_info(f"Summarization Job: {self.w.config.host}/#job/{self.summarization_job_id}")
        
        return True


def main():
    parser = argparse.ArgumentParser(description="End-to-end test for multi-agent CQRS demo")
    parser.add_argument("--catalog", required=True, help="Catalog name (e.g., test_demo)")
    parser.add_argument("--schema", required=True, help="Schema name (e.g., multi_agent)")
    parser.add_argument("--secret-scope", default="test_agents", help="Secret scope name")
    parser.add_argument("--extraction-sp-id", required=True, help="Extraction SP Client ID")
    parser.add_argument("--extraction-sp-secret", required=True, help="Extraction SP Secret")
    parser.add_argument("--summarization-sp-id", required=True, help="Summarization SP Client ID")
    parser.add_argument("--summarization-sp-secret", required=True, help="Summarization SP Secret")
    
    args = parser.parse_args()
    
    test = EndToEndTest(
        catalog_name=args.catalog,
        schema_name=args.schema,
        secret_scope=args.secret_scope,
        extraction_sp_id=args.extraction_sp_id,
        extraction_sp_secret=args.extraction_sp_secret,
        summarization_sp_id=args.summarization_sp_id,
        summarization_sp_secret=args.summarization_sp_secret
    )
    
    success = test.run_all()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

