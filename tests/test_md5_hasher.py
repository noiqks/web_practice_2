import hashlib
import tempfile
import unittest
from pathlib import Path

from src.md5_hasher import calculate_md5


class TestCalculateMd5(unittest.TestCase):
    def test_calculate_md5(self):
        content = b"hello"
        expected = hashlib.md5(content).hexdigest()

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.txt"
            input_path.write_bytes(content)

            result = calculate_md5(input_path)

        self.assertEqual(result, expected)


if __name__ == "__main__":
    unittest.main()
