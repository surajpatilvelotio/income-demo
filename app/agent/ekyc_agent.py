"""eKYC Agent factory for identity verification processing."""

from strands import Agent
from strands.session.file_session_manager import FileSessionManager

from app.agent.llm import get_bedrock_model
from app.agent.ekyc_prompts import EKYC_SYSTEM_PROMPT
from app.agent.tools import (
    extract_document_data,
    parse_identity_info,
    verify_with_government,
    check_fraud_indicators,
    make_kyc_decision,
    update_kyc_stage,
)
from app.config import settings


def create_ekyc_agent(session_id: str) -> Agent:
    """
    Create a specialized eKYC verification agent.
    
    This agent is equipped with tools for document OCR, data extraction,
    government verification, fraud detection, and KYC decision making.

    Args:
        session_id: Unique identifier for the session (typically application_id)

    Returns:
        Agent: Configured eKYC agent instance with all verification tools
    """
    session_manager = FileSessionManager(
        session_id=f"ekyc-{session_id}",
        storage_dir=settings.session_storage_dir,
    )
    
    return Agent(
        model=get_bedrock_model(),
        system_prompt=EKYC_SYSTEM_PROMPT,
        session_manager=session_manager,
        tools=[
            extract_document_data,
            parse_identity_info,
            verify_with_government,
            check_fraud_indicators,
            make_kyc_decision,
            update_kyc_stage,
        ],
        callback_handler=None,
    )


def process_kyc_application(
    application_id: str,
    documents: list[dict],
) -> dict:
    """
    Process a KYC application using the eKYC agent.
    
    This function creates an eKYC agent and instructs it to process
    the uploaded documents through all verification stages.
    
    Note: This is a synchronous function because the Strands agent
    uses synchronous calls internally.
    
    Args:
        application_id: The KYC application ID
        documents: List of document info dicts with file_path, document_type
        
    Returns:
        dict: Processing result with decision and extracted data
    """
    agent = create_ekyc_agent(application_id)
    
    # Build the processing prompt
    docs_info = "\n".join([
        f"- {doc['document_type']}: {doc['file_path']}"
        for doc in documents
    ])
    
    prompt = f"""Process the following KYC application:

Application ID: {application_id}

Uploaded Documents:
{docs_info}

Please process this application through all verification stages:
1. First, update the stage to 'document_uploaded' as completed
2. Extract data from each document using OCR
3. Parse and structure the identity information
4. Verify the identity against the government database
5. Check for fraud indicators
6. Make a final KYC decision

Update the stage status after completing each step. Provide a comprehensive summary of your findings and final decision.
"""
    
    # Run the agent (synchronous call)
    result = agent(prompt)
    
    # Extract response text
    response_text = ""
    if result.message and result.message.get("content"):
        for content_block in result.message.get("content", []):
            if isinstance(content_block, dict) and "text" in content_block:
                response_text += content_block["text"]
    
    return {
        "application_id": application_id,
        "processing_complete": True,
        "agent_response": response_text,
    }

