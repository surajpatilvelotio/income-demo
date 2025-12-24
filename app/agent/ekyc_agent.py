"""
eKYC Agent using the KYC Workflow pattern.

This module provides the main entry point for KYC processing,
using a sequential workflow: OCR → User Review → Gov Verification → Fraud Detection
"""

import asyncio
import logging
import time

from app.agent.kyc_workflow import KYCWorkflow, process_kyc_workflow

logger = logging.getLogger(__name__)


def process_kyc_application(application_id: str, documents: list[dict]) -> dict:
    """
    Process a KYC application using the workflow pattern.
    
    This is the main entry point for background KYC processing.
    Uses the sequential workflow:
    1. OCR extraction
    2. User review (auto-confirmed in background)
    3. Government database verification
    4. Fraud detection (only if gov verification passes)
    5. Final decision
    
    Args:
        application_id: The KYC application ID
        documents: List of document info dicts with file_path, document_type, original_filename
        
    Returns:
        dict: Processing result with decision
    """
    logger.info(f"=" * 60)
    logger.info(f"[KYC Processing] Starting for application: {application_id}")
    logger.info(f"[KYC Processing] Documents: {len(documents)}")
    logger.info(f"=" * 60)
    
    max_retries = 3
    retry_delay = 1
    
    for attempt in range(max_retries):
        try:
            # Run the async workflow in sync context
            result = asyncio.run(process_kyc_workflow(application_id, documents))
            
            logger.info(f"=" * 60)
            logger.info(f"[KYC Processing] Completed for application: {application_id}")
            
            final_result = result.get("final_result", {})
            decision = final_result.get("decision", final_result.get("status", "unknown"))
            logger.info(f"[KYC Processing] Decision: {decision}")
            logger.info(f"=" * 60)
            
            return {
                "application_id": application_id,
                "processing_complete": True,
                "result": result,
            }
            
        except PermissionError as e:
            logger.warning(f"Attempt {attempt + 1}/{max_retries}: PermissionError: {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay * (attempt + 1))
            else:
                logger.error(f"All {max_retries} attempts failed due to PermissionError")
                return {
                    "application_id": application_id,
                    "processing_complete": False,
                    "error": f"File access error after {max_retries} attempts: {str(e)}",
                }
                
        except Exception as e:
            logger.error(f"[KYC Processing] Error: {e}", exc_info=True)
            return {
                "application_id": application_id,
                "processing_complete": False,
                "error": str(e),
            }
    
    return {
        "application_id": application_id,
        "processing_complete": False,
        "error": "Unknown error during processing",
    }


# Legacy function for backward compatibility
def create_ekyc_agent(session_id: str):
    """
    Legacy function - now returns a workflow manager instead.
    
    The eKYC processing now uses a workflow pattern instead of a single agent.
    """
    logger.warning("create_ekyc_agent is deprecated. Use process_kyc_application instead.")
    return KYCWorkflow(session_id)
