from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from ..db import get_db, Base, engine
from ..models import Company, User
from ..schemas import CompanyCreate, CompanyUpdate, CompanyOut, CompanySimple, UserCreate, UserOut, SuperadminCreate, AdminUserUpdate, PaginatedResponse
from ..security import require_superadmin, SUPERADMIN_SYSTEM_TENANT
from ..auth import hash_password
from ..dependencies import get_pagination_params, PaginationParams

router = APIRouter(prefix="/superadmin/companies", tags=["Superadmin"])

# Create tables on import (demo convenience)
Base.metadata.create_all(bind=engine)


@router.post("", response_model=CompanyOut, dependencies=[Depends(require_superadmin)])
def create_company(payload: CompanyCreate, db: Session = Depends(get_db)):
    """
    Create a new company/tenant. Superadmin only.
    """
    # Prevent using the reserved superadmin tenant code
    if payload.tenant_code.upper() == SUPERADMIN_SYSTEM_TENANT.upper():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"The tenant code '{SUPERADMIN_SYSTEM_TENANT}' is reserved for system use and cannot be used for regular companies"
        )

    # slug_url default
    slug_url = payload.slug_url or f"https://service.local/{payload.tenant_code}"

    exists = db.query(Company).filter(
        (Company.tenant_code == payload.tenant_code) | (Company.slug_url == slug_url)
    ).first()

    if exists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="tenant_code or slug already exists"
        )

    c = Company(
        name=payload.name,
        tenant_code=payload.tenant_code,
        slug_url=slug_url,
        email=payload.email,
        phone=payload.phone,
        website=payload.website,
        address=payload.address,
        city=payload.city,
        state=payload.state,
        country=payload.country
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


@router.get("", response_model=PaginatedResponse[CompanyOut], dependencies=[Depends(require_superadmin)])
def list_companies(
    db: Session = Depends(get_db),
    pagination: PaginationParams = Depends(get_pagination_params),
):
    """
    List all companies with pagination. Superadmin only.
    - Supports pagination via page and size query parameters (default: page=1, size=10)
    """
    # Get total count
    total = db.query(Company).count()

    # Apply pagination
    offset = (pagination.page - 1) * pagination.size
    companies = db.query(Company).order_by(Company.created_at.desc()).offset(offset).limit(pagination.size).all()

    # Calculate total pages
    import math
    pages = math.ceil(total / pagination.size) if total > 0 else 0

    return PaginatedResponse(
        items=companies,
        total=total,
        page=pagination.page,
        size=pagination.size,
        pages=pages
    )


@router.get("/all", response_model=list[CompanySimple], dependencies=[Depends(require_superadmin)])
def list_all_companies_simple(
    db: Session = Depends(get_db)
):
    """
    List all companies without pagination, returning only id, name, and tenant_code.
    Useful for dropdowns and simple lists. Superadmin only.
    """
    companies = db.query(Company).order_by(Company.created_at.desc()).all()
    return companies


@router.get("/admins", response_model=PaginatedResponse[UserOut], dependencies=[Depends(require_superadmin)])
def list_all_company_admins(
    db: Session = Depends(get_db),
    pagination: PaginationParams = Depends(get_pagination_params),
):
    """
    List all admin users across all companies with their company names and pagination.
    Superadmin only.
    - Supports pagination via page and size query parameters (default: page=1, size=10)
    """
    # Get total count
    query = db.query(User).filter(User.role.in_(["admin", "superadmin"]))
    total = query.count()

    # Apply pagination
    offset = (pagination.page - 1) * pagination.size
    admins = query.order_by(User.created_at.desc()).offset(offset).limit(pagination.size).all()

    # Add company_name to each admin
    result = []
    for admin in admins:
        admin_dict = {
            "id": admin.id,
            "display_name": admin.display_name,
            "user_code": admin.user_code,
            "role": admin.role,
            "api_key": admin.api_key,
            # Convert empty string to None for proper validation
            "firstname": admin.firstname,
            "lastname": admin.lastname,
            "email": admin.email if admin.email else None,
            "contact_number": admin.contact_number,
            "profile_image": admin.profile_image,
            "company_name": admin.company.name if admin.company else None,
            "address": admin.address,
            "city": admin.city,
            "state": admin.state,
            "country": admin.country
        }
        result.append(admin_dict)

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


@router.get("/admins/{admin_id}", response_model=UserOut, dependencies=[Depends(require_superadmin)])
def get_admin_by_id(
    admin_id: int,
    db: Session = Depends(get_db)
):
    """
    Get a specific admin user by ID.
    Superadmin only.
    """
    admin = db.query(User).filter(
        User.id == admin_id,
        User.role.in_(["admin", "superadmin"])
    ).first()

    if not admin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Admin with ID {admin_id} not found"
        )

    # Add company_name to response
    admin_dict = {
        "id": admin.id,
        "display_name": admin.display_name,
        "user_code": admin.user_code,
        "role": admin.role,
        "api_key": admin.api_key,
        "firstname": admin.firstname,
        "lastname": admin.lastname,
        "email": admin.email if admin.email else None,
        "contact_number": admin.contact_number,
        "profile_image": admin.profile_image,
        "company_name": admin.company.name if admin.company else None,
        "address": admin.address,
        "city": admin.city,
        "state": admin.state,
        "country": admin.country,
        "is_active": admin.is_active
    }

    return admin_dict


@router.put("/admins/{admin_id}", response_model=UserOut, dependencies=[Depends(require_superadmin)])
def update_admin(
    admin_id: int,
    payload: AdminUserUpdate,
    db: Session = Depends(get_db)
):
    """
    Update an admin user's information.
    Superadmin only.

    Allows updating: display_name, role (between admin/superadmin), email,
    contact info, and is_active status.
    """
    admin = db.query(User).filter(
        User.id == admin_id,
        User.role.in_(["admin", "superadmin"])
    ).first()

    if not admin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Admin with ID {admin_id} not found"
        )

    # Prevent demoting the last superadmin
    if admin.role == "superadmin" and payload.role and payload.role != "superadmin":
        superadmin_count = db.query(User).filter(User.role == "superadmin").count()
        if superadmin_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot demote the last superadmin user"
            )

    # Check if email is being changed and if it's already taken
    if payload.email and payload.email != admin.email:
        existing = db.query(User).filter(
            User.email == payload.email,
            User.id != admin_id
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already in use by another user"
            )

    # Update fields if provided
    update_data = payload.dict(exclude_unset=True)
    for key, value in update_data.items():
        if hasattr(admin, key):
            setattr(admin, key, value)

    db.commit()
    db.refresh(admin)

    # Add company_name to response
    admin_dict = {
        "id": admin.id,
        "display_name": admin.display_name,
        "user_code": admin.user_code,
        "role": admin.role,
        "api_key": admin.api_key,
        "firstname": admin.firstname,
        "lastname": admin.lastname,
        "email": admin.email if admin.email else None,
        "contact_number": admin.contact_number,
        "profile_image": admin.profile_image,
        "company_name": admin.company.name if admin.company else None,
        "address": admin.address,
        "city": admin.city,
        "state": admin.state,
        "country": admin.country,
        "is_active": admin.is_active
    }

    return admin_dict


@router.delete("/admins/{admin_id}", dependencies=[Depends(require_superadmin)])
def delete_admin(
    admin_id: int,
    db: Session = Depends(get_db)
):
    """
    Delete an admin user.
    Superadmin only.

    WARNING: This will also delete all documents and websites uploaded by this admin.
    """
    admin = db.query(User).filter(
        User.id == admin_id,
        User.role.in_(["admin", "superadmin"])
    ).first()

    if not admin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Admin with ID {admin_id} not found"
        )

    # Prevent deleting the last superadmin
    if admin.role == "superadmin":
        superadmin_count = db.query(User).filter(User.role == "superadmin").count()
        if superadmin_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete the last superadmin user"
            )

    # Store admin info for response
    admin_user_code = admin.user_code
    admin_company = admin.company.name if admin.company else None

    # Delete the admin (cascade should handle related records)
    db.delete(admin)
    db.commit()

    return {
        "message": f"Admin user '{admin_user_code}' deleted successfully",
        "admin_id": admin_id,
        "user_code": admin_user_code,
        "company": admin_company
    }


@router.get("/{tenant_code}", response_model=CompanyOut, dependencies=[Depends(require_superadmin)])
def get_company(
    tenant_code: str,
    db: Session = Depends(get_db)
):
    """
    Get a specific company by tenant_code. Superadmin only.
    """
    company = db.query(Company).filter(Company.tenant_code == tenant_code).first()
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Company with tenant_code '{tenant_code}' not found"
        )
    return company


@router.put("/{tenant_code}", response_model=CompanyOut, dependencies=[Depends(require_superadmin)])
def update_company(
    tenant_code: str,
    payload: CompanyUpdate,
    db: Session = Depends(get_db)
):
    """
    Update a company's information. Superadmin only.
    """
    # Find the company
    company = db.query(Company).filter(Company.tenant_code == tenant_code).first()
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Company with tenant_code '{tenant_code}' not found"
        )

    # Prevent updating the reserved superadmin tenant
    if company.tenant_code.upper() == SUPERADMIN_SYSTEM_TENANT.upper():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"The system tenant '{SUPERADMIN_SYSTEM_TENANT}' cannot be updated"
        )

    # Check for slug_url uniqueness if being updated
    if payload.slug_url and payload.slug_url != company.slug_url:
        existing = db.query(Company).filter(
            Company.slug_url == payload.slug_url,
            Company.id != company.id
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="slug_url already exists for another company"
            )

    # Update fields that are provided
    update_data = payload.dict(exclude_unset=True)
    for key, value in update_data.items():
        if hasattr(company, key):
            setattr(company, key, value)

    db.commit()
    db.refresh(company)
    return company


@router.delete("/{tenant_code}", dependencies=[Depends(require_superadmin)])
def delete_company(
    tenant_code: str,
    db: Session = Depends(get_db)
):
    """
    Delete a company and all associated users. Superadmin only.
    WARNING: This is a destructive operation that will delete all users belonging to this company.
    Documents and websites remain in storage and Pinecone.
    """
    # Find the company
    company = db.query(Company).filter(Company.tenant_code == tenant_code).first()
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Company with tenant_code '{tenant_code}' not found"
        )

    # Prevent deleting the reserved superadmin tenant
    if company.tenant_code.upper() == SUPERADMIN_SYSTEM_TENANT.upper():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"The system tenant '{SUPERADMIN_SYSTEM_TENANT}' cannot be deleted"
        )

    # Count associated users for logging/warning
    user_count = db.query(User).filter(User.company_id == company.id).count()

    # Delete the company (cascade should handle users if configured in models)
    db.delete(company)
    db.commit()

    return {
        "message": f"Company '{tenant_code}' and {user_count} associated user(s) deleted successfully",
        "tenant_code": tenant_code,
        "users_deleted": user_count
    }


@router.post("/{tenant_code}/admin", response_model=UserOut, dependencies=[Depends(require_superadmin)])
def create_first_admin(
    tenant_code: str,
    payload: UserCreate,
    db: Session = Depends(get_db)
):
    """
    Create the first admin user for a company/tenant.
    This solves the chicken-and-egg problem of needing an admin to create users.
    Superadmin only.

    After creating this first admin, they can use /auth/register or /users endpoints
    to create additional users.
    """
    # Prevent creating regular users in the reserved superadmin tenant
    if tenant_code.upper() == SUPERADMIN_SYSTEM_TENANT.upper():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot create regular users in the reserved tenant '{SUPERADMIN_SYSTEM_TENANT}'. Use POST /superadmin/companies/superadmin to create superadmin users."
        )

    # Find the company
    company = db.query(Company).filter(Company.tenant_code == tenant_code).first()
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Company with tenant_code '{tenant_code}' not found"
        )

    # Ensure tenant_code in payload matches
    if payload.tenant_code != tenant_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Payload tenant_code must match URL tenant_code '{tenant_code}'"
        )

    # Ensure user_code starts with tenant_code
    if not payload.user_code.startswith(f"{tenant_code}-"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"user_code must start with '{tenant_code}-'"
        )

    # Force role to admin
    if payload.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This endpoint only creates admin users. Use role='admin'"
        )

    # Check if user already exists (by email or user_code)
    existing = db.query(User).filter(
        (User.user_code == payload.user_code) | (User.email == payload.email)
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User with this email or user_code already exists"
        )

    # Hash the password
    hashed_pass = hash_password(payload.password)

    # Create admin user with password (no API key)
    user = User(
        company_id=company.id,
        display_name=payload.display_name,
        user_code=payload.user_code,
        role="admin",
        hashed_password=hashed_pass,
        firstname=payload.firstname,
        lastname=payload.lastname,
        email=payload.email,
        contact_number=payload.contact_number,
        api_key=None,  # No API key for JWT users
        address=payload.address,
        city=payload.city,
        state=payload.state,
        country=payload.country
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return user


@router.post("/superadmin", response_model=UserOut, dependencies=[Depends(require_superadmin)])
def create_superadmin_user(
    payload: SuperadminCreate,
    db: Session = Depends(get_db)
):
    """
    Create a superadmin user.
    This endpoint is only accessible with token-based superadmin authentication
    (not JWT-based), to bootstrap the first superadmin user.

    Superadmin users have system-wide privileges including:
    - Creating and managing companies
    - Creating admin users for any company
    - All capabilities of the superadmin token

    Superadmin users automatically belong to a reserved system company with
    tenant_code '{SUPERADMIN_SYSTEM_TENANT}' which cannot be used by regular companies.
    The system company is auto-created if it doesn't exist.
    """
    # Ensure the reserved system company exists
    company = db.query(Company).filter(Company.tenant_code == SUPERADMIN_SYSTEM_TENANT).first()
    if not company:
        # Auto-create the system company for superadmin users
        company = Company(
            name="System Administration",
            tenant_code=SUPERADMIN_SYSTEM_TENANT,
            slug_url=f"https://service.local/{SUPERADMIN_SYSTEM_TENANT.lower()}",
            email="system@admin.local",
            phone=None,
            website=None,
            address="System Reserved"
        )
        db.add(company)
        db.commit()
        db.refresh(company)

    # Check if user_code starts with the system tenant prefix
    expected_prefix = f"{SUPERADMIN_SYSTEM_TENANT}-"
    if not payload.user_code.startswith(expected_prefix):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Superadmin user_code must start with '{expected_prefix}'"
        )

    # Check if user already exists (by email or user_code)
    existing = db.query(User).filter(
        (User.user_code == payload.user_code) | (User.email == payload.email)
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User with this email or user_code already exists"
        )

    # Hash the password
    hashed_pass = hash_password(payload.password)

    # Create superadmin user with password (no API key)
    user = User(
        company_id=company.id,
        display_name=payload.display_name,
        user_code=payload.user_code,
        role="superadmin",
        hashed_password=hashed_pass,
        firstname=payload.firstname,
        lastname=payload.lastname,
        email=payload.email,
        contact_number=payload.contact_number,
        api_key=None,  # No API key for JWT users
        address=payload.address,
        city=payload.city,
        state=payload.state,
        country=payload.country
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return user
