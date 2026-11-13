/** Render a typed semantic table with safe horizontal overflow. */
import type { ReactNode } from 'react';
interface Column<T> { key: string; label: string; render: (row: T) => ReactNode }
interface DataTableProps<T> { caption: string; rows: T[]; columns: Column<T>[]; rowKey: (row: T) => string }
/** Preserve column relationships for assistive technology. */
export function DataTable<T>({ caption, rows, columns, rowKey }: DataTableProps<T>) {
  return (
    <div className="table-scroll" tabIndex={0} role="region" aria-label={caption}>
      <table>
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key} scope="col">{column.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={rowKey(row)}>
              {columns.map((column) => (
                <td key={column.key}>{column.render(row)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
