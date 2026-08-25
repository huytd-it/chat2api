"""Kho SQLite dùng chung cho toàn app (xem docs/design-v2.md §2).

Ba ràng buộc định hình module này:

1. **SQLite là blocking.** Không được gọi thẳng trên event loop. Mọi lệnh GHI đi
   qua một thread ghi duy nhất (`_Writer`) theo kiểu bắn-rồi-quên; mọi lệnh ĐỌC
   chạy trong `asyncio.to_thread` với connection riêng theo thread.
2. **Ghi log không được làm hỏng request.** `submit()` không bao giờ ném lỗi —
   DB hỏng thì app vẫn chat được, chỉ mất phần ghi lịch sử.
3. **Import không được ghi ra đĩa.** `chat2api.main` tạo `app` ngay lúc import,
   nên `connect()` chỉ được gọi trong lifespan chứ không phải lúc dựng app —
   cùng lý do với `accounts.migrate_legacy`.

Quy ước migration: `schema.sql` luôn là *trạng thái sau khi apply toàn bộ
migration*, không bao giờ sửa để thêm cột. DB rỗng chạy `schema.sql` rồi đóng
dấu thẳng mọi version đã biết; DB cũ chỉ apply những file `migrations/NNNN_*.sql`
còn thiếu.
"""

import queue
import sqlite3
import sys
import threading
import time
from pathlib import Path

PACKAGE_DIR = Path(__file__).parent
SCHEMA_PATH = PACKAGE_DIR / "schema.sql"
MIGRATIONS_DIR = PACKAGE_DIR / "migrations"
# Version của chính schema.sql. File migrations/ bắt đầu từ 2.
BASELINE_VERSION = 1
BASELINE_NAME = "schema.sql"

_STOP = object()
_MAX_BATCH = 256


def now_ms() -> int:
    """Epoch milliseconds — đơn vị thời gian của mọi cột INTEGER trong schema."""
    return int(time.time() * 1000)


class _Flush:
    __slots__ = ("event",)

    def __init__(self) -> None:
        self.event = threading.Event()


class _Writer(threading.Thread):
    """Thread ghi duy nhất: gom lệnh theo lô, một transaction cho mỗi lô.

    Một writer nghĩa là không bao giờ có hai transaction ghi tranh nhau, nên
    không gặp SQLITE_BUSY dù WAL đã cho phép đọc song song.
    """

    def __init__(self, db_path: Path):
        super().__init__(name="chat2api-store-writer", daemon=True)
        self._db_path = db_path
        self._queue: queue.Queue = queue.Queue()

    def submit(self, sql: str, params: tuple) -> None:
        self._queue.put((sql, params))

    def flush(self, timeout: float = 5.0) -> bool:
        marker = _Flush()
        self._queue.put(marker)
        return marker.event.wait(timeout)

    def stop(self, timeout: float = 5.0) -> None:
        self._queue.put(_STOP)
        self.join(timeout)

    def run(self) -> None:
        conn = _new_connection(self._db_path)
        try:
            while True:
                item = self._queue.get()
                if item is _STOP:
                    return
                batch, flushes, stopping = self._drain(item)
                if batch:
                    self._apply(conn, batch)
                for marker in flushes:
                    marker.event.set()
                if stopping:
                    return
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _drain(self, first) -> tuple[list, list, bool]:
        """Gom thêm những lệnh đã xếp hàng để một transaction ghi được nhiều dòng."""
        batch: list = []
        flushes: list = []
        stopping = False
        item = first
        while True:
            if item is _STOP:
                stopping = True
                break
            if isinstance(item, _Flush):
                flushes.append(item)
            else:
                batch.append(item)
            if len(batch) >= _MAX_BATCH:
                break
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
        return batch, flushes, stopping

    @staticmethod
    def _apply(conn: sqlite3.Connection, batch: list) -> None:
        try:
            with conn:
                for sql, params in batch:
                    conn.execute(sql, params)
            return
        except Exception as error:
            # Nuốt lỗi có chủ đích: ghi lịch sử hỏng không được kéo theo app.
            # In ra stderr để còn thấy được khi chạy dưới sidecar.
            print(f"[chat2api] store write failed ({len(batch)} lệnh): {error}",
                  file=sys.stderr)
        # Cả lô nằm trong một transaction, nên một lệnh hỏng vừa cuốn theo mọi
        # lệnh lành cùng lô. Thử lại từng lệnh một để chỉ mất đúng cái hỏng.
        for sql, params in batch:
            try:
                with conn:
                    conn.execute(sql, params)
            except Exception:
                pass


def _new_connection(db_path: Path) -> sqlite3.Connection:
    """Connection cho một thread. Chỉ đặt pragma theo-connection ở đây.

    `journal_mode` là thuộc tính bền của chính file DB, không phải của
    connection: đặt lại từ connection thứ hai cần khoá độc quyền và trả
    SQLITE_BUSY ngay lập tức (busy_timeout không cứu được) khi có reader khác
    đang mở. Nó được đặt đúng một lần trong `Store.__init__`.
    """
    # check_same_thread=False chỉ để `close()` lúc shutdown chạy được từ thread
    # khác. Bản thân connection vẫn chỉ được *dùng* bởi thread tạo ra nó —
    # `Store._local` là threading.local, không có connection nào bị chia sẻ.
    conn = sqlite3.connect(str(db_path), timeout=5.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


class Store:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # WAL phải được bật khi còn đúng một connection mở — xem _new_connection.
        bootstrap = sqlite3.connect(str(self.db_path), timeout=5.0)
        try:
            bootstrap.execute("PRAGMA journal_mode=WAL")
        finally:
            bootstrap.close()
        self._local = threading.local()
        # Connection đọc được tạo theo từng thread của to_thread pool; giữ danh
        # sách để đóng hết lúc shutdown thay vì để file handle rơi rớt.
        self._readers: list[sqlite3.Connection] = []
        self._readers_lock = threading.Lock()
        self._writer = _Writer(self.db_path)
        self._writer.start()

    # ---------------------------------------------------------------- ghi

    def submit(self, sql: str, params: tuple = ()) -> None:
        """Xếp một lệnh ghi vào hàng đợi. Không bao giờ ném lỗi, không chờ."""
        try:
            self._writer.submit(sql, params)
        except Exception:
            pass

    def flush(self, timeout: float = 5.0) -> bool:
        """Chờ hàng đợi ghi rỗng. Dùng trong test và lúc shutdown."""
        try:
            return self._writer.flush(timeout)
        except Exception:
            return False

    # ---------------------------------------------------------------- đọc

    def connection(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = _new_connection(self.db_path)
            self._local.conn = conn
            with self._readers_lock:
                self._readers.append(conn)
        return conn

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        """Đọc đồng bộ. Gọi từ `asyncio.to_thread` khi ở trong handler async."""
        return self.connection().execute(sql, params).fetchall()

    # ------------------------------------------------------------ vòng đời

    def migrate(self) -> int:
        """Đưa DB lên version mới nhất. Trả về version sau khi xong."""
        conn = self.connection()
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at INTEGER NOT NULL)")
        conn.commit()
        applied = {row["version"] for row in conn.execute(
            "SELECT version FROM schema_migrations")}
        pending = _migration_files()

        if not applied:
            # DB rỗng: schema.sql đã chứa kết quả của mọi migration, nên chạy nó
            # rồi đóng dấu hết — apply lại từng file sẽ là double-apply.
            with conn:
                conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
                _stamp(conn, BASELINE_VERSION, BASELINE_NAME)
                for version, path in pending:
                    _stamp(conn, version, path.name)
            return max([BASELINE_VERSION] + [v for v, _ in pending])

        for version, path in pending:
            if version in applied:
                continue
            with conn:
                conn.executescript(path.read_text(encoding="utf-8"))
                _stamp(conn, version, path.name)
        return conn.execute(
            "SELECT COALESCE(MAX(version), 0) AS v FROM schema_migrations").fetchone()["v"]

    def close(self) -> None:
        self._writer.stop()
        with self._readers_lock:
            readers, self._readers = self._readers, []
        for conn in readers:
            try:
                conn.close()
            except Exception:
                pass


def _stamp(conn: sqlite3.Connection, version: int, name: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
        (version, name, now_ms()))


def _migration_files() -> list[tuple[int, Path]]:
    if not MIGRATIONS_DIR.is_dir():
        return []
    out: list[tuple[int, Path]] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        prefix = path.name.split("_", 1)[0]
        if not prefix.isdigit():
            continue
        version = int(prefix)
        if version <= BASELINE_VERSION:
            raise RuntimeError(
                f"migration {path.name} dùng version {version}, phải > {BASELINE_VERSION}")
        out.append((version, path))
    return out


# ----------------------------------------------------------- singleton toàn app

_default: Store | None = None
_default_lock = threading.Lock()


def connect(db_path: Path) -> Store:
    """Mở kho và đặt làm mặc định toàn app. Gọi một lần trong lifespan."""
    global _default
    with _default_lock:
        if _default is not None:
            _default.close()
        _default = Store(db_path)
        return _default


def default() -> Store | None:
    """Kho mặc định, hoặc None khi chưa mở (CLI, test đơn vị, import-time)."""
    return _default


def shutdown() -> None:
    global _default
    with _default_lock:
        store, _default = _default, None
    if store is not None:
        store.flush(timeout=3.0)
        store.close()
