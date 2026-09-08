import asyncio
import hashlib
import hmac
import logging
import secrets
import time
from datetime import datetime, timezone

from pickmate.domain.language import exact_confirmation, fixture_intent, resolve, speaking_bin
from pickmate.domain.models import Confirmation, Faults, Intent, Item, PickTask, Session, Speech, identity


class Controller:
    def __init__(self, db, interpreter=None):
        self.db = db
        self.interpreter = interpreter
        self.pending: set[asyncio.Task] = set()
        self.lookups: dict[str, asyncio.Task] = {}
        self.interpretations: dict[str, asyncio.Task] = {}

    async def initialize(self):
        await self.db.initialize()

    def spawn(self, coro):
        task = asyncio.create_task(coro)
        self.pending.add(task)

        def finished(done):
            self.pending.discard(done)
            if not done.cancelled() and (error := done.exception()):
                # No exception messages/transcripts/secrets in process diagnostics.
                logging.getLogger(__name__).warning("Background operation stopped: %s", type(error).__name__)

        task.add_done_callback(finished)
        return task

    async def wait_idle(self):
        while self.pending:
            await asyncio.gather(*list(self.pending), return_exceptions=True)

    async def close(self):
        for task in list(self.pending):
            task.cancel()
        await self.wait_idle()
        if self.interpreter:
            await self.interpreter.close()

    async def create_session(self, mode):
        token = secrets.token_urlsafe(32)
        s = Session(mode=mode, owner_hash=hashlib.sha256(token.encode()).hexdigest())
        s.room = f"pickmate-{s.session_id}"
        s.provider = dict(
            name="fixture" if mode == "fixture" else "rime",
            status="fixture" if mode == "fixture" else "awaiting_worker",
            model=None,
            speaker=None,
            language="en",
            endpoint=None,
        )
        await self.db.create(s)

        def start(s, con, emit):
            emit("session_started", mode=mode, room=s.room, synthetic_inventory=True)
            self._say(s, emit, "Welcome to PickMate. What item and quantity do you need?")

        await self.db.change(s.session_id, start)
        return s.session_id, token

    async def authorize(self, sid, token):
        return await self.db.change(
            sid, lambda s, c, e: hmac.compare_digest(s.owner_hash, hashlib.sha256(token.encode()).hexdigest())
        )

    async def snapshot(self, sid):
        return await self.db.snapshot(sid)

    @staticmethod
    def _invalidate(s, emit):
        if s.confirmation:
            emit("confirmation_invalidated", confirmation_id=s.confirmation.confirmation_id)
            s.confirmation = None

    @staticmethod
    def _interrupt(s, emit):
        if s.speech and s.speech.status in ("generated", "queued", "playing"):
            s.speech.status = "interrupted"
            emit(
                "speech_stopped",
                response_id=s.speech.response_id,
                reason="interrupted",
                physical_audibility="unverified",
            )
            Controller._invalidate(s, emit)

    @staticmethod
    def _advance(s, emit):
        Controller._interrupt(s, emit)
        s.response_epoch += 1
        emit("response_epoch_changed")

    @staticmethod
    def _say(s, emit, text, substantive=True, allow_paused=False):
        if s.ended or s.resolving or (s.paused and not allow_paused) or s.provider.get("status") == "failed":
            emit("speech_suppressed", reason="session_gate")
            return
        Controller._interrupt(s, emit)
        s.speech = Speech(
            response_epoch=s.response_epoch,
            task_version=s.task.task_version if s.task else None,
            task_id=s.task.task_id if s.task else None,
            text=text,
            substantive=substantive,
            allow_while_paused=allow_paused,
        )
        emit("speech_generated", response_id=s.speech.response_id, text=text, substantive=substantive)
        s.speech.status = "queued"
        emit("speech_queued", response_id=s.speech.response_id, text=text, substantive=substantive)

    @staticmethod
    def _status(s, emit):
        t = s.task
        if not t:
            Controller._say(s, emit, "Tell me an item and quantity to start a pick.")
        elif t.status == "committed":
            Controller._say(
                s, emit, f"Already recorded {t.quantity} {t.item.name}. Inventory was updated once."
            )
        elif t.status == "cancelled":
            Controller._say(s, emit, "This pick is cancelled. What do you need next?")
        elif t.status in ("looking_up", "requested"):
            Controller._say(s, emit, f"I am checking {t.quantity} {t.item.name}.", substantive=False)
        else:
            Controller._say(
                s,
                emit,
                f"Pick {t.quantity} {t.item.name} from {speaking_bin(t.item.bin)}. Tell me when you have them.",
            )

    async def speech_onset(self, sid):
        def onset(s, c, emit):
            if s.ended:
                return
            emit("user_speech_onset")
            self._interrupt(s, emit)
            # Fence earlier reasoning before any correction transcript exists.
            # Read-only lookups retain their task identity while output is held.
            s.input_id = None
            s.resolving = True

        await self.db.change(sid, onset)
        pending = self.interpretations.get(sid)
        if pending and pending is not asyncio.current_task():
            pending.cancel()

    async def false_interruption(self, sid):
        def resume(s, c, emit):
            if s.ended:
                return
            s.resolving = False
            emit("false_interruption", meaningful_transcript=False)
            self._advance(s, emit)
            self._status(s, emit)

        await self.db.change(sid, resume)

    async def turn(self, sid, text, event_id=None):
        event_id = event_id or identity()

        def begin(s, con, emit):
            if s.ended:
                return None
            inserted = con.execute("INSERT OR IGNORE INTO inputs VALUES(?,?)", (sid, event_id)).rowcount
            if not inserted:
                emit("input_replay_rejected", event_id=event_id)
                return None
            emit("user_speech_end", source="final_transcript_boundary")
            emit("final_transcript", text=text, event_id=event_id)
            self._advance(s, emit)
            s.resolving = True
            s.input_id = event_id
            return dict(
                epoch=s.response_epoch,
                mode=s.mode,
                task=s.task.model_dump() if s.task else None,
                items=self.db.items(con),
                fail=s.faults.fail_provider,
            )

        context = await self.db.change(sid, begin)
        if context is None:
            return
        previous = self.interpretations.get(sid)
        if previous and previous is not asyncio.current_task():
            previous.cancel()
        self.interpretations[sid] = asyncio.current_task()
        try:
            if context["fail"] in ("stt", "llm"):
                await self.provider_error(sid, context["fail"], "timeout", input_id=event_id)
                return
            if context["mode"] == "live":
                if self.interpreter is None:
                    raise RuntimeError("LLM is not configured")
                async with asyncio.timeout(12):
                    intent = await self.interpreter.interpret(text, context["task"], context["items"])
            else:
                intent = fixture_intent(text, context["task"])
            await self.accept_intent(sid, intent, text, event_id, context["epoch"])
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            category = (
                "timeout"
                if isinstance(exc, TimeoutError)
                else "invalid_configuration"
                if isinstance(exc, RuntimeError)
                else "provider_error"
            )
            await self.provider_error(sid, "llm", category, input_id=event_id)
        finally:
            if self.interpretations.get(sid) is asyncio.current_task():
                self.interpretations.pop(sid, None)

    async def accept_intent(self, sid, intent: Intent, transcript, input_id, epoch):
        def apply(s, con, emit):
            if s.ended or s.input_id != input_id or s.response_epoch != epoch:
                emit("stale_result_rejected", source="llm", input_id=input_id, result_epoch=epoch)
                return None
            s.resolving = False
            emit("intent_accepted", normalized=intent.model_dump(), input_id=input_id)
            a = intent.action
            if a in ("pause", "resume", "cancel"):
                self._control(s, con, emit, a)
                return None
            if s.paused:
                self._say(s, emit, "Paused. Say resume to continue.", allow_paused=True)
                return None
            if a == "backchannel":
                emit("false_interruption", meaningful_transcript=False)
                self._status(s, emit)
            elif a == "status":
                self._invalidate(s, emit)
                self._status(s, emit)
            elif a == "request":
                self._invalidate(s, emit)
                item = resolve(intent.query or "", self.db.items(con))
                if not item or not intent.quantity:
                    self._say(
                        s, emit, "Please say the full item name and a quantity between one and one thousand."
                    )
                    return None
                if item["available"] < intent.quantity:
                    self._say(
                        s,
                        emit,
                        f"Only {item['available']} {item['name']} are available. What quantity do you need?",
                    )
                    return None
                if (
                    s.task
                    and s.task.status == "committed"
                    and not transcript.lower().strip().startswith(("find", "pick"))
                ):
                    self._status(s, emit)
                    return None
                if s.task and s.task.status not in ("committed", "cancelled"):
                    t = s.task
                    t.task_version += 1
                    t.item, t.quantity, t.status = Item(**item), intent.quantity, "requested"
                else:
                    s.task = PickTask(item=Item(**item), quantity=intent.quantity)
                for tool in s.tool_states.values():
                    if tool["status"] in ("pending", "running"):
                        tool["status"] = "superseded"
                emit("task_version_changed")
                t = s.task
                call_id = identity()
                s.tool_states[call_id] = dict(
                    status="pending", task_id=t.task_id, task_version=t.task_version
                )
                t.status = "looking_up"
                emit("lookup_pending", tool_call_id=call_id)
                self._say(s, emit, f"Checking {t.quantity} {t.item.name}.", substantive=False)
                return dict(
                    task_id=t.task_id,
                    version=t.task_version,
                    sku=t.item.sku,
                    tool_call_id=call_id,
                    faults=s.faults.model_dump(),
                )
            elif a == "complete":
                self._readback(s, emit)
            elif a == "confirm":
                self._confirm(s, con, emit, intent, transcript)
            else:
                self._invalidate(s, emit)
                self._say(s, emit, "Please repeat the full item name and quantity so I can check it.")
            return None

        lookup = await self.db.change(sid, apply)
        if lookup:
            old = self.lookups.get(sid)
            if old:
                old.cancel()
            self.lookups[sid] = self.spawn(self._lookup(sid, **lookup))

    async def _lookup(self, sid, task_id, version, sku, tool_call_id, faults):
        def started(s, c, emit):
            tool = s.tool_states.get(tool_call_id)
            if tool and tool["status"] == "pending":
                tool["status"] = "running"
            emit("lookup_started", tool_call_id=tool_call_id, result_task_version=version)

        await self.db.change(sid, started)
        delay = faults["lookup_delay_ms"] / 1000
        start = time.monotonic()
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            if not faults["ignore_cancellation"]:
                await self.db.change(sid, lambda s, c, e: self._cancel_tool(s, e, tool_call_id))
                return
            await asyncio.sleep(max(0, delay - (time.monotonic() - start)))

        def finish(s, con, emit):
            valid = (
                not s.ended
                and s.task
                and s.task.task_id == task_id
                and s.task.task_version == version
                and s.task.status == "looking_up"
            )
            if not valid:
                s.tool_states[tool_call_id]["status"] = "superseded"
                emit(
                    "stale_result_rejected",
                    source="lookup",
                    tool_call_id=tool_call_id,
                    result_task_version=version,
                )
                return
            if faults["fail_provider"] == "lookup":
                s.tool_states[tool_call_id]["status"] = "failed"
                s.task.status = "requested"
                emit("provider_error", provider="lookup", category="timeout", tool_call_id=tool_call_id)
                self._say(s, emit, "The inventory lookup timed out. Please repeat the request.")
                return
            item = next(i for i in self.db.items(con) if i["sku"] == sku)
            s.tool_states[tool_call_id]["status"] = "completed"
            emit(
                "lookup_completed",
                tool_call_id=tool_call_id,
                result_task_version=version,
                duration_ms=(time.monotonic() - start) * 1000,
            )
            s.task.item = Item(**item)
            if item["available"] < s.task.quantity:
                s.task.status = "requested"
                self._say(
                    s, emit, f"Only {item['available']} {item['name']} remain. Please choose a new quantity."
                )
                return
            s.task.status = "ready"
            # Retained status turns re-render through the CURRENT epoch. While resolving,
            # the task may become ready but no instruction is queued until input settles.
            self._status(s, emit)

        await self.db.change(sid, finish)

    @staticmethod
    def _cancel_tool(s, emit, call_id):
        if call_id in s.tool_states:
            s.tool_states[call_id]["status"] = "cancelled"
        emit("lookup_cancelled", tool_call_id=call_id)

    @staticmethod
    def _readback(s, emit):
        t = s.task
        if not t or t.status not in ("ready", "awaiting_confirmation"):
            Controller._status(s, emit)
            return
        Controller._invalidate(s, emit)
        t.status = "awaiting_confirmation"
        wording = f"Record {t.quantity} {t.item.name}?"
        if s.mode == "live":
            wording += f" Say, confirm {t.quantity} {t.item.name}."
        Controller._say(s, emit, wording)
        s.confirmation = Confirmation(
            task_id=t.task_id,
            task_version=t.task_version,
            sku=t.item.sku,
            quantity=t.quantity,
            response_id=s.speech.response_id,
        )
        emit(
            "confirmation_created",
            confirmation_id=s.confirmation.confirmation_id,
            response_id=s.speech.response_id,
        )

    @staticmethod
    def _confirm(s, con, emit, intent, transcript):
        t = s.task
        if not t:
            Controller._status(s, emit)
            return
        existing = con.execute("SELECT * FROM completions WHERE task_id=?", (t.task_id,)).fetchone()
        if existing:
            emit("write_replayed", operation_id=existing["operation_id"])
            Controller._status(s, emit)
            return
        if t.status not in ("ready", "awaiting_confirmation"):
            Controller._status(s, emit)
            return
        explicit = exact_confirmation(transcript, t.item.model_dump(), t.quantity)
        conf = s.confirmation
        generic = (
            transcript.lower().strip(" .!?") in ("yes", "yes please")
            and conf is not None
            and conf.delivered
            and time.time() <= conf.expires_at
            and conf.task_id == t.task_id
            and conf.task_version == t.task_version
            and conf.sku == t.item.sku
            and conf.quantity == t.quantity
        )
        if not explicit and not generic:
            Controller._readback(s, emit)
            return
        if explicit:
            conf = Confirmation(
                task_id=t.task_id,
                task_version=t.task_version,
                sku=t.item.sku,
                quantity=t.quantity,
                response_id=s.speech.response_id if s.speech else "",
            )
        emit("write_attempted", operation_id=t.operation_id, confirmation_id=conf.confirmation_id)
        # All validation, compare-and-decrement, receipt, state and event writes share this transaction.
        item = con.execute("SELECT * FROM inventory WHERE sku=?", (t.item.sku,)).fetchone()
        if item is None or item["available"] < t.quantity or not 1 <= t.quantity <= 1000:
            Controller._invalidate(s, emit)
            t.status = "requested"
            Controller._say(s, emit, "Stock changed. Please request the item again before confirming.")
            emit("write_rejected", reason="stock_changed", operation_id=t.operation_id)
            return
        updated = con.execute(
            "UPDATE inventory SET available=available-?,version=version+1 WHERE sku=? AND version=? AND available>=?",
            (t.quantity, t.item.sku, item["version"], t.quantity),
        ).rowcount
        if updated != 1:
            raise RuntimeError("Inventory compare-and-swap failed")
        con.execute(
            "INSERT INTO completions VALUES(?,?,?,?,?,?,?,?)",
            (
                t.operation_id,
                t.task_id,
                s.session_id,
                t.task_version,
                t.item.sku,
                t.quantity,
                conf.confirmation_id,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        t.status = "committed"
        t.item.available = item["available"] - t.quantity
        t.item.inventory_version = item["version"] + 1
        Controller._invalidate(s, emit)
        emit(
            "write_committed",
            operation_id=t.operation_id,
            sku=t.item.sku,
            quantity=t.quantity,
            confirmation_id=conf.confirmation_id,
        )
        Controller._say(s, emit, f"Recorded {t.quantity} {t.item.name}. Your pick is complete.")

    async def playback(self, sid, response_id, status, trusted=False):
        def update(s, c, emit):
            speech = s.speech
            if (
                s.ended
                or not speech
                or speech.response_id != response_id
                or speech.response_epoch != s.response_epoch
                or speech.status in ("interrupted", "completed")
                or s.resolving
            ):
                emit("stale_result_rejected", source="tts_playback", response_id=response_id)
                return
            if status == "completed" and speech.status != "playing":
                emit("playback_ack_rejected", response_id=response_id, reason="never_started")
                return
            speech.status = status
            speech.delivered_estimate = "fixture" if trusted and s.mode == "fixture" else "sdk_playout_proxy"
            emit(
                "speech_started" if status == "playing" else "speech_stopped",
                response_id=response_id,
                status=status,
                delivery_estimate=speech.delivered_estimate,
                physical_audibility="unverified",
            )
            if status == "interrupted":
                self._invalidate(s, emit)
            if status == "completed" and s.confirmation and s.confirmation.response_id == response_id:
                # Fixture authorization models known delivery. A live SDK playout completion
                # is only a proxy, so generic yes remains disabled without stronger evidence.
                s.confirmation.delivered = trusted and s.mode == "fixture"
                s.confirmation.expires_at = time.time() + 30

        await self.db.change(sid, update)

    def _control(self, s, con, emit, action):
        self._invalidate(s, emit)
        s.resolving = False
        if action == "pause":
            s.paused = True
            self._say(s, emit, "Paused. Say resume when you are ready.", allow_paused=True)
        elif action == "resume":
            s.paused = False
            self._status(s, emit)
        elif action == "cancel":
            if s.task and s.task.status == "committed":
                self._status(s, emit)
            else:
                if s.task:
                    s.task.status = "cancelled"
                    s.task.task_version += 1
                    emit("task_version_changed")
                self._say(s, emit, "Pick cancelled. Inventory has not been changed.")
        elif action == "end":
            s.ended = True
            self._interrupt(s, emit)
            emit("session_ended")
            emit("cleanup", pending_callbacks_fenced=True)
        elif action == "recover":
            s.paused = False
            if s.mode == "fixture":
                s.provider["status"] = "fixture"
            if s.task and s.task.status == "looking_up":
                s.task.task_version += 1
                s.task.status = "requested"
                self._say(s, emit, "The lookup was interrupted. Please repeat the item and quantity.")
            else:
                self._status(s, emit)
            emit("session_recovered", durable_outcome_preserved=True)
        elif action == "repeat":
            self._status(s, emit)
        emit("control_applied", action=action)

    async def control(self, sid, action):
        def apply(s, con, emit):
            if s.ended:
                return
            self._advance(s, emit)
            self._control(s, con, emit, action)

        await self.db.change(sid, apply)
        if action in ("cancel", "end"):
            task = self.lookups.get(sid)
            if task:
                task.cancel()
            task = self.interpretations.get(sid)
            if task:
                task.cancel()

    async def faults(self, sid, **values):
        def apply(s, c, emit):
            s.faults = Faults(**(s.faults.model_dump() | values))
            emit("faults_configured", **s.faults.model_dump())

        await self.db.change(sid, apply)
        if values.get("fail_provider") == "rime":
            await self.provider_error(sid, "rime", "timeout")

    async def provider_error(self, sid, provider, category, input_id=None):
        def fail(s, c, emit):
            if s.ended or (input_id and s.input_id != input_id):
                emit("stale_result_rejected", source="provider_error")
                return
            s.resolving = False
            self._interrupt(s, emit)
            self._invalidate(s, emit)
            if provider == "rime":
                s.provider["status"] = "failed"
                s.paused = True
            else:
                self._say(s, emit, "I could not understand that request. Please repeat it.")
            emit("provider_error", provider=provider, category=category, state_preserved=True)

        await self.db.change(sid, fail)

    async def provider(self, sid, payload):
        def apply(s, c, emit):
            if s.ended:
                return
            s.provider.update(payload)
            emit("provider_status", **payload)

        await self.db.change(sid, apply)
        if payload.get("status") == "failed":
            await self.provider_error(
                sid, payload.get("name", "rime"), payload.get("error_category", "provider_error")
            )

    async def metric(self, sid, kind, data):
        await self.db.change(sid, lambda s, c, emit: emit(kind, **data))

    async def claim_worker(self, sid, worker_id):
        def claim(s, con, emit):
            if s.ended:
                raise ValueError("Cannot attach a worker to an ended session")
            s.worker_epoch += 1
            s.worker_id = worker_id
            s.input_id = None
            s.resolving = False
            self._advance(s, emit)
            self._invalidate(s, emit)
            emit("worker_claimed", worker_id=worker_id, worker_epoch=s.worker_epoch)
            return {"worker_epoch": s.worker_epoch}

        result = await self.db.change(sid, claim)
        pending = self.interpretations.get(sid)
        if pending:
            pending.cancel()
        return result
