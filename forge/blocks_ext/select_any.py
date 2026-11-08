# ⚒ NIXFORGE · evolved block 'select_any' (E3) — forged by Swanix 🐸
from forge.blocks import block, retry
from bs4 import BeautifulSoup

@block('select_any', side_effect=False, doc='select_any(html, selectors:list, all=False, attr=None) -> text or list of texts')
def select_any(ctx, html, selectors, all=False, attr=None):
    soup=BeautifulSoup(html,'html.parser')
    for sel in selectors:
        elements=soup.select(sel)
        if elements:
            if all:
                if attr:
                    return [el.get(attr,'') for el in elements]
                return [el.get_text(strip=True) for el in elements]
            else:
                el=elements[0]
                if attr:
                    return el.get(attr,'')
                return el.get_text(strip=True)
    return [] if all else ''

def selftest():
    html='<div class="a">One</div><p class="b">Two</p>'
    res=select_any(None, html, ['.b', '.a'], all=False)
    assert res=='Two'
    res_all=select_any(None, html, ['.a', '.b'], all=True)
    assert res_all==['One']
    return True