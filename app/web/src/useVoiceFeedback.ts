import { useCallback, useEffect, useRef, useState } from 'react';
import { flushSync } from 'react-dom';
import { createAudioAnalyser, Room, RoomEvent, Track, type LocalAudioTrack, type RemoteAudioTrack } from 'livekit-client';
import { clearVoicePlayback, resumeVoicePlayback } from './voicePlayback';
import type { InterfaceStatus } from './api';
import { LocalVoiceOnset } from './localVoiceOnset';

export type Caption = { id: string; text: string; speaker: 'You' | 'Heard' };
type Meter = ReturnType<typeof createAudioAnalyser>;

export function useVoiceFeedback(client: Room | null, mic: boolean, paused: boolean, onPlaybackBlocked?: () => void) {
  const [caption, setCaption] = useState<Caption | null>(null);
  const [userSpeaking, setUserSpeaking] = useState(false);
  const [agentSpeaking, setAgentSpeaking] = useState(false);
  const [status, setStatus] = useState<InterfaceStatus | null>(null);
  const [interruption, setInterruption] = useState(0);
  const meters = useRef<{ input?: Meter; output?: Meter }>({});
  const permissions = useRef({ mic, paused });
  permissions.current = { mic, paused };
  const blocked = useRef(false);
  const playbackBlocked = useRef(onPlaybackBlocked);
  playbackBlocked.current = onPlaybackBlocked;
  const [phase, setPhase] = useState<string | null>(null);

  const silence = useCallback(() => {
    blocked.current = true;
    setAgentSpeaking(false);
    setCaption(null);
    clearVoicePlayback();
  }, []);

  useEffect(() => {
    if (!mic) setUserSpeaking(false);
    if (paused) silence();
  }, [mic, paused, silence]);

  useEffect(() => {
    setCaption(null);
    setUserSpeaking(false);
    setAgentSpeaking(false);
    setPhase(null);
    setStatus(null);
    setInterruption(0);
    blocked.current = false;
    if (!client) return;
    let disposed = false;
    const activeStreams = new Map<string, number>();
    let streamSerial = 0;
    let lastSequence = 0;
    let workerEpoch = -1;
    let userActive = false;
    let agentActive = false;
    let explicitState = false;
    let provisional = false;
    let provisionalTimer = 0;
    let localAttempted = false;
    const speak = () => {
      if (permissions.current.paused || userActive || provisional) return;
      blocked.current = false;
      agentActive = true;
      // Commit the visual handshake before asking the browser to resume audio.
      flushSync(() => {
        setAgentSpeaking(true);
        setUserSpeaking(false);
        setPhase('SPEAKING');
        setStatus('SPEAKING');
      });
      resumeVoicePlayback(() => playbackBlocked.current?.());
    };
    const attach = (track: LocalAudioTrack | RemoteAudioTrack, side: 'input' | 'output') => {
      void meters.current[side]?.cleanup();
      delete meters.current[side];
      try { meters.current[side] = createAudioAnalyser(track, { fftSize: 256, minDecibels: -80, maxDecibels: -10 }); }
      catch { /* Voice still works in browsers without audio analysis. */ }
    };
    const subscribed = (track: Track) => {
      if (track.kind === Track.Kind.Audio) attach(track as RemoteAudioTrack, 'output');
    };
    const published = () => {
      const track = client.localParticipant.getTrackPublication(Track.Source.Microphone)?.audioTrack;
      if (track) attach(track as LocalAudioTrack, 'input');
    };
    const clearMeter = (side: 'input' | 'output') => {
      void meters.current[side]?.cleanup();
      delete meters.current[side];
    };
    const unsubscribed = (track: Track) => { if (track.kind === Track.Kind.Audio) clearMeter('output'); };
    const unpublished = () => clearMeter('input');
    const data = (payload: Uint8Array, participant?: { isAgent: boolean }, _kind?: unknown, topic?: string) => {
      if (topic !== 'heard.voice' || !participant?.isAgent) return;
      try {
        const event = JSON.parse(new TextDecoder().decode(payload));
        if (!['user_state', 'voice_state'].includes(event.type)) return;
        if (!['LISTENING', 'PROCESSING', 'SPEAKING', 'PAUSED'].includes(event.status)) return;
        if (event.type === 'voice_state') {
          if (!Number.isInteger(event.worker_epoch) || !Number.isInteger(event.sequence)) return;
          if (event.worker_epoch < workerEpoch || (event.worker_epoch === workerEpoch && event.sequence <= lastSequence)) return;
          workerEpoch = event.worker_epoch;
          lastSequence = event.sequence;
          explicitState = true;
        }
        if (provisional && event.status === 'SPEAKING') return;
        const alreadySignaledInterruption = provisional;
        window.clearTimeout(provisionalTimer);
        provisional = false;
        if (event.status === 'SPEAKING') localAttempted = false;
        if (event.status === 'SPEAKING') { speak(); return; }
        const listening = event.status === 'LISTENING' && (event.type === 'user_state' || event.state === 'USER_INTERRUPTED') && permissions.current.mic && !permissions.current.paused;
        const interrupted = listening && !userActive && (agentActive || event.state === 'USER_INTERRUPTED');
        userActive = listening;
        agentActive = false;
        flushSync(() => {
          setPhase(event.state || event.status);
          setStatus(event.status);
          setUserSpeaking(listening);
          setAgentSpeaking(false);
          if (interrupted && !alreadySignaledInterruption) setInterruption(value => value + 1);
          if (event.command === 'clear_audio' || listening) { activeStreams.delete('Heard'); silence(); }
        });
      } catch { /* Ignore malformed optional visual feedback. */ }
    };
    const attributes = (changed: Record<string, string>, participant: { isAgent: boolean }) => {
      if (!participant.isAgent || !changed['lk.agent.state']) return;
      const speaking = changed['lk.agent.state'] === 'speaking' && !permissions.current.paused;
      // Explicit worker events are sequenced and lease-fenced; late SDK attributes
      // must not reopen interrupted audio. Older workers still use attributes.
      if (explicitState) return;
      if (speaking) speak();
      else {
        agentActive = false;
        setAgentSpeaking(false);
        setStatus(changed['lk.agent.state'] === 'thinking' ? 'PROCESSING' : 'LISTENING');
      }
    };
    client.registerTextStreamHandler('lk.transcription', async (reader, participant) => {
      const speaker = participant.identity === client.localParticipant.identity ? 'You' : 'Heard';
      if (speaker === 'Heard' && !client.remoteParticipants.get(participant.identity)?.isAgent) return;
      const id = reader.info.attributes?.['lk.segment_id'] || reader.info.id;
      const serial = ++streamSerial;
      // Final STT corrections may replace an interim stream with the same segment ID.
      activeStreams.set(speaker, serial);
      let text = '';
      try {
        for await (const chunk of reader) {
          text += chunk;
          if (disposed || activeStreams.get(speaker) !== serial || permissions.current.paused) continue;
          if (speaker === 'You' && !permissions.current.mic) continue;
          if (speaker === 'Heard' && blocked.current) continue;
          setCaption({ id, speaker, text: text.slice(-4000) });
        }
      } catch { /* Completed server messages remain available after a lost stream. */ }
    });
    client.on(RoomEvent.TrackSubscribed, subscribed);
    client.on(RoomEvent.TrackUnsubscribed, unsubscribed);
    client.on(RoomEvent.LocalTrackPublished, published);
    client.on(RoomEvent.LocalTrackUnpublished, unpublished);
    client.on(RoomEvent.DataReceived, data);
    client.on(RoomEvent.ParticipantAttributesChanged, attributes);
    const onset = new LocalVoiceOnset();
    const samples = new Float32Array(256);
    const localTimer = window.setInterval(() => {
      const analyser = meters.current.input?.analyser;
      const enabled = !!analyser && agentActive && !userActive && !blocked.current && !localAttempted && permissions.current.mic && !permissions.current.paused;
      if (analyser) analyser.getFloatTimeDomainData(samples);
      if (!onset.observe(samples, performance.now(), enabled)) return;
      provisional = true;
      localAttempted = true;
      activeStreams.delete('Heard');
      flushSync(() => { silence(); setStatus('LISTENING'); setUserSpeaking(true); setPhase('LISTENING'); setInterruption(value => value + 1); });
      // A noise burst can briefly preempt sound, but must not cancel a model
      // turn or strand playback. Only confirmed server VAD owns cancellation.
      provisionalTimer = window.setTimeout(() => {
        provisional = false;
        if (agentActive && !userActive && !permissions.current.paused) speak();
        else setUserSpeaking(false);
      }, 1200);
    }, 20);
    published();
    client.remoteParticipants.forEach(participant => participant.audioTrackPublications.forEach(publication => {
      if (publication.audioTrack) attach(publication.audioTrack, 'output');
    }));
    return () => {
      disposed = true;
      window.clearInterval(localTimer);
      window.clearTimeout(provisionalTimer);
      client.unregisterTextStreamHandler('lk.transcription');
      client.off(RoomEvent.TrackSubscribed, subscribed);
      client.off(RoomEvent.TrackUnsubscribed, unsubscribed);
      client.off(RoomEvent.LocalTrackPublished, published);
      client.off(RoomEvent.LocalTrackUnpublished, unpublished);
      client.off(RoomEvent.DataReceived, data);
      client.off(RoomEvent.ParticipantAttributesChanged, attributes);
      clearMeter('input');
      clearMeter('output');
    };
  }, [client, silence]);

  const spectrum = useCallback((side: 'input' | 'output', bins: Uint8Array<ArrayBuffer>) => {
    const meter = meters.current[side];
    if (!meter || permissions.current.paused || (side === 'input' && !permissions.current.mic) || (side === 'output' && blocked.current)) {
      bins.fill(0);
      return;
    }
    meter.analyser.getByteFrequencyData(bins);
  }, []);
  return { caption, userSpeaking, agentSpeaking, spectrum, silence, phase, status, interruption };
}
