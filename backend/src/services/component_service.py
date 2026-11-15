from fastapi import HTTPException
from ..models import PhaseVersion
from .study_service import get_study
from .phase_service import get_active_version,version_components


def list_components(db,sid,version_id=None):
    get_study(db,sid)
    if version_id is None:return version_components(db,get_active_version(db,sid))
    version=db.get(PhaseVersion,version_id)
    if not version or version.study_id!=sid:raise HTTPException(404,"相通道版本不存在")
    return version_components(db,version)
