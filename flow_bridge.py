"""Cầu nối WebSocket giữa ThinAPTM (đồng bộ, threading) và Chrome Extension
(flow_bridge trong extension/) chạy trong tab flow.google.com thật của từng
tài khoản.

Kiến trúc: 1 luồng nền chạy asyncio event loop riêng (loop.run_forever),
websockets.serve() lắng nghe trên loop đó. Phần còn lại của ThinAPTM (chạy
threading.Thread thuần, không asyncio) chỉ gọi hàm chặn đồng bộ `call()`,
được cài bằng asyncio.run_coroutine_threadsafe — process_one() không cần biết
asyncio tồn tại.

Khác biệt CỐ Ý so với bản gốc FlowKit (E:\\0 -Flowkit\\agent\\services\\flow_client.py):
bản gốc coi mọi extension kết nối là ngang hàng/thay thế cho nhau (1 dòng job
logic duy nhất, nhiều profile chỉ để failover). ThinAPTM có N tài khoản khác
nhau, mỗi tài khoản có hàng đợi job riêng — job của tài khoản A KHÔNG được lọt
sang tab của tài khoản B. Vì vậy không có logic "chọn cái nào đang rảnh" —
định tuyến theo đúng email, không có kết nối thì báo lỗi rõ ràng, không dùng
tài khoản khác thay thế.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import threading
import time
import uuid
from typing import Any, Optional

import websockets

logger = logging.getLogger(__name__)

WS_HOST = "127.0.0.1"
WS_PORT = 9333  # khác cổng 9222 của FlowKit, phòng chạy song song 2 tool trên cùng máy


class FlowBridge:
    def __init__(self):
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._server = None
        self._connections: dict[str, Any] = {}          # email -> websocket
        self._connected_at: dict[str, float] = {}        # email -> timestamp
        self._pending: dict[str, asyncio.Future] = {}     # req_id -> future
        self._projects: dict[str, str] = {}               # email -> Flow project id, TỰ PHÁT HIỆN
                                                            # từ URL tab (extension/content.js) — không
                                                            # cần người dùng tự tay copy UUID nữa.
        self._on_project_detected = None                  # fn(email, project_id) — app gắn để tự lưu accounts.json
        self._lock = threading.Lock()                     # bảo vệ _connections/_connected_at khi đọc từ luồng khác

    # ── vòng đời ──────────────────────────────────────────────

    def start(self):
        """Khởi động luồng nền + event loop + WS server. Gọi nhiều lần an toàn (no-op nếu đã chạy)."""
        if self._thread and self._thread.is_alive():
            return
        ready = threading.Event()

        def _run():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.create_task(self._serve())
            ready.set()
            try:
                self._loop.run_forever()
            finally:
                self._loop.close()

        self._thread = threading.Thread(target=_run, daemon=True, name="FlowBridgeLoop")
        self._thread.start()
        ready.wait(timeout=5)

    def stop(self):
        """Đóng server + dừng event loop. An toàn khi gọi dù chưa start()."""
        loop = self._loop
        if not loop or not loop.is_running():
            return

        async def _shutdown():
            if self._server is not None:
                self._server.close()
                await self._server.wait_closed()

        try:
            fut = asyncio.run_coroutine_threadsafe(_shutdown(), loop)
            fut.result(timeout=5)
        except Exception:
            pass
        loop.call_soon_threadsafe(loop.stop)
        if self._thread:
            self._thread.join(timeout=5)
        with self._lock:
            self._connections.clear()
            self._connected_at.clear()

    async def _serve(self):
        self._server = await websockets.serve(self._handler, WS_HOST, WS_PORT)
        logger.info("FlowBridge WS server listening on ws://%s:%s", WS_HOST, WS_PORT)

    # ── xử lý kết nối extension ───────────────────────────────

    async def _handler(self, websocket):
        path = getattr(websocket, "path", "") or ""
        email = self._email_from_path(path)
        if not email:
            # Chờ 1 lần "extension_ready" mang email nếu path không có query string
            try:
                raw = await asyncio.wait_for(websocket.recv(), timeout=5)
                data = json.loads(raw)
                email = data.get("email")
            except Exception:
                email = None
        if not email:
            logger.warning("FlowBridge: extension connected without account email, closing")
            await websocket.close()
            return

        with self._lock:
            self._connections[email] = websocket
            self._connected_at[email] = time.time()
        logger.info("FlowBridge: account connected: %s", email)

        try:
            async for raw in websocket:
                try:
                    data = json.loads(raw)
                except Exception:
                    continue
                # Extension tự phát hiện project id từ URL tab (content.js đọc
                # flow.google.com/project/<uuid>) và báo lên đây liên tục — không
                # cần người dùng tự tay copy UUID dán vào accounts.json nữa, và tự
                # bắt được project MỚI nếu người dùng đổi/tạo project khác giữa chừng.
                if data.get("type") == "project_detected" and data.get("projectId"):
                    pid = data["projectId"]
                    with self._lock:
                        changed = self._projects.get(email) != pid
                        self._projects[email] = pid
                    if changed:
                        logger.info("FlowBridge: project id của %s = %s", email, pid)
                        if self._on_project_detected:
                            try:
                                self._on_project_detected(email, pid)
                            except Exception:
                                pass
                    continue
                req_id = data.get("id")
                if req_id and req_id in self._pending:
                    if not self._pending[req_id].done():
                        self._pending[req_id].set_result(data)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            with self._lock:
                if self._connections.get(email) is websocket:
                    self._connections.pop(email, None)
                    self._connected_at.pop(email, None)
            logger.info("FlowBridge: account disconnected: %s", email)

    @staticmethod
    def _email_from_path(path: str) -> Optional[str]:
        if not path or "?" not in path:
            return None
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(path).query)
        vals = qs.get("email")
        return vals[0] if vals else None

    # ── định tuyến/gọi RPC (chạy trên event loop) ──────────────

    async def _call_async(self, email: str, method: str, params: dict, timeout: float) -> dict:
        ws = self._connections.get(email)
        if ws is None:
            return {"error": "account_not_connected"}
        req_id = str(uuid.uuid4())
        future = self._loop.create_future()
        self._pending[req_id] = future
        try:
            await ws.send(json.dumps({"id": req_id, "method": method, "params": params}))
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            return {"error": "bridge_timeout"}
        except websockets.exceptions.ConnectionClosed:
            return {"error": "account_not_connected"}
        except Exception as e:
            return {"error": str(e)}
        finally:
            self._pending.pop(req_id, None)

    # ── API chặn đồng bộ cho phần threading.Thread hiện có ─────

    def call(self, email: str, method: str, params: dict, timeout: float = 120) -> dict:
        """Hàm chặn (blocking) bình thường — process_one()/engine_ext.py gọi thẳng,
        không cần biết bên trong dùng asyncio."""
        if not self._loop or not self._loop.is_running():
            return {"error": "bridge_not_started"}
        fut = asyncio.run_coroutine_threadsafe(
            self._call_async(email, method, params, timeout), self._loop
        )
        try:
            return fut.result(timeout=timeout + 5)
        except (asyncio.TimeoutError, concurrent.futures.TimeoutError):
            return {"error": "bridge_timeout"}
        except Exception as e:
            return {"error": str(e)}

    def is_account_connected(self, email: str) -> bool:
        with self._lock:
            return email in self._connections

    def connected_accounts(self) -> list[str]:
        with self._lock:
            return list(self._connections.keys())

    def get_project(self, email: str) -> Optional[str]:
        """Project id MỚI NHẤT do extension tự phát hiện từ URL tab — luôn là
        nguồn ưu tiên (không phải giá trị tĩnh lưu sẵn), nên nếu người dùng tạo
        project mới/đổi project giữa chừng, lần gọi tiếp theo tự nhận đúng cái mới."""
        with self._lock:
            return self._projects.get(email)

    def set_on_project_detected(self, fn):
        """App gắn callback fn(email, project_id) — gọi mỗi khi phát hiện project
        MỚI/khác, để tự lưu vào accounts.json làm fallback (không bắt buộc)."""
        self._on_project_detected = fn


_bridge: Optional[FlowBridge] = None
_bridge_lock = threading.Lock()


def get_bridge() -> FlowBridge:
    global _bridge
    with _bridge_lock:
        if _bridge is None:
            _bridge = FlowBridge()
        return _bridge


def start():
    get_bridge().start()


def stop():
    if _bridge is not None:
        _bridge.stop()


def call(email: str, method: str, params: dict, timeout: float = 120) -> dict:
    return get_bridge().call(email, method, params, timeout=timeout)


def is_account_connected(email: str) -> bool:
    return get_bridge().is_account_connected(email)


def get_project(email: str) -> Optional[str]:
    return get_bridge().get_project(email)


def set_on_project_detected(fn):
    get_bridge().set_on_project_detected(fn)
