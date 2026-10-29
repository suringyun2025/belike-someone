from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Export, Project
from ..schemas import ExportOut

router = APIRouter(tags=["exports"])


@router.get("/projects/{project_id}/exports", response_model=list[ExportOut])
def list_exports(project_id: str, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="项目不存在")
    exports = db.scalars(
        select(Export).where(Export.project_id == project_id).order_by(Export.created_at.desc())
    ).all()
    return [ExportOut.model_validate(export) for export in exports]


@router.get("/exports/{export_id}", response_model=ExportOut)
def get_export(export_id: str, db: Session = Depends(get_db)):
    export = db.get(Export, export_id)
    if not export:
        raise HTTPException(status_code=404, detail="导出不存在")
    return ExportOut.model_validate(export)


@router.get("/exports/{export_id}/download")
def download_export(export_id: str, db: Session = Depends(get_db)):
    export = db.get(Export, export_id)
    if not export:
        raise HTTPException(status_code=404, detail="导出不存在")
    path = Path(export.path).resolve()
    root = settings.export_dir.resolve()
    if not path.is_relative_to(root) or not path.exists():
        raise HTTPException(status_code=404, detail="导出文件不存在")
    project = db.get(Project, export.project_id)
    name = f"{(project.codename or project.name) if project else 'persona'}-package.zip"
    return FileResponse(path, filename=name, media_type="application/zip")
