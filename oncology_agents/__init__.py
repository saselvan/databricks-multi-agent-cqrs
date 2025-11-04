"""
Oncology Multi-Agent System

Demonstrates two authentication patterns:
1. Manual OAuth - For Jobs API (EXTRACTION_SP, SUMMARIZATION_SP)
2. Automatic Passthrough - For UC Volumes (FileStorageAgent)
"""

from .extraction_agent import ExtractionAgent
from .summarization_agent import SummarizationAgent
from .file_storage_agent import FileStorageAgent
from .coordinator_agent import CoordinatorAgent

__version__ = "0.1.0"
__all__ = ["ExtractionAgent", "SummarizationAgent", "FileStorageAgent", "CoordinatorAgent"]
