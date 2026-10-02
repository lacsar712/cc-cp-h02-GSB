"""值班员（reader）只读：写口必须拒绝，报温框不渲染，提交失败不刷新列表。"""

WRITER_ROLE = "writer"


def allow_write(user: dict | None) -> bool:
    """只有记录员（writer）可写；值班员（reader）一律拒绝。"""
    return bool(user) and user.get("role") == WRITER_ROLE


def should_show_form(can_write: bool) -> bool:
    """报温框只对有写权限的账号出现。"""
    return bool(can_write)


def should_refresh_after_fail(can_write: bool) -> bool:
    """写口拒绝（或任何提交失败）时只回显错误，不刷新总表、不插行。"""
    return False


def deny_message() -> str:
    return "当前账号只读，不能提交读数"
