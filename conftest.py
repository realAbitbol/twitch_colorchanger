# Ensure project root is on sys.path so 'src' is importable when running pytest from
# environments that don't automatically include it.
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
async def cancel_pending_flush_after_test():
    """Cancel any pending flush tasks after each test to prevent warnings."""
    yield
    from src.config.async_persistence import cancel_pending_flush

    await cancel_pending_flush()
