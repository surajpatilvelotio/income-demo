"""Document storage service for file uploads."""

import os
import uuid
from pathlib import Path
from typing import BinaryIO

from app.config import settings


class DocumentStorageService:
    """Service for handling document file storage."""

    def __init__(self, base_dir: str | None = None):
        """
        Initialize document storage service.
        
        Args:
            base_dir: Base directory for file storage. Defaults to settings.upload_dir
        """
        self.base_dir = Path(base_dir or settings.upload_dir)
        self._ensure_base_dir()

    def _ensure_base_dir(self) -> None:
        """Create base directory if it doesn't exist."""
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _get_application_dir(self, application_id: str) -> Path:
        """Get or create directory for an application's documents."""
        app_dir = self.base_dir / application_id
        app_dir.mkdir(parents=True, exist_ok=True)
        return app_dir

    def save_document(
        self,
        application_id: str,
        file: BinaryIO,
        original_filename: str,
        document_type: str,
    ) -> tuple[str, str]:
        """
        Save an uploaded document.
        
        Args:
            application_id: ID of the KYC application
            file: File-like object containing the document data
            original_filename: Original name of the uploaded file
            document_type: Type of document (id_card, passport)
            
        Returns:
            Tuple of (file_path, generated_filename)
        """
        app_dir = self._get_application_dir(application_id)
        
        # Generate unique filename with original extension
        ext = Path(original_filename).suffix.lower()
        generated_filename = f"{document_type}_{uuid.uuid4().hex}{ext}"
        file_path = app_dir / generated_filename
        
        # Write file content
        with open(file_path, "wb") as f:
            content = file.read()
            f.write(content)
        
        return str(file_path), generated_filename

    def get_document_path(self, application_id: str, filename: str) -> Path | None:
        """
        Get the full path to a document.
        
        Args:
            application_id: ID of the KYC application
            filename: Name of the file
            
        Returns:
            Path to the document or None if not found
        """
        file_path = self.base_dir / application_id / filename
        if file_path.exists():
            return file_path
        return None

    def read_document(self, file_path: str) -> bytes | None:
        """
        Read document content from a file path.
        
        Args:
            file_path: Path to the document
            
        Returns:
            Document content as bytes or None if not found
        """
        path = Path(file_path)
        if path.exists():
            with open(path, "rb") as f:
                return f.read()
        return None

    def delete_document(self, file_path: str) -> bool:
        """
        Delete a document.
        
        Args:
            file_path: Path to the document
            
        Returns:
            True if deleted, False if not found
        """
        path = Path(file_path)
        if path.exists():
            os.remove(path)
            return True
        return False

    def delete_application_documents(self, application_id: str) -> bool:
        """
        Delete all documents for an application.
        
        Args:
            application_id: ID of the KYC application
            
        Returns:
            True if directory was deleted, False otherwise
        """
        import shutil
        
        app_dir = self.base_dir / application_id
        if app_dir.exists():
            shutil.rmtree(app_dir)
            return True
        return False


# Default instance
document_storage = DocumentStorageService()

