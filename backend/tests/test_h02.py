"""H02 越权修复回归测试。

覆盖三处缺陷：
1. 值班员首页不得再出现报温框（should_show_form 跟随真实权限）。
2. 值班员 POST /api/readings 必须 403，且数据库零插入（总表不多一行）。
3. 放行失败后不得刷新列表（should_refresh_after_fail 恒 False）。
另含：记录员压线样本 8.0℃ 必须落库成功；令牌缺失 401；GET 双角色可用。

HTTP 用例基于 aiohttp 自带 test_utils + IsolatedAsyncioTestCase，
无需 pytest-aiohttp / 真实 PostgreSQL（以 FakePool 断言插入次数）。
"""

import json
import unittest

import jwt

from rules import judge_temp
from watcher_pass import (
    allow_write,
    should_refresh_after_fail,
    should_show_form,
)

SECRET = "coldchain-probe-dev-secret"


def make_token(username, role):
    return jwt.encode({"sub": username, "role": role}, SECRET, algorithm="HS256")


# ---------- 策略单元测试 ----------

def test_allow_write_only_for_writer():
    assert allow_write({"username": "logger", "role": "writer"}) is True
    # 值班员只读，写口必须拒绝
    assert allow_write({"username": "watcher", "role": "reader"}) is False
    assert allow_write(None) is False
    assert allow_write({"username": "x", "role": "WRITER"}) is False


def test_form_visibility_follows_permission():
    # 值班员（can_write=False）首页不得画出报温框
    assert should_show_form(True) is True
    assert should_show_form(False) is False


def test_no_refresh_after_failure():
    # 放行失败后无论角色都不得刷新总表
    assert should_refresh_after_fail(False) is False
    assert should_refresh_after_fail(True) is False


def test_temp_rule_boundary_and_seeds():
    # 压线样本：8.0℃ 恰好合格；记录员甲/乙种子结论
    assert judge_temp(8.0) == ("合格", "探头温度未超过 8℃ 上限")
    assert judge_temp(4.2)[0] == "合格"
    assert judge_temp(12.5)[0] == "超温"


# ---------- HTTP 端到端：用假连接池验证真实写边界 ----------

class FakePool:
    """记录 INSERT 调用次数的假连接池，零残行可直接断言。"""

    def __init__(self):
        self.inserts = 0
        self.rows = []
        self.next_id = 1

    async def fetch(self, *_args, **_kwargs):
        return list(self.rows)

    async def close(self):
        return None

    async def fetchrow(self, sql, *args, **_kwargs):
        if sql.lstrip().upper().startswith("INSERT"):
            self.inserts += 1
            probe_id, temp_c, created_by = args[0], args[1], args[2]
            verdict, reason = judge_temp(temp_c)
            row = {
                "id": self.next_id,
                "probe_id": probe_id,
                "temp_c": temp_c,
                "verdict": verdict,
                "reason": reason,
                "status": "pending",
                "created_by": created_by,
                "created_at": None,
                "processed_at": None,
            }
            self.next_id += 1
            self.rows.append(row)

            class Row(dict):
                def __getitem__(self, key):
                    return self.get(key)

            return Row(row)
        raise AssertionError("unexpected fetchrow sql")


class HttpPermissionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import api
        from aiohttp.test_utils import TestClient, TestServer

        self.api = api
        app = api.create_app()
        app.on_startup.clear()  # 跳过对真实 PostgreSQL 的建表/种子

        async def fake_startup(application):
            application["pool"] = FakePool()

        app.on_startup.append(fake_startup)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    @property
    def pool(self):
        return self.client.app["pool"]

    async def test_writer_submission_is_persisted(self):
        token = make_token("logger", "writer")
        resp = await self.client.post(
            "/api/readings",
            headers={"Authorization": f"Bearer {token}"},
            json={"probe_id": "探头Z08", "temp_c": 8.0},  # 压线样本必须落库成功
        )
        assert resp.status == 201
        data = await resp.json()
        assert data["verdict"] == "合格"
        assert self.pool.inserts == 1  # 记录员交完多一行

    async def test_watcher_forbidden_with_zero_residual_rows(self):
        watcher = {"Authorization": f"Bearer {make_token('watcher', 'reader')}"}
        before = await (await self.client.get("/api/readings", headers=watcher)).json()

        resp = await self.client.post(
            "/api/readings",
            headers=watcher,
            json={"probe_id": "探头X99", "temp_c": 5.0},
        )
        assert resp.status == 403
        detail = json.loads(await resp.text())
        assert "只读" in detail["detail"]

        # 值班交完行数不变：写口拒绝后必须零残行，不得插空行/pending 行
        assert self.pool.inserts == 0
        after = await (await self.client.get("/api/readings", headers=watcher)).json()
        assert len(after) == len(before)

    async def test_get_readings_allowed_for_both_roles(self):
        for username, role in [("logger", "writer"), ("watcher", "reader")]:
            resp = await self.client.get(
                "/api/readings",
                headers={
                    "Authorization": f"Bearer {make_token(username, role)}"
                },
            )
            assert resp.status == 200  # 值班员仍可只读看总表

    async def test_missing_token_is_unauthorized(self):
        resp = await self.client.post(
            "/api/readings", json={"probe_id": "探头X1", "temp_c": 1}
        )
        assert resp.status == 401
        assert self.pool.inserts == 0


if __name__ == "__main__":
    unittest.main()
