# ⚒ NIXFORGE · evolved block 'select_safe' (E4) — forged by Swanix 🐸
from forge.blocks import block, retry
from bs4 import BeautifulSoup

@block('select_safe', side_effect=False, doc='select_safe(html, css, all=False, attr=None) -> str or list: returns matched text or empty if none')
def select_safe(ctx, html, css, all=False, attr=None):
    soup = BeautifulSoup(html, 'html.parser')
    elements = soup.select(css)
    if not elements:
        return [] if all else ''
    results = []
    for el in elements:
        if attr:
            val = el.get(attr, '')
        else:
            val = el.get_text()
        results.append(val)
    if all:
        return results
    else:
        return results[0]

def selftest():
    html = "<div><p class='a'>Hello</p><p class='b'>World</p></div>"
    res1 = select_safe(None, html, "p.a")
    if res1 != "Hello":
        return False
    res2 = select_safe(None, html, "span")
    if res2 != "":
        return False
    res3 = select_safe(None, html, "p", all=True)
    if res3 != ["Hello", "World"]:
        return False
    html2 = "<img src='a.png' alt='Image'>"
    res4 = select_safe(None, html2, "img", attr="src")
    if res4 != "a.png":
        return False
    return True