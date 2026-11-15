import csv,io
from redis import Redis
from fastapi import HTTPException
from ..models import CompositionRun,ResampleNote,CompositionStudy
from ..config.settings import REDIS_URL
from ..utils.serialize import record
from .study_service import get_study
from .phase_service import get_active_version,build_snapshot,ensure_base_version
from .analysis_service import prepare_snapshot
from .audit_service import log
queue=Redis.from_url(REDIS_URL,decode_responses=True)
def list_runs(db):return [record(r) for r in db.query(CompositionRun).order_by(CompositionRun.id.desc())]
def get_run(db,rid):
    row=db.get(CompositionRun,rid)
    if not row:raise HTTPException(404,"组成运行不存在")
    return row
def create_run(db,data,user):
    study=get_study(db,data.study_id)
    # Lock the study row, then read the active version, channels and samples in this
    # transaction. A concurrent activation either commits first (we freeze the new
    # version) or waits (we freeze the old one) — never a mix. The queued run keeps
    # the snapshot it captured here even if the version switches afterwards.
    db.query(CompositionStudy).filter_by(id=study.id).with_for_update().one()
    ensure_base_version(db,study)
    if data.phase_version_id is None:
        version=get_active_version(db,study.id,lock=True)
    else:
        from ..models import PhaseVersion
        version=db.query(PhaseVersion).filter_by(id=data.phase_version_id,study_id=study.id).with_for_update().first()
        if not version:raise HTTPException(404,"相通道版本不存在")
        if version.status=='invalidated':raise HTTPException(409,f"版本 v{version.version} 已失效：{version.invalidated_reason or '竞争迁移已由另一版生效'}")
    snapshot=build_snapshot(db,study,version)
    try:
        prepare_snapshot(snapshot,data.delta)
        if len(snapshot['samples'])*data.permutations>150000:raise ValueError("样本数×置换数超额")
    except ValueError as e:raise HTTPException(422,str(e))
    payload=data.model_dump();payload.pop('phase_version_id',None)
    row=CompositionRun(**payload,input_snapshot=snapshot,owner=user.name,phase_version_id=version.id);db.add(row);db.flush();log(db,user.email,'composition.enqueue',row.id);db.commit()
    try:queue.rpush('composition:jobs',row.id)
    except Exception:row.status='failed';row.error='队列不可用，请重提';db.commit();raise HTTPException(503,row.error)
    return record(row)
def export_run(db,rid):
    row=get_run(db,rid)
    if row.status!='completed' or not db.query(ResampleNote).filter_by(run_id=rid,status='approved').first():raise HTTPException(403,'仅获批完成研究可导出')
    o=io.StringIO();w=csv.writer(o);stats=row.result['statistics'];w.writerow(['sample','group','component','raw','closed','replaced','CLR','zero_count','delta','R2','pseudo_F','F_status','global_p','B','seed','input_hash','phase_version'])
    for s in row.result['transformed']:
        for i,c in enumerate(row.result['components']):w.writerow([s['sample']['code'],s['sample']['group'],c['code'],s['raw'][i],s['closed'][i],s['replaced'][i],s['clr'][i],s['zero_count'],row.delta,stats['R2'],stats['F'],stats['F_status'],stats['p'],row.permutations,row.seed,row.result['input_hash'],(row.result.get('phase_version') or {}).get('version')])
    return o.getvalue()
