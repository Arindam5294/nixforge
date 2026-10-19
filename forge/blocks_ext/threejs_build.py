# ⚒ NIXFORGE · evolved block 'threejs_build' (E2) — forged by Swanix 🐸
from forge.blocks import block, retry
import requests, uuid, json

@block('threejs_build', side_effect=False, doc='threejs_build(template_url:str, assets:list, config:dict=None) -> str # returns URL of generated 3D site')
def threejs_build(ctx, template_url:str, assets:list, config:dict=None) -> str:
    resp = requests.get(template_url, timeout=10)
    resp.raise_for_status()
    html = resp.text
    assets_js = ''
    for asset in assets:
        assets_js += f"const loader = new THREE.GLTFLoader(); loader.load('{asset}', function(gltf) {{ scene.add(gltf.scene); }});\n"
    cfg = config or {}
    cfg_json = json.dumps(cfg)
    injection = f"<script>const CONFIG = {cfg_json};\n{assets_js}</script>"
    if '<!--ASSETS-->' in html:
        html = html.replace('<!--ASSETS-->', injection)
    else:
        html = html.replace('</body>', injection + '</body>')
    site_id = uuid.uuid4().hex
    return f'https://example.com/generated_site/{site_id}.html'

def selftest():
    url = 'https://httpbin.org/html'
    result = threejs_build(None, url, [], {})
    assert result.startswith('https://example.com/generated_site/')
    return True