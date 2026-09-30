import { useEffect, useMemo, useState } from 'react'
import { X } from 'lucide-react'
import {
  fetchFinanceEmployeeSalaries,
  fetchFinanceEmployees,
  type FinanceEmployee,
  type FinanceSalary
} from '../financeApi'
import { AdminDataTable } from '../components/shared/AdminDataTable'
import { AdminFilterBar } from '../components/shared/AdminFilterBar'
import { AdminPageHeader } from '../components/shared/AdminPageHeader'
import { AdminPageShell } from '../components/shared/AdminPageShell'
import { matchesSearch } from '../utils/tableFilters'

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Не удалось загрузить данные'
}

export function FinanceEmployeesPage(): React.JSX.Element {
  const [employees, setEmployees] = useState<FinanceEmployee[]>([])
  const [salaries, setSalaries] = useState<FinanceSalary[]>([])
  const [drawerEmployee, setDrawerEmployee] = useState<FinanceEmployee | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const visibleEmployees = useMemo(
    () =>
      employees.filter((employee) =>
        matchesSearch([employee.fio, employee.position, employee.department], search)
      ),
    [employees, search]
  )

  useEffect(() => {
    let active = true
    void fetchFinanceEmployees()
      .then((items) => {
        if (!active) return
        setEmployees(items)
      })
      .catch((reason) => active && setError(errorMessage(reason)))
      .finally(() => active && setLoading(false))
    return () => {
      active = false
    }
  }, [])

  async function openSalaries(employee: FinanceEmployee): Promise<void> {
    setDrawerEmployee(employee)
    setSalaries([])
    setError('')
    try {
      setSalaries(await fetchFinanceEmployeeSalaries(employee.id))
    } catch (reason) {
      setError(errorMessage(reason))
    }
  }

  return (
    <AdminPageShell breadcrumb="" className="admin-page--fill finance-page finance-employees-page">
      <AdminPageHeader
        title="Сотрудники"
        subtitle="История изменения окладов сотрудников"
      />
      {error ? <p className="finance-message finance-message--error" role="alert">{error}</p> : null}
      <section className="admin-panel admin-panel--table-fill finance-employees-panel">
        <h2 className="finance-section-title">Список сотрудников</h2>
        <AdminFilterBar
          filters={[]}
          searchPlaceholder="Поиск по ФИО, должности или подразделению"
          onFiltersChange={(_, value) => setSearch(value)}
        />
        {loading ? <p className="finance-message">Загрузка…</p> : null}
        {!loading && !employees.length ? <p className="finance-empty">Сотрудники не найдены</p> : null}
        {!loading && employees.length > 0 && !visibleEmployees.length ? (
          <p className="finance-empty">По вашему запросу ничего не найдено</p>
        ) : null}
        <div className="admin-table-area">
          <AdminDataTable
            columns={[
              { id: 'fio', label: 'ФИО' },
              { id: 'position', label: 'Должность' },
              { id: 'department', label: 'Подразделение' }
            ]}
            rows={visibleEmployees.map((employee) => [
              employee.id ? (
                <button
                  type="button"
                  className="finance-link-button"
                  onClick={() => void openSalaries(employee)}
                >
                  {employee.fio}
                </button>
              ) : employee.fio,
              employee.position || '—',
              employee.department || '—'
            ])}
          />
        </div>
      </section>

      {drawerEmployee ? (
        <div className="finance-drawer-backdrop" onMouseDown={() => setDrawerEmployee(null)}>
          <aside
            className="finance-drawer"
            aria-label={`История окладов: ${drawerEmployee.fio}`}
            onMouseDown={(event) => event.stopPropagation()}
          >
            <header className="finance-drawer__header">
              <div>
                <h2>История окладов</h2>
                <p>{drawerEmployee.fio}</p>
                <p>
                  {[drawerEmployee.position, drawerEmployee.department].filter(Boolean).join(' · ')}
                </p>
              </div>
              <button type="button" aria-label="Закрыть" onClick={() => setDrawerEmployee(null)}>
                <X size={20} />
              </button>
            </header>
            {!salaries.length ? <p className="finance-empty">История окладов отсутствует</p> : null}
            <div className="finance-salary-list">
              {salaries.map((salary) => (
                <article key={salary.id}>
                  <div>
                    <strong>{salary.period || 'Дата не указана'}</strong>
                    <p>{salary.department ? `Подразделение: ${salary.department}` : 'Без подразделения — загружен до привязки, перезагрузите'}</p>
                    {salary.reason ? <p>{salary.reason}</p> : null}
                  </div>
                  <span>{salary.amount || '—'} {salary.currency}</span>
                </article>
              ))}
            </div>
          </aside>
        </div>
      ) : null}
    </AdminPageShell>
  )
}
