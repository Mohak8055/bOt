from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import Company
from ..schemas import QueryRequest, QueryAnswer
from ..security import require_superadmin
from ..rag import search, synthesize_answer
from ..auth import get_current_user
from .. import models
import secrets

router = APIRouter(prefix="/widget", tags=["Widget"])

@router.get("/{tenant_code}/key", dependencies=[Depends(require_superadmin)])
def get_widget_key(
    tenant_code: str,
    db: Session = Depends(get_db)
):
    """
    Get or generate the widget key for a company. Superadmin only.
    This key allows the embeddable widget to query company data.
    """
    company = db.query(Company).filter(Company.tenant_code == tenant_code).first()
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Company with tenant_code '{tenant_code}' not found"
        )

    # Generate widget key if not exists
    if not company.widget_key:
        company.widget_key = f"wk_{secrets.token_urlsafe(32)}"
        db.commit()
        db.refresh(company)

    return {
        "tenant_code": tenant_code,
        "widget_key": company.widget_key,
        "company_name": company.name
    }

@router.post("/{tenant_code}/regenerate", dependencies=[Depends(require_superadmin)])
def regenerate_widget_key(
    tenant_code: str,
    db: Session = Depends(get_db)
):
    """
    Regenerate the widget key for a company. Superadmin only.
    WARNING: This will invalidate the existing widget embedded on websites.
    """
    company = db.query(Company).filter(Company.tenant_code == tenant_code).first()
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Company with tenant_code '{tenant_code}' not found"
        )

    # Regenerate widget key
    company.widget_key = f"wk_{secrets.token_urlsafe(32)}"
    db.commit()
    db.refresh(company)

    return {
        "tenant_code": tenant_code,
        "widget_key": company.widget_key,
        "company_name": company.name,
        "message": "Widget key regenerated successfully"
    }

@router.post("/query", response_model=QueryAnswer)
def widget_query(
    payload: QueryRequest,
    widget_key: str,
    db: Session = Depends(get_db)
):
    """
    Public endpoint for embeddable widget to query company data.
    Requires widget_key as a query parameter or header.
    Sources are hidden from widget users for privacy.
    """
    # Find company by widget key
    company = db.query(Company).filter(Company.widget_key == widget_key).first()
    if not company:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid widget key"
        )

    # Validate source_type
    if payload.source_type not in ["all", "documents", "websites"]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid source_type '{payload.source_type}'. Must be 'all', 'documents', or 'websites'."
        )

    # Search in company's namespace
    matches = search(
        tenant_code=company.tenant_code,
        query=payload.question,
        top_k=payload.top_k,
        filter_user_code=None,  # Widget searches all company data
        source_type=payload.source_type,
        min_score=payload.min_score
    )

    if not matches:
        return QueryAnswer(
            answer="Apologies! I don't have enough information to answer this question. The available content may not be relevant to your query.",
            sources=[]
        )

    contexts = [m.metadata.get("text", "") for m in matches if m.metadata]

    # Widget query does not expose sources to users for privacy
    answer = synthesize_answer(payload.question, contexts)
    return QueryAnswer(answer=answer, sources=[])


@router.post("/superadmin/query/{tenant_code}", response_model=QueryAnswer, dependencies=[Depends(require_superadmin)])
def superadmin_company_query(
    tenant_code: str,
    payload: QueryRequest,
    db: Session = Depends(get_db)
):
    """
    Super-admin endpoint to query any company's data by tenant_code.
    This allows super-admin to test and interact with company chatbots.
    """
    # Verify company exists
    company = db.query(Company).filter(Company.tenant_code == tenant_code).first()
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Company with tenant_code '{tenant_code}' not found"
        )

    # Validate source_type
    if payload.source_type not in ["all", "documents", "websites"]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid source_type '{payload.source_type}'. Must be 'all', 'documents', or 'websites'."
        )

    # Search in company's namespace
    matches = search(
        tenant_code=tenant_code,
        query=payload.question,
        top_k=payload.top_k,
        filter_user_code=None,  # Super-admin searches all company data
        source_type=payload.source_type,
        min_score=payload.min_score
    )

    if not matches:
        return QueryAnswer(
            answer="Apologies! I don't have enough information to answer this question. The available content may not be relevant to your query.",
            sources=[]
        )

    contexts = [m.metadata.get("text", "") for m in matches if m.metadata]

    # Handle both document and website sources
    sources = []
    for m in matches:
        if m.metadata:
            source_type = m.metadata.get("source_type", "document")
            if source_type == "website":
                sources.append(m.metadata.get("url", "unknown"))
            else:
                sources.append(m.metadata.get("doc", "unknown"))

    answer = synthesize_answer(payload.question, contexts)
    return QueryAnswer(answer=answer, sources=sources[:payload.top_k])
