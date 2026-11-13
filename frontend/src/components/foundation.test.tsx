/** Verify the actual shared foundation controls and inherited token contracts. */
import { useState } from 'react';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { AppLayout } from './AppLayout';
import { Modal } from './Modal';
import { Button } from './Button';
import { Pagination } from './Pagination';
import { FormField } from './FormField';
import { DataTable } from './DataTable';
import { landingChoices, landingPath } from '../features/profile/profileApi';
import theme from '../../tailwind.config';
import type { SafeUser } from '../types';
const state = vi.hoisted(() => ({ user: null as SafeUser | null, error: null as string | null, logout: vi.fn(), refresh: vi.fn() }));
vi.mock('../features/auth/SessionProvider', () => ({ useSession: () => ({ ...state, loading: false }) }));
const roles = ['Administrator', 'Executive', 'Portfolio Leader', 'Engineer', 'Auditor', 'Read Only'] as const;
beforeEach(() => {
  state.user = { id: 'id', name: 'Demo', email: 'demo@example.com', role: 'Engineer', portfolioAccess: [], status: 'Active', mustChangePassword: false, defaultLandingPage: null };
  state.error = null;
});

/** Compose real controls with observable open/close state. */
function DialogHarness({ empty = false }: { empty?: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button onClick={() => setOpen(true)}>Open dialog</Button>
      {open && (
        <Modal title="Confirm action" onClose={() => setOpen(false)}>
          {!empty && <Button onClick={() => setOpen(false)}>Cancel</Button>}
          {!empty && <Button>Confirm</Button>}
          <p>Review before continuing</p>
        </Modal>
      )}
    </>
  );
}

describe('foundation semantics and navigation', () => {
  it.each(roles)('offers only role-ceiling administration links for %s', (role) => {
    state.user!.role = role;
    render(<MemoryRouter initialEntries={['/applications']}><AppLayout><h1>Inventory</h1></AppLayout></MemoryRouter>);
    const nav = screen.getByRole('navigation', { name: 'Session navigation' });
    expect(within(nav).getByRole('link', { name: 'Applications' })).toHaveAttribute('aria-current', 'page');
    expect(within(nav).queryByRole('link', { name: 'Users' }) !== null).toBe(role === 'Administrator');
    expect(within(nav).queryByRole('link', { name: 'Roles' }) !== null).toBe(role === 'Administrator');
    expect(within(nav).queryByRole('link', { name: 'Audit history' }) !== null).toBe(['Administrator', 'Auditor'].includes(role));
    for (const choice of landingChoices(role)) expect(landingPath(choice)).not.toBe('/');
    expect(landingPath('unsupported')).toBe('/');
    expect(landingPath(null)).toBe('/');
  });
  it('opens and traps the mobile drawer, closes on a link, and restores trigger focus', async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><AppLayout /></MemoryRouter>);
    const trigger = screen.getByRole('button', { name: 'Open navigation' });
    await user.click(trigger);
    const dialog = screen.getByRole('dialog', { name: 'Navigation' });
    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    expect(within(dialog).getByRole('button', { name: 'Close navigation' })).toHaveFocus();
    await user.keyboard('{Shift>}{Tab}{/Shift}');
    expect(within(dialog).getByRole('button', { name: 'Sign out' })).toHaveFocus();
    await user.click(within(dialog).getByRole('link', { name: 'Applications' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });
  it('keeps the first-password gate ahead of inventory navigation', () => {
    state.user!.role = 'Administrator';
    state.user!.mustChangePassword = true;
    render(<MemoryRouter><AppLayout><h1>Private inventory</h1></AppLayout></MemoryRouter>);
    expect(screen.getByRole('heading', {name:'Secure your account'})).toBeInTheDocument();
    expect(screen.queryByRole('heading', {name:'Private inventory'})).not.toBeInTheDocument();
    expect(screen.queryByRole('link', {name:'Applications'})).not.toBeInTheDocument();
    expect(screen.queryByRole('link', {name:'Users'})).not.toBeInTheDocument();
  });
  it('renders no shell for an absent identity and exposes refresh failures safely', () => {
    state.user = null;
    const { rerender } = render(<MemoryRouter><AppLayout /></MemoryRouter>);
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
    state.user = { id:'id', name:'Demo', email:'demo@example.com', role:'Engineer', portfolioAccess:[], status:'Active', mustChangePassword:false, defaultLandingPage:null };
    state.error = 'Identity refresh unavailable';
    rerender(<MemoryRouter><AppLayout /></MemoryRouter>);
    expect(screen.getByRole('alert')).toHaveTextContent('Identity refresh unavailable');
  });
});

it('contains keyboard focus, locks scroll, ignores panel clicks and closes on Escape/overlay', async () => {
  const user = userEvent.setup();
  render(<DialogHarness />);
  const trigger = screen.getByRole('button', { name:'Open dialog' });
  await user.click(trigger);
  expect(document.body.style.overflow).toBe('hidden');
  expect(screen.getByRole('button', {name:'Cancel'})).toHaveFocus();
  await user.keyboard('{Shift>}{Tab}{/Shift}');
  expect(screen.getByRole('button', {name:'Confirm'})).toHaveFocus();
  await user.tab();
  expect(screen.getByRole('button', {name:'Cancel'})).toHaveFocus();
  await user.click(screen.getByText('Review before continuing'));
  expect(screen.getByRole('dialog')).toBeInTheDocument();
  await user.keyboard('{Escape}');
  expect(trigger).toHaveFocus();
  expect(document.body.style.overflow).toBe('');
  await user.click(trigger);
  await user.click(screen.getByRole('dialog').parentElement!);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});
it('keeps an empty dialog focusable without escaping on Tab', async () => {
  const user = userEvent.setup();
  render(<DialogHarness empty />);
  await user.click(screen.getByRole('button'));
  await user.tab();
  expect(screen.getByRole('dialog')).toHaveFocus();
  await user.keyboard('{Escape}');
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});
it('bounds paging, handles empty/out-of-range results and invokes keyboard actions', async () => {
  const user = userEvent.setup(); const onPage = vi.fn();
  const { rerender } = render(<Pagination page={1} pageSize={10} total={21} onPage={onPage} />);
  expect(screen.getByRole('button', {name:'Previous'})).toBeDisabled();
  screen.getByRole('button', {name:'Next'}).focus();
  await user.keyboard('{Enter}'); expect(onPage).toHaveBeenLastCalledWith(2);
  rerender(<Pagination page={3} pageSize={10} total={21} onPage={onPage} />);
  expect(screen.getByRole('button', {name:'Next'})).toBeDisabled();
  rerender(<Pagination page={1} pageSize={10} total={0} onPage={onPage} />);
  expect(screen.getByText('Page 1 of 1 · 0 results')).toHaveAttribute('aria-current','page');
  expect(screen.getByRole('button', {name:'Next'})).toBeDisabled();
  rerender(<Pagination page={5} pageSize={10} total={1} onPage={onPage} />);
  await user.click(screen.getByRole('button', {name:'Previous'})); expect(onPage).toHaveBeenLastCalledWith(4);
});
it('associates errors and headers and disables pending actions without calling handlers', async () => {
  const action = vi.fn(); const user = userEvent.setup();
  render(
    <>
      <FormField id="name" label="Name" error="Required name" required />
      <Button loading onClick={action}>Save</Button>
      <DataTable
        caption="Inventory"
        rows={[{id:'a',name:'Demo'}]}
        rowKey={row=>row.id}
        columns={[{key:'name',label:'Name',render:row=>row.name}]}
      />
    </>,
  );
  expect(screen.getByRole('textbox')).toHaveAccessibleDescription('Required name');
  expect(screen.getByRole('textbox')).toHaveAttribute('aria-invalid','true');
  expect(screen.getByRole('columnheader')).toHaveAttribute('scope','col');
  expect(screen.getByRole('table')).toHaveAccessibleName('Inventory');
  await user.click(screen.getByRole('button')); expect(action).not.toHaveBeenCalled();
  expect(screen.getByRole('button')).toHaveAttribute('aria-busy','true');
});
it('mirrors every exact palette/radius/font token and bans feature-local hex/font overrides', () => {
  const css = readFileSync(resolve('src/styles/tokens.css'),'utf8');
  const colors = Object.fromEntries([...css.matchAll(/--([\w-]+):\s*(#[\da-fA-F]{6});/g)].map(match=>[match[1],match[2]]));
  expect(colors).toEqual(theme.theme.extend.colors);
  expect(Object.keys(colors)).toHaveLength(36);
  expect(css).toContain("--font-family: 'Public Sans', sans-serif");
  expect(theme.theme.extend.fontFamily.sans).toEqual(['Public Sans','sans-serif']);
  for (const [key,value] of Object.entries(theme.theme.extend.borderRadius)) expect(css).toContain(`--radius-${key === 'DEFAULT' ? 'default' : key}: ${value};`);
  for (const entry of readdirSync(resolve('src'), { recursive:true, withFileTypes:true })) {
    if (!entry.isFile() || !entry.name.endsWith('.tsx') || entry.name.endsWith('.test.tsx')) continue;
    const source = readFileSync(resolve(entry.parentPath, entry.name),'utf8');
    expect(source).not.toMatch(/#[\da-fA-F]{6}\b|fontFamily\s*:/);
  }
});
