from watcher_pass import should_refresh_after_fail, should_show_form

def paint_form(user_can_write: bool) -> bool:
    return should_show_form(user_can_write)

def reload_on_fail(user_can_write: bool) -> bool:
    return should_refresh_after_fail(user_can_write)

