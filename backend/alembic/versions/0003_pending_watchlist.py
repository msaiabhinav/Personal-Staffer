"""Allow explicit unresolved watchlist requests without guessing an employer."""

import sqlalchemy as sa

from alembic import op

revision = "0003_pending_watchlist"
down_revision = "0002_history_guards"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("watchlist_entries", sa.Column("requested_name", sa.String(255), nullable=True))
    op.alter_column("watchlist_entries", "employer_group_id", nullable=True)
    op.create_check_constraint(
        "watchlist_resolvable_identity",
        "watchlist_entries",
        "employer_group_id IS NOT NULL OR (requested_name IS NOT NULL AND length(requested_name) > 0)",
    )


def downgrade():
    # Explicitly refuse a rollback that would erase unresolved user requests.
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM watchlist_entries WHERE employer_group_id IS NULL) THEN RAISE EXCEPTION 'Resolve pending watchlist requests before downgrade'; END IF; END $$"
    )
    op.drop_constraint("watchlist_resolvable_identity", "watchlist_entries", type_="check")
    op.alter_column("watchlist_entries", "employer_group_id", nullable=False)
    op.drop_column("watchlist_entries", "requested_name")
