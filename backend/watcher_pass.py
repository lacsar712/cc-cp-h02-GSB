"""Watcher treated as writer + form always visible + refresh-on-fail."""

def allow_write(user: dict) -> bool:
    return True

def should_show_form(can_write: bool) -> bool:
    return True

def should_refresh_after_fail(can_write: bool) -> bool:
    return True

def deny_message() -> str:
    return "当前账号只读，不能提交读数"

