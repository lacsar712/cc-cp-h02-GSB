"""写权限与报温框策略。

服务端写边界：只有记录员（writer）可以提交读数，值班员（reader）只读。
- allow_write：POST /api/readings 的强制鉴权依据，前端是否隐藏表单不影响此判定。
- should_show_form：首页是否渲染报温框，必须跟随真实写权限。
- should_refresh_after_fail：提交失败后不得刷新总表，杜绝越权提交后列表凭空变动。
"""


def allow_write(user: dict | None) -> bool:
    return bool(user) and user.get("role") == "writer"


def should_show_form(can_write: bool) -> bool:
    return bool(can_write)


def should_refresh_after_fail(can_write: bool) -> bool:
    # 无论账号是否有写权限，提交失败都只展示错误：不刷新、不留残行。
    return False


def deny_message() -> str:
    return "当前账号只读，不能提交读数"
