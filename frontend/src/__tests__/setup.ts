import { afterAll, afterEach, beforeAll, beforeEach } from 'vitest'
import { server } from '@/mocks/node'
import { resetMockDb } from '@/mocks/db'
import { setUnauthorizedHandler } from '@/api/client'
import { auth } from '@/stores/auth'

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
beforeEach(() => {
  resetMockDb()
  auth.reset()
  setUnauthorizedHandler(null)
})
afterEach(() => server.resetHandlers())
afterAll(() => server.close())
