"""eKYC Agent Tools module."""

from app.agent.tools.ocr import extract_document_data
from app.agent.tools.data_extraction import parse_identity_info
from app.agent.tools.government_db import verify_with_government
from app.agent.tools.fraud_detection import check_fraud_indicators
from app.agent.tools.kyc_decision import make_kyc_decision
from app.agent.tools.stage_tracker import update_kyc_stage
from app.agent.tools.user_tools import (
    register_user,
    get_user_status,
    find_user_by_email,
    initiate_kyc_process,
    check_kyc_application_status,
    get_user_kyc_applications,
    get_kyc_requirements,
    upload_kyc_document,
    get_uploaded_documents,
    run_ocr_extraction,
    confirm_and_verify,
    process_kyc,
    get_kyc_status,
)

__all__ = [
    # eKYC Processing Tools
    "extract_document_data",
    "parse_identity_info",
    "verify_with_government",
    "check_fraud_indicators",
    "make_kyc_decision",
    "update_kyc_stage",
    # User & KYC Management Tools
    "register_user",
    "get_user_status",
    "find_user_by_email",
    "initiate_kyc_process",
    "check_kyc_application_status",
    "get_user_kyc_applications",
    "get_kyc_requirements",
    # Document Upload Tools
    "upload_kyc_document",
    "get_uploaded_documents",
    # KYC Workflow Tools (integrated with chat)
    "run_ocr_extraction",
    "confirm_and_verify",
    "process_kyc",
    "get_kyc_status",
]

