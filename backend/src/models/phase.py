from sqlalchemy import String,Text,JSON,ForeignKey,Double,UniqueConstraint
from sqlalchemy.orm import Mapped,mapped_column
from ..config.database import Base
from ..utils.clock import now


class PhaseVersion(Base):
    """One immutable set of phase channels for a study.

    v1 is the base version and reads sample values from ``composition_samples``.
    Every later version is derived from a source version and materializes its
    own sample values in ``sample_version_values``. Retired versions stay
    readable so historical results can still be re-analyzed on their original
    channel basis.
    """

    __tablename__="phase_versions"
    __table_args__=(UniqueConstraint("study_id","version"),)
    id:Mapped[int]=mapped_column(primary_key=True)
    study_id:Mapped[int]=mapped_column(ForeignKey("composition_studies.id"))
    version:Mapped[int]
    label:Mapped[str]=mapped_column(String(160))
    status:Mapped[str]=mapped_column(String(24),default="draft")
    source_version_id:Mapped[int|None]=mapped_column(ForeignKey("phase_versions.id"),nullable=True)
    created_at:Mapped[str]=mapped_column(String(64),default=now)
    activated_at:Mapped[str]=mapped_column(String(64),default="")
    retired_at:Mapped[str]=mapped_column(String(64),default="")
    invalidated_reason:Mapped[str]=mapped_column(Text,default="")
    lock_version:Mapped[int]=mapped_column(default=0)


class PhaseVersionComponent(Base):
    """Channel definitions belonging to one version.

    Backfilled from ``component_specs`` for the base version and copied forward
    for every derived version, so all version reads use one code path and a
    retired version keeps its original channel list.
    """

    __tablename__="phase_version_components"
    __table_args__=(UniqueConstraint("version_id","code"),UniqueConstraint("version_id","position"))
    id:Mapped[int]=mapped_column(primary_key=True)
    version_id:Mapped[int]=mapped_column(ForeignKey("phase_versions.id"))
    code:Mapped[str]=mapped_column(String(40))
    label:Mapped[str]=mapped_column(String(80))
    unit:Mapped[str]=mapped_column(String(40))
    position:Mapped[int]
    meaning:Mapped[str]=mapped_column(Text)


class SampleVersionValue(Base):
    """Frozen sample values for a derived version, written only at activation."""

    __tablename__="sample_version_values"
    __table_args__=(UniqueConstraint("version_id","sample_id"),)
    id:Mapped[int]=mapped_column(primary_key=True)
    version_id:Mapped[int]=mapped_column(ForeignKey("phase_versions.id"))
    sample_id:Mapped[int]=mapped_column(ForeignKey("composition_samples.id"))
    values:Mapped[dict]=mapped_column(JSON)
    origin:Mapped[str]=mapped_column(String(24),default="migration")
    created_at:Mapped[str]=mapped_column(String(64),default=now)


class PhaseMigration(Base):
    """A draft attempt to split one channel of the active version into two."""

    __tablename__="phase_migrations"
    id:Mapped[int]=mapped_column(primary_key=True)
    study_id:Mapped[int]=mapped_column(ForeignKey("composition_studies.id"))
    source_version_id:Mapped[int]=mapped_column(ForeignKey("phase_versions.id"))
    target_version_id:Mapped[int]=mapped_column(ForeignKey("phase_versions.id"))
    label:Mapped[str]=mapped_column(String(160))
    split_code:Mapped[str]=mapped_column(String(40))
    new_codes:Mapped[list]=mapped_column(JSON)
    status:Mapped[str]=mapped_column(String(24),default="in_progress")
    owner:Mapped[str]=mapped_column(String(100))
    created_at:Mapped[str]=mapped_column(String(64),default=now)
    activated_at:Mapped[str]=mapped_column(String(64),default="")
    invalidated_reason:Mapped[str]=mapped_column(Text,default="")


class PhaseSplitEntry(Base):
    """Per-sample split amounts entered by batch; confirmed rows are immutable."""

    __tablename__="phase_split_entries"
    __table_args__=(UniqueConstraint("migration_id","sample_id"),)
    id:Mapped[int]=mapped_column(primary_key=True)
    migration_id:Mapped[int]=mapped_column(ForeignKey("phase_migrations.id"))
    sample_id:Mapped[int]=mapped_column(ForeignKey("composition_samples.id"))
    values:Mapped[dict]=mapped_column(JSON)
    submitted_sum:Mapped[float|None]=mapped_column(Double(asdecimal=False),nullable=True)
    expected_value:Mapped[float|None]=mapped_column(Double(asdecimal=False),nullable=True)
    status:Mapped[str]=mapped_column(String(24),default="pending")
    reason:Mapped[str]=mapped_column(Text,default="")
    created_at:Mapped[str]=mapped_column(String(64),default=now)
    updated_at:Mapped[str]=mapped_column(String(64),default=now)
    confirmed_at:Mapped[str]=mapped_column(String(64),default="")
