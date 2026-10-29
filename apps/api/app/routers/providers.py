from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..llm import PROTOCOL_LABELS, capabilities_for, get_adapter
from ..models import AuditEvent, Project, Provider, utcnow
from ..schemas import ProviderCreate, ProviderOut, ProviderTestOut, ProviderUpdate
from ..security import encrypt_secret
from .common import provider_out

router = APIRouter(prefix="/providers", tags=["providers"])


def _get_provider(db: Session, provider_id: str) -> Provider:
    provider = db.get(Provider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="模型配置不存在")
    return provider


@router.get("", response_model=list[ProviderOut])
def list_providers(db: Session = Depends(get_db)):
    providers = db.scalars(select(Provider).order_by(Provider.created_at.desc())).all()
    return [provider_out(provider) for provider in providers]


@router.get("/meta")
def provider_meta():
    return {
        "protocols": [
            {"value": key, "label": label, "capabilities": capabilities_for(key)}
            for key, label in PROTOCOL_LABELS.items()
        ]
    }


@router.post("", response_model=ProviderOut, status_code=201)
def create_provider(payload: ProviderCreate, db: Session = Depends(get_db)):
    if not payload.base_url.strip() or not payload.model_id.strip():
        raise HTTPException(status_code=400, detail="Base URL 与 Model ID 不能为空")
    provider = Provider(
        name=payload.name.strip(),
        protocol=payload.protocol,
        base_url=payload.base_url.strip(),
        model_id=payload.model_id.strip(),
        api_version=payload.api_version.strip(),
        api_key_encrypted=encrypt_secret(payload.api_key.strip()),
        params=payload.params,
        capabilities=capabilities_for(payload.protocol),
        enabled=payload.enabled,
    )
    db.add(provider)
    db.commit()
    db.refresh(provider)
    db.add(
        AuditEvent(
            project_id=None,
            action="provider.create",
            detail={"provider_id": provider.id, "protocol": provider.protocol},
        )
    )
    db.commit()
    return provider_out(provider)


@router.get("/{provider_id}", response_model=ProviderOut)
def get_provider(provider_id: str, db: Session = Depends(get_db)):
    return provider_out(_get_provider(db, provider_id))


@router.patch("/{provider_id}", response_model=ProviderOut)
def update_provider(provider_id: str, payload: ProviderUpdate, db: Session = Depends(get_db)):
    provider = _get_provider(db, provider_id)
    data = payload.model_dump(exclude_unset=True)
    api_key = data.pop("api_key", None)
    if api_key is not None and str(api_key).strip():
        provider.api_key_encrypted = encrypt_secret(str(api_key).strip())
    for key, value in data.items():
        setattr(provider, key, value)
    if "protocol" in data:
        provider.capabilities = capabilities_for(provider.protocol)
    db.add(provider)
    db.add(
        AuditEvent(
            project_id=None,
            action="provider.update",
            detail={"provider_id": provider.id, "fields": list(data.keys())},
        )
    )
    db.commit()
    db.refresh(provider)
    return provider_out(provider)


@router.delete("/{provider_id}", status_code=204)
def delete_provider(provider_id: str, db: Session = Depends(get_db)):
    provider = _get_provider(db, provider_id)
    for project in db.scalars(select(Project).where(Project.provider_id == provider.id)).all():
        project.provider_id = None
        db.add(project)
    db.delete(provider)
    db.add(
        AuditEvent(
            project_id=None,
            action="provider.delete",
            detail={"provider_id": provider_id},
        )
    )
    db.commit()
    return None


@router.post("/{provider_id}/test", response_model=ProviderTestOut)
def test_provider(
    provider_id: str,
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
):
    provider = _get_provider(db, provider_id)
    try:
        adapter = get_adapter(provider)
        result = adapter.test_connection(json_mode=bool(payload.get("json_mode")))
    except Exception as exc:
        result = {
            "ok": False,
            "latency_ms": 0,
            "text": "",
            "model": provider.model_id,
            "warnings": [],
            "error_code": "INVALID_REQUEST",
            "error_message": str(exc),
        }
    provider.last_test_status = "ok" if result["ok"] else "error"
    provider.last_test_error = "" if result["ok"] else f"{result['error_code']}: {result['error_message']}"[:1000]
    provider.last_tested_at = utcnow()
    db.add(provider)
    db.commit()
    return ProviderTestOut(**result)
