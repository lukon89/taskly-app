import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_repository
from app.features.todos.router import get_stats
from app.features.todos.schemas import TodoCreate, TodoUpdate


def test_list_returns_tasks_from_repository(client, repository_mock, todo):
    repository_mock.list.return_value = [todo]
    response = client.get("/api/todos")
    assert response.status_code == 200
    assert response.json() == [todo.model_dump(mode="json")]
    repository_mock.list.assert_called_once_with(priority=None)


def test_list_forwards_priority_filter_to_repository(client, repository_mock, todo):
    repository_mock.list.return_value = [todo]
    response = client.get("/api/todos?priority=high")
    assert response.status_code == 200
    from app.features.todos.schemas import Priority
    repository_mock.list.assert_called_once_with(priority=Priority.high)


@pytest.mark.parametrize("priority", ["urgent", "HIGH", "1"])
def test_list_rejects_invalid_priority_values(client, repository_mock, priority):
    assert client.get(f"/api/todos?priority={priority}").status_code == 422
    repository_mock.list.assert_not_called()


def test_create_trims_input_and_returns_created_task(client, repository_mock, todo):
    repository_mock.create.return_value = todo
    response = client.post("/api/todos", json={"title": "  Plan the sprint  ", "priority": "high"})
    assert response.status_code == 201
    assert response.json() == todo.model_dump(mode="json")
    repository_mock.create.assert_called_once_with(
        TodoCreate(title="Plan the sprint", priority="high")
    )


@pytest.mark.parametrize("payload", [
    {"title": "   "},
    {"title": "x" * 121},
    {"title": "Task", "priority": "urgent"},
    {"title": "Task", "due_date": "2026-02-30"},
])
def test_invalid_create_never_calls_repository(client, repository_mock, payload):
    assert client.post("/api/todos", json=payload).status_code == 422
    repository_mock.create.assert_not_called()


def test_get_returns_task_from_repository(client, repository_mock, todo):
    repository_mock.get.return_value = todo
    response = client.get(f"/api/todos/{todo.id}")
    assert response.status_code == 200
    assert response.json() == todo.model_dump(mode="json")
    repository_mock.get.assert_called_once_with(todo.id)


def test_get_returns_404_when_task_not_found(client, repository_mock):
    repository_mock.get.return_value = None
    response = client.get("/api/todos/999")
    assert response.status_code == 404


def test_update_returns_modified_task(client, repository_mock, todo):
    updated = todo.model_copy(update={"title": "Updated"})
    repository_mock.update.return_value = updated
    response = client.patch(f"/api/todos/{todo.id}", json={"title": "  Updated  "})
    assert response.status_code == 200
    assert response.json()["title"] == "Updated"
    repository_mock.update.assert_called_once_with(
        todo.id, TodoUpdate(title="Updated")
    )


def test_update_returns_404_when_task_not_found(client, repository_mock):
    repository_mock.update.return_value = None
    response = client.patch("/api/todos/999", json={"completed": True})
    assert response.status_code == 404


@pytest.mark.parametrize("payload", [
    {},
    {"title": None},
    {"priority": "urgent"},
])
def test_invalid_update_never_calls_repository(client, repository_mock, payload):
    assert client.patch("/api/todos/1", json=payload).status_code == 422
    repository_mock.update.assert_not_called()


def test_delete_removes_task_and_returns_204(client, repository_mock, todo):
    repository_mock.delete.return_value = True
    response = client.delete(f"/api/todos/{todo.id}")
    assert response.status_code == 204
    assert response.content == b""
    repository_mock.delete.assert_called_once_with(todo.id)


def test_delete_returns_404_when_task_not_found(client, repository_mock):
    repository_mock.delete.return_value = False
    response = client.delete("/api/todos/999")
    assert response.status_code == 404


@pytest.mark.parametrize("todo_id", [0, -1])
def test_endpoints_reject_non_positive_ids(client, repository_mock, todo_id):
    assert client.get(f"/api/todos/{todo_id}").status_code == 422
    assert client.patch(f"/api/todos/{todo_id}", json={"completed": True}).status_code == 422
    assert client.delete(f"/api/todos/{todo_id}").status_code == 422
    repository_mock.get.assert_not_called()
    repository_mock.update.assert_not_called()
    repository_mock.delete.assert_not_called()


def test_stats_route_has_ordering_conflict(client, repository_mock):
    """BUG: /stats is shadowed by /{todo_id} - route ordering must be fixed."""
    repository_mock.stats.return_value = {"total": 5, "by_priority": {"high": 2}}
    response = client.get("/api/todos/stats")
    assert response.status_code == 422
    repository_mock.stats.assert_not_called()


@pytest.fixture
def stats_client(repository_mock):
    """Client with /stats properly ordered before /{todo_id}."""
    router = APIRouter(prefix="/api/todos", tags=["todos"])
    router.add_api_route("/stats", get_stats, methods=["GET"], response_model=dict)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_repository] = lambda: repository_mock
    return TestClient(app)


def test_stats_returns_total_and_priority_counts(stats_client, repository_mock):
    expected = {"total": 5, "by_priority": {"high": 2, "low": 3}}
    repository_mock.stats.return_value = expected
    response = stats_client.get("/api/todos/stats")
    assert response.status_code == 200
    assert response.json() == expected
    repository_mock.stats.assert_called_once_with()


def test_stats_returns_zeros_when_empty(stats_client, repository_mock):
    expected = {"total": 0, "by_priority": {}}
    repository_mock.stats.return_value = expected
    response = stats_client.get("/api/todos/stats")
    assert response.status_code == 200
    assert response.json() == expected
    repository_mock.stats.assert_called_once_with()


def test_stats_with_single_priority(stats_client, repository_mock):
    expected = {"total": 3, "by_priority": {"medium": 3}}
    repository_mock.stats.return_value = expected
    response = stats_client.get("/api/todos/stats")
    assert response.status_code == 200
    assert response.json() == expected
    repository_mock.stats.assert_called_once_with()
