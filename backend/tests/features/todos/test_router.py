import pytest

from app.features.todos.schemas import TodoCreate, TodoUpdate


def test_list_returns_tasks_from_repository(client, repository_mock, todo):
    repository_mock.list.return_value = [todo]
    response = client.get("/api/todos")
    assert response.status_code == 200
    assert response.json() == [todo.model_dump(mode="json")]
    repository_mock.list.assert_called_once_with()


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
