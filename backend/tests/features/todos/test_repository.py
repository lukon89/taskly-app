from unittest.mock import Mock

from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.features.todos.models import TodoRecord
from app.features.todos.repository import TodoRepository


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
