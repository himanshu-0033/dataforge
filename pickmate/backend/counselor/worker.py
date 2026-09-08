"""Use the verified speech relay with a separate counselor room/agent binding."""

import os

os.environ["LIVEKIT_AGENT_NAME"] = "heard"
os.environ["LIVEKIT_ROOM_PREFIX"] = "heard"

from livekit import agents  # noqa: E402
from pickmate.voice.worker import server  # noqa: E402

if __name__ == "__main__":
    agents.cli.run_app(server)
