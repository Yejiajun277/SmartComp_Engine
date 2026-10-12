from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DefaultModelConfigTests(unittest.TestCase):
    def test_unconfigured_runtime_defaults_to_mimo_v2_6_pro(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            shutil.copy2(PROJECT_ROOT / "config.py", Path(temp_dir) / "config.py")
            env = os.environ.copy()
            env.pop("MIMO_MODEL", None)

            result = subprocess.run(
                [sys.executable, "-c", "import config; print(config.MIMO_MODEL)"],
                cwd=temp_dir,
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )

        self.assertEqual(result.stdout.strip(), "mimo-v2.6-pro")


if __name__ == "__main__":
    unittest.main()
