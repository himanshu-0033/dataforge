"""Explicit same-room dispatch; token room_config only handles newly created rooms."""

import asyncio

from livekit import api


class Dispatcher:
    def __init__(self, settings, agent_name="pickmate"):
        self.settings = settings
        self.agent_name = agent_name
        self.locks = {}
        self.replacements = {}

    async def ensure(self, session):
        room = session["room"]
        async with self.locks.setdefault(room, asyncio.Lock()):
            async with asyncio.timeout(10):
                async with api.LiveKitAPI(
                    url=self.settings.livekit_url,
                    api_key=self.settings.livekit_api_key,
                    api_secret=self.settings.livekit_api_secret,
                ) as client:
                    await client.room.create_room(
                        api.CreateRoomRequest(
                            name=room, max_participants=2, empty_timeout=120, departure_timeout=60
                        )
                    )
                    dispatches = await client.agent_dispatch.list_dispatch(room)
                    own = [d for d in dispatches if d.agent_name == self.agent_name]
                    # An existing pending/running dispatch survives ordinary reconnects.
                    alive = [
                        d
                        for d in own
                        if not d.state.deleted_at
                        and (not d.state.jobs or any(not j.state.ended_at for j in d.state.jobs))
                    ]
                    if alive:
                        replacement = self.replacements.get(room)
                        same_retry = (
                            replacement
                            and replacement[0] == session["worker_epoch"]
                            and any(d.id == replacement[1] for d in alive)
                        )
                        if same_retry or session["provider"]["status"] not in ("failed", "disconnected"):
                            return
                    for old in own:
                        await client.agent_dispatch.delete_dispatch(old.id, room)
                    created = await client.agent_dispatch.create_dispatch(
                        api.CreateAgentDispatchRequest(room=room, agent_name=self.agent_name)
                    )
                    self.replacements[room] = (session["worker_epoch"], created.id)
