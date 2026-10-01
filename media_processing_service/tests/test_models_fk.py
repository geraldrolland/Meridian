"""Model schema tests — cascade FKs let db.delete(job) remove the tree."""

from app.models.transcode_task import TranscodeTask
from app.models.upload_task import UploadTask


class TestCascadeForeignKeys:
    def test_transcode_task_job_id_cascades(self):
        column = TranscodeTask.__table__.c.job_id
        fks = list(column.foreign_keys)
        assert len(fks) == 1
        fk = fks[0]
        assert fk.target_fullname == "jobs.id"
        assert fk.ondelete == "CASCADE"
        assert fk.name == "transcode_tasks_job_id_fkey"

    def test_upload_task_transcode_id_cascades(self):
        column = UploadTask.__table__.c.transcode_id
        fks = list(column.foreign_keys)
        assert len(fks) == 1
        fk = fks[0]
        assert fk.target_fullname == "transcode_tasks.id"
        assert fk.ondelete == "CASCADE"
        assert fk.name == "upload_tasks_transcode_id_fkey"

    def test_no_duplicate_foreign_key_constraints(self):
        for table in (TranscodeTask.__table__, UploadTask.__table__):
            fk_constraints = [
                c
                for c in table.constraints
                if c.__class__.__name__ == "ForeignKeyConstraint"
            ]
            assert len(fk_constraints) == 1
