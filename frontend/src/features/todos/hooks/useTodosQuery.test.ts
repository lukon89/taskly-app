import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import React from 'react'
import { beforeEach, expect, it, vi } from 'vitest'
import { todoFixture } from '../../../test/todoFixture'
import { todosApi } from '../api/todos'
import { useTodosQuery } from './useTodosQuery'

vi.mock('../api/todos', () => ({
  todosApi: { list: vi.fn() },
}))

beforeEach(() => vi.clearAllMocks())

it('returns todos from the API on a successful fetch', async () => {
  vi.mocked(todosApi.list).mockResolvedValue([todoFixture])

  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const wrapper = ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client }, children)

  const { result } = renderHook(() => useTodosQuery(), { wrapper })

  await waitFor(() => expect(result.current.isSuccess).toBe(true))
  expect(result.current.data).toEqual([todoFixture])
})

it('exposes an error state when the API call fails', async () => {
  vi.mocked(todosApi.list).mockRejectedValue(new Error('Network error'))

  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const wrapper = ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client }, children)

  const { result } = renderHook(() => useTodosQuery(), { wrapper })

  await waitFor(() => expect(result.current.isError).toBe(true))
  expect((result.current.error as Error).message).toBe('Network error')
})
