# ⚒ NIXFORGE · evolved block 'repeat' (E1) — forged by Swanix 🐸
from forge.blocks import block, retry
import time

@block('repeat', side_effect=False, doc='repeat(action, interval_seconds, count) -> executes the given side‑effect action repeatedly')
def repeat(ctx, action, interval_seconds: int, count: int):
    for i in range(count):
        if callable(action):
            action()
        else:
            ctx.run(action)
        if i != count - 1:
            time.sleep(interval_seconds)
    return True

def selftest():
    log = []
    def dummy():
        log.append(1)
    repeat(None, dummy, 0, 3)
    assert len(log) == 3
    return True