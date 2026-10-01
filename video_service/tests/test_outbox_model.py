"""Outbox model schema tests — the FK must never block deleting a video."""

from app.models.outbox import Outbox


class TestOutboxVideoIdForeignKey:
    def test_video_id_is_nullable(self):
        column = Outbox.__table__.c.video_id
        assert column.nullable is True

    def test_fk_ondelete_is_set_null(self):
        fks = list(Outbox.__table__.c.video_id.foreign_keys)
        assert len(fks) == 1
        fk = fks[0]
        assert fk.target_fullname == "videos.id"
        assert fk.ondelete == "SET NULL"
        assert fk.name == "outbox_video_id_fkey"

    def test_no_duplicate_foreign_key_constraints(self):
        # A leftover Field(foreign_key=...) alongside __table_args__ would
        # create a second NO ACTION constraint that still blocks DELETE.
        fk_constraints = [
            c for c in Outbox.__table__.constraints if c.__class__.__name__ == "ForeignKeyConstraint"
        ]
        assert len(fk_constraints) == 1
