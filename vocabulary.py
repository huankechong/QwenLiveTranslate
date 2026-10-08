"""生词本：从同传句流自动采集生词，SQLite 存储，Anki 导出。

数据模型（vocabulary 表）：
- word        生词（原文语言的单词条目，小写归一）
- translation 释义（句级译文太粗，这里存句译文供 Anki 例句上下文）
- context     出处句（原文整句——Anki 的 Example 字段）
- source      来源（mic/loopback + 引擎 id，溯源用）
- first_ts / hits  首次遇到时间 / 出现次数（同词重复出现只计次不重插）

采集策略（P2a，词级切分）：
- 句终回调（on_source final）时对原文分词
- 只收"生词候选"：长度 ≥3 的字母词（英文场景）且不在停用词表
- 已在库中的词只 +1 hits（高频词自动浮现，按 hits 排序复习优先级）
"""

from __future__ import annotations

import re
import sqlite3
import threading
import time
from pathlib import Path

import settings as st

# 英语高频功能词（生词本不该收 the/and/is…）
_STOPWORDS = frozenset("""
the a an and or but if then else of to in on at for with by from as is are was
were be been being do does did have has had will would can could should may
might must shall this that these those it its he she they we you i me my his
her their our your them us him so not no yes what which who whom when where
why how all any some more most other such only own same too very just also
than there here about into over after before under above out up down off again
once each few both between during without within along across behind beyond
plus ok okay yeah hey well like really actually basically maybe right going
get got go goes come came make made take taken know knew think thought want
wanted see saw look looked say said tell told ask asked
""".split())

_WORD_RE = re.compile(r"[A-Za-z]{3,}")


def db_path() -> Path:
    """生词库路径：与 settings/history 同目录策略。"""
    return st._base_dir() / "vocabulary.db"


class VocabStore:
    """线程安全生词仓库（与 HistoryStore 同款：单连接 + 锁 + WAL）。"""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else db_path()
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS vocabulary(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word TEXT NOT NULL,
                translation TEXT,
                context TEXT,
                source TEXT,
                first_ts REAL,
                hits INTEGER DEFAULT 1,
                UNIQUE(word))"""
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_vocab_hits ON vocabulary(hits DESC)")
        self._conn.commit()

    # ---------- 采集 ----------
    @staticmethod
    def extract_candidates(sentence: str) -> list[str]:
        """从一句原文提取生词候选（≥3 字母词、去停用词、小写去重）。"""
        words = [w.lower() for w in _WORD_RE.findall(sentence or "")]
        seen: set[str] = set()
        out: list[str] = []
        for w in words:
            if w in _STOPWORDS or w in seen:
                continue
            seen.add(w)
            out.append(w)
        return out

    def record_sentence(self, sentence: str, translation: str = "",
                        source: str = "") -> list[str]:
        """句终采集：新词入库（返回新入库的词），旧词 hits+1。"""
        newly: list[str] = []
        with self._lock:
            for w in self.extract_candidates(sentence):
                cur = self._conn.execute(
                    "SELECT id FROM vocabulary WHERE word=?", (w,)).fetchone()
                if cur:
                    self._conn.execute(
                        "UPDATE vocabulary SET hits=hits+1 WHERE id=?",
                        (cur[0],))
                else:
                    self._conn.execute(
                        "INSERT INTO vocabulary(word,translation,context,source,first_ts)"
                        " VALUES(?,?,?,?,?)",
                        (w, translation, sentence, source, time.time()))
                    newly.append(w)
            self._conn.commit()
        return newly

    # ---------- 查询 ----------
    def recent(self, limit: int = 200, offset: int = 0) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id,word,translation,context,source,first_ts,hits"
                " FROM vocabulary ORDER BY first_ts DESC LIMIT ? OFFSET ?",
                (limit, offset)).fetchall()
        keys = ("id", "word", "translation", "context", "source",
                "first_ts", "hits")
        return [dict(zip(keys, r)) for r in rows]

    def top(self, limit: int = 50) -> list[dict]:
        """高频词（复习优先）。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id,word,translation,context,source,first_ts,hits"
                " FROM vocabulary ORDER BY hits DESC, first_ts DESC LIMIT ?",
                (limit,)).fetchall()
        keys = ("id", "word", "translation", "context", "source",
                "first_ts", "hits")
        return [dict(zip(keys, r)) for r in rows]

    def search(self, q: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id,word,translation,context,source,first_ts,hits"
                " FROM vocabulary WHERE word LIKE ? ORDER BY hits DESC",
                (f"%{q}%",)).fetchall()
        keys = ("id", "word", "translation", "context", "source",
                "first_ts", "hits")
        return [dict(zip(keys, r)) for r in rows]

    def count(self) -> int:
        with self._lock:
            return self._conn.execute(
                "SELECT COUNT(*) FROM vocabulary").fetchone()[0]

    def delete(self, word_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM vocabulary WHERE id=?", (word_id,))
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass

    # ---------- 导出 ----------
    def export_anki_tsv(self, out_path: str | Path,
                        limit: int | None = None) -> int:
        """Anki 直接导入的 TSV（制表符分隔，UTF-8 无 BOM）。

        列：word TAB context TAB translation
        Anki「导入文件」选 Basic (and reversed card) 可直接吃。
        """
        with self._lock:
            if limit:
                rows = self._conn.execute(
                    "SELECT word,context,translation FROM vocabulary"
                    " ORDER BY hits DESC LIMIT ?", (limit,)).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT word,context,translation FROM vocabulary"
                    " ORDER BY hits DESC").fetchall()
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8", newline="") as f:
            for w, ctx, tr in rows:
                # TSV 转义：制表符/换行在字段内替换（Anki 导入容错）
                esc = lambda s: (s or "").replace("\t", " ").replace("\n", " ")
                f.write(f"{esc(w)}\t{esc(ctx)}\t{esc(tr)}\n")
        return len(rows)


# ---------- 单例（与 history 同款懒加载） ----------
_STORE: VocabStore | None = None
_STORE_LOCK = threading.Lock()


def shutdown():
    """应用退出时关闭连接（console.closeEvent 调用；与 history.shutdown 对称）。"""
    global _STORE
    with _STORE_LOCK:
        if _STORE is not None:
            try:
                _STORE.close()
            except Exception:  # noqa: BLE001
                pass
            _STORE = None


def store() -> VocabStore:
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            try:
                _STORE = VocabStore()
            except Exception:  # noqa: BLE001 — 只读目录等：生词本静默停用
                _STORE = _NullVocab()
        return _STORE


class _NullVocab:
    """降级空实现（库不可用时保启动）。"""

    def record_sentence(self, *a, **k):  # noqa: ANN002, ANN003
        return []

    def recent(self, limit=200, offset=0):  # noqa: ANN001
        return []

    def top(self, limit=50):  # noqa: ANN001
        return []

    def search(self, q):  # noqa: ANN001
        return []

    def count(self):  # noqa: ANN201
        return 0

    def delete(self, word_id):  # noqa: ANN001
        pass

    def export_anki_tsv(self, out_path, limit=None):  # noqa: ANN001
        raise RuntimeError("生词库不可用（目录只读？），无法导出")

    def close(self):  # noqa: D102
        pass
