from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from test_auth_email_people_postgres import engine as engine  # noqa: PLC0414 - register shared pytest fixture
from test_auth_email_people_postgres import owner as owner  # noqa: PLC0414 - register shared pytest fixture
from test_auth_email_people_postgres import seed_connection
from test_auth_email_people_postgres import settings as settings  # noqa: PLC0414 - register shared pytest fixture

from app.db.models import GmailSyncState
from app.email.gmail import MessageBatch
from app.email.orchestration import synchronize_batched

pytestmark = pytest.mark.postgres


def test_mail_fetch_does_not_hold_user_lock_and_cursor_commits(engine, owner, settings):
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session, session.begin():
        connection = seed_connection(session, owner)
        session.add(GmailSyncState(connection_id=connection.id, history_cursor="before", reconciliation_progress={}))

    def history(*args):
        # NOWAIT fails immediately if orchestration keeps a provider request under a user lock.
        from app.db.models import User

        with factory() as other, other.begin():
            other.execute(select(User).where(User.id == owner).with_for_update(nowait=True)).scalar_one()
        return MessageBatch((), None, "after")

    result = synchronize_batched(factory, owner, settings, api=SimpleNamespace(history=history))
    assert result["state"] == "HEALTHY"
    with factory() as session:
        assert session.scalar(select(GmailSyncState)).history_cursor == "after"


def test_concurrent_cursor_change_discards_prefetched_page(engine, owner, settings):
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session, session.begin():
        connection = seed_connection(session, owner)
        session.add(GmailSyncState(connection_id=connection.id, history_cursor="before", reconciliation_progress={}))

    def history(*args):
        with factory() as other, other.begin():
            state = other.scalar(select(GmailSyncState).with_for_update())
            state.history_cursor = "newer-committed-cursor"
        return MessageBatch((), None, "stale-prefetch-result")

    result = synchronize_batched(factory, owner, settings, api=SimpleNamespace(history=history))
    assert result["reason"] == "SYNC_STATE_CHANGED_RETRY"
    with factory() as session:
        assert session.scalar(select(GmailSyncState)).history_cursor == "newer-committed-cursor"
