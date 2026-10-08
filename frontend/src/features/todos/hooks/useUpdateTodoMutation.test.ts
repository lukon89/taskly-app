import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import React from 'react'
import { beforeEach, expect, it, vi } from 'vitest'
import { todoFixture } from '../../../test/todoFixture'
import { todosApi } from '../api/todos'
import { todoKeys } from '../api/queryKeys'
import { useUpdateTodoMutation } from './useUpdateTodoMutation'

vi.mock('../api/todos', () => ({
  todosApi: { update: vi.fn() },
}))

beforeEach(() => vi.clearAllMocks())

it('replaces the updated todo in the cached list on success', async () => {
  const other = { ...todoFixture, id: 99 }
  const saved = { ...todoFixture, title: 'Revised title' }
  vi.mocked(todosApi.update).mockResolvedValue(saved)

  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  client.setQueryData(todoKeys.list, [todoFixture, other])

  const wrapper = ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client }, children)

  const { result } = renderHook(() => useUpdateTodoMutation(), { wrapper })
  result.current.mutate({ id: todoFixture.id, input: { title: 'Revised title' } })

  await waitFor(() => expect(result.current.isSuccess).toBe(true))

  const cached = client.getQueryData<typeof todoFixture[]>(todoKeys.list)
  expect(cached?.[0]).toEqual(saved)
  expect(cached).toHaveLength(2)
})

it('does not mutate other items in the list', async () => {
  const other = { ...todoFixture, id: 99, title: 'Keep me' }
  const saved = { ...todoFixture, completed: true }
  vi.mocked(todosApi.update).mockResolvedValue(saved)

  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  client.setQueryData(todoKeys.list, [todoFixture, other])

  const wrapper = ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client }, children)

  const { result } = renderHook(() => useUpdateTodoMutation(), { wrapper })
  result.current.mutate({ id: todoFixture.id, input: { completed: true } })

  await waitFor(() => expect(result.current.isSuccess).toBe(true))

  const cached = client.getQueryData<typeof todoFixture[]>(todoKeys.list)
  expect(cached?.find((t) => t.id === 99)).toEqual(other)
})
