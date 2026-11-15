from fastapi import HTTPException
from ..models import CompositionStudy
from ..utils.serialize import record
from .analysis_service import prepare_snapshot
from .phase_service import build_snapshot, get_active_version, version_meta, ensure_base_version


def get_study(db, sid):
    row = db.get(CompositionStudy, sid)
    if not row:
        raise HTTPException(404, "组成研究不存在")
    return row


def create_snapshot(db, study, version=None):
    return build_snapshot(db, study, version)


def list_studies(db):
    out = []
    for s in db.query(CompositionStudy).order_by(CompositionStudy.code):
        ensure_base_version(db, s)
        db.commit()
        from ..models import PhaseVersion, PhaseMigration
        version_count = db.query(PhaseVersion).filter_by(study_id=s.id).count()
        pending = db.query(PhaseMigration).filter_by(study_id=s.id, status="in_progress").count()
        try:
            active = get_active_version(db, s.id)
            snapshot = build_snapshot(db, s, active)
        except HTTPException as exc:
            out.append({**record(s), "sample_count": 0, "component_count": 0, "group_counts": {},
                        "zero_rows": 0, "supported": False, "reason": exc.detail,
                        "active_version": None, "version_count": version_count,
                        "migration_in_progress": pending})
            continue
        counts = {}
        zero_rows = 0
        for row in snapshot['samples']:
            counts[row['group']] = counts.get(row['group'], 0) + 1
            zero_rows += any(v == 0 for v in row['values'].values())
        supported = True
        reason = '成分与组规模完整，支持CLR置换研究'
        if active.source_version_id is not None:
            reason = f'当前为 v{active.version}（相通道迁移后）；成分与组规模完整，支持CLR置换研究'
        try:
            prepare_snapshot(snapshot, s.default_delta)
        except ValueError as e:
            supported = False
            reason = str(e)
        out.append({**record(s), "sample_count": len(snapshot['samples']),
                    "component_count": len(snapshot['components']), "group_counts": counts,
                    "zero_rows": zero_rows, "supported": supported, "reason": reason,
                    "active_version": version_meta(active),
                    "version_count": version_count, "migration_in_progress": pending})
    return out
