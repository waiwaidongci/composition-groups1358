import math
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from ..models import (
    CompositionStudy, ComponentSpec, CompositionSample,
    PhaseVersion, PhaseVersionComponent, SampleVersionValue,
    PhaseMigration, PhaseSplitEntry,
)
from ..utils.serialize import record
from ..utils.clock import now
from .audit_service import log

ACTIVE = "active"
DRAFT = "draft"
RETIRED = "retired"
INVALIDATED = "invalidated"

MIGRATION_IN_PROGRESS = "in_progress"
MIGRATION_ACTIVATED = "activated"
MIGRATION_INVALIDATED = "invalidated"

ENTRY_PENDING = "pending"
ENTRY_CONFIRMED = "confirmed"
ENTRY_MISMATCH = "mismatch"
ENTRY_INVALID = "invalid"

ENTRY_LABEL = {
    ENTRY_PENDING: "待补录",
    ENTRY_CONFIRMED: "已确认",
    ENTRY_MISMATCH: "和值不符",
    ENTRY_INVALID: "补录无效",
}
MIN_COMPONENTS, MAX_COMPONENTS = 4, 6
TOLERANCE = 1e-9
BLOCKING_PREVIEW = 20


def study_or_404(db, sid):
    study = db.get(CompositionStudy, sid)
    if not study:
        raise HTTPException(404, "组成研究不存在")
    return study


def _finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _close_enough(a, b):
    """Relative agreement only.

    An absolute floor would let a genuinely tiny split channel be replaced by
    zero, so the comparison scales with the larger magnitude. Equal zero stays
    equal; zero versus any non-zero is a mismatch.
    """
    scale = max(abs(a), abs(b))
    if scale == 0:
        return True
    return abs(a - b) <= TOLERANCE * scale


def version_meta(version):
    if not version:
        return None
    return {"id": version.id, "version": version.version, "label": version.label, "status": version.status}


def _base_version(db, study_id):
    return db.query(PhaseVersion).filter_by(study_id=study_id, source_version_id=None).first()


def ensure_base_version(db, study):
    """Create the immutable v1 channel set for a study if it does not exist yet."""
    existing = _base_version(db, study.id)
    if existing:
        return existing
    try:
        with db.begin_nested():
            version = PhaseVersion(study_id=study.id, version=1, label="初始五相",
                                   status=ACTIVE, source_version_id=None, activated_at=now())
            db.add(version)
            db.flush()
            specs = db.query(ComponentSpec).filter_by(study_id=study.id).order_by(ComponentSpec.position).all()
            for spec in specs:
                db.add(PhaseVersionComponent(version_id=version.id, code=spec.code, label=spec.label,
                                             unit=spec.unit, position=spec.position, meaning=spec.meaning))
            db.flush()
        return version
    except IntegrityError:
        # A concurrent request created v1 first; use the committed row.
        existing = _base_version(db, study.id)
        if not existing:
            raise
        return existing


def get_active_version(db, study_id, lock=False):
    """Return the single active version; never fall back to a retired base.

    Callers that also create runs or activate migrations lock the study row first
    so that version reads and snapshots are serialized against a switch.
    """
    query = db.query(PhaseVersion).filter_by(study_id=study_id, status=ACTIVE)
    if lock:
        query = query.with_for_update()
    version = query.order_by(PhaseVersion.version.desc()).first()
    if version:
        return version
    study = study_or_404(db, study_id)
    if _base_version(db, study_id):
        raise HTTPException(409, "该研究当前没有生效的相通道版本，请检查版本状态")
    version = ensure_base_version(db, study)
    db.commit()
    return version


def version_components(db, version):
    rows = db.query(PhaseVersionComponent).filter_by(version_id=version.id).order_by(PhaseVersionComponent.position).all()
    return [{**record(row), "study_id": version.study_id, "version_id": version.id} for row in rows]


def version_samples(db, version):
    samples = db.query(CompositionSample).filter_by(study_id=version.study_id).order_by(CompositionSample.code).all()
    if version.source_version_id is None:
        return [{**record(sample), "version_id": version.id} for sample in samples]
    stored = {row.sample_id: row.values for row in db.query(SampleVersionValue).filter_by(version_id=version.id)}
    out = []
    for sample in samples:
        if sample.id not in stored:
            raise HTTPException(409, f"版本 v{version.version} 缺少样本 {sample.code} 的冻结原量")
        out.append({"id": sample.id, "study_id": sample.study_id, "code": sample.code, "group": sample.group,
                    "values": stored[sample.id], "note": sample.note, "version_id": version.id})
    return out


def build_snapshot(db, study, version=None):
    version = version or get_active_version(db, study.id)
    return {"study": record(study), "phase_version": version_meta(version),
            "components": version_components(db, version), "samples": version_samples(db, version)}


def list_versions(db, study_id):
    study_or_404(db, study_id)
    ensure_base_version(db, study_or_404(db, study_id))
    db.commit()
    # Resolve any stale in-progress migration before reporting version status so a
    # losing draft is never shown as still selectable. Collect first: _settle_status
    # may commit, which would otherwise invalidate the query's iteration.
    for migration in db.query(PhaseMigration).filter_by(study_id=study_id).all():
        _settle_status(db, migration)
    out = []
    for version in db.query(PhaseVersion).filter_by(study_id=study_id).order_by(PhaseVersion.version):
        out.append({**record(version), "component_count": db.query(PhaseVersionComponent).filter_by(version_id=version.id).count()})
    return out


def _progress(db, migration):
    entries = db.query(PhaseSplitEntry).filter_by(migration_id=migration.id).all()
    counts = {ENTRY_PENDING: 0, ENTRY_CONFIRMED: 0, ENTRY_MISMATCH: 0, ENTRY_INVALID: 0}
    for entry in entries:
        counts[entry.status] = counts.get(entry.status, 0) + 1
    total = len(entries)
    return {"total": total, "confirmed": counts[ENTRY_CONFIRMED], "pending": counts[ENTRY_PENDING],
            "mismatch": counts[ENTRY_MISMATCH], "invalid": counts[ENTRY_INVALID],
            "complete": total > 0 and counts[ENTRY_CONFIRMED] == total}


def _migration_row(db, migration, progress=None):
    return {**record(migration), "progress": progress or _progress(db, migration)}


def _entry_row(entry, sample_codes):
    return {**record(entry), "sample_code": sample_codes.get(entry.sample_id, ""),
            "status_label": ENTRY_LABEL.get(entry.status, entry.status)}


def _sample_codes(db, study_id):
    return {row.id: row.code for row in db.query(CompositionSample).filter_by(study_id=study_id)}


def list_migrations(db, study_id):
    study_or_404(db, study_id)
    codes = _sample_codes(db, study_id)
    out = []
    for migration in db.query(PhaseMigration).filter_by(study_id=study_id).order_by(PhaseMigration.id.desc()).all():
        _settle_status(db, migration)
        progress = _progress(db, migration)
        target = db.get(PhaseVersion, migration.target_version_id)
        out.append({**_migration_row(db, migration, progress), "target_version": version_meta(target),
                    "entries": [_entry_row(e, codes) for e in
                                db.query(PhaseSplitEntry).filter_by(migration_id=migration.id).order_by(PhaseSplitEntry.id)]})
    return out


def migration_detail(db, mid):
    migration = db.get(PhaseMigration, mid)
    if not migration:
        raise HTTPException(404, "相通道迁移不存在")
    _settle_status(db, migration)
    codes = _sample_codes(db, migration.study_id)
    source = db.get(PhaseVersion, migration.source_version_id)
    target = db.get(PhaseVersion, migration.target_version_id)
    return {**_migration_row(db, migration), "source_version": version_meta(source),
            "target_version": version_meta(target),
            "components": version_components(db, target),
            "entries": [_entry_row(e, codes) for e in
                        db.query(PhaseSplitEntry).filter_by(migration_id=migration.id).order_by(PhaseSplitEntry.id)]}


def create_migration(db, study_id, data, user):
    study = study_or_404(db, study_id)
    # Serialize version numbering and channel-set reads against concurrent creation/activation.
    db.query(CompositionStudy).filter_by(id=study.id).with_for_update().one()
    ensure_base_version(db, study)
    source = get_active_version(db, study.id, lock=True)
    components = version_components(db, source)
    codes = [c["code"] for c in components]
    if data.split_code not in codes:
        raise HTTPException(422, f"待拆分通道 {data.split_code} 不在当前版本 v{source.version} 中")
    if len(components) + 1 > MAX_COMPONENTS:
        raise HTTPException(422, f"拆分后为 {len(components) + 1} 个通道，超过 {MAX_COMPONENTS} 个上限，不能再拆")
    new_codes = [c.code for c in data.new_components]
    if len(set(new_codes)) != 2:
        raise HTTPException(422, "两个新通道编号必须不同")
    clash = sorted(set(new_codes) & set(codes))
    if clash:
        raise HTTPException(422, f"新通道编号与现有通道冲突：{'、'.join(clash)}")
    split_index = next(i for i, c in enumerate(components) if c["code"] == data.split_code)
    split_component = components[split_index]
    next_version = (db.query(PhaseVersion.version).filter_by(study_id=study.id)
                    .order_by(PhaseVersion.version.desc()).limit(1).scalar() or 0) + 1
    target = PhaseVersion(study_id=study.id, version=next_version, label=data.label, status=DRAFT,
                          source_version_id=source.id)
    db.add(target)
    db.flush()
    position = 0
    for component in components:
        if component["code"] != data.split_code:
            db.add(PhaseVersionComponent(version_id=target.id, code=component["code"], label=component["label"],
                                         unit=component["unit"], position=position, meaning=component["meaning"]))
            position += 1
            continue
        for spec in data.new_components:
            db.add(PhaseVersionComponent(version_id=target.id, code=spec.code,
                                         label=spec.label or spec.code, unit=spec.unit or split_component["unit"],
                                         position=position,
                                         meaning=spec.meaning or f"由{source.label} 的{split_component['label']}拆出的互斥分析相；与其他通道共同闭合。"))
            position += 1
    migration = PhaseMigration(study_id=study.id, source_version_id=source.id, target_version_id=target.id,
                               label=data.label, split_code=data.split_code, new_codes=new_codes,
                               status=MIGRATION_IN_PROGRESS, owner=user.name)
    db.add(migration)
    db.flush()
    samples = version_samples(db, source)
    for sample in samples:
        raw = sample["values"].get(data.split_code)
        if not _finite_number(raw) or raw < 0:
            db.add(PhaseSplitEntry(migration_id=migration.id, sample_id=sample["id"], values={},
                                   expected_value=None, status=ENTRY_INVALID,
                                   reason=f"源版本样本缺少可用的{data.split_code}原量，无法核验拆分和值"))
            continue
        db.add(PhaseSplitEntry(migration_id=migration.id, sample_id=sample["id"], values={},
                               expected_value=float(raw), status=ENTRY_PENDING,
                               reason=f"尚未补录{data.split_code}的拆分原量"))
    log(db, user.email, "phase.migration.create", migration.id)
    db.commit()
    return migration_detail(db, migration.id)


def _resolve_sample(db, study_id, item):
    if (item.sample_id is None) == (item.sample_code is None):
        raise HTTPException(422, "每条补录须且只须给出 sample_id 或 sample_code")
    if item.sample_id is not None:
        sample = db.get(CompositionSample, item.sample_id)
        if not sample or sample.study_id != study_id:
            raise HTTPException(422, f"样本 {item.sample_id} 不属于该研究")
        return sample
    sample = db.query(CompositionSample).filter_by(study_id=study_id, code=item.sample_code).first()
    if not sample:
        raise HTTPException(422, f"样本编号 {item.sample_code} 不存在")
    return sample


def _judge(values, entry, new_codes):
    """Return (status, reason, submitted_sum) for one sample's split amounts."""
    ordered = []
    missing = []
    for code in new_codes:
        value = values.get(code)
        if value is None:
            missing.append(code)
        elif not _finite_number(value) or value < 0:
            return ENTRY_INVALID, f"{code} 须为有限非负实数", None
        else:
            ordered.append(float(value))
    extra = sorted(set(values) - set(new_codes))
    if extra:
        return ENTRY_INVALID, f"包含不属于本次拆分的通道：{'、'.join(extra)}", None
    if missing:
        return ENTRY_PENDING, f"尚未补录{'、'.join(missing)}的拆分原量", None
    total = ordered[0] + ordered[1]
    expected = entry.expected_value
    if not _close_enough(total, expected):
        return ENTRY_MISMATCH, (f"两者之和 {total:.12g} 与旧值 {expected:.12g} 相差 {total - expected:+.3g}，"
                                f"超出相对容差 {TOLERANCE:g}"), total
    return ENTRY_CONFIRMED, "", total


def _settle_status(db, migration):
    """Lazily invalidate a migration whose source version is no longer active.

    Activation invalidates in-progress siblings in the same transaction, but a
    migration created while another switch was committing can be left
    in_progress against a retired source. Resolving it here keeps the
    "one version wins, the other is explicitly invalid" rule true on every read
    and write path, not only on activation.
    """
    if migration.status != MIGRATION_IN_PROGRESS:
        return migration
    source = db.get(PhaseVersion, migration.source_version_id)
    if source and source.status != ACTIVE:
        reason = f"源版本 v{source.version} 已退役或被新的迁移取代，本版明确失效"
        _invalidate(db, migration, reason)
        log(db, "system", "phase.migration.invalidate", migration.id)
        db.commit()
    return migration


def upsert_entries(db, mid, data, user):
    migration = db.get(PhaseMigration, mid)
    if not migration:
        raise HTTPException(404, "相通道迁移不存在")
    _settle_status(db, migration)
    if migration.status == MIGRATION_INVALIDATED:
        raise HTTPException(409, f"该迁移已失效：{migration.invalidated_reason or '竞争迁移已由另一版生效'}")
    if migration.status == MIGRATION_ACTIVATED:
        raise HTTPException(409, "该迁移已整版切换，补录只读")
    entries = {entry.sample_id: entry for entry in db.query(PhaseSplitEntry).filter_by(migration_id=migration.id)}
    new_codes = list(migration.new_codes)
    updated, skipped, seen = [], [], set()
    for item in data.entries:
        sample = _resolve_sample(db, migration.study_id, item)
        if sample.id in seen:
            raise HTTPException(422, f"样本 {sample.code} 在同一批中重复出现")
        seen.add(sample.id)
        entry = entries.get(sample.id)
        if not entry:
            raise HTTPException(422, f"样本 {sample.code} 不属于该迁移")
        if entry.status == ENTRY_CONFIRMED:
            skipped.append({"sample_code": sample.code, "status": ENTRY_CONFIRMED,
                            "reason": "已确认值不覆盖；如需修正请在切换前新建迁移"})
            continue
        # An entry marked invalid because the source value was missing cannot be
        # repaired by补录 — there is no trusted old value to compare against.
        if entry.status == ENTRY_INVALID and entry.expected_value is None:
            skipped.append({"sample_code": sample.code, "status": ENTRY_INVALID,
                            "reason": entry.reason})
            continue
        status, reason, total = _judge(dict(item.values), entry, new_codes)
        entry.values = {code: value for code, value in item.values.items() if value is not None}
        entry.status = status
        entry.reason = reason
        entry.submitted_sum = total
        entry.updated_at = now()
        entry.confirmed_at = now() if status == ENTRY_CONFIRMED else ""
        updated.append({"sample_code": sample.code, "status": status, "reason": reason, "submitted_sum": total})
    log(db, user.email, "phase.migration.entries", migration.id)
    db.commit()
    return {"migration_id": migration.id, "updated": updated, "skipped": skipped,
            "applied": len(updated), "duplicates_only": len(updated) == 0 and bool(skipped),
            "progress": _progress(db, migration)}


def _normalize_pair(first, expected):
    """Split into two exactly-additive parts, preserving the first value when possible."""
    if first < 0:
        first = 0.0
    if first > expected:
        first = expected
    second = expected - first
    if second < 0:
        second = 0.0
    return first, second


def _blocking(db, migration):
    codes = _sample_codes(db, migration.study_id)
    entries = {}
    for entry in db.query(PhaseSplitEntry).filter_by(migration_id=migration.id).order_by(PhaseSplitEntry.id):
        entries[entry.sample_id] = entry
    rows = []
    for entry in entries.values():
        if entry.status != ENTRY_CONFIRMED:
            rows.append({"sample_code": codes.get(entry.sample_id, str(entry.sample_id)),
                         "status": entry.status, "status_label": ENTRY_LABEL.get(entry.status, entry.status),
                         "reason": entry.reason})
    # Samples present in the source version but missing a migration entry would
    # otherwise be silently dropped; treat them as blocking.
    source = db.get(PhaseVersion, migration.source_version_id)
    if source:
        known = {sample["id"] for sample in version_samples(db, source)}
        for sample_id in sorted(known - set(entries)):
            rows.append({"sample_code": codes.get(sample_id, str(sample_id)), "status": "invalid",
                         "status_label": "缺少迁移条目", "reason": "该样本在迁移创建后新增，尚无拆分补录条目"})
    return rows


def _blocking_message(blocking):
    preview = "；".join(f"{row['sample_code']}（{row['status_label']}：{row['reason']}）"
                       for row in blocking[:BLOCKING_PREVIEW])
    more = "" if len(blocking) <= BLOCKING_PREVIEW else f"；另 {len(blocking) - BLOCKING_PREVIEW} 条略"
    return f"{len(blocking)} 个样本尚未确认，未整版切换：{preview}{more}"


def activate_migration(db, mid, user):
    migration = db.get(PhaseMigration, mid)
    if not migration:
        raise HTTPException(404, "相通道迁移不存在")
    _settle_status(db, migration)
    if migration.status == MIGRATION_ACTIVATED:
        target = db.get(PhaseVersion, migration.target_version_id)
        return {"migration": _migration_row(db, migration), "already_active": True,
                "target_version": version_meta(target)}
    if migration.status == MIGRATION_INVALIDATED:
        raise HTTPException(409, f"该迁移已失效：{migration.invalidated_reason or '竞争迁移已由另一版生效'}")
    # The study row is the single lock serializing competing migrations, version
    # reads and run creation. Taking it first keeps lock order consistent with
    # create_run/create_migration and prevents mixed channel/sample snapshots.
    db.query(CompositionStudy).filter_by(id=migration.study_id).with_for_update().one()
    # Re-read under the lock: a competing transaction may have resolved this row
    # while we waited. Do not use refresh(): it would also discard the pending
    # SampleVersionValue rows added below if the session had flushed them.
    locked = db.query(PhaseMigration).filter_by(id=mid).with_for_update().one()
    migration = locked
    if migration.status == MIGRATION_ACTIVATED:
        target = db.get(PhaseVersion, migration.target_version_id)
        return {"migration": _migration_row(db, migration), "already_active": True,
                "target_version": version_meta(target)}
    if migration.status == MIGRATION_INVALIDATED:
        raise HTTPException(409, f"该迁移已失效：{migration.invalidated_reason or '竞争迁移已由另一版生效'}")
    source = (db.query(PhaseVersion).filter_by(id=migration.source_version_id)
              .with_for_update().one())
    if source.status != ACTIVE:
        reason = "源版本已退役或被新的迁移取代，本迁移失效"
        _invalidate(db, migration, reason)
        db.commit()
        raise HTTPException(409, reason)
    blocking = _blocking(db, migration)
    if blocking:
        raise HTTPException(409, _blocking_message(blocking))

    target = db.get(PhaseVersion, migration.target_version_id)
    if target.status == INVALIDATED:
        raise HTTPException(409, "目标版本已失效，不能切换")
    split_code = migration.split_code
    first_code, second_code = migration.new_codes
    entries = {entry.sample_id: entry for entry in db.query(PhaseSplitEntry).filter_by(migration_id=migration.id)}
    samples = version_samples(db, source)
    if any(not _finite_number(sample["values"].get(split_code)) for sample in samples):
        raise HTTPException(409, "源版本存在缺失的拆分通道原量，不能切换")
    for sample in samples:
        entry = entries.get(sample["id"])
        if not entry:
            raise HTTPException(409, f"样本 {sample['code']} 缺少迁移补录条目，不能切换")
        expected = float(sample["values"][split_code])
        first, second = _normalize_pair(float(entry.values[first_code]), expected)
        values = {}
        for component in version_components(db, target):
            if component["code"] == first_code:
                values[component["code"]] = first
            elif component["code"] == second_code:
                values[component["code"]] = second
            else:
                values[component["code"]] = sample["values"][component["code"]]
        db.add(SampleVersionValue(version_id=target.id, sample_id=sample["id"], values=values, origin="migration"))

    stamp = now()
    # Atomic compare-and-swap on the source version: only the transaction that
    # flips the still-active source to retired may activate its target. This is a
    # hard guarantee independent of row-lock strength (MySQL FOR UPDATE plus this
    # UPDATE; SQLite also serializes writers). If 0 rows change, a competing
    # migration already won.
    claimed = (db.query(PhaseVersion)
               .filter_by(id=source.id, status=ACTIVE, version=source.version)
               .update({"status": RETIRED, "retired_at": stamp}, synchronize_session=False))
    if claimed != 1:
        db.rollback()
        # This transaction lost the race after reading a still-active source.
        # Mark the migration (and its draft target) invalidated in a fresh
        # transaction so it is never left dangling as "in progress".
        reason = "源版本已被另一迁移切换，本版明确失效"
        current = db.get(PhaseMigration, mid)
        if current and current.status == MIGRATION_IN_PROGRESS:
            _invalidate(db, current, reason)
            log(db, user.email, "phase.migration.invalidate", current.id)
            db.commit()
        raise HTTPException(409, reason)
    target.status = ACTIVE
    target.activated_at = stamp
    migration.status = MIGRATION_ACTIVATED
    migration.activated_at = stamp
    for other in db.query(PhaseMigration).filter_by(study_id=migration.study_id, status=MIGRATION_IN_PROGRESS):
        if other.id != migration.id:
            _invalidate(db, other, f"另一迁移 v{target.version} 已先行切换生效，本版明确失效")
    log(db, user.email, "phase.migration.activate", migration.id)
    db.commit()
    db.refresh(source)
    return {"migration": _migration_row(db, migration), "already_active": False,
            "source_version": version_meta(source), "target_version": version_meta(target),
            "components": version_components(db, target)}


def _invalidate(db, migration, reason):
    migration.status = MIGRATION_INVALIDATED
    migration.invalidated_reason = reason
    target = db.get(PhaseVersion, migration.target_version_id)
    if target and target.status == DRAFT:
        target.status = INVALIDATED
        target.invalidated_reason = reason


def migration_progress_for_study(db, study_id):
    study = study_or_404(db, study_id)
    if not _base_version(db, study_id):
        ensure_base_version(db, study)
        db.commit()
    active = db.query(PhaseVersion).filter_by(study_id=study_id, status=ACTIVE).order_by(PhaseVersion.version.desc()).first()
    versions = db.query(PhaseVersion).filter_by(study_id=study_id).count()
    migrations = []
    for migration in db.query(PhaseMigration).filter_by(study_id=study_id).order_by(PhaseMigration.id.desc()).all():
        _settle_status(db, migration)
        target = db.get(PhaseVersion, migration.target_version_id)
        migrations.append({**_migration_row(db, migration), "target_version": version_meta(target)})
    in_progress = [m for m in migrations if m["status"] == MIGRATION_IN_PROGRESS]
    return {"active_version": version_meta(active), "version_count": versions,
            "in_progress": len(in_progress),
            "in_progress_progress": [{"migration_id": m["id"], "label": m["label"],
                                      "progress": m["progress"]} for m in in_progress],
            "migrations": migrations}


def backfill_versions(db):
    """Create v1 for studies seeded before versioning existed, and stamp old runs."""
    from ..models import CompositionRun
    changed = 0
    for study in db.query(CompositionStudy).all():
        version = _base_version(db, study.id)
        if not version:
            version = ensure_base_version(db, study)
            changed += 1
        # Old runs get their version pointer for convenience only; their frozen
        # input_snapshot and result already carry the original five channels.
        db.query(CompositionRun).filter_by(study_id=study.id, phase_version_id=None).update(
            {"phase_version_id": version.id})
    db.commit()
    return changed


LEGACY_COLUMNS = {
    "composition_runs": {"phase_version_id": "INTEGER NULL"},
}


def ensure_upgrade_columns(engine):
    """Add columns introduced after the first metadata bootstrap.

    ``Base.metadata.create_all`` creates missing tables but never alters
    existing ones, and the project has no full DDL migration tool. Adding the
    nullable version pointer on start-up keeps an existing MySQL volume usable;
    it is a no-op on fresh databases.
    """
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    if "composition_runs" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("composition_runs")}
    if "phase_version_id" in columns:
        return
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE composition_runs ADD COLUMN phase_version_id INTEGER NULL"))
