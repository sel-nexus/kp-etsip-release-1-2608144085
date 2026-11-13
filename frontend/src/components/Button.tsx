/** Share semantic action controls and visible pending feedback. */
import type { ButtonHTMLAttributes } from 'react';
interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> { loading?: boolean; variant?: 'primary' | 'secondary' }
const variants = { primary: 'button-primary', secondary: 'button-secondary' };
/** Keep disabled and pending states consistent without blocking keyboard focus otherwise. */
export function Button({ loading = false, variant = 'primary', children, disabled, ...props }: ButtonProps) {
  return (
    <button {...props} disabled={disabled || loading} aria-busy={loading} className={`button ${variants[variant]}`}>
      {children}
    </button>
  );
}
