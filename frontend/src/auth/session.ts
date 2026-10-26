// The login of the current user. Device storage keys use it, so two users on one device stay apart.
let current = ''
export const setSessionLogin = (login: string) => {
  current = login
}
export const sessionLogin = () => current
export const sessionKey = (name: string) => `${name}:${current}`
