-- First schema bootstraps via metadata. Optional upgrade indexes:
CREATE INDEX sample_study_group_idx ON composition_samples (study_id,`group`);
CREATE INDEX note_run_status_idx ON resample_notes (run_id,status);

-- Phase-channel versioning (metadata also creates these; upgrade notes):
--   composition_runs.phase_version_id is added on start-up by ensure_upgrade_columns.
CREATE INDEX phase_version_study_idx ON phase_versions (study_id,status);
CREATE INDEX phase_migration_study_idx ON phase_migrations (study_id,status);
CREATE INDEX phase_entry_migration_idx ON phase_split_entries (migration_id,status);
