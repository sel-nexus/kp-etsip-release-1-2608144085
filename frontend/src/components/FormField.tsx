/** Bind required credential inputs to labels and safe inline errors. */
import type { InputHTMLAttributes } from 'react';
interface FormFieldProps extends InputHTMLAttributes<HTMLInputElement> { id: string; label: string; error?: string }
/** Preserve native input behavior including paste, zoom, and password managers. */
export function FormField({ id, label, error, required, ...props }: FormFieldProps) {
  return (
    <div className="form-field">
      <label htmlFor={id}>{label}</label>
      <input {...props} id={id} required={required} aria-required={required} aria-invalid={Boolean(error)}
        aria-describedby={error ? `${id}-error` : undefined} />
      {error && <p id={`${id}-error`} role="alert" className="error-text">{error}</p>}
    </div>
  );
}
