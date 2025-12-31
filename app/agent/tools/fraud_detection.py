"""Fraud detection tool for KYC verification."""

from datetime import datetime, date

from strands import tool


@tool
def check_fraud_indicators(
    document_number: str,
    document_type: str,
    first_name: str,
    last_name: str,
    date_of_birth: str,
    address: str | None = None,
    expiry_date: str | None = None,
    ocr_confidence: float = 1.0,
    government_verified: bool = False,
    government_verification_status: str = "unknown",
    # Passport data for cross-validation (optional, for non-local users)
    passport_data: dict | None = None,
    # Visa data for cross-validation (optional, for non-local users)
    visa_data: dict | None = None,
    # Visa verification status
    visa_verified: bool | None = None,
) -> dict:
    """
    Check for fraud indicators in the KYC application.
    
    This tool analyzes various factors to detect potential fraud patterns,
    including document validity, data consistency, and known fraud indicators.
    For non-local users, it also cross-validates passport and visa data.
    
    Args:
        document_number: The document ID number
        document_type: Type of document - 'id_card' or 'passport'
        first_name: Applicant's first name
        last_name: Applicant's last name
        date_of_birth: Date of birth (format: YYYY-MM-DD)
        address: Applicant's address (optional)
        expiry_date: Document expiry date (format: YYYY-MM-DD, optional)
        ocr_confidence: Confidence score from OCR extraction (0.0 to 1.0)
        government_verified: Whether government verification passed
        government_verification_status: Status from government verification
        passport_data: Passport extracted data for cross-validation (optional)
        visa_data: Visa extracted data for cross-validation (optional)
        visa_verified: Whether visa was verified in government DB (optional)
        
    Returns:
        Dictionary containing:
        - success: Whether fraud check completed
        - fraud_detected: Whether fraud was detected
        - risk_level: 'low', 'medium', 'high', or 'critical'
        - risk_score: Numeric risk score (0.0 to 1.0)
        - fraud_indicators: List of detected fraud indicators
        - recommendation: Recommended action
    """
    try:
        fraud_indicators = []
        risk_score = 0.0
        
        # Check 1: Document expiry
        if expiry_date:
            try:
                expiry = datetime.strptime(expiry_date, "%Y-%m-%d").date()
                today = date.today()
                if expiry < today:
                    fraud_indicators.append({
                        "type": "expired_document",
                        "severity": "high",
                        "message": f"Document expired on {expiry_date}",
                    })
                    risk_score += 0.4
            except ValueError:
                fraud_indicators.append({
                    "type": "invalid_date_format",
                    "severity": "medium",
                    "message": "Invalid expiry date format",
                })
                risk_score += 0.2
        
        # Check 2: Age verification
        if date_of_birth:
            try:
                dob = datetime.strptime(date_of_birth, "%Y-%m-%d").date()
                today = date.today()
                age = (today - dob).days // 365
                
                if age < 18:
                    fraud_indicators.append({
                        "type": "underage",
                        "severity": "critical",
                        "message": f"Applicant is {age} years old (under 18)",
                    })
                    risk_score += 0.5
                elif age > 100:
                    fraud_indicators.append({
                        "type": "suspicious_age",
                        "severity": "high",
                        "message": f"Applicant age ({age}) is unusually high",
                    })
                    risk_score += 0.3
            except ValueError:
                fraud_indicators.append({
                    "type": "invalid_dob_format",
                    "severity": "medium",
                    "message": "Invalid date of birth format",
                })
                risk_score += 0.2
        
        # Check 3: OCR confidence
        if ocr_confidence < 0.5:
            fraud_indicators.append({
                "type": "low_ocr_confidence",
                "severity": "high",
                "message": f"OCR confidence is low ({ocr_confidence:.2f})",
            })
            risk_score += 0.3
        elif ocr_confidence < 0.7:
            fraud_indicators.append({
                "type": "medium_ocr_confidence",
                "severity": "medium",
                "message": f"OCR confidence is medium ({ocr_confidence:.2f})",
            })
            risk_score += 0.1
        
        # Check 4: Government verification status
        if not government_verified:
            if government_verification_status == "not_found":
                fraud_indicators.append({
                    "type": "document_not_in_government_db",
                    "severity": "high",
                    "message": "Document not found in government database",
                })
                risk_score += 0.4
            elif government_verification_status == "flagged":
                fraud_indicators.append({
                    "type": "government_flagged",
                    "severity": "critical",
                    "message": "Document is flagged in government database",
                })
                risk_score += 0.6
            elif government_verification_status == "mismatch":
                fraud_indicators.append({
                    "type": "data_mismatch",
                    "severity": "high",
                    "message": "Data does not match government records",
                })
                risk_score += 0.4
            elif government_verification_status == "invalid":
                fraud_indicators.append({
                    "type": "invalid_document",
                    "severity": "critical",
                    "message": "Document marked as invalid in government records",
                })
                risk_score += 0.5
        
        # Check 5: Document number pattern validation
        if document_type == "id_card" and not document_number.startswith("ID-"):
            fraud_indicators.append({
                "type": "suspicious_document_number",
                "severity": "low",
                "message": "ID card number does not follow expected pattern",
            })
            risk_score += 0.1
        elif document_type == "passport" and not document_number.startswith("PASS-"):
            fraud_indicators.append({
                "type": "suspicious_document_number",
                "severity": "low",
                "message": "Passport number does not follow expected pattern",
            })
            risk_score += 0.1
        
        # Check 6: Suspicious patterns in names
        if first_name and (len(first_name) < 2 or first_name.isdigit()):
            fraud_indicators.append({
                "type": "suspicious_name",
                "severity": "medium",
                "message": "First name appears suspicious",
            })
            risk_score += 0.2
        
        if last_name and (len(last_name) < 2 or last_name.isdigit()):
            fraud_indicators.append({
                "type": "suspicious_name",
                "severity": "medium",
                "message": "Last name appears suspicious",
            })
            risk_score += 0.2
        
        # Check 7: Visa verification status (for non-local users)
        if visa_verified is not None and not visa_verified:
            fraud_indicators.append({
                "type": "visa_not_verified",
                "severity": "high",
                "message": "Visa could not be verified in immigration database",
            })
            risk_score += 0.4
        
        # Check 8: Cross-validate passport and visa data (for non-local users)
        if passport_data and visa_data:
            # Cross-validate names
            passport_first = (passport_data.get("first_name") or "").lower().strip()
            passport_last = (passport_data.get("last_name") or "").lower().strip()
            visa_first = (visa_data.get("first_name") or "").lower().strip()
            visa_last = (visa_data.get("last_name") or "").lower().strip()
            
            if passport_first and visa_first and passport_first != visa_first:
                fraud_indicators.append({
                    "type": "name_mismatch_passport_visa",
                    "severity": "high",
                    "message": f"First name mismatch: passport '{passport_data.get('first_name')}' vs visa '{visa_data.get('first_name')}'",
                })
                risk_score += 0.3
            
            if passport_last and visa_last and passport_last != visa_last:
                fraud_indicators.append({
                    "type": "name_mismatch_passport_visa",
                    "severity": "high",
                    "message": f"Last name mismatch: passport '{passport_data.get('last_name')}' vs visa '{visa_data.get('last_name')}'",
                })
                risk_score += 0.3
            
            # Cross-validate DOB
            passport_dob = passport_data.get("date_of_birth", "")
            visa_dob = visa_data.get("date_of_birth", "")
            if passport_dob and visa_dob and passport_dob != visa_dob:
                fraud_indicators.append({
                    "type": "dob_mismatch_passport_visa",
                    "severity": "high",
                    "message": f"Date of birth mismatch: passport '{passport_dob}' vs visa '{visa_dob}'",
                })
                risk_score += 0.3
            
            # Cross-validate passport number on visa matches actual passport
            visa_passport_num = (visa_data.get("passport_number") or visa_data.get("document_number") or "").upper().strip()
            # Use passport_number field (document-specific ID)
            passport_num = (passport_data.get("passport_number") or "").upper().strip()
            if visa_passport_num and passport_num and visa_passport_num != passport_num:
                fraud_indicators.append({
                    "type": "passport_number_mismatch",
                    "severity": "critical",
                    "message": f"Passport number on visa '{visa_passport_num}' does not match actual passport '{passport_num}'",
                })
                risk_score += 0.5
            
            # Cross-validate nationality
            passport_nationality = (passport_data.get("nationality") or "").upper().strip()
            visa_nationality = (visa_data.get("nationality") or "").upper().strip()
            if passport_nationality and visa_nationality and passport_nationality != visa_nationality:
                fraud_indicators.append({
                    "type": "nationality_mismatch",
                    "severity": "medium",
                    "message": f"Nationality mismatch: passport '{passport_nationality}' vs visa '{visa_nationality}'",
                })
                risk_score += 0.2
        
        # Normalize risk score
        risk_score = min(1.0, risk_score)
        
        # Determine risk level
        if risk_score >= 0.7:
            risk_level = "critical"
        elif risk_score >= 0.4:
            risk_level = "high"
        elif risk_score >= 0.2:
            risk_level = "medium"
        else:
            risk_level = "low"
        
        # Generate recommendation
        if risk_level == "critical":
            recommendation = "REJECT: Critical fraud indicators detected. Manual review required."
        elif risk_level == "high":
            recommendation = "REJECT: High-risk indicators detected. Recommend rejection."
        elif risk_level == "medium":
            recommendation = "REVIEW: Medium-risk indicators present. Manual review recommended."
        else:
            recommendation = "PROCEED: Low risk. Safe to proceed with approval."
        
        return {
            "success": True,
            "fraud_detected": risk_level in ["high", "critical"],
            "risk_level": risk_level,
            "risk_score": risk_score,
            "fraud_indicators": fraud_indicators,
            "recommendation": recommendation,
            "details": {
                "total_indicators": len(fraud_indicators),
                "government_verified": government_verified,
                "ocr_confidence": ocr_confidence,
            },
        }
        
    except Exception as e:
        return {
            "success": False,
            "fraud_detected": False,
            "risk_level": "unknown",
            "risk_score": 0.0,
            "fraud_indicators": [],
            "recommendation": f"REVIEW: Fraud check failed with error: {str(e)}",
            "error": str(e),
        }

