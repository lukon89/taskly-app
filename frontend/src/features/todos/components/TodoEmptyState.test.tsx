import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import { TodoEmptyState } from './TodoEmptyState'

vi.mock('../../../design-system', () => import('../../../design-system/mocks'))

it('shows the first-task prompt when there are no todos at all', () => {
  render(
    <TodoEmptyState hasTodos={false} disabled={false} onCreate={vi.fn()} />,
  )
  expect(screen.getByRole('heading', { name: 'Add your first task' })).toBeVisible()
  expect(screen.getByRole('button', { name: /add your first task/i })).toBeVisible()
})

it('shows the no-match prompt when todos exist but none match the filter', () => {
  render(
    <TodoEmptyState hasTodos={true} disabled={false} onCreate={vi.fn()} />,
  )
  expect(screen.getByRole('heading', { name: 'No matching tasks' })).toBeVisible()
  expect(screen.queryByRole('button')).toBeNull()
})

it('calls onCreate when the add-first-task button is clicked', async () => {
  const user = userEvent.setup()
  const onCreate = vi.fn()
  render(
    <TodoEmptyState hasTodos={false} disabled={false} onCreate={onCreate} />,
  )
  await user.click(screen.getByRole('button', { name: /add your first task/i }))
  expect(onCreate).toHaveBeenCalledTimes(1)
})

it('disables the button when the busy flag is set', () => {
  render(
    <TodoEmptyState hasTodos={false} disabled={true} onCreate={vi.fn()} />,
  )
  expect(screen.getByRole('button', { name: /add your first task/i })).toBeDisabled()
})
