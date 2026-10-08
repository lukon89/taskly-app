import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import React from 'react'
import { beforeEach, expect, it, vi } from 'vitest'
import { todoFixture } from '../../../test/todoFixture'
import { todosApi } from '../api/todos'
import { todoKeys } from '../api/queryKeys'
import { useDeleteTodoMutation } from './useDeleteTodoMutation'

vi.mock('../api/todos', () => ({
  todosApi: { remove: vi.fn() },
}))

beforeEach(() => vi.clearAllMocks())

it('removes the deleted todo from the cached list on success', async () => {
  const other = { ...todoFixture, id: 99 }
  vi.mocked(todosApi.remove).mockResolvedValue(undefined)

  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  client.setQueryData(todoKeys.list, [todoFixture, other])

  const wrapper = ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client }, children)

  const { result } = renderHook(() => useDeleteTodoMutation(), { wrapper })
  result.current.mutate(todoFixture.id)

  await waitFor(() => expect(result.current.isSuccess).toBe(true))

  const cached = client.getQueryData<typeof todoFixture[]>(todoKeys.list)
  expect(cached).toEqual([other])
})

it('leaves cache unchanged if deleted id was not present', async () => {
  vi.mocked(todosApi.remove).mockResolvedValue(undefined)

  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  client.setQueryData(todoKeys.list, [todoFixture])

  const wrapper = ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client }, children)

  const { result } = renderHook(() => useDeleteTodoMutation(), { wrapper })
  result.current.mutate(999)

  await waitFor(() => expect(result.current.isSuccess).toBe(true))

  const cached = client.getQueryData<typeof todoFixture[]>(todoKeys.list)
  expect(cached).toEqual([todoFixture])
})
