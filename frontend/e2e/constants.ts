import path from 'node:path'

// A fixed admin token for the e2e server only. It is not a secret.
export const ADMIN_TOKEN = 'e2e-admin-token-not-secret-0123456789'
export const STORAGE_STATE = (dbName: string) => path.resolve(import.meta.dirname, '..', 'test-results', `${dbName}.state.json`)
