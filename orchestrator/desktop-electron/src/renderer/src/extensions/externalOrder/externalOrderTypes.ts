export type ExternalOrderRole = { id: string; label: string }

export type ExternalOrderMeta = {
  role: string
  role_label: string
  can_switch: boolean
  roles: ExternalOrderRole[]
  desk: { title: string; sees: string[]; denied: string[] }
  integrations: { system: string; state: string; note: string }[]
  routes: ExternalOrderRole[]
}

export type ExternalOrderBrief = {
  id: string
  code: string
  customer: string
  product: string
  stage_label: string
  status: string
  status_label: string
  blocks: string[]
  payment_note: string
  onec_number?: string
  onec_key?: string
  onec_tkp_key?: string
  path_label?: string
}

export type ExternalOrderCheck = {
  id: string
  gate: string
  text: string
  owner_role: string
  owner_label: string
  status: string
  evidence: string
}

export type ExternalOrderDiff = {
  id: string
  code: string
  area: string
  title: string
  owner_role: string
  owner_label: string
  level: string
  status: string
  left_value: string
  right_value: string
  note: string
}

export type ExternalOrderFinding = {
  id: string
  field: string
  value: string
  source_ref: string
  status: string
  owner_role: string
}

export type ExternalOrderDecision = {
  id: string
  protocol: string
  decision: string
  conditions: string
  conditions_closed: boolean
  base_version: string
}

export type ExternalOrderMatrix = {
  counts: { done: number; gap: number; wait: number; out: number }
  rows: {
    id: string
    module: string
    requirement: string
    priority: string
    owner: string
    acceptance: string
    state: string
    state_label: string
    note: string
  }[]
}

export type ExternalOrderReview = {
  summary: string
  prompt: string
  checks: { id: string; gate: string; text: string; owner_label: string; verdict: string; note: string }[]
  diffs: { code: string; area: string; title: string; owner_label: string; level: string; verdict: string; note: string }[]
}

export type ExternalOnecTkp = {
  key: string
  number: string
  date: string
  amount: string
  status?: string
  client?: string
  counterparty?: string
  end_customer?: string
  deal?: string
  contract?: string
  order_number?: string
  organization?: string
  manager?: string
  agreement?: string
  currency?: string
  valid_until?: string
  delivery_days?: string
  payment_form?: string
  delivery?: string
  vat?: string
  approved?: string
  agreed?: string
  operation?: string
  has_order?: string
}

export type ExternalOnecSearch = {
  configured: boolean
  counterparties: { key: string; name: string; inn: string }[]
  orders: ExternalOnecTkp[]
}

export type ExternalOrder = ExternalOrderBrief & {
  inn: string
  contact: string
  route: string
  project_note: string
  owners: Record<string, string>
  sections: Record<string, Record<string, string>>
  checks: ExternalOrderCheck[]
  diffs: ExternalOrderDiff[]
  risks: { id: string; title: string; impact: string; status: string }[]
  decisions: ExternalOrderDecision[]
  findings: ExternalOrderFinding[]
  documents: { id: string; kind: string; title: string; version: string; note: string }[]
  audit: { id: string; actor_fio: string; actor_role: string; action: string; detail: string }[]
}
