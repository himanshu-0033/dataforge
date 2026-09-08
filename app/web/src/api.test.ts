import { afterEach, describe, expect, it, vi } from 'vitest';
import { request, RequestError, route } from './api';

afterEach(() => vi.unstubAllGlobals());

describe('counselor requests', () => {
  const credential = { id: 'session-id', token: 'session-token' };

  it('sends authenticated turns with their event identity', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ revision: 2 })));
    vi.stubGlobal('fetch', fetch);
    const turn = { text: 'Hello', event_id: 'turn-id' };
    await expect(request(route(credential, '/turn'), turn, credential)).resolves.toEqual({ revision: 2 });
    expect(fetch).toHaveBeenCalledWith('/api/sessions/session-id/turn', expect.objectContaining({
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: 'Bearer session-token' },
      body: JSON.stringify(turn),
    }));
  });

  it('polls state without a POST body', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ revision: 1 })));
    vi.stubGlobal('fetch', fetch);
    await request(route(credential), undefined, credential);
    expect(fetch).toHaveBeenCalledWith('/api/sessions/session-id', expect.objectContaining({
      method: 'GET', body: undefined,
    }));
  });

  it('preserves authorization status and the server detail', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ detail: 'This conversation has expired.' }), { status: 403 },
    )));
    await expect(request('/sessions/expired')).rejects.toMatchObject({
      status: 403, message: 'This conversation has expired.',
    });
  });

  it('reports a dropped connection as a retryable request error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    await expect(request('/health')).rejects.toBeInstanceOf(RequestError);
    await expect(request('/health')).rejects.toMatchObject({ status: 0 });
  });
});
