"""TradeSathi AI — Rate Limiter Unit Tests
Verifies sliding-window IP rate limiting, threshold enforcement, 429 response,
and test-bypass safety switches.
"""

import os
import time
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

from app.rate_limiter import SlidingWindowRateLimiter


def test_sliding_window_rate_limiter_logic():
    """Verify in-memory sliding window throttling and retry-after calculation."""
    limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=2, name="test_limiter")
    limiter.reset()

    # Requests 1, 2, 3 should be permitted
    assert limiter.check("192.168.1.100")[0] is True
    assert limiter.check("192.168.1.100")[0] is True
    assert limiter.check("192.168.1.100")[0] is True

    # 4th request must be blocked
    allowed, retry_after = limiter.check("192.168.1.100")
    assert allowed is False
    assert 1 <= retry_after <= 2

    # Different IP is unaffected
    assert limiter.check("192.168.1.200")[0] is True

    # After window expiration, requests should be permitted again
    time.sleep(2.1)
    assert limiter.check("192.168.1.100")[0] is True


def test_rate_limiter_fastapi_dependency():
    """Verify HTTP 429 response and Retry-After header via FastAPI TestClient."""
    limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=5, name="api_test")
    limiter.reset()

    test_app = FastAPI()

    @test_app.post("/test-auth", dependencies=[Depends(limiter)])
    def dummy_auth():
        return {"status": "ok"}

    # Temporarily force rate limiter active despite pytest environment
    old_test_mode = os.environ.get("TRADESATHI_TEST_MODE")
    old_pytest = os.environ.get("PYTEST_CURRENT_TEST")
    try:
        if "PYTEST_CURRENT_TEST" in os.environ:
            del os.environ["PYTEST_CURRENT_TEST"]
        os.environ["TRADESATHI_TEST_MODE"] = "0"
        os.environ["RATE_LIMITING_ENABLED"] = "1"

        client = TestClient(test_app)

        # First 2 requests succeed
        res1 = client.post("/test-auth")
        assert res1.status_code == 200

        res2 = client.post("/test-auth")
        assert res2.status_code == 200

        # 3rd request blocked with 429
        res3 = client.post("/test-auth")
        assert res3.status_code == 429
        assert "Rate limit exceeded" in res3.json()["detail"]
        assert "Retry-After" in res3.headers
    finally:
        if old_pytest:
            os.environ["PYTEST_CURRENT_TEST"] = old_pytest
        if old_test_mode is not None:
            os.environ["TRADESATHI_TEST_MODE"] = old_test_mode
        else:
            os.environ.pop("TRADESATHI_TEST_MODE", None)
