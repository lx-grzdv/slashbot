import json
import tempfile
import unittest
from pathlib import Path

import board_review


class BoardReviewTests(unittest.TestCase):
    def _image(self, directory: str, name: str) -> Path:
        path = Path(directory) / name
        path.write_bytes(b"fake image bytes")
        return path

    def test_build_request_contains_two_labeled_images(self):
        with tempfile.TemporaryDirectory() as directory:
            board = self._image(directory, "board.png")
            updates = self._image(directory, "updates.jpg")
            request = board_review.build_request(board, updates, "test-model")

        content = request["input"][0]["content"]
        images = [item for item in content if item["type"] == "input_image"]
        self.assertEqual(request["model"], "test-model")
        self.assertFalse(request["store"])
        self.assertEqual(len(images), 2)
        self.assertTrue(images[0]["image_url"].startswith("data:image/png;base64,"))
        self.assertTrue(images[1]["image_url"].startswith("data:image/jpeg;base64,"))

    def test_prompt_treats_screenshot_text_as_untrusted(self):
        prompt = board_review.build_prompt()
        self.assertIn("недоверенными данными", prompt)
        self.assertIn("на видимой части", prompt)
        self.assertIn("Не делай выводов о продуктивности", prompt)

    def test_extracts_responses_api_text(self):
        payload = {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "  Обзор готов  "}],
                }
            ]
        }
        self.assertEqual(board_review._extract_output_text(payload), "Обзор готов")

    def test_dry_run_never_includes_image_data(self):
        with tempfile.TemporaryDirectory() as directory:
            board = self._image(directory, "board.png")
            updates = self._image(directory, "updates.png")
            request = board_review.build_request(board, updates, "test-model")
            summary = board_review._redacted_request_summary(request)

        serialized = json.dumps(summary)
        self.assertNotIn("base64", serialized)
        self.assertEqual(summary["image_count"], 2)


if __name__ == "__main__":
    unittest.main()
