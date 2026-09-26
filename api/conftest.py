import pytest

from security import api_limiter, invite_limiter


@pytest.fixture(autouse=True)
def fresh_rate_limits() -> None:
    api_limiter.reset()
    invite_limiter.reset()
