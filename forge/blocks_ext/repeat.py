# ⚒ NIXFORGE · evolved block 'repeat' (E1) — forged by Swanix 🐸
from forge.blocks import block, retry
import time

@block('repeat', side_effect=False, doc='repeat(action, interval_seconds, count) -> executes the given side‑effect action repeatedly')
def repeat(ctx, action, interval_seconds, count):
    results = []
    for i in range(count):
        if callable(action):
            res = action(ctx)
        else:
            res = ctx.run_block(action)
        results.append(res)
        if i < count - 1:
            time.sleep(interval_seconds)
    return results

def selftest():
    def act(_):
        return "ok"
    out = repeat(object(), act, 0, 3)
    assert out == ["ok","ok","ok"]
    return True