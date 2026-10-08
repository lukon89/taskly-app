import { MutationCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook } from '@testing-library/react'
import React from 'react'
import { expect, it } from 'vitest'
import { useTodosBusy } from './useTodosBusy'

it('returns false when no mutations are in flight', () => {
  const client = new QueryClient()
  const wrapper = ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client }, children)

  const { result } = renderHook(() => useTodosBusy(), { wrapper })
  expect(result.current).toBe(false)
})
