import type { LoginResult } from './types'

export interface LocalTestUser {
  id: string
  fio: string
  password: string
  department: string
  position: string
  anyPassword: boolean
}

export const LOCAL_TEST_USERS: LocalTestUser[] = [
  {
    id: 'M11ZHALYBIN00000000000000000001',
    fio: 'Жалыбин Максим Дмитриевич',
    password: 'mdj',
    department: 'Сектор по внедрению искусственного интеллекта',
    position: 'Промпт-инженер 2 категории',
    anyPassword: true
  },
  {
    id: 'A11ADEA24A5000000000000000000001',
    fio: 'Анна Де Армас',
    password: 'anna',
    department: 'Тест',
    position: 'Тестовый пользователь',
    anyPassword: true
  },
  {
    id: 'E11C4E11K00000000000000000000001',
    fio: 'Ильченко Екатерина Александровна',
    password: 'ilchenko',
    department: 'Корпоративное управление',
    position: 'Помощник Председателя совета директоров',
    anyPassword: true
  }
]

function norm(value: string): string {
  return value.trim().toLowerCase().replace(/\s+/g, ' ')
}

function fioMatches(entered: string, full: string): boolean {
  const left = norm(entered)
  const right = norm(full)
  if (!left) return false
  if (left === right) return true
  const leftParts = left.split(' ')
  const rightParts = right.split(' ')
  return (
    leftParts.length >= 2 &&
    rightParts.length >= 2 &&
    leftParts[0] === rightParts[0] &&
    leftParts[1] === rightParts[1]
  )
}

export function findTestUser(fio: string): LocalTestUser | undefined {
  return LOCAL_TEST_USERS.find((user) => fioMatches(fio, user.fio))
}

export function isTestCredentials(fio: string, password: string): boolean {
  const user = findTestUser(fio)
  if (!user || !password) return false
  return user.anyPassword || password === user.password
}

export function testLoginResult(fio: string): LoginResult | null {
  const user = findTestUser(fio)
  if (!user) return null
  return {
    accessToken: '',
    user: {
      id: user.id,
      fio: user.fio,
      department: user.department,
      position: user.position,
      avatarUrl: null,
      canChangeDepartment: true,
      activityStatus: 'online',
      isSupport: false
    }
  }
}
