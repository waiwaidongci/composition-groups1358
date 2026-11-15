from fastapi import HTTPException
from ..models import CompositionSample
from ..utils.serialize import record
from .study_service import get_study
from .phase_service import get_active_version,version_samples
from .audit_service import log


def list_samples(db,sid,version_id=None):
    get_study(db,sid)
    from ..models import PhaseVersion
    if version_id is None:version=get_active_version(db,sid)
    else:
        version=db.get(PhaseVersion,version_id)
        if not version or version.study_id!=sid:raise HTTPException(404,"相通道版本不存在")
    return [{**s,"zero_count":sum(v==0 for v in s["values"].values())} for s in version_samples(db,version)]


def annotate(db,sid,data,user):
    row=db.get(CompositionSample,sid)
    if not row:raise HTTPException(404,"组成样本不存在")
    row.note=data.note;log(db,user.email,'sample.annotate',sid);db.commit();return record(row)
