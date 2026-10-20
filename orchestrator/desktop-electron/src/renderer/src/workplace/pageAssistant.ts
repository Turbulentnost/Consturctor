import { PAGE_LABELS, type PageKey } from '../components/Sidebar'

export type AssistantAction =
  | { type: 'navigate'; key: PageKey }
  | { type: 'open_url'; url: string }

export type AssistantReply = {
  text: string
  actions: AssistantAction[]
  /** Вопрос не про переход: его отвечает агент приложения. */
  askAgent: boolean
}

type PageGuide = {
  key: PageKey
  about: string
  aliases: string[]
}

const GUIDES: PageGuide[] = [
  {
    key: 'today',
    about: 'Рабочий стол: что сделать сегодня, просроченное и вход в остальные разделы.',
    aliases: ['сегодня', 'главная', 'рабочий стол']
  },
  {
    key: 'tasks',
    about: 'Все задачи сотрудника: документооборот, проекты и платформа.',
    aliases: ['задачи', 'задачу', 'мои задачи']
  },
  {
    key: 'processes',
    about: 'Процессы должности: статус, регламент и связанные задачи.',
    aliases: ['процессы', 'процесс']
  },
  {
    key: 'projects',
    about: 'Проекты TurboProject: роли, сроки и задачи.',
    aliases: ['turboproject', 'турбопроект', 'проекты', 'проект']
  },
  {
    key: 'mail',
    about: 'Письма Outlook и процессы, которые к ним привязаны.',
    aliases: ['письма', 'письмо', 'почта', 'outlook']
  },
  {
    key: 'docflow',
    about: 'Документооборот: корреспонденция, служебные записки, приказы, поручения и протоколы.',
    aliases: ['документооборот', 'протокол', 'служебн']
  },
  {
    key: 'meetings',
    about: 'Совещания: календарь, подготовка и материалы.',
    aliases: ['совещания', 'совещание', 'встречи']
  },
  {
    key: 'decisions',
    about: 'Решения по процессам, которые нужно подтвердить.',
    aliases: ['решения', 'решение']
  },
  {
    key: 'kpi',
    about: 'Показатели KPI за выбранный период.',
    aliases: ['kpi', 'показатели', 'показатель']
  },
  {
    key: 'assignments_registry',
    about: 'Реестр поручений и их исполнение.',
    aliases: ['реестр поручений', 'поручения', 'поручение']
  },
  {
    key: 'subordinate_tasks',
    about: 'Задачи, которые вы поставили подчиненным в 1С.',
    aliases: ['подчиненным', 'подчиненные', 'задачи подчинен']
  },
  {
    key: 'knowledge',
    about: 'База знаний: регламенты и материалы.',
    aliases: ['база знаний', 'регламент']
  },
  {
    key: 'extensions',
    about: 'Подключённые расширения рабочего места.',
    aliases: ['расширения', 'расширение']
  },
  {
    key: 'agent_library',
    about: 'Библиотека агентов, которых можно запустить.',
    aliases: ['библиотека агентов', 'библиотека']
  },
  {
    key: 'ai_agents',
    about: 'ИИ-агенты: запуск и настройка.',
    aliases: ['ии-агент', 'ии агент']
  },
  {
    key: 'history',
    about: 'История запусков и действий.',
    aliases: ['история']
  },
  {
    key: 'settings',
    about: 'Настройки приложения и учётной записи.',
    aliases: ['настройки', 'настройка']
  },
  {
    key: 'task_create',
    about: 'Форма новой задачи сотруднику.',
    aliases: ['создать задачу', 'новая задача']
  }
]

const MOVE_RE =
  /(открой|открыть|перейди|перейти|покажи|показать|зайди|зайти|перенеси|перенести|веди меня|веди к)/

function fold(value: string): string {
  return value.toLowerCase().replace(/ё/g, 'е').replace(/\s+/g, ' ').trim()
}

export function pageGuide(key: PageKey | null): { title: string; about: string } {
  if (!key) return { title: 'Оркестратор', about: 'Рабочее место сотрудника.' }
  const guide = GUIDES.find((item) => item.key === key)
  return {
    title: PAGE_LABELS[key] || key,
    about: guide?.about || 'Раздел приложения «Оркестратор».'
  }
}

export function assistantGreeting(key: PageKey | null): string {
  const page = pageGuide(key)
  return `Я помощник по приложению. Сейчас открыто: «${page.title}». ${page.about} Спросите про эту страницу или про всё приложение — перейду в нужный раздел или открою сайт в браузере.`
}

function findPage(text: string): PageGuide | null {
  let best: { guide: PageGuide; length: number } | null = null
  for (const guide of GUIDES) {
    for (const alias of guide.aliases) {
      if (!text.includes(alias)) continue
      if (!best || alias.length > best.length) best = { guide, length: alias.length }
    }
  }
  return best?.guide ?? null
}

function normalizeUrl(raw: string): string {
  const trimmed = raw.trim().replace(/[.,;]+$/, '')
  if (/^https?:\/\//i.test(trimmed)) return trimmed
  return `https://${trimmed}`
}

function extractUrl(text: string, folded: string): string | null {
  const direct = text.match(/https?:\/\/[^\s)]+/i)
  if (direct) return normalizeUrl(direct[0])
  const named = text.match(
    /(?:сайт|браузере|браузер|интернете)\s+([a-z0-9][-a-z0-9.]*\.[a-zа-я]{2,}(?:\/\S*)?)/i
  )
  if (named) return normalizeUrl(named[1])
  if (!MOVE_RE.test(folded) && !/(браузер|сайт)/.test(folded)) return null
  const domain = text.match(/\b([a-z0-9][-a-z0-9]{0,62}\.(?:ru|com|рф|org|net|io)(?:\/[^\s)]*)?)/i)
  return domain ? normalizeUrl(domain[1]) : null
}

export function replyToAssistant(message: string, pageKey: PageKey | null): AssistantReply {
  const text = message.trim()
  const folded = fold(text)
  if (!folded) return { text: 'Напишите вопрос или куда перейти.', actions: [], askAgent: false }

  const url = extractUrl(text, folded)
  const wantsMove = MOVE_RE.test(folded) || /(браузер|сайт)/.test(folded)
  if (url && (wantsMove || /^https?:/i.test(text.trim()))) {
    return {
      text: `Открываю в браузере: ${url}`,
      actions: [{ type: 'open_url', url }],
      askAgent: false
    }
  }

  const page = findPage(folded)
  if (page && wantsMove) {
    const title = PAGE_LABELS[page.key]
    return {
      text: `Открываю раздел «${title}». ${page.about}`,
      actions: [{ type: 'navigate', key: page.key }],
      askAgent: false
    }
  }

  if (/(что (это|здесь|на этой)|эта страниц|этот раздел|где я|что открыто|про эту страниц)/.test(folded)) {
    const here = pageGuide(pageKey)
    return {
      text: `Сейчас открыто «${here.title}». ${here.about}`,
      actions: [],
      askAgent: false
    }
  }

  if (/(какие раздел|что умеешь|что ты умеешь|что можешь|карта приложения|помощь по приложению)/.test(folded)) {
    const lines = GUIDES.map((guide) => `• ${PAGE_LABELS[guide.key]} — ${guide.about}`).join('\n')
    return {
      text: `Могу ответить по текущей странице и по всему приложению, открыть раздел или сайт в браузере.\n${lines}`,
      actions: [],
      askAgent: false
    }
  }

  if (page && /(где|что такое|зачем|для чего|расскажи)/.test(folded)) {
    return {
      text: `«${PAGE_LABELS[page.key]}» — ${page.about} Если нужно перейти, напишите «открой ${PAGE_LABELS[page.key]}».`,
      actions: [],
      askAgent: false
    }
  }

  return { text: '', actions: [], askAgent: true }
}

export function agentPrompt(message: string, pageKey: PageKey | null): string {
  const here = pageGuide(pageKey)
  const keys = GUIDES.map((guide) => `${guide.key} = ${PAGE_LABELS[guide.key]}`).join('; ')
  return [
    'Ответь кратко по-русски. Ты помощник внутри приложения «Оркестратор».',
    'Отвечай по текущей странице и по всему приложению.',
    'Если сотруднику нужно открыть раздел, последней строкой напиши [[nav:КЛЮЧ]] и больше ничего.',
    `Ключи: ${keys}.`,
    'Если нужно открыть сайт в браузере, последней строкой напиши [[url:https://адрес]].',
    'Маркер добавляй только когда сотрудник просит куда-то перейти.',
    `Сейчас открыто: «${here.title}». ${here.about}`,
    `Вопрос: ${message.trim()}`
  ].join('\n')
}

const MARKER = /\[\[(nav|url):([^\]]+)\]\]/g

export function takeMarkers(answer: string): { text: string; actions: AssistantAction[] } {
  const actions: AssistantAction[] = []
  const text = answer
    .replace(MARKER, (_all, kind: string, value: string) => {
      const raw = String(value || '').trim()
      if (kind === 'nav') {
        const guide = GUIDES.find((item) => item.key === raw)
        if (guide) actions.push({ type: 'navigate', key: guide.key })
      } else if (/^https?:\/\//i.test(normalizeUrl(raw))) {
        actions.push({ type: 'open_url', url: normalizeUrl(raw) })
      }
      return ''
    })
    .trim()
  return { text: text || 'Готово.', actions }
}
