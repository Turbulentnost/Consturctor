import {
  Award,
  ClipboardList,
  FileText,
  NotebookPen,
  ScrollText,
  Truck,
  Wallet,
  Mail,
  Wrench,
  type LucideIcon
} from 'lucide-react'

export type JournalId =
  | 'correspondence'
  | 'memos'
  | 'orders'
  | 'incentives'
  | 'assignments'
  | 'protocols'
  | 'payments'
  | 'forwarding'
  | 'requests'

export const DOCFLOW_JOURNALS: { id: JournalId; title: string; hint: string; icon: LucideIcon; tone: string }[] = [
  { id: 'correspondence', title: 'Корреспонденция', hint: 'Входящие и исходящие письма', icon: Mail, tone: 'blue' },
  { id: 'memos', title: 'Служебные записки', hint: 'Кому, от кого, срок и маршрут', icon: FileText, tone: 'green' },
  { id: 'orders', title: 'Приказы и распоряжения', hint: 'Статус, гриф и согласующие', icon: ScrollText, tone: 'purple' },
  {
    id: 'incentives',
    title: 'Приказы о мерах материального стимулирования',
    hint: 'Сотрудник, процент и основание',
    icon: Award,
    tone: 'purple'
  },
  { id: 'assignments', title: 'Поручения', hint: 'Мероприятия, исполнители и сроки', icon: ClipboardList, tone: 'orange' },
  { id: 'protocols', title: 'Протоколы', hint: 'Совещания, решения и участники', icon: NotebookPen, tone: 'teal' },
  {
    id: 'payments',
    title: 'Заявка на расходование ДС',
    hint: 'Суммы, статусы оплаты и получатели',
    icon: Wallet,
    tone: 'green'
  },
  {
    id: 'forwarding',
    title: 'Поручение экспедитору',
    hint: 'Доставка, груз и ответственные',
    icon: Truck,
    tone: 'blue'
  },
  {
    id: 'requests',
    title: 'Заявки в службы',
    hint: '1С, IT, эксплуатация, номенклатура, рынок и PR',
    icon: Wrench,
    tone: 'orange'
  }
]
