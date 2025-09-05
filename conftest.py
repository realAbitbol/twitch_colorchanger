# Ensure project root is on sys.path so 'src' is importable when running pytest from
# environments that don't automatically include it.
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
