// Правила для формы «Новый пользователь» — те же, что в контракте (UserCreate).
const USERNAME_RE = /^[A-Za-z0-9._-]+$/

/** Пустая строка — логин подходит, иначе текст ошибки. */
export function validateUsername(username: string): string {
  if (username.length < 3) return 'Логин — от 3 символов'
  if (username.length > 32) return 'Логин — не длиннее 32 символов'
  if (!USERNAME_RE.test(username)) return 'Только латинские буквы, цифры и «.», «_», «-»'
  return ''
}

/** Пустая строка — пароль подходит, иначе текст ошибки. */
export function validatePassword(password: string): string {
  if (password.length < 8) return 'Пароль — не короче 8 символов'
  if (password.length > 256) return 'Пароль — не длиннее 256 символов'
  return ''
}
