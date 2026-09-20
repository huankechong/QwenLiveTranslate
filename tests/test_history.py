# -*- coding: utf-8 -*-
"""history 存储：增删查/CSV 导出/降级单例。"""
import csv
import time

import history


class TestHistoryStore:
    def test_add_recent_roundtrip(self, tmp_path):
        s = history.HistoryStore(tmp_path / "h.db")
        sid = s.add("zh", "de", None, "你好", "Hallo", 123)
        assert sid >= 1
        rows = s.recent(limit=10)
        assert len(rows) == 1
        assert rows[0]["original"] == "你好"
        assert rows[0]["translation"] == "Hallo"
        assert rows[0]["latency_ms"] == 123
        s.close()

    def test_recent_order_desc(self, tmp_path):
        s = history.HistoryStore(tmp_path / "h.db")
        for i in range(5):
            s.add("zh", "en", None, f"o{i}", f"t{i}")
        rows = s.recent(limit=3)
        assert [r["original"] for r in rows] == ["o4", "o3", "o2"]
        s.close()

    def test_clear(self, tmp_path):
        s = history.HistoryStore(tmp_path / "h.db")
        s.add("zh", "en", None, "a", "b")
        s.clear()
        assert s.count() == 0
        s.close()

    def test_export_csv_bom_and_order(self, tmp_path):
        s = history.HistoryStore(tmp_path / "h.db")
        s.add("zh", "en", None, "第一句", "first")
        s.add("zh", "en", None, "第二句", "second")
        out = tmp_path / "out.csv"
        n = s.export_csv(str(out))
        assert n == 2
        raw = out.read_bytes()
        assert raw[:3] == b"\xef\xbb\xbf"  # UTF-8 BOM
        rows = list(csv.reader(raw.decode("utf-8-sig").splitlines()))
        assert rows[0][:3] == ["时间", "源语种", "目标语种"]
        assert rows[1][3] == "第一句"  # 旧→新正序
        assert rows[2][3] == "第二句"
        s.close()

    def test_null_store_fallback(self, tmp_path, monkeypatch):
        """目录不可写时降级 _NullStore，不崩。"""
        monkeypatch.setattr(history, "_db_path",
                            lambda: tmp_path / "ro" / "h.db")
        store = history.get_store()
        assert store.add("a", "b", None, "x", "y") == -1
        assert store.recent() == []
