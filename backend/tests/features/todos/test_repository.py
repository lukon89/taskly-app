from datetime import datetime, timezone
from unittest.mock import Mock, call, patch

from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.features.todos.models import TodoRecord
from app.features.todos.repository import TodoRepository
from app.features.todos.schemas import TodoCreate, TodoUpdate


def test_list_maps_models_and_orders_tasks_newest_first(model_factory, todo_values, todo):
    session = Mock(spec=Session)
    session.scalars.return_value = [model_factory(todo_values)]
    assert TodoRepository(session).list() == [todo]
    statement = session.scalars.call_args.args[0]
    expected = select(TodoRecord).order_by(TodoRecord.created_at.desc(), TodoRecord.id.desc())
    assert statement.compare(expected)
    compiled = str(statement.compile(dialect=postgresql.dialect()))
    assert "ORDER BY todos.created_at DESC, todos.id DESC" in compiled


def test_list_adds_where_clause_when_priority_filter_is_given(model_factory, todo_values, todo):
    from app.features.todos.schemas import Priority
    session = Mock(spec=Session)
    session.scalars.return_value = [model_factory(todo_values)]
    TodoRepository(session).list(priority=Priority.high)
    compiled = str(
        session.scalars.call_args.args[0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "WHERE todos.priority = 'high'" in compiled


def test_list_omits_where_clause_when_no_priority_filter(model_factory, todo_values):
    session = Mock(spec=Session)
    session.scalars.return_value = []
    TodoRepository(session).list(priority=None)
    compiled = str(
        session.scalars.call_args.args[0].compile(dialect=postgresql.dialect())
    )
    assert "WHERE" not in compiled


def test_get_returns_none_for_missing_task():
    session = Mock(spec=Session)
    session.get.return_value = None
    assert TodoRepository(session).get(404) is None
    session.get.assert_called_once_with(TodoRecord, 404)


def test_get_maps_found_record(model_factory, todo_values, todo):
    session = Mock(spec=Session)
    session.get.return_value = model_factory(todo_values)
    assert TodoRepository(session).get(todo_values["id"]) == todo


def test_create_sets_timestamps_and_persists(model_factory, todo_values):
    fixed_now = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
    session = Mock(spec=Session)

    def fake_refresh(record):
        for k, v in todo_values.items():
            setattr(record, k, v)

    session.refresh.side_effect = fake_refresh
    payload = TodoCreate(title="Plan the sprint", priority="high")

    with patch("app.features.todos.repository.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        TodoRepository(session).create(payload)

    record = session.add.call_args.args[0]
    assert record.title == "Plan the sprint"
    assert record.priority == "high"
    assert record.created_at == fixed_now
    assert record.updated_at == fixed_now
    session.commit.assert_called_once()
    session.refresh.assert_called_once_with(record)


def test_update_returns_none_for_missing_task():
    session = Mock(spec=Session)
    session.get.return_value = None
    assert TodoRepository(session).update(999, TodoUpdate(completed=True)) is None
    session.commit.assert_not_called()


def test_update_applies_only_set_fields_and_bumps_timestamp(model_factory, todo_values, todo):
    fixed_now = datetime(2026, 10, 8, 9, tzinfo=timezone.utc)
    record = model_factory(todo_values)
    session = Mock(spec=Session)
    session.get.return_value = record

    def fake_refresh(r):
        pass  # record is already the source of truth in this unit test

    session.refresh.side_effect = fake_refresh
    payload = TodoUpdate(title="Revised title")

    with patch("app.features.todos.repository.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        TodoRepository(session).update(todo_values["id"], payload)

    assert record.title == "Revised title"
    assert record.updated_at == fixed_now
    # Fields not in the patch must remain unchanged
    assert record.priority == todo_values["priority"]
    session.commit.assert_called_once()


def test_delete_returns_false_for_missing_task():
    session = Mock(spec=Session)
    session.get.return_value = None
    assert TodoRepository(session).delete(999) is False
    session.commit.assert_not_called()


def test_delete_removes_record_and_returns_true(model_factory, todo_values):
    record = model_factory(todo_values)
    session = Mock(spec=Session)
    session.get.return_value = record
    assert TodoRepository(session).delete(todo_values["id"]) is True
    session.delete.assert_called_once_with(record)
    session.commit.assert_called_once()
