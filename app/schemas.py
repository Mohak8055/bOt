from pydantic import BaseModel, Field, EmailStr, field_validator
from typing import Optional, List, Generic, TypeVar
from datetime import datetime

# Generic type for paginated responses
T = TypeVar('T')

class CompanyCreate(BaseModel):
    name: str
    tenant_code: str
    slug_url: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None

class CompanyUpdate(BaseModel):
    """Schema for updating company information."""
    name: Optional[str] = None
    slug_url: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None

    class Config:
        from_attributes = True

class CompanyOut(BaseModel):
    id: int
    name: str
    tenant_code: str
    slug_url: str
    widget_key: Optional[str] = None

    email: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None

    class Config:
        from_attributes = True

class CompanySimple(BaseModel):
    """Simple company schema with only essential fields for dropdowns/lists."""
    id: int
    name: str
    tenant_code: str

    class Config:
        from_attributes = True

class UserBase(BaseModel):
    display_name: str
    user_code: str
    role: str = Field(pattern="^(superadmin|admin|user)$")

    # --- FIELD ADDED ---
    # Added email to base, as it's common
    email: EmailStr


class UserCreate(BaseModel):
    tenant_code: str
    display_name: str
    user_code: str
    role: str = Field(pattern="^(superadmin|admin|user)$")

     # NEW FIELDS
    email: EmailStr  # <--- 2. CHANGED to EmailStr for consistency
    contact_number: Optional[str] = None
    # website: Optional[str] = None

    # --- FIELD ADDED FOR AUTH ---
    # Add password field for registration
    password: str
    firstname: Optional[str] = None
    lastname: Optional[str] = None
    contact_number: Optional[str] = None
    address: Optional[str] = None # Deprecated
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None

class UserOut(BaseModel):
    id: int
    display_name: str
    user_code: str
    role: str

    # --- FIELD MODIFIED FOR AUTH ---
    # Made api_key optional, as password-users might not have one
    api_key: Optional[str] = None

    # NEW FIELDS
    # Made email optional to handle older records with empty/null email values
    email: Optional[EmailStr] = None
    firstname: Optional[str] = None
    lastname: Optional[str] = None
    contact_number: Optional[str] = None
    profile_image: Optional[str] = None
    company_name: Optional[str] = None  # Added for list users response
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    is_active: bool = True

    class Config:
        from_attributes = True


class UserUpdate(BaseModel):
    """Schema for updating user profile information."""
    display_name: Optional[str] = None
    email: Optional[str] = None
    firstname: Optional[str] = None
    lastname: Optional[str] = None
    contact_number: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None

    @field_validator('*', mode='before')
    @classmethod
    def empty_str_to_none(cls, v):
        """Convert empty strings to None for all fields."""
        if isinstance(v, str) and v.strip() == '':
            return None
        return v

    class Config:
        from_attributes = True


# --- NEW SCHEMA ADDED FOR ADMIN UPDATES ---
class AdminUserUpdate(BaseModel):
    """Schema for superadmin updating admin/user profile information."""
    display_name: Optional[str] = None
    role: Optional[str] = Field(None, pattern="^(superadmin|admin|user)$") # Allow role changes including superadmin
    email: Optional[EmailStr] = None
    firstname: Optional[str] = None
    lastname: Optional[str] = None
    contact_number: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    is_active: Optional[bool] = None # Optional: Allow admin to activate/deactivate

    # Note: Password changes should go through the reset flow.

    class Config:
        from_attributes = True
# --- END OF NEW SCHEMA ---


# --- NEW SCHEMAS ADDED FOR AUTHENTICATION ---

class Token(BaseModel):
    """Schema for the login response."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class TokenData(BaseModel):
    """Schema for the data encoded in the JWT."""
    sub: str # 'sub' is standard for 'subject', we'll use user's email
    type: str # We'll use this to differentiate 'access' vs 'refresh'

class PasswordResetRequest(BaseModel):
    """Schema for requesting a password reset."""
    email: EmailStr

class PasswordResetConfirm(BaseModel):
    """Schema for confirming the password reset."""
    new_password: str

class SuperadminCreate(BaseModel):
    """Schema for creating a superadmin user. Does not require tenant_code as it uses a reserved system tenant."""
    display_name: str
    user_code: str
    email: EmailStr
    password: str
    firstname: Optional[str] = None
    lastname: Optional[str] = None
    address: Optional[str] = None
    contact_number: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None

# --- END OF NEW SCHEMAS ---


class UploadResponse(BaseModel):
    document_id: int
    stored_filename: str
    chunks_indexed: int
    status: str = "pending"  # New field to track processing status

class BatchUploadResponse(BaseModel):
    """Response for batch document uploads."""
    results: List[UploadResponse]
    total: int
    accepted: int  # Number of files accepted for processing
    errors: List[dict]  # List of {"filename": str, "error": str}

class DocumentRetryRequest(BaseModel):
    """Request schema for retrying failed document uploads."""
    document_ids: List[int] = Field(..., min_items=1, description="List of document IDs to retry")

class DocumentRetryResponse(BaseModel):
    """Response schema for retry operation."""
    retried: List[dict]  # List of {"document_id": int, "filename": str, "status": str}
    skipped: List[dict]  # List of {"document_id": int, "reason": str}
    total: int
    retried_count: int
    skipped_count: int

class QueryRequest(BaseModel):
    question: str
    top_k: int = 15
    user_filter: bool = False  # if True, filter by uploader user_code too
    source_type: str = "all"  # "all", "documents", or "websites" - filter by source type
    min_score: float = 0.2  # Minimum similarity score (0.0-1.0). Results below this are filtered out as irrelevant

class QueryAnswer(BaseModel):
    answer: str
    sources: List[str]

class DocumentOut(BaseModel):
    id: int
    filename: str
    original_name: str
    filepath: str  # Full path to the document file for download
    uploader_id: int
    user_code: str  # Added user_code field
    user_name: Optional[str] = None  # Display name of the uploader
    company_name: Optional[str] = None  # Company name of the uploader
    num_chunks: int
    status: str
    created_at: datetime
    error_message: Optional[str] = None
    class Config:
        from_attributes = True

class WebsiteSubmit(BaseModel):
    url: str

class WebsiteSubmitBatch(BaseModel):
    """Schema for submitting multiple websites at once."""
    urls: List[str]

class WebsiteResponse(BaseModel):
    website_id: int
    url: str
    title: str
    chunks_indexed: int

class WebsiteBatchResponse(BaseModel):
    """Response for batch website scraping."""
    results: List[WebsiteResponse]
    total: int
    successful: int
    failed: int
    errors: List[dict]  # List of {"url": str, "error": str}

class WebsiteOut(BaseModel):
    id: int
    url: str
    title: Optional[str]
    uploader_id: int
    user_code: str  # Added user_code field
    user_name: Optional[str] = None  # Display name of the uploader
    company_name: Optional[str] = None  # Company name of the uploader
    num_chunks: int
    status: str
    created_at: datetime
    error_message: Optional[str] = None
    class Config:
        from_attributes = True

class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response schema."""
    items: List[T]
    total: int
    page: int
    size: int
    pages: int

    class Config:
        from_attributes = True
