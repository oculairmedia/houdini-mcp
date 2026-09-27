// CGA facade grammar.
// Müller et al., Procedural Modeling of Buildings (SIGGRAPH 2006):
// mass, component split, floor split, repeat tiles. A tile is wall |
// opening | wall, and every facade shares the floor heights.
// Bao, Schwarz, Wonka, Procedural Facade Variations (TOG 2013): one
// layout per building, a wider center bay, and the door on that axis.
// Ilčík et al., Layer-Based Procedural Design of Facades (CGF 2015):
// pilasters and cornices drawn over the wall field so they cross floors.
// Wonka et al., Instant Architecture (SIGGRAPH 2003): the building picks
// one window rule (single, paired with a mullion, or stone quoins).
void addCard(const vector center; const vector axisU; const vector axisV; const float su; const float sv; const vector cd) {
    vector p0 = center - axisU * (su * 0.5) - axisV * (sv * 0.5);
    vector p1 = center + axisU * (su * 0.5) - axisV * (sv * 0.5);
    vector p2 = center + axisU * (su * 0.5) + axisV * (sv * 0.5);
    vector p3 = center - axisU * (su * 0.5) + axisV * (sv * 0.5);
    int a = addpoint(geoself(), p0);
    int b = addpoint(geoself(), p1);
    int c = addpoint(geoself(), p2);
    int d = addpoint(geoself(), p3);
    vector n = normalize(cross(axisU, axisV));
    setpointattrib(geoself(), "N", a, n);
    setpointattrib(geoself(), "N", b, n);
    setpointattrib(geoself(), "N", c, n);
    setpointattrib(geoself(), "N", d, n);
    setpointattrib(geoself(), "Cd", a, cd);
    setpointattrib(geoself(), "Cd", b, cd);
    setpointattrib(geoself(), "Cd", c, cd);
    setpointattrib(geoself(), "Cd", d, cd);
    int prim = addprim(geoself(), "poly", a, d, c, b);
    setprimattrib(geoself(), "Cd", prim, cd);
}

void addTri(const vector p0; const vector p1; const vector p2; const vector cd) {
    int a = addpoint(geoself(), p0);
    int b = addpoint(geoself(), p1);
    int c = addpoint(geoself(), p2);
    vector n = normalize(cross(p1 - p0, p2 - p0));
    setpointattrib(geoself(), "N", a, n);
    setpointattrib(geoself(), "N", b, n);
    setpointattrib(geoself(), "N", c, n);
    setpointattrib(geoself(), "Cd", a, cd);
    setpointattrib(geoself(), "Cd", b, cd);
    setpointattrib(geoself(), "Cd", c, cd);
    int prim = addprim(geoself(), "poly", a, c, b);
    setprimattrib(geoself(), "Cd", prim, cd);
}

void addBox(const vector origin; const vector ax; const vector ay; const vector az; const vector size; const vector cd) {
    if (size.x < 0.02 || size.y < 0.02 || size.z < 0.02) return;
    vector c = origin + ax * (size.x * 0.5) + ay * (size.y * 0.5) + az * (size.z * 0.5);
    addCard(c + ax * (size.x * 0.5), ay, az, size.y, size.z, cd);
    addCard(c - ax * (size.x * 0.5), az, ay, size.z, size.y, cd);
    addCard(c + ay * (size.y * 0.5), az, ax, size.z, size.x, cd);
    addCard(c - ay * (size.y * 0.5), ax, az, size.x, size.z, cd);
    addCard(c + az * (size.z * 0.5), ax, ay, size.x, size.y, cd);
    addCard(c - az * (size.z * 0.5), ay, ax, size.y, size.x, cd);
}

void addOutCard(const vector center; const vector along; const vector ay; const vector outward; const float h; const float w; const vector cd) {
    if (dot(cross(ay, along), outward) > 0)
        addCard(center, ay, along, h, w, cd);
    else
        addCard(center, along, ay, w, h, cd);
}

void addWall(const vector origin; const vector along; const vector ay; const vector inward; const float w; const float h; const vector cd) {
    if (w < 0.02 || h < 0.02) return;
    vector c = origin + along * (w * 0.5) + ay * (h * 0.5);
    addOutCard(c, along, ay, -inward, h, w, cd);
}

// Recessed opening. Wall scopes stop at the hole, so the glass is not
// painted on top of a solid face.
void addOpening(const vector origin; const vector along; const vector ay; const vector inward; const float w; const float h; const int door; const vector frame; const vector glass; const vector panel; const int mullions) {
    float recess = 0.22;
    vector outward = -inward;
    vector fill = door ? panel : glass;
    addCard(origin + ay * (h * 0.5) + inward * (recess * 0.5), ay, inward, h, recess, frame);
    addCard(origin + along * w + ay * (h * 0.5) + inward * (recess * 0.5), inward, ay, recess, h, frame);
    addCard(origin + along * (w * 0.5) + inward * (recess * 0.5), inward, along, recess, w, frame);
    addCard(origin + along * (w * 0.5) + ay * h + inward * (recess * 0.5), along, inward, w, recess, frame);
    addOutCard(origin + along * (w * 0.5) + ay * (h * 0.5) + inward * (recess + 0.015), along, ay, outward, h - 0.06, w - 0.06, fill);
    float ft = 0.055;
    addOutCard(origin + along * (w * 0.5) - inward * 0.02 + ay * (ft * 0.5), along, ay, outward, ft, w + 0.08, frame);
    addOutCard(origin + along * (w * 0.5) - inward * 0.02 + ay * (h - ft * 0.5), along, ay, outward, ft, w + 0.08, frame);
    addOutCard(origin - inward * 0.02 + along * (ft * 0.5) + ay * (h * 0.5), along, ay, outward, h, ft, frame);
    addOutCard(origin - inward * 0.02 + along * (w - ft * 0.5) + ay * (h * 0.5), along, ay, outward, h, ft, frame);
    if (!door)
        addOutCard(origin + along * (w * 0.5) - inward * 0.06 - ay * 0.035, along, ay, outward, 0.07, w + 0.12, frame);
    if (mullions > 0 && !door) {
        for (int m = 1; m <= mullions; m++) {
            float u = w * float(m) / float(mullions + 1);
            addOutCard(origin + along * u - inward * 0.025 + ay * (h * 0.5), along, ay, outward, h - 0.12, 0.055, frame);
        }
    }
}

// One facade scope. along/ay/inward must be right-handed.
// doorTile >= 0 marks the entrance tile; upper floors keep the same x split.
// doorSide: -1 none, 0 first tile, 1 last tile.
void addFacade(const vector origin; const vector along; const vector ay; const vector inward; const float width; const float y0; const float groundH; const float floorH; const int floors; const int doorSide; const int layout; const float targetTile; const int seed; const vector wall; const vector shop; const vector frame; const vector glass; const vector lit; const vector panel) {
    if (width < 1.4 || floors < 1) return;
    int quoin = layout == 3;
    float border = quoin ? min(1.05, width * 0.16) : (width < 5.0 ? 0.28 : 0.42);
    float usable = width - border * 2.0;
    if (usable < 1.1) {
        border = 0.16;
        usable = max(0.8, width - border * 2.0);
    }
    int tiles = max(1, int(usable / targetTile + 0.5));
    float tileW = usable / float(tiles);
    float sideTile = tileW;
    float centerTile = tileW;
    int useCenter = layout == 1 && tiles >= 3;
    if (useCenter) {
        centerTile = min(tileW * 1.45, usable * 0.42);
        sideTile = (usable - centerTile) / float(tiles - 1);
    }
    vector ledge = clamp(wall * 1.12, set(0, 0, 0), set(1, 1, 1));
    vector quoinC = clamp(wall * 0.72 + set(0.08, 0.07, 0.06), set(0, 0, 0), set(1, 1, 1));
    int mullions = layout == 2 ? 1 : 0;

    for (int f = 0; f < floors; f++) {
        float y = y0 + (f == 0 ? 0.0 : groundH + floorH * float(f - 1));
        float h = f == 0 ? groundH : floorH;
        vector col = f == 0 ? shop : wall;
        vector edge = quoin ? quoinC : col;
        addWall(origin + ay * y, along, ay, inward, border, h, edge);
        addWall(origin + along * (width - border) + ay * y, along, ay, inward, border, h, edge);
        float cursor = border;
        for (int t = 0; t < tiles; t++) {
            float tw = (useCenter && t == tiles / 2) ? centerTile : sideTile;
            vector tileO = origin + along * cursor + ay * y;
            int doorTile = -1;
            if (doorSide >= 0)
                doorTile = useCenter ? tiles / 2 : (doorSide == 0 ? 0 : tiles - 1);
            int isDoor = f == 0 && t == doorTile;
            float openingFrac = f == 0 ? 0.7 : (layout == 2 ? 0.72 : 0.52);
            float openingW = isDoor ? min(1.2, tw * 0.55) : min(1.7, tw * openingFrac);
            openingW = max(0.5, min(openingW, tw - 0.28));
            float side = (tw - openingW) * 0.5;
            addWall(tileO, along, ay, inward, side, h, col);
            addWall(tileO + along * (side + openingW), along, ay, inward, side, h, col);
            int columnLit = rand(float(seed) + float(t) * 4.1) > 0.84;
            if (isDoor) {
                float doorH = min(2.55, h - 0.85);
                addWall(tileO + along * side + ay * doorH, along, ay, inward, openingW, h - doorH, col);
                addOpening(tileO + along * side + inward * 0.02, along, ay, inward, openingW, doorH, 1, frame, glass, panel, 0);
            } else {
                float sill = f == 0 ? 0.45 : 0.85;
                float winH = f == 0 ? min(2.35, h - sill - 0.45) : min(1.55, h - sill - 0.5);
                if (sill + winH > h - 0.22) winH = h - sill - 0.28;
                addWall(tileO + along * side, along, ay, inward, openingW, sill, col);
                addWall(tileO + along * side + ay * (sill + winH), along, ay, inward, openingW, h - sill - winH, col);
                vector glassC = columnLit ? lit : glass;
                addOpening(tileO + along * side + ay * sill + inward * 0.02, along, ay, inward, openingW, winH, 0, frame, glassC, panel, mullions);
            }
            cursor += tw;
        }
    }

    // Overlapping layers: a base cornice, a crown, and pilasters that
    // cross the floor seams. These are not part of the tile tree.
    if (floors > 1) {
        float totalH = groundH + floorH * float(floors - 1);
        addBox(origin + ay * (groundH - 0.2) - inward * 0.045, along, ay, inward, set(width, 0.22, 0.11), ledge);
        addBox(origin + ay * (totalH - 0.12) - inward * 0.05, along, ay, inward, set(width, 0.16, 0.12), ledge);
        float x = border;
        for (int p = 0; p <= tiles; p++) {
            addBox(origin + along * (x - 0.07) + ay * groundH - inward * 0.03, along, ay, inward, set(0.14, max(0.2, totalH - groundH), 0.07), quoin ? quoinC : frame);
            if (p < tiles) {
                float pw = (useCenter && p == tiles / 2) ? centerTile : sideTile;
                x += pw;
            }
        }
    }
}

void addRailing(const vector origin; const vector ax; const vector ay; const vector az; const float width; const float depth; const float y; const vector cd) {
    float ht = 0.95;
    addBox(origin + ay * y, ax, ay, az, set(width, ht, 0.08), cd);
    addBox(origin + az * (depth - 0.08) + ay * y, ax, ay, az, set(width, ht, 0.08), cd);
    addBox(origin + ay * y, ax, ay, az, set(0.08, ht, depth), cd);
    addBox(origin + ax * (width - 0.08) + ay * y, ax, ay, az, set(0.08, ht, depth), cd);
}

void addUpQuad(const vector a; const vector b; const vector c; const vector d; const vector cd) {
    if (cross(b - a, c - a).y >= 0) {
        addTri(a, b, c, cd);
        addTri(a, c, d, cd);
    } else {
        addTri(a, c, b, cd);
        addTri(a, d, c, cd);
    }
}

void addFacingTri(const vector a; const vector b; const vector c; const vector outward; const vector cd) {
    if (dot(cross(b - a, c - a), outward) >= 0)
        addTri(a, b, c, cd);
    else
        addTri(a, c, b, cd);
}

void addRoofDeck(const vector origin; const vector ax; const vector az; const float width; const float depth; const float y; const vector cd) {
    vector c = origin + ax * (width * 0.5) + az * (depth * 0.5) + set(0, y, 0);
    if (cross(az, ax).y >= 0)
        addCard(c, az, ax, depth, width, cd);
    else
        addCard(c, ax, az, width, depth, cd);
}

void addParapet(const vector origin; const vector ax; const vector ay; const vector az; const float width; const float depth; const float y; const vector cd) {
    float ht = 0.45;
    float t = 0.12;
    addRoofDeck(origin, ax, az, width, depth, y, cd * 0.85);
    addBox(origin + ay * y, ax, ay, az, set(width, ht, t), cd);
    addBox(origin + az * (depth - t) + ay * y, ax, ay, az, set(width, ht, t), cd);
    addBox(origin + ay * y, ax, ay, az, set(t, ht, depth), cd);
    addBox(origin + ax * (width - t) + ay * y, ax, ay, az, set(t, ht, depth), cd);
}

vector palette(const int i) {
    if (i == 0) return set(0.62, 0.34, 0.26);
    if (i == 1) return set(0.80, 0.74, 0.62);
    if (i == 2) return set(0.50, 0.54, 0.58);
    if (i == 3) return set(0.76, 0.66, 0.46);
    if (i == 4) return set(0.42, 0.50, 0.48);
    if (i == 5) return set(0.55, 0.36, 0.32);
    if (i == 6) return set(0.84, 0.82, 0.74);
    return set(0.38, 0.44, 0.52);
}

void build_building(const vector pos; const vector xaxis; const vector zaxis; const float in_width; const float in_depth; const int in_floors; const int style; const int seed; const int landmark; const int pt) {
vector ax = normalize(xaxis);
vector az = normalize(zaxis);
vector ay = set(0, 1, 0);
if (dot(cross(ax, ay), az) < 0)
    ax = -ax;

float width = in_width;
float depth = in_depth;
int floors = max(1, in_floors);
removepoint(0, pt);

float rs = float(abs(seed));
vector wall = palette(int(rand(rs) * 8.0));
vector shop = clamp(wall * 0.62 + set(0.1, 0.07, 0.05), set(0, 0, 0), set(1, 1, 1));
vector roofc = set(0.22, 0.2, 0.18);
vector frame = set(0.16, 0.15, 0.14);
vector glass = set(0.07, 0.1, 0.14);
vector lit = set(0.95, 0.78, 0.42);
vector panel = set(0.22, 0.13, 0.08);
float groundH = fit01(rand(rs + 1.7), 3.9, 4.5);
float floorH = fit01(rand(rs + 2.4), 3.05, 3.45);
float targetTile = fit01(rand(rs + 3.1), 2.9, 4.1);
vector origin0 = pos - ax * (width * 0.5);

int setback = style == 1 && floors >= 5;
int podium = setback ? floors - 2 : floors;
int doorOnLeft = rand(rs + 8.1) > 0.5;
int layout = min(3, int(rand(rs + 6.2) * 4.0));

// Each facade is exactly one face of the footprint, so the roof
// lands on the same rectangle as the walls.
addFacade(origin0, ax, ay, az, width, 0.0, groundH, floorH, podium, doorOnLeft ? 0 : 1, layout, targetTile, seed, wall, shop, frame, glass, lit, panel);
addFacade(origin0 + ax * width + az * depth, -ax, ay, -az, width, 0.0, groundH, floorH, podium, -1, layout, targetTile, seed + 5, wall, shop, frame, glass, lit, panel);
if (depth > 1.6) {
    addFacade(origin0 + ax * width, az, ay, -ax, depth, 0.0, groundH, floorH, podium, -1, layout, targetTile, seed + 11, wall, shop, frame, glass, lit, panel);
    addFacade(origin0 + az * depth, -az, ay, ax, depth, 0.0, groundH, floorH, podium, -1, layout, targetTile, seed + 17, wall, shop, frame, glass, lit, panel);
}

float podiumTop = groundH + floorH * float(max(0, podium - 1));

if (setback) {
    float tw = width * 0.66;
    float td = depth * 0.66;
    vector towerO = origin0 + ax * ((width - tw) * 0.5) + az * ((depth - td) * 0.5);
    addRoofDeck(origin0, ax, az, width, depth, podiumTop, roofc);
    addRailing(origin0, ax, ay, az, width, depth, podiumTop, frame);
    addFacade(towerO + ay * podiumTop, ax, ay, az, tw, 0.0, floorH, floorH, 2, -1, layout, targetTile, seed + 23, wall, wall, frame, glass, lit, panel);
    addFacade(towerO + ax * tw + az * td + ay * podiumTop, -ax, ay, -az, tw, 0.0, floorH, floorH, 2, -1, layout, targetTile, seed + 29, wall, wall, frame, glass, lit, panel);
    if (td > 1.6) {
        addFacade(towerO + ax * tw + ay * podiumTop, az, ay, -ax, td, 0.0, floorH, floorH, 2, -1, layout, targetTile, seed + 31, wall, wall, frame, glass, lit, panel);
        addFacade(towerO + az * td + ay * podiumTop, -az, ay, ax, td, 0.0, floorH, floorH, 2, -1, layout, targetTile, seed + 37, wall, wall, frame, glass, lit, panel);
    }
    float towerTop = podiumTop + floorH * 2.0;
    addParapet(towerO, ax, ay, az, tw, td, towerTop, roofc);
} else if (style == 2 && floors <= 4 && !landmark) {
    float rh = fit01(rand(rs + 4.4), 1.6, 2.6);
    vector b0 = origin0 + ay * podiumTop;
    vector fl = b0;
    vector fr = b0 + ax * width;
    vector bl = b0 + az * depth;
    vector br = b0 + ax * width + az * depth;
    vector rl = b0 + az * (depth * 0.5) + ay * rh;
    vector rr = b0 + ax * width + az * (depth * 0.5) + ay * rh;
    addUpQuad(fl, fr, rr, rl, roofc);
    addUpQuad(bl, br, rr, rl, roofc);
    addFacingTri(fl, rl, bl, -ax, wall);
    addFacingTri(fr, rr, br, ax, wall);
} else {
    addParapet(origin0, ax, ay, az, width, depth, podiumTop, roofc);
}

if (landmark) {
    float sx = max(2.4, width * 0.24);
    float sz = max(2.4, depth * 0.24);
    vector so = origin0 + ax * ((width - sx) * 0.5) + az * ((depth - sz) * 0.5) + ay * (podiumTop + 0.55);
    addFacade(so, ax, ay, az, sx, 0.0, 3.2, 3.2, 3, -1, layout, 2.2, seed + 41, wall * 0.8, wall * 0.8, frame, glass, lit, panel);
    addFacade(so + ax * sx + az * sz, -ax, ay, -az, sx, 0.0, 3.2, 3.2, 3, -1, layout, 2.2, seed + 43, wall * 0.8, wall * 0.8, frame, glass, lit, panel);
    float shaftTop = 3.2 * 3.0;
    vector apex = so + ax * (sx * 0.5) + az * (sz * 0.5) + ay * (shaftTop + 3.4);
    vector b0 = so + ay * shaftTop;
    addTri(b0, b0 + ax * sx, apex, roofc);
    addTri(b0 + ax * sx, b0 + ax * sx + az * sz, apex, roofc * 0.9);
    addTri(b0 + ax * sx + az * sz, b0 + az * sz, apex, roofc * 0.8);
    addTri(b0 + az * sz, b0, apex, roofc);
}
}
