import { describe, expect, it } from 'vitest'
import { mcpCommand, planLesson, type Plan } from './mcp'

const plan: Plan = { created_at: '', summary: '', focus_themes: [], lessons: ['b', 'c', 'zz'], openings: [] }

describe('planLesson', () => {
  it('takes the first plan lesson that is not done', () => {
    const lessons = [{ slug: 'a' }, { slug: 'b', completed: true }, { slug: 'c', completed: false }]
    expect(planLesson(plan, lessons)?.slug).toBe('c')
  })
  it('returns null when all are done or unknown', () => {
    expect(planLesson(plan, [{ slug: 'b', completed: true }, { slug: 'c', completed: true }])).toBeNull()
  })
})

describe('mcpCommand', () => {
  it('puts address and key into the command', () => {
    expect(mcpCommand('http://h/mcp', 'k')).toBe(
      'claude mcp add --scope user --transport http chess http://h/mcp --header "Authorization: Bearer k"',
    )
  })
})
