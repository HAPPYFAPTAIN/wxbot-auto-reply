import os
import tempfile
import unittest
from unittest import mock

import wxbot


class VisionTests(unittest.TestCase):
    def test_content_accepts_openai_content_parts(self):
        data = {"choices": [{"message": {"content": [
            {"type": "text", "text": "最终答案：一张模型排行榜截图。"},
        ]}}]}
        self.assertEqual("一张模型排行榜截图。", wxbot._vision_content(data))

    def test_retries_transient_tls_error(self):
        cfg = {"vision": {
            "enabled": True, "base_url": "https://example.test/v1",
            "model": "vision-model", "api_key": "test", "retries": 1,
        }}
        good = {"choices": [{"message": {"content": "一张模型排行榜截图。"}}]}
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as image:
            image.write(b"test-image")
            image_path = image.name
        try:
            with mock.patch.object(
                wxbot, "_http_post_json",
                side_effect=[RuntimeError("TLS connect error"), good],
            ) as post, mock.patch.object(wxbot.time, "sleep"):
                self.assertEqual("一张模型排行榜截图。", wxbot.vision_describe(cfg, image_path))
                self.assertEqual(2, post.call_count)
        finally:
            os.remove(image_path)

    def test_fallback_runs_after_primary_failure(self):
        cfg = {"vision": {
            "enabled": True, "base_url": "https://primary.test/v1",
            "model": "primary", "api_key": "test", "retries": 0,
            "fallbacks": [{
                "base_url": "https://fallback.test/v1", "model": "fallback",
                "api_key": "test", "retries": 0,
            }],
        }}
        good = {"choices": [{"message": {"content": "备用通道识图成功。"}}]}
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as image:
            image.write(b"test-image")
            image_path = image.name
        try:
            with mock.patch.object(wxbot, "_http_post_json", side_effect=[RuntimeError("bad request"), good]) as post:
                self.assertEqual("备用通道识图成功。", wxbot.vision_describe(cfg, image_path))
                self.assertEqual(2, post.call_count)
        finally:
            os.remove(image_path)


class InteractionTests(unittest.TestCase):
    def test_avatar_point_is_inside_message_row(self):
        import wxmini2
        rect = (840, 360, 1700, 470)
        x, y = wxmini2.avatar_point_from_message_rect(rect)
        self.assertGreater(x, rect[0])
        self.assertLess(x, rect[0] + 60)
        self.assertGreater(y, rect[1])
        self.assertLess(y, rect[3])

    def test_poke_marker_survives_sentence_split(self):
        self.assertEqual(["这波可以", "[POKE]", "[EMOJI:旺柴]"],
                         wxbot.split_sentences("这波可以\n[POKE]\n[EMOJI:旺柴]"))

    def test_behavior_defaults_include_poke(self):
        beh = wxbot.behavior_for({"reply": {"personas": {}}}, "")
        self.assertEqual(0.1, beh["poke"])

    def test_poke_system_notice_is_filtered(self):
        self.assertTrue(wxbot.is_poke_notice("张三拍了拍李四"))
        self.assertFalse(wxbot.is_poke_notice("拍一拍这个功能怎么用"))


if __name__ == "__main__":
    unittest.main()
