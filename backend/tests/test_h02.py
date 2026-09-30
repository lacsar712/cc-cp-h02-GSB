from watcher_pass import allow_write, should_show_form

def test_watcher_allowed():
    assert allow_write({"role": "reader"}) is True
    assert should_show_form(False) is True

