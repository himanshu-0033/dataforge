import { describe, expect, it, vi } from 'vitest';
import { PlaybackAcknowledger } from './playback';

describe('fixture playback', () => {
  it('does not complete a replacement response from an old timer', async () => {
    vi.useFakeTimers(); const sent:string[]=[];
    const p = new PlaybackAcknowledger(async (id,status)=>{sent.push(`${id}:${status}`)});
    p.start('old',1000); p.start('new',1000);
    await vi.advanceTimersByTimeAsync(1000);
    expect(sent).toEqual(['old:playing','old:interrupted','new:playing','new:completed']);
    vi.useRealTimers();
  });
});
