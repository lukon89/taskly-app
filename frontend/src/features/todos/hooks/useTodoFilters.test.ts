import { act, renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { todoFixture } from '../../../test/todoFixture'
import { useTodoFilters } from './useTodoFilters'

const completedTodo = { ...todoFixture, id: 2, completed: true }
const todos = [todoFixture, completedTodo]

describe('useTodoFilters', () => {
  it('initialises with all todos visible and default controls', () => {
    const { result } = renderHook(() => useTodoFilters(todos))
    expect(result.current.filter).toBe('all')
    expect(result.current.search).toBe('')
    expect(result.current.sort).toBe('newest')
    expect(result.current.visible).toEqual(todos)
  })

  it('filters to active todos only', () => {
    const { result } = renderHook(() => useTodoFilters(todos))
    act(() => result.current.setFilter('active'))
    expect(result.current.visible).toEqual([todoFixture])
  })

  it('filters to completed todos only', () => {
    const { result } = renderHook(() => useTodoFilters(todos))
    act(() => result.current.setFilter('completed'))
    expect(result.current.visible).toEqual([completedTodo])
  })

  it('searches case-insensitively across title and description', () => {
    const matchingByTitle = { ...todoFixture, id: 3, title: 'Fix the API bug' }
    const { result } = renderHook(() =>
      useTodoFilters([todoFixture, matchingByTitle]),
    )
    act(() => result.current.setSearch('api'))
    expect(result.current.visible).toEqual([matchingByTitle])
  })

  it('returns an empty list when search matches nothing', () => {
    const { result } = renderHook(() => useTodoFilters(todos))
    act(() => result.current.setSearch('xyzzy'))
    expect(result.current.visible).toHaveLength(0)
  })
})
