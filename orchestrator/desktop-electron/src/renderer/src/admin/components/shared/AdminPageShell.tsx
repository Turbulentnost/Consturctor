interface AdminPageShellProps {
  breadcrumb: string
  children: React.ReactNode
  className?: string
}

export function AdminPageShell({ breadcrumb, children, className = '' }: AdminPageShellProps): React.JSX.Element {
  return (
    <div className={`admin-page ${className}`.trim()}>
      {breadcrumb ? <div className="admin-breadcrumb">{breadcrumb}</div> : null}
      {children}
    </div>
  )
}
