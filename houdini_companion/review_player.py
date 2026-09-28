"""Portable image-sequence player: synchronized views, no codec or web service needed."""

import html
import json
import shutil
from pathlib import Path

from .core import atomic_json
from .errors import CompanionError

PLAYER = r"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title><style>
body{background:#101b22;color:#eceddf;font:15px system-ui;margin:32px}h1{font:36px Georgia,serif}
#views{display:flex;gap:12px;flex-wrap:wrap}figure{margin:0;flex:1;min-width:240px}img{width:100%;background:#03080b}
button,input,select{margin:12px 12px 12px 0;padding:9px;background:#25454d;color:white;border:1px solid #527177}
input{width:45%;accent-color:#d3bf8e}#metrics,small{color:#aebfc3}a{color:#d3bf8e}#error{color:#ffae93}pre{white-space:pre-wrap}
</style><h1>__TITLE__</h1><p id="source"></p><div id="views"></div>
<button id="play">Play</button><input id="frame" aria-label="Frame" type="range" min="0" step="1" value="0">
<select id="speed" aria-label="Playback speed"><option value="1">Normal speed</option><option value="0.5">Half speed</option></select>
<span id="counter"></span><p id="annotation"></p><p id="metrics"></p><p id="error" role="alert"></p>
<p><a id="geometry" download>Geometry sample</a> · <a href="review.json" download>Review manifest</a></p>
<small>Arrow keys step through samples. All views share the selected sample. Geometry is evaluated at sampled times.</small>
<script>const data=__DATA__;let selected=0,playing=false,timer=null,epoch=0;
const slider=document.querySelector('#frame'),btn=document.querySelector('#play');slider.max=data.rows.length-1;
document.querySelector('#source').textContent=`${data.path} | Render ${data.render_id}`;
const pictures=Object.keys(data.recipes).map(view=>{const figure=document.createElement('figure'),img=document.createElement('img'),caption=document.createElement('figcaption');img.alt=view;caption.textContent=view;figure.append(img,caption);document.querySelector('#views').append(figure);return img});
async function show(index){selected=Math.max(0,Math.min(data.rows.length-1,index));const row=data.rows[selected],ticket=++epoch;slider.value=selected;
 try{const loaded=await Promise.all(row.images.map(async item=>{const image=new Image();image.src=item.name;await image.decode();return image}));if(ticket!==epoch)return;
 loaded.forEach((image,i)=>{pictures[i].src=image.src;pictures[i].dataset.frame=row.frame});
 document.querySelector('#counter').textContent=`Frame ${row.frame} · ${selected+1}/${data.rows.length}`;
 document.querySelector('#annotation').textContent=(data.annotations||[]).filter(a=>a.frame===row.frame).map(a=>a.text).join(' · ');
 document.querySelector('#metrics').textContent=`${row.geometry.points} points · ${row.geometry.primitives} primitives · cook ${row.cook_ms.toFixed(1)} ms · render ${row.render_ms.toFixed(1)} ms · job ${row.job_id}`;
 document.querySelector('#geometry').href=row.geometry_artifact.name;
 document.querySelector('#error').textContent='';}catch(e){document.querySelector('#error').textContent='Image decode failed: '+e.message;stop()}}
function stop(){playing=false;clearTimeout(timer);btn.textContent='Play'}
function schedule(){if(!playing)return;const current=data.rows[selected],next=data.rows[selected+1];if(!next){stop();return}
const delay=Math.max(16,(next.frame-current.frame)*1000/data.fps/Number(document.querySelector('#speed').value));timer=setTimeout(async()=>{await show(selected+1);schedule()},delay)}
btn.onclick=()=>{if(playing)stop();else{playing=true;btn.textContent='Pause';if(selected===data.rows.length-1)show(0);schedule()}};
slider.oninput=()=>{stop();show(Number(slider.value))};document.querySelector('#speed').onchange=()=>{clearTimeout(timer);schedule()};
document.onkeydown=e=>{if(e.code==='ArrowRight'){stop();show(selected+1)}if(e.code==='ArrowLeft'){stop();show(selected-1)}};show(0);
</script></html>"""


def publish_files(folder, data, destination, title, annotations, image_validator):
    from .plugins.render_sequence import file_ok

    folder, dest = Path(folder), Path(destination).expanduser().resolve()
    if dest.exists():
        raise CompanionError("TARGET_EXISTS", "Review destination must be new")
    if not data["rows"] or any(row is None for row in data["rows"]):
        raise CompanionError("INCOMPLETE_REVIEW", "Finish all frames before publication")
    for row in data["rows"]:
        if len(row["images"]) != len(data["recipes"]):
            raise CompanionError("INCOMPLETE_REVIEW", "Missing synchronized view")
        for item in [row["geometry_artifact"], *row["images"]]:
            if not file_ok(folder, item, strict=True):
                raise CompanionError("ARTIFACT_CORRUPT", item.get("name", ""))
        for image in row["images"]:
            image_validator(folder / image["name"])
    dest.mkdir(parents=True)
    for row in data["rows"]:
        for item in [row["geometry_artifact"], *row["images"]]:
            shutil.copy2(folder / item["name"], dest / item["name"])
    public = {**data, "annotations": annotations, "title": title}
    atomic_json(dest / "review.json", public)
    page = PLAYER.replace("__TITLE__", html.escape(title)).replace(
        "__DATA__", json.dumps(public, allow_nan=False).replace("<", "\\u003c")
    )
    (dest / "index.html").write_text(page, encoding="utf-8")
    return {
        "index": str(dest / "index.html"),
        "manifest": str(dest / "review.json"),
        "image_decode_verified": True,
        "frames": len(data["rows"]),
        "views": len(data["recipes"]),
    }
