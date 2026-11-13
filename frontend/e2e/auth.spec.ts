/** Verify local sign-in, real backend identity, reload, and sign-out through UI. */
import { test, expect } from './fixtures';
for (const viewport of [{ width: 1280, height: 800 }, { width: 390, height: 844 }]) {
  test(`secure session journey at ${viewport.width}px`, async ({ page, identity, browserErrors }) => {
    await page.setViewportSize(viewport);
    await page.goto('/'); // sole entry navigation; all further routes use UI
    await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible();
    await page.getByLabel('Email').fill(identity.email);
    await page.getByLabel('Password').fill('invalid-test-credential');
    const rejected = page.waitForResponse((response) => response.url().endsWith('/api/auth/login') && response.status() === 401);
    await page.getByRole('button', { name: 'Sign in' }).click();
    const invalidResponse = await rejected;
    expect((await invalidResponse.json()).error.code).toBe('UNAUTHENTICATED');
    await expect(page.getByRole('alert')).toContainText('Unable to authenticate');
    expect(await page.evaluate(() => localStorage.getItem('kp-etsip-token'))).toBeNull();
    await page.getByLabel('Password').fill(identity.password);
    const signedIn = page.waitForResponse((response) => response.url().endsWith('/api/auth/login') && response.status() === 200);
    await page.getByRole('button', { name: 'Sign in' }).click();
    const response = await signedIn;
    expect(response.request().headers()['authorization']).toBeUndefined();
    const result = await response.json();
    expect(result.user.id).toBe(identity.id);
    expect(result.user.passwordHash).toBeUndefined();
    await expect(page.getByRole('heading', { name: result.user.name })).toBeVisible();
    await expect(page.getByText(result.user.email, { exact: true })).toBeVisible();
    await expect(page.getByText(result.user.role, { exact: true })).toBeVisible();
    const restored = page.waitForResponse((reply) => reply.url().endsWith('/api/auth/me') && reply.status() === 200);
    await page.reload();
    const me = await restored;
    expect(me.request().headers()['authorization']).toBe(`Bearer ${result.token}`);
    expect((await me.json()).id).toBe(identity.id);
    await expect(page.getByRole('heading', { name: identity.name })).toBeVisible();
    await page.getByRole('link', { name: 'Session', exact: true }).click();
    await page.screenshot({ path: test.info().outputPath('session.png') });
    const logout = page.waitForResponse((reply) => reply.url().endsWith('/api/auth/logout'));
    await page.getByRole('button', { name: 'Sign out' }).click();
    const logoutResponse = await logout;
    expect(logoutResponse.status()).toBe(200);
    expect(await logoutResponse.json()).toEqual({ message: 'Signed out' });
    await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible();
    expect(await page.evaluate(() => localStorage.getItem('kp-etsip-token'))).toBeNull();
    await page.reload();
    await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible();
    await expect(page.getByText(identity.name)).toHaveCount(0);
    expect(browserErrors).toEqual([]);
  });
}
