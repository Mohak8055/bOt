import os,mimetypes
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import Document # We get the User model from 'models'
from .. import models          # <--- 1. Import 'models'
from ..schemas import UploadResponse, BatchUploadResponse, DocumentOut, DocumentRetryRequest, DocumentRetryResponse, PaginatedResponse
from typing import List, Optional
from ..rag import document_to_pinecone, delete_document_vectors
from ..auth import get_current_user  # <--- 2. Import your new auth function
from ..security import require_superadmin  # Import superadmin auth
from ..dependencies import get_pagination_params, PaginationParams

# --- 3. REMOVED old auth imports (require_caller, require_admin, Caller) ---

UPLOAD_DIR = "uploaded_documents"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Background task to process document
def process_document_background(document_id: int, file_path: str, tenant_code: str, user_code: str, filename: str):
    """
    Background task to process a document and update its status.
    This allows immediate response to user while processing happens asynchronously.
    """
    from ..db import SessionLocal

    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == document_id).first()
        if not doc:
            print(f"ERROR: Document {document_id} not found for processing")
            return

        # Update status to processing
        doc.status = "processing"
        db.commit()

        try:
            # Process the document
            chunks = document_to_pinecone(file_path, tenant_code, user_code, filename)

            # Update status to completed
            doc.status = "completed"
            doc.num_chunks = chunks
            doc.error_message = None
            db.commit()
            print(f"INFO: Successfully processed document {document_id} ({filename}): {chunks} chunks")

        except Exception as e:
            # Update status to error
            doc.status = "error"
            doc.error_message = str(e)
            db.commit()
            print(f"ERROR: Failed to process document {document_id} ({filename}): {e}")

    except Exception as e:
        print(f"ERROR: Background processing failed for document {document_id}: {e}")
    finally:
        db.close()

# Supported file extensions
SUPPORTED_EXTENSIONS = {
    '.pdf', '.docx', '.doc', '.xlsx', '.xls',
    '.pptx', '.ppt', '.txt', '.csv', '.md',
    '.rst', '.log'
}

# Helper function to find document path
def get_document_path(filename: str) -> str:
    """
    Find the document file path, checking both new and legacy directories.
    Returns the full path to the document file.
    """
    # Check in the current upload directory first
    path = os.path.join(UPLOAD_DIR, filename)
    if os.path.exists(path):
        return path

    # Check legacy directory if it exists
    legacy_dir = "uploaded_pdfs"
    legacy_path = os.path.join(legacy_dir, filename)
    if os.path.exists(legacy_path):
        return legacy_path

    # Return the expected path even if file doesn't exist
    # (the calling code will handle the 404)
    return path

router = APIRouter(prefix="/documents", tags=["Documents"])

@router.post("/upload", response_model=BatchUploadResponse)
def upload_documents(
    files: List[UploadFile] = File(...),
    background_tasks: BackgroundTasks = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Upload one or multiple documents. Processing happens in the background.
    Returns immediately with status "pending" for each document.
    Use GET /documents to check processing status.
    """
    results = []
    errors = []
    accepted = 0

    for file in files:
        try:
            # Validate file extension
            if not file.filename:
                errors.append({"filename": "unknown", "error": "Filename is required"})
                continue

            file_ext = os.path.splitext(file.filename.lower())[1]
            if file_ext not in SUPPORTED_EXTENSIONS:
                errors.append({
                    "filename": file.filename,
                    "error": f"Unsupported file type. Supported types: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
                })
                continue

            # Generate unique filename
            user_suffix = current_user.user_code.split('-', 1)[1] if '-' in current_user.user_code else current_user.user_code
            unique_id = uuid.uuid4().hex[:8]
            stored_name = f"{current_user.company.tenant_code}_{user_suffix}_{unique_id}{file_ext}"
            path = os.path.join(UPLOAD_DIR, stored_name)

            # Save file to disk
            content = file.file.read()
            with open(path, "wb") as f:
                f.write(content)

            # Create document record with "pending" status
            doc = Document(
                company_id=current_user.company_id,
                uploader_id=current_user.id,
                tenant_code=current_user.company.tenant_code,
                user_code=current_user.user_code,
                filename=stored_name,
                original_name=file.filename,
                mime_type=file.content_type or "application/octet-stream",
                status="pending",  # Start with pending status
            )
            db.add(doc)
            db.commit()
            db.refresh(doc)

            # Schedule background processing
            if background_tasks:
                background_tasks.add_task(
                    process_document_background,
                    doc.id,
                    path,
                    current_user.company.tenant_code,
                    current_user.user_code,
                    stored_name
                )

            results.append(UploadResponse(
                document_id=doc.id,
                stored_filename=stored_name,
                chunks_indexed=0,
                status="pending"
            ))
            accepted += 1

        except Exception as e:
            errors.append({
                "filename": file.filename if file.filename else "unknown",
                "error": str(e)
            })

    return BatchUploadResponse(
        results=results,
        total=len(files),
        accepted=accepted,
        errors=errors
    )


@router.post("/retry", response_model=DocumentRetryResponse)
def retry_failed_documents(
    payload: DocumentRetryRequest,
    background_tasks: BackgroundTasks = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Retry processing for failed document uploads.
    Only processes documents with status="error" that belong to the current user's tenant.
    Admins can retry any document in their tenant, regular users can only retry their own documents.
    """
    retried = []
    skipped = []

    for doc_id in payload.document_ids:
        try:
            # Get the document
            doc = db.query(Document).filter(Document.id == doc_id).first()

            if not doc:
                skipped.append({
                    "document_id": doc_id,
                    "reason": "Document not found"
                })
                continue

            # Check tenant isolation
            if doc.company_id != current_user.company_id:
                skipped.append({
                    "document_id": doc_id,
                    "reason": "Access denied: Document belongs to a different tenant"
                })
                continue

            # Check authorization: owner or admin can retry
            if doc.uploader_id != current_user.id and current_user.role not in ["admin", "superadmin"]:
                skipped.append({
                    "document_id": doc_id,
                    "reason": "Access denied: You can only retry your own documents unless you are an admin"
                })
                continue

            # Only retry documents with error status
            if doc.status != "error":
                skipped.append({
                    "document_id": doc_id,
                    "reason": f"Document status is '{doc.status}', can only retry documents with 'error' status"
                })
                continue

            # Check if file exists
            file_path = get_document_path(doc.filename)
            if not os.path.exists(file_path):
                skipped.append({
                    "document_id": doc_id,
                    "reason": "Document file not found on server"
                })
                continue

            # Reset status to pending
            doc.status = "pending"
            doc.error_message = None
            doc.num_chunks = 0
            db.commit()

            # Schedule background reprocessing
            if background_tasks:
                background_tasks.add_task(
                    process_document_background,
                    doc.id,
                    file_path,
                    doc.tenant_code,
                    doc.user_code,
                    doc.filename
                )

            retried.append({
                "document_id": doc.id,
                "filename": doc.original_name,
                "status": "pending"
            })

        except Exception as e:
            skipped.append({
                "document_id": doc_id,
                "reason": f"Error: {str(e)}"
            })

    return DocumentRetryResponse(
        retried=retried,
        skipped=skipped,
        total=len(payload.document_ids),
        retried_count=len(retried),
        skipped_count=len(skipped)
    )


@router.get("", response_model=PaginatedResponse[DocumentOut])
def list_documents(
    # --- 6. USE new dependency ---
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
    my_docs_only: bool = False,
    pagination: PaginationParams = Depends(get_pagination_params),
):
    """
    List documents in the tenant with pagination.
    - Admins can see all documents in their tenant
    - Regular users can see all tenant docs by default, or set my_docs_only=true to see only their uploads
    - Supports pagination via page and size query parameters (default: page=1, size=10)
    """
    # --- 7. UPDATE logic to use 'current_user' ---
    query = db.query(Document).filter(Document.company_id == current_user.company_id) # <-- Changed

    # If user wants only their documents or if they're not an admin
    if my_docs_only or current_user.role not in ["admin", "superadmin"]: # <-- Changed
        query = query.filter(Document.uploader_id == current_user.id) # <-- Changed

    # Get total count
    total = query.count()

    # Apply pagination
    offset = (pagination.page - 1) * pagination.size
    documents = query.order_by(Document.created_at.desc()).offset(offset).limit(pagination.size).all()

    # Add filepath, user name, and company name to each document
    result = []
    for doc in documents:
        doc_dict = {
            "id": doc.id,
            "filename": doc.filename,
            "original_name": doc.original_name,
            "filepath": os.path.join(UPLOAD_DIR, doc.filename),
            "uploader_id": doc.uploader_id,
            "user_code": doc.user_code,
            "user_name": doc.uploader.display_name if doc.uploader else None,
            "company_name": doc.uploader.company.name if doc.uploader and doc.uploader.company else None,
            "num_chunks": doc.num_chunks,
            "status": doc.status,
            "created_at": doc.created_at,
            "error_message": doc.error_message
        }
        result.append(doc_dict)

    # Calculate total pages
    import math
    pages = math.ceil(total / pagination.size) if total > 0 else 0

    return PaginatedResponse(
        items=result,
        total=total,
        page=pagination.page,
        size=pagination.size,
        pages=pages
    )

@router.delete("/{document_id}")
def delete_document(
    document_id: int,
    # --- 8. USE new dependency ---
    current_user: models.User = Depends(get_current_user), 
    db: Session = Depends(get_db),
):
    """
    Delete a document. Users can only delete their own documents, admins can delete any document in their tenant.
    """
    doc = db.query(Document).filter(Document.id == document_id).first()

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # --- 9. UPDATE logic to use 'current_user' ---
    # Check tenant isolation
    if doc.company_id != current_user.company_id: # <-- Changed
        raise HTTPException(
            status_code=403,
            detail="Access denied: This document belongs to a different tenant"
        )

    # Check authorization: owner or admin can delete
    if doc.uploader_id != current_user.id and current_user.role not in ["admin", "superadmin"]: # <-- Changed
        raise HTTPException(
            status_code=403,
            detail="Access denied: You can only delete your own documents unless you are an admin"
        )

    # Delete vectors from Pinecone first
    try:
        deleted_vectors = delete_document_vectors(doc.tenant_code, doc.filename)
        print(f"INFO: Deleted {deleted_vectors} vectors from Pinecone for document {doc.filename}")
    except Exception as e:
        print(f"WARNING: Failed to delete vectors from Pinecone: {e}")
        # Continue with deletion even if Pinecone cleanup fails

    # Delete the physical file
    file_path = os.path.join(UPLOAD_DIR, doc.filename)
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception as e:
            # Log but don't fail if file deletion fails
            print(f"Warning: Could not delete file {file_path}: {e}")

    # Delete from database
    db.delete(doc)
    db.commit()

    return {"message": "Document deleted successfully", "document_id": document_id}


@router.get("/{document_id}/download")
def download_document(
    document_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Download a document.
    Users can download documents in their tenant. Admins can download any document in their tenant.
    """
    doc = db.query(Document).filter(Document.id == document_id).first()

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Check tenant isolation
    if doc.company_id != current_user.company_id:
        raise HTTPException(
            status_code=403,
            detail="Access denied: This document belongs to a different tenant"
        )

    # Find the file in the correct directory
    file_path = get_document_path(doc.filename)

    mime_type, _ = mimetypes.guess_type(file_path)
    if not mime_type:
        mime_type = "application/octet-stream"

    # Debug logging
    print(f"DEBUG - Download request (normal user):")
    print(f"  Document ID: {document_id}")
    print(f"  Filename: {doc.filename}")
    print(f"  UPLOAD_DIR: {UPLOAD_DIR}")
    print(f"  Found path: {file_path}")

    # Check if file exists
    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=404,
            detail="Document file not found on server"
        )

    # Return file for download
    return FileResponse(
        path=file_path,
        filename=doc.original_name,  # Use original filename for download
        media_type=mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{doc.original_name}"',
        }
    )


@router.get("/superadmin/all", response_model=PaginatedResponse[DocumentOut], dependencies=[Depends(require_superadmin)])
def list_all_documents_superadmin(
    db: Session = Depends(get_db),
    tenant_code: Optional[str] = None,
    pagination: PaginationParams = Depends(get_pagination_params),
):
    """
    List all documents across all companies with pagination. Superadmin only.

    Query Parameters:
    - tenant_code: Optional filter to show documents from a specific company by tenant code
    - page: Page number (default: 1)
    - size: Page size (default: 10, max: 100)
    """
    query = db.query(Document)

    # Filter by tenant code if provided
    if tenant_code:
        query = query.join(Document.uploader).join(models.User.company).filter(
            models.Company.tenant_code == tenant_code
        )

    # Get total count
    total = query.count()

    # Apply pagination
    offset = (pagination.page - 1) * pagination.size
    documents = query.order_by(Document.created_at.desc()).offset(offset).limit(pagination.size).all()

    # Build response with user name and company name
    result = []
    for doc in documents:
        doc_dict = {
            "id": doc.id,
            "filename": doc.filename,
            "original_name": doc.original_name,
            "filepath": os.path.join(UPLOAD_DIR, doc.filename),
            "uploader_id": doc.uploader_id,
            "user_code": doc.user_code,
            "user_name": doc.uploader.display_name if doc.uploader else None,
            "company_name": doc.uploader.company.name if doc.uploader and doc.uploader.company else None,
            "num_chunks": doc.num_chunks,
            "status": doc.status,
            "created_at": doc.created_at,
            "error_message": doc.error_message
        }
        result.append(doc_dict)

    # Calculate total pages
    import math
    pages = math.ceil(total / pagination.size) if total > 0 else 0

    return PaginatedResponse(
        items=result,
        total=total,
        page=pagination.page,
        size=pagination.size,
        pages=pages
    )


@router.get("/superadmin/{document_id}/download", dependencies=[Depends(require_superadmin)])
def download_document_superadmin(
    document_id: int,
    db: Session = Depends(get_db),
):
    """
    Download any document. Superadmin only.
    Allows superadmin to download documents from any company.
    """
    doc = db.query(Document).filter(Document.id == document_id).first()

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Find the file in the correct directory
    file_path = get_document_path(doc.filename)

    # Guess MIME type based on file extension
    mime_type, _ = mimetypes.guess_type(file_path)
    if not mime_type:
        mime_type = "application/octet-stream"

    # Debug logging
    print(f"DEBUG - Download request (superadmin):")
    print(f"  Document ID: {document_id}")
    print(f"  Filename: {doc.filename}")
    print(f"  UPLOAD_DIR: {UPLOAD_DIR}")
    print(f"  Found path: {file_path}")

    # Check if file exists
    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=404,
            detail="Document file not found on server"
        )

    # Return file for download
    return FileResponse(
        path=file_path,
        filename=doc.original_name,  # Use original filename for download
        media_type=mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{doc.original_name}"',
        }
    )

