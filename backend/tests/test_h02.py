"""H02 越权修复回归：值班员只读，写口拒绝且零残行；记录员落库成功。

覆盖三层：
1. 策略层 watcher_pass / h02_ui_trap：reader 不可写、报温框仅 writer 可见、失败不刷新；
2. 接口层 aiohttp：reader 写口 403 且 INSERT 一次都不执行，writer 201 落库，reader 读口仍可用；
3. 种子判定不变：A01 4.2℃ 合格、B02 12.5℃ 超温。
"""

import json
import unittest
from datetime import datetime, timezone

from aiohttp.test_utils import AioHTTPTestCase

import api
import h02_ui_trap
from rules import judge_temp
from watcher_pass import (
    allow_write,
    should_refresh_after_fail,
    should_show_form,
)


# ---------------------------------------------------------------- 策略层

class PolicyTests(unittest.TestCase):
    def test_reader_cannot_write(self):
        assert allow_write({"username": "watcher", "role": "reader"}) is False

    def test_writer_can_write(self):
        assert allow_write({"username": "logger", "role": "writer"}) is True

    def test_form_visible_only_to_writer(self):
        assert should_show_form(True) is True
        assert should_show_form(False) is False
        assert h02_ui_trap.paint_form(True) is True
        assert h02_ui_trap.paint_form(False) is False

    def test_failed_submit_never_refreshes_list(self):
        # 无论身份，提交失败都不得刷新总表（刷新正是“随后多一行/空行”的入口）。
        assert should_refresh_after_fail(False) is False
        assert should_refresh_after_fail(True) is False
        assert h02_ui_trap.reload_on_fail(False) is False
        assert h02_ui_trap.reload_on_fail(True) is False

    def test_seed_verdicts_unchanged(self):
        assert judge_temp(4.2) == ("合格", "探头温度未超过 8℃ 上限")
        assert judge_temp(12.5) == ("超温", "探头温度超过 8℃ 冷链上限")


# ---------------------------------------------------------------- 接口层

class FakeRow:
    def __init__(self, data):
        self._data = data

    def __getitem__(self, key):
        return self._data[key]


class FakePool:
    """记录 INSERT 调用：任何一次 fetchrow 都算总表多出一行。"""

    def __init__(self):
        self.inserts = []

    async def fetchrow(self, query, *args):
        probe_id, temp_c, username = args
        self.inserts.append((probe_id, temp_c, username))
        return FakeRow(
            {
                "id": 1,
                "probe_id": probe_id,
                "temp_c": temp_c,
                "verdict": None,
                "reason": None,
                "status": "pending",
                "created_by": username,
                "created_at": datetime(2026, 10, 2, tzinfo=timezone.utc),
                "processed_at": None,
            }
        )

    async def fetch(self, query, *args):
        return []

    async def close(self):
        return None


class ApiPermissionTests(AioHTTPTestCase):
    async def setUpAsync(self):
        self.pool = FakePool()
        await super().setUpAsync()

    async def get_application(self):
        app = api.create_app()
        # 跳过真实数据库启动/清理钩子，直接注入假连接池。
        app.on_startup.clear()
        app.on_cleanup.clear()
        app["pool"] = self.pool
        return app

    async def _token(self, username, password):
        async with self.client.post(
            "/api/auth/login", json={"username": username, "password": password}
        ) as resp:
            assert resp.status == 200
            return (await resp.json())["access_token"]

    async def test_writer_submit_persists_one_row(self):
        token = await self._token("logger", "log123456")
        async with self.client.post(
            "/api/readings",
            json={"probe_id": "探头C03", "temp_c": 5.0},
            headers={"Authorization": f"Bearer {token}"},
        ) as resp:
            assert resp.status == 201
            body = await resp.json()
            assert body["created_by"] == "logger"
            assert body["status"] == "pending"
        # 记录员交压一次：总表恰好落库一行。
        assert self.pool.inserts == [("探头C03", 5.0, "logger")]

    async def test_reader_submit_forbidden_with_zero_residual_rows(self):
        token = await self._token("watcher", "watch123456")
        async with self.client.post(
            "/api/readings",
            json={"probe_id": "探头C03", "temp_c": 5.0},
            headers={"Authorization": f"Bearer {token}"},
        ) as resp:
            assert resp.status == 403
            data = json.loads(await resp.text())
            assert "只读" in data["detail"]
        # 核心验收：值班员交压后行数不变——INSERT 根本不得被执行。
        assert self.pool.inserts == []

    async def test_reader_can_still_read_list(self):
        token = await self._token("watcher", "watch123456")
        async with self.client.get(
            "/api/readings", headers={"Authorization": f"Bearer {token}"}
        ) as resp:
            assert resp.status == 200
            assert await resp.json() == []

    async def test_anonymous_submit_rejected(self):
        async with self.client.post(
            "/api/readings", json={"probe_id": "x", "temp_c": 1}
        ) as resp:
            assert resp.status == 401
        assert self.pool.inserts == []


if __name__ == "__main__":
    unittest.main()
