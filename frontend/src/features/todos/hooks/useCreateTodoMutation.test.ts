import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import React from 'react'
import { beforeEach, expect, it, vi } from 'vitest'
import { todoFixture } from '../../../test/todoFixture'
import { todosApi } from '../api/todos'
import { todoKeys } from '../api/queryKeys'
import { useCreateTodoMutation } from './useCreateTodoMutation'

vi.mock('../api/todos', () => ({
  todosApi: { create: vi.fn() },
}))

function makeWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client }, children)
}

beforeEach(() => vi.clearAllMocks())

it('prepends the saved todo to the cached list on success', async () => {
  const existing = { ...todoFixture, id: 1 }
  const saved = { ...todoFixture, id: 2, title: 'New task' }
  vi.mocked(todosApi.create).mockResolvedValue(saved)

  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  client.setQueryData(todoKeys.list, [existing])

  const wrapper = ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client }, children)

  const { result } = renderHook(() => useCreateTodoMutation(), { wrapper })
  result.current.mutate(saved)

  await waitFor(() => expect(result.current.isSuccess).toBe(true))

  const cached = client.getQueryData<typeof saved[]>(todoKeys.list)
  expect(cached?.[0]).toEqual(saved)
  expect(cached).toHaveLength(2)
})

it('deduplicates if the saved id already exists in the list', async () => {
  const saved = { ...todoFixture, id: 7 }
  vi.mocked(todosApi.create).mockResolvedValue(saved)

  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  client.setQueryData(todoKeys.list, [todoFixture]) // id: 7 already present

  const wrapper = ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client }, children)

  const { result } = renderHook(() => useCreateTodoMutation(), { wrapper })
  result.current.mutate(saved)

  await waitFor(() => expect(result.current.isSuccess).toBe(true))

  const cached = client.getQueryData<typeof saved[]>(todoKeys.list)
  expect(cached).toHaveLength(1)
  expect(cached?.[0]).toEqual(saved)
})
