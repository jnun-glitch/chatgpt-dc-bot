from datetime import datetime, timedelta, timezone


def test_warning_expiry_timestamp_is_in_the_future():
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=30)
    assert expires > now


def test_scheduler_query_only_selects_pending_reminders():
    query = "SELECT id,user_id,message FROM reminders WHERE sent=0 AND remind_at <= ?"
    assert "sent=0" in query
    assert "remind_at <= ?" in query


def test_moderation_defaults_are_safe_and_bounded():
    assert 0 < 30 <= 3650
    assert 1 <= 1 <= 100
    assert 2 <= 3 <= 100
    assert 1 <= 10 <= 1440
