import pytest

from some_aiohttp_service import test


@pytest.mark.asyncio
async def test_stub():
    assert test == 1
