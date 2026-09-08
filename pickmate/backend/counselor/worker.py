"""LiveKit speech relay. The API owns conversation history and response generation."""

import asyncio
import contextlib
import os
import re
from uuid import uuid4

import httpx
from dotenv import load_dotenv
from livekit import agents
from livekit.agents import Agent, AgentServer, AgentSession, StopResponse, room_io
from livekit.agents.voice.agent_session import SessionConnectOptions
from livekit.plugins import deepgram, silero
from livekit.plugins import rime as _rime  # noqa: F401 -- register before Windows job threads start

from .config import AGENT_NAME, ROOM_PREFIX
from .providers import RimeConfig, error_category

# AgentServer reads its connection settings during construction. Load the same
# working-directory .env as the API before creating it, only for the executable.
if __name__ == "__main__":
    load_dotenv(".env")

server = AgentServer()


def eligible_speech(snapshot):
    """Pure identity fence shared by scheduling and deterministic tests."""
    speech = snapshot.get("speech")
    if snapshot.get("ended") or snapshot.get("resolving") or not speech:
        return None
    if snapshot.get("paused"):
        return None
    if speech["response_epoch"] != snapshot["response_epoch"] or speech["status"] not in (
        "queued",
        "playing",
    ):
        return None
    return speech


class Bridge:
    def __init__(self, sid, room, http):
        self.sid, self.room, self.http = sid, room, http
        self.session = None
        self.queue = asyncio.Queue(maxsize=100)
        self.failed = False
        self.worker_epoch = None
        self.failure_task = None
        self.closed = False
        self.pending_controls = 0
        self.input_serial = 0
        self.input_resolved = True
        self.transcript_seen = False
        self.current = None
        self.handle = None
        self.seen = set()
        self.tasks = set()
        self.handles = {}
        self.config = RimeConfig.from_env()

    async def call(self, route, data=None):
        url = f"{os.getenv('API_URL', 'http://127.0.0.1:8000').rstrip('/')}/api/internal/sessions/{self.sid}/{route}"
        headers = {"X-Worker-Key": os.environ["WORKER_SECRET"], "X-Room-Name": self.room}
        if self.worker_epoch is not None:
            headers["X-Worker-Epoch"] = str(self.worker_epoch)
        response = await self.http.request(
            "GET" if data is None else "POST",
            url,
            json=data,
            headers=headers,
        )
        response.raise_for_status()
        return response.json()

    def spawn(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.add(task)

        def done(task):
            self.tasks.discard(task)
            if not task.cancelled() and task.exception() is not None:
                self.fail("api_transport", task.exception())

        task.add_done_callback(done)
        return task

    def fail(self, source, error):
        if self.failed:
            return
        self.failed = True
        self.closed = True
        self.session.interrupt(force=True)
        while not self.queue.empty():
            route, _, future = self.queue.get_nowait()
            if route in ("onset", "turn", "false-interruption"):
                self.pending_controls -= 1
            if not future.done():
                future.set_result(False)
            self.queue.task_done()
        self.failure_task = self.spawn(self.report_failure(source, error))

    async def report_failure(self, source, error):
        with contextlib.suppress(Exception):
            if source in ("rime", "stt"):
                await self.call("error", {"provider": source, "category": error_category(error)})
                if source == "rime":
                    await self.provider("failed", error)

    async def recover(self):
        # 'connected' means the initialized worker path, not a synthesis smoke pass.
        await self.provider("connected")
        await self.call("recover", {})

    def submit(self, route, data):
        future = asyncio.get_running_loop().create_future()
        if self.closed:
            future.set_result(False)
            return future
        try:
            self.queue.put_nowait((route, data, future))
            if route in ("onset", "turn", "false-interruption"):
                self.pending_controls += 1
        except asyncio.QueueFull:
            self.fail("control_queue", RuntimeError("Control queue full"))
            future.set_result(False)
        return future

    async def controls(self):
        while not self.closed:
            route, data, future = await self.queue.get()
            try:
                await self.call(route, data)
                if not future.done():
                    future.set_result(True)
            except asyncio.CancelledError:
                if not future.done():
                    future.set_result(False)
                raise
            except Exception as error:
                self.fail("api_transport", error)
                if not future.done():
                    future.set_result(False)
            finally:
                if route in ("onset", "turn", "false-interruption"):
                    self.pending_controls -= 1
                self.queue.task_done()

    async def provider(self, status, error=None):
        data = {
            "name": "rime",
            "status": status,
            "model": self.config.model,
            "speaker": self.config.speaker,
            "language": self.config.language,
            "endpoint": self.config.base_url + "/ws3",
        }
        if error:
            data["error_category"] = error_category(error)
        await self.call("provider", data)

    async def playback(self, response_id, status):
        await self.call("playback", {"response_id": response_id, "status": status})

    def false_interruption(self):
        if not self.input_resolved and not self.transcript_seen:
            self.input_resolved = True
            self.submit("false-interruption", {})

    async def silence_fallback(self, serial):
        # SDK false-interruption events require an interrupted speech handle;
        # silent response generation also needs recovery after VAD-only noise.
        await asyncio.sleep(1.5)
        if serial == self.input_serial and self.session.user_state != "speaking":
            self.false_interruption()

    async def finish(self, handle, response_id):
        try:
            async with asyncio.timeout(45):
                await handle.wait_for_playout()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            handle.interrupt(force=True)
            self.fail("playback", error)
            return
        finally:
            self.handles.pop(getattr(handle, "id", None), None)
        try:
            await self.playback(response_id, "interrupted" if handle.interrupted else "completed")
        except Exception as error:
            self.fail("api_transport", error)

    async def poll(self):
        while not self.closed:
            try:
                snapshot = await self.call("snapshot")
                speech = eligible_speech(snapshot)
                if self.handle and (self.failed or not speech or speech["response_id"] != self.current):
                    self.handle.interrupt(force=True)
                    self.handle = None
                if snapshot.get("ended"):
                    return
                if speech and not self.failed and speech["response_id"] not in self.seen:
                    # API reads can race with an onset; pending controls also suppress speech.
                    fresh = eligible_speech(await self.call("snapshot"))
                    if (
                        not fresh
                        or fresh["response_id"] != speech["response_id"]
                        or self.pending_controls
                        or self.session.user_state == "speaking"
                    ):
                        await asyncio.sleep(0.1)
                        continue
                    self.current = speech["response_id"]
                    self.seen.add(self.current)
                    self.handle = self.session.say(
                        speech["text"], allow_interruptions=True, add_to_chat_ctx=True
                    )
                    self.handles[self.handle.id] = self.current
                    self.spawn(self.finish(self.handle, self.current))
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.fail("api_transport", error)
                return
            await asyncio.sleep(0.1)


class CounselorAgent(Agent):
    def __init__(self, bridge):
        super().__init__(
            instructions="Relay final user speech to the application conversation controller. Never generate autonomous responses."
        )
        self.bridge = bridge

    async def on_user_turn_completed(self, turn_ctx, new_message):
        if not self.bridge.failed:
            self.bridge.input_resolved = True
            await self.bridge.submit("turn", {"text": new_message.text_content, "event_id": uuid4().hex})
        raise StopResponse()


@server.rtc_session(agent_name=AGENT_NAME)
async def entrypoint(ctx: agents.JobContext):
    # Override cloud recording defaults before any counselor session initialization.
    ctx.init_recording({"audio": False, "traces": False, "logs": False, "transcript": False})
    room = ctx.room.name
    if not re.fullmatch(re.escape(ROOM_PREFIX) + r"[a-f0-9]{32}", room):
        raise ValueError("Unexpected room binding")
    sid = room.removeprefix(ROOM_PREFIX)
    await ctx.connect()
    participant = await asyncio.wait_for(ctx.wait_for_participant(identity=f"worker-{sid}"), timeout=30)
    async with httpx.AsyncClient(timeout=5) as http:
        bridge = Bridge(sid, room, http)
        snapshot = await bridge.call("snapshot")
        if snapshot.get("mode") != "live" or snapshot.get("room") != room or snapshot.get("ended"):
            raise ValueError("Invalid live session binding")
        lease = await bridge.call("claim", {"worker_id": ctx.job.id})
        bridge.worker_epoch = lease["worker_epoch"]
        tts = bridge.config.make_tts()
        stt = deepgram.STT(
            model="nova-3",
            language="en-US",
            api_key=os.environ["DEEPGRAM_API_KEY"],
        )
        session = bridge.session = AgentSession(
            stt=stt,
            tts=tts,
            # Leave room for a reflective pause and reject very brief noise onsets.
            vad=silero.VAD.load(min_speech_duration=0.15, min_silence_duration=0.8),
            turn_detection="vad",
            min_endpointing_delay=0.8,
            min_interruption_duration=0.1,
            min_interruption_words=0,
            resume_false_interruption=False,
            false_interruption_timeout=1.0,
            use_tts_aligned_transcript=True,
            conn_options=SessionConnectOptions(
                stt_conn_options=agents.APIConnectOptions(timeout=10, max_retry=1),
                tts_conn_options=agents.APIConnectOptions(timeout=10, max_retry=0),
            ),
        )

        @session.on("user_state_changed")
        def user_state(event):
            if event.new_state == "speaking":
                bridge.input_serial += 1
                bridge.input_resolved = False
                bridge.transcript_seen = False
                session.interrupt(force=True)
                bridge.submit("onset", {})
            elif event.old_state == "speaking":
                bridge.spawn(bridge.silence_fallback(bridge.input_serial))

        @session.on("agent_false_interruption")
        def false_interruption(event):
            bridge.false_interruption()

        @session.on("user_input_transcribed")
        def transcript(event):
            if event.transcript.strip():
                bridge.transcript_seen = True

        @session.on("agent_state_changed")
        def agent_state(event):
            handle = session.current_speech
            response_id = bridge.handles.get(handle.id) if handle else None
            if event.new_state == "speaking" and response_id:
                bridge.submit(
                    "playback",
                    {"response_id": response_id, "status": "playing"},
                )
                bridge.spawn(bridge.provider("active"))

        @session.on("error")
        def provider_error(event):
            provider = "rime" if event.source is tts else "stt"
            bridge.fail(provider, event.error)

        @session.on("close")
        def closed(event):
            bridge.closed = True

        bridge.spawn(bridge.controls())
        try:
            await session.start(
                agent=CounselorAgent(bridge),
                room=ctx.room,
                room_options=room_io.RoomOptions(participant_identity=participant.identity, text_input=False),
                record=False,
            )
            await bridge.recover()
            await bridge.poll()
        finally:
            bridge.closed = True
            session.interrupt(force=True)
            if bridge.failure_task:
                with contextlib.suppress(Exception):
                    async with asyncio.timeout(6):
                        await asyncio.shield(bridge.failure_task)
            for task in list(bridge.tasks):
                task.cancel()
            await asyncio.gather(*list(bridge.tasks), return_exceptions=True)
            with contextlib.suppress(Exception):
                async with asyncio.timeout(10):
                    await session.aclose()
                    await tts.aclose()
                    await stt.aclose()
            with contextlib.suppress(Exception):
                await bridge.provider("disconnected")
            ctx.shutdown(reason="heard_worker_failed" if bridge.failed else "heard_worker_closed")


if __name__ == "__main__":
    agents.cli.run_app(server)
