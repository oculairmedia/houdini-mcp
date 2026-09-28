"""Generate five standalone detail-wrangle variants from the supplied sculpture."""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent / "relativity.vfl"

VARIANTS = [
    {
        "slug": "gothic_vertigo",
        "title": "Gothic Vertigo",
        "description": "Pointed vaults, tall finials and an ivory-and-slate recursive cathedral.",
        "ratio": 0.55,
        "twist": -4,
        "width": 20,
    },
    {
        "slug": "clockwork_helix",
        "title": "Clockwork Helix",
        "description": "Brass wheels and spokes form a tightly wound mechanical stair universe.",
        "ratio": 0.58,
        "twist": 28,
        "width": 19,
    },
    {
        "slug": "library_of_babel",
        "title": "Library of Babel",
        "description": "Book-lined passages alternate into a hexagonal recursive library.",
        "ratio": 0.53,
        "twist": 60,
        "width": 18,
    },
    {
        "slug": "hanging_gardens",
        "title": "Hanging Gardens",
        "description": "Mossy stair terraces support branching trees in three directions of gravity.",
        "ratio": 0.55,
        "twist": -20,
        "width": 20,
    },
    {
        "slug": "fractured_neon",
        "title": "Fractured Neon",
        "description": "Floating checker steps and luminous diamond gates dissolve into a vortex.",
        "ratio": 0.59,
        "twist": 42,
        "width": 18,
    },
]

LEAVES = """
function void leaftri(vector a,b,c,center,col; int gen) {
    vector corners[]=array(a,b,c);
    if(dot(cross(b-a,c-a),(a+b+c)/3-center)>0) corners=array(c,b,a);
    int pts[];
    foreach(vector v; corners) {
        int pt=addpoint(0,world(v,gen)); setpointattrib(0,"id",pt,pt); append(pts,pt);
    }
    int pr=addprim(0,"poly",pts); setprimattrib(0,"Cd",pr,col);
    setprimattrib(0,"generation",pr,gen); setprimattrib(0,"part",pr,5);
}
function void leaf(vector c,x,y,z,dim,col; int gen) {
    vector ring[]=array(c+x*dim.x,c+z*dim.z,c-x*dim.x,c-z*dim.z);
    for(int i=0;i<4;i++) {
        leaftri(c+y*dim.y,ring[i],ring[(i+1)%4],c,col,gen);
        leaftri(c-y*dim.y,ring[(i+1)%4],ring[i],c,col*.8,gen);
    }
}
"""


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError(f"Expected exactly one source anchor: {old[:80]}")
    return source.replace(old, new)


def source_for(config):
    source = BASE.read_text(encoding="utf-8")
    source = source.replace("pow(.53,generation)", f"pow({config['ratio']},generation)")
    source = source.replace("-14.0*generation", f"{config['twist']}.0*generation")
    source = source.replace('"Recursive Relativity"', json.dumps(config["title"]))
    slug = config["slug"]
    palette = {
        "gothic_vertigo": (
            "set(.40,.43,.50),ivory=set(.93,.90,.79)",
            "set(.035,.04,.065),teal=set(.08,.12,.22),gold=set(.8,.50,.17)",
        ),
        "clockwork_helix": (
            "set(.25,.13,.07),ivory=set(.72,.46,.16)",
            "set(.025,.045,.045),teal=set(.04,.22,.19),gold=set(.98,.70,.22)",
        ),
        "library_of_babel": (
            "set(.48,.21,.13),ivory=set(.84,.67,.42)",
            "set(.085,.03,.035),teal=set(.23,.095,.07),gold=set(.25,.66,.65)",
        ),
        "hanging_gardens": (
            "set(.28,.35,.18),ivory=set(.75,.72,.46)",
            "set(.07,.12,.07),teal=set(.13,.34,.13),gold=set(.94,.37,.12)",
        ),
        "fractured_neon": (
            "set(.055,.025,.12),ivory=set(.08,.68,.78)",
            "set(.12,.04,.2),teal=set(.64,.025,.32),gold=set(.92,.64,.08)",
        ),
    }[slug]
    source = source.replace("set(.64,.59,.47),ivory=set(.91,.85,.69)", palette[0])
    source = source.replace(
        "set(.042,.083,.091),teal=set(.08,.27,.29),gold=set(.92,.47,.11)", palette[1]
    )
    cap = "            box(foot+u*2.1,d,u,w,set(1.94,.08,.42),ivory,gen,2);"
    if slug == "gothic_vertigo":
        for variable in ("a", "b"):
            source = source.replace(
                f"sin({variable})", f"sqrt(max(0,4-pow(abs(cos({variable}))+1,2)))"
            )
        source = source.replace("foot+u*2.0", "foot+u*2.45").replace("foot+u*2.1", "foot+u*2.57")
        source = replace_once(
            source,
            cap.replace("2.1", "2.57"),
            cap.replace("2.1", "2.57")
            + """
            for(int side=-1;side<=1;side+=2) {
                vector tower=foot+d*side*.82;
                box(tower+u*2.8,d,u,w,set(.23,.43,.26),ivory,gen,5);
                box(tower+u*3.13,d,u,w,set(.14,.29,.17),tone,gen,5);
                box(tower+u*3.36,d,u,w,set(.055,.20,.055),gold,gen,5);
            }""",
        )
    elif slug == "clockwork_helix":
        source = source.replace(
            "float r=.62, thickness=.14, depth=.18;", "float r=.73, thickness=.085, depth=.22;"
        )
        source = (
            source.replace("j<12", "j<24")
            .replace("M_PI*j/12", "2*M_PI*j/24")
            .replace("M_PI*(j+1)/12", "2*M_PI*(j+1)/24")
        )
        source = replace_once(
            source,
            cap,
            cap
            + """
            vector hub=foot+u*1.18;
            for(int tooth=0;tooth<12;tooth++) {
                float a=tooth*2*M_PI/12;
                vector radial=d*cos(a)+u*sin(a),tangent=-d*sin(a)+u*cos(a);
                box(hub+radial*.86,tangent,radial,w,set(.12,.17,.25),gold,gen,5);
                if(tooth%2==0) box(hub+radial*.36,tangent,radial,w,set(.045,.64,.10),gold,gen,5);
            }
            box(hub,d,u,w,set(.20,.20,.30),teal,gen,5);""",
        )
        source = source.replace("set(12,.8,1.75)", "set(12,.40,1.75)")
    elif slug == "library_of_babel":
        source = replace_once(
            source,
            "            arch(foot+u*1.18,d,u,w,ivory,gen);",
            """
            box(foot+u*1.78,d,u,w,set(1.56,.17,.4),ivory,gen,2);
            for(int shelf=0;shelf<3;shelf++) {
                box(foot+u*(.35+shelf*.48),d,u,w,set(1.42,.075,.50),ivory,gen,5);
                for(int book=0;book<10;book++) {
                    float height=.24+.12*rand(book+shelf*19+leg*83+gen*127);
                    float blend=rand(book*13+shelf*37);
                    vector col=lerp(set(.17,.06,.035),set(.65,.27,.075),blend);
                    if(book%4==0) col=set(.075,.23,.22);
                    vector spine=foot+d*(book-4.5)*.126+u*(.4+shelf*.48+height*.5)-w*.13;
                    box(spine,d,u,w,set(.108,height,.28),col,gen,5);
                    box(spine-u*height*.28-w*.148,d,u,w,set(.072,.027,.015),gold,gen,5);
                }
            }""",
        )
    elif slug == "hanging_gardens":
        source = replace_once(source, "vector stone=", LEAVES + "\nvector stone=")
        source = replace_once(
            source,
            cap,
            cap
            + """
            vector planter=foot+w*.42;
            box(planter+u*.18,d,u,w,set(1.3,.36,.8),tone,gen,5);
            box(planter+u*.38,d,u,w,set(1.16,.06,.66),ink,gen,5);
            beam(planter+u*.4,planter+u*1.8,w,.095,set(.22,.12,.045),gen,5);
            for(int branch=-1;branch<=1;branch++) {
                vector tip=planter+d*branch*.48+u*(2.2-.25*abs(branch));
                beam(planter+u*1.4,tip,w,.075,set(.3,.18,.06),gen,5);
                leaf(tip+u*.34,d,u,w,set(.48,.65,.4),lerp(set(.16,.40,.06),set(.42,.57,.12),(branch+1)*.5),gen);
            }
            leaf(planter+d*.47+u*.66,d,u,w,set(.30,.36,.25),set(.26,.48,.14),gen);""",
        )
    elif slug == "fractured_neon":
        start = source.index("        // A continuous sloping stone spine")
        end = source.index("        for(int j=0;j<steps;j++)", start)
        source = (
            source[:start]
            + "        // Floating treads: the supporting spine is intentionally absent.\n"
            + source[end:]
        )
        source = source.replace(
            "for(int j=0;j<steps;j++) {",
            "for(int j=0;j<steps;j++) {\n            if(j%4==3) continue;",
        )
        start = source.index("        // Repeated Romanesque arcades")
        end = source.index("        // Amber figures", start)
        source = (
            source[:start]
            + """
        // Floating diamond portals replace the stone colonnade.
        for(int bay=0;bay<4;bay++) {
            vector c=a+slope*(1.5+bay*3)+w*.89+u*1.0;
            vector corners[]=array(c+d*.75,c+u*1.05,c-d*.75,c-u*1.05);
            for(int edge=0;edge<4;edge++) beam(corners[edge],corners[(edge+1)%4],w,.08,gold,gen,5);
            box(c+u*1.05,d,u,w,set(.16,.16,.16),ivory,gen,5);
        }
"""
            + source[end:]
        )
    return f"// VARIANT: {config['title']}\n// {config['description']}\n" + source


def main():
    for config in VARIANTS:
        (HERE / (config["slug"] + ".vfl")).write_text(source_for(config), encoding="utf-8")
    (HERE / "variants.json").write_text(json.dumps(VARIANTS, indent=2) + "\n", encoding="utf-8")
    print("Generated five standalone detail-wrangle sources.")


if __name__ == "__main__":
    main()
