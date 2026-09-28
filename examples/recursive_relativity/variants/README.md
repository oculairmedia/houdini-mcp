# Five Recursive Relativity variants

Five complete VEX sources derived from the artist's supplied Recursive Relativity
wrangle. Paste one into an **empty Attribute Wrangle**, set to **Detail (only once)**.
No external includes or spare parameters are required. The figures animate with
the current frame and repeat every 240 frames; each sculpture contains six finite
recursive generations.

| Source | Architectural change | Live object |
| --- | --- | --- |
| [Gothic Vertigo](gothic_vertigo.vfl) | Pointed vaults, tall stepped finials, nearly aligned recursion | `/obj/relativity_gothic_vertigo` |
| [Clockwork Helix](clockwork_helix.vfl) | Circular brass wheels, radial spokes and gear teeth, tighter twisted recursion | `/obj/relativity_clockwork_helix` |
| [Library of Babel](library_of_babel.vfl) | Rectangular bookcases, individual book spines and shelf bands, alternating triangular layers | `/obj/relativity_library_of_babel` |
| [Hanging Gardens](hanging_gardens.vfl) | Planters, branching trunks and faceted leaf canopies along the arcades | `/obj/relativity_hanging_gardens` |
| [Fractured Neon](fractured_neon.vfl) | Floating treads without a supporting spine, diamond gates and a stronger twist | `/obj/relativity_fractured_neon` |

The corresponding cameras are beneath `/obj/relativity_variant_views`, named by
variant. The illusion depends on their orthographic direction: the separated
world-space ends project onto the same point. These are not physically closed
walkable stair loops. Fractured Neon deliberately includes gaps between treads.

## Reproduce

```powershell
python examples/recursive_relativity/variants/generate.py
python examples/recursive_relativity/variants/build.py
python examples/recursive_relativity/variants/gallery.py
```

Use an editable installation with one live companion. `generate.py` recreates the
standalone sources and `variants.json` from the original example. `build.py`
stages, checks, renders and promotes each owned object, placing it away from
pre-existing scenes. It records state in `~/.houdini-companion/relativity-variants`.
The builder refuses an existing receipt unless `--resume` is supplied; resuming
requires every recorded variant to have completed promotion and its source to
match. Partial candidates require explicit inspection/recovery.

The local gallery includes five poses per variant, standalone VEX downloads and
individual frame-review players. It works directly from `index.html`, without a
server. No artist HIP is saved or reloaded. Existing artist camera definitions and
timeline settings are compared before/after; showing a new camera is a separate
explicit presentation step.

See [verification.json](verification.json) for sampled geometry, stable-ID loop
checks and browser evidence. Surface-profile checks detect nonfinite/degenerate
polygons; they do not certify watertight unions or continuous collision freedom
between decorative components.
