import pytest
from pickmate.domain.controller import Controller
from pickmate.storage.database import Database


@pytest.fixture
async def app(tmp_path):
    controller = Controller(Database(tmp_path / "test.sqlite"))
    await controller.initialize()
    yield controller
    await controller.close()
