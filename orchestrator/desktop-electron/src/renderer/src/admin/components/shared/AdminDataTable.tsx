export interface AdminTableColumn {
  id: string
  label: string
  align?: 'left' | 'center' | 'right'
  width?: string
}

interface AdminDataTableProps {
  columns: AdminTableColumn[]
  rows: React.ReactNode[][]
  stretchRows?: boolean
  selectedRowIndex?: number | null
  onRowClick?: (rowIndex: number) => void
}

export function AdminDataTable({
  columns,
  rows,
  stretchRows = false,
  selectedRowIndex = null,
  onRowClick
}: AdminDataTableProps): React.JSX.Element {
  return (
    <div
      className={stretchRows ? 'admin-table-wrap admin-table-wrap--stretch' : 'admin-table-wrap'}
      style={stretchRows ? ({ '--admin-table-rows': Math.max(rows.length, 1) } as React.CSSProperties) : undefined}
    >
      <table className="admin-table">
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.id} style={column.width ? { width: column.width } : undefined} className={column.align ? `is-${column.align}` : ''}>
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((cells, rowIndex) => (
            <tr
              key={rowIndex}
              className={[
                onRowClick ? 'is-clickable' : '',
                selectedRowIndex === rowIndex ? 'is-selected' : ''
              ].filter(Boolean).join(' ')}
              onClick={onRowClick ? () => onRowClick(rowIndex) : undefined}
            >
              {cells.map((cell, cellIndex) => (
                <td key={`${rowIndex}-${cellIndex}`} className={columns[cellIndex]?.align ? `is-${columns[cellIndex].align}` : ''}>
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
