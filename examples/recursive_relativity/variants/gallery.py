"""Publish the five local variants as one source-download comparison gallery."""

import html
import json
import zipfile
from pathlib import Path

DIRECTORY = Path.home() / ".houdini-companion" / "relativity-variants"


def main():
    state = json.loads((DIRECTORY / "build.json").read_text())
    assert len(state["variants"]) == 5 and state.get("artist_state_preserved")
    with zipfile.ZipFile(DIRECTORY / "five-variants.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for variant in state["variants"]:
            name = variant["slug"] + ".vfl"
            archive.write(DIRECTORY / variant["slug"] / name, name)
        archive.writestr(
            "README.txt",
            "Paste one VEX file into an empty Attribute Wrangle set to Detail (only once). Play frames 1-240. Six finite recursive generations. Orthographic camera at (35,35,35), rotation (-35.26438968,45,0), width 18-20. No external includes or spare parameters required.\n",
        )
    cards = []
    for index, variant in enumerate(state["variants"]):
        slug, title = variant["slug"], html.escape(variant["title"])
        code = (DIRECTORY / slug / (slug + ".vfl")).read_text(encoding="utf-8")
        cards.append(f"""<article data-slug="{slug}">
<div class="number">0{index + 1}</div><a href="{slug}/index.html" aria-label="Review {title}"><img src="{slug}/frame-0000-view0.png" alt="{title}" width="900" height="900"></a>
<div class="text"><h2>{title}</h2><p>{html.escape(variant["description"])}</p>
<div class="actions"><a href="{slug}/{slug}.vfl" download>Download VEX ↗</a><a href="{slug}/index.html">Frame review →</a></div>
<details><summary>Show pasteable VEX</summary><pre>{html.escape(code)}</pre></details></div></article>""")
    page = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Five variations on impossible architecture</title><style>
*{box-sizing:border-box}body{margin:0;background:#101b20;color:#f0e9d8;font:16px system-ui}main{max-width:1580px;margin:auto;padding:40px}
.eyebrow{color:#8dbbb5;font-size:12px;letter-spacing:.22em;text-transform:uppercase}h1{font:clamp(32px,4vw,58px) Georgia,serif;margin:14px 0}header p{color:#b6c4c2;max-width:740px;line-height:1.6}
.controls{display:flex;align-items:center;gap:18px;margin:28px 0}input{width:260px;accent-color:#d9b677}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:22px}
article{position:relative;background:#19272c;border:1px solid #33464a;border-radius:8px;overflow:hidden}img{width:100%;height:auto;display:block;background:#000}.number{position:absolute;top:18px;left:20px;color:#dfc08e;font:24px Georgia,serif;z-index:1}
.text{padding:22px}h2{font:27px Georgia,serif;margin:0 0 12px}.text p{color:#adbfbd;line-height:1.55;min-height:72px}.actions{display:flex;justify-content:space-between;gap:8px}a{color:#d9bd88;text-decoration:none}a:hover{text-decoration:underline}
details{margin-top:20px;color:#93aeaa;font-size:13px}pre{white-space:pre-wrap;max-height:380px;overflow:auto;color:#ddd;font:11px monospace}footer{color:#9cb2af;margin:30px 0;font-size:14px;line-height:1.6}#error{color:#f3aa99}
@media(max-width:1050px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:660px){main{padding:22px}.grid{grid-template-columns:1fr}}
</style><main><header><div class="eyebrow">Recursive Relativity / Five architectural studies</div><h1>Five ways to bend reality.</h1><p>The same impossible stair loop, rebuilt five ways. Compare the silhouettes, then open a frame review or take the complete VEX source into Houdini.</p></header>
<div class="controls"><label for="frame">Compare pose</label><input type="range" id="frame" min="0" max="4" step="1" value="0"><span id="label">Frame 1</span><a href="five-variants.zip" download>Download all five VEX files ↗</a></div><p id="error" role="alert"></p>
<div class="grid">__CARDS__</div><footer>All five exist as separate Houdini objects. Paste any VEX file into an empty Attribute Wrangle set to <b>Detail (only once)</b>. Figures repeat every 240 frames; recursion is bounded to six generations.<br>These are camera-dependent illusions. Their separate ends align from the dedicated orthographic cameras.</footer></main>
<script>const frames=[1,61,121,181,241];let epoch=0;document.querySelector('#frame').oninput=async e=>{const index=Number(e.target.value),ticket=++epoch;
try{const cards=[...document.querySelectorAll('article')];const images=await Promise.all(cards.map(async card=>{const image=new Image();image.src=`${card.dataset.slug}/frame-${String(index).padStart(4,'0')}-view0.png`;await image.decode();return image}));if(ticket!==epoch)return;cards.forEach((card,i)=>card.querySelector('img').src=images[i].src);document.querySelector('#label').textContent=`Frame ${frames[index]}`;document.querySelector('#error').textContent='';}catch(error){document.querySelector('#error').textContent=error.message}};</script></html>"""
    (DIRECTORY / "index.html").write_text(
        page.replace("__CARDS__", "\n".join(cards)), encoding="utf-8"
    )
    print(DIRECTORY / "index.html")


if __name__ == "__main__":
    main()
