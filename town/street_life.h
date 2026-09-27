// Toronto street layer. Distances follow Municipal Code 950-400 and the
// usual arterial pattern: 9 m clear of every corner, 15 m clear of a
// signal, ladder crosswalks and tactile pads at the curb, streetcars
// centered on the two main streets.
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

void addBox(const vector origin; const vector ax; const vector ay; const vector az; const vector size; const vector cd) {
    vector c = origin + ax * (size.x * 0.5) + ay * (size.y * 0.5) + az * (size.z * 0.5);
    addCard(c + ax * (size.x * 0.5), ay, az, size.y, size.z, cd);
    addCard(c - ax * (size.x * 0.5), az, ay, size.z, size.y, cd);
    addCard(c + ay * (size.y * 0.5), az, ax, size.z, size.x, cd);
    addCard(c - ay * (size.y * 0.5), ax, az, size.x, size.z, cd);
    addCard(c + az * (size.z * 0.5), ax, ay, size.x, size.y, cd);
    addCard(c - az * (size.z * 0.5), ay, ax, size.y, size.x, cd);
}

void addRect(const float x0; const float x1; const float z0; const float z1; const float y; const vector cd) {
    vector c = set((x0 + x1) * 0.5, y, (z0 + z1) * 0.5);
    addCard(c, set(0, 0, 1), set(1, 0, 0), abs(z1 - z0), abs(x1 - x0), cd);
}

float rw(const int idx; const int mainidx; const float wide; const float narrow) {
    if (idx == mainidx) return wide;
    return narrow;
}

vector carPaint(const int n) {
    int k = n % 6;
    if (k == 0) return set(0.15, 0.16, 0.18);
    if (k == 1) return set(0.75, 0.76, 0.78);
    if (k == 2) return set(0.45, 0.12, 0.12);
    if (k == 3) return set(0.12, 0.22, 0.38);
    if (k == 4) return set(0.82, 0.72, 0.35);
    return set(0.25, 0.28, 0.26);
}

void addCar(const vector origin; const vector ax; const vector az; const vector paint) {
    vector glass = set(0.12, 0.16, 0.2);
    vector ay = set(0, 1, 0);
    addBox(origin, ax, ay, az, set(4.3, 0.85, 1.75), paint);
    addBox(origin + ax * 0.85 + ay * 0.85 + az * 0.12, ax, ay, az, set(2.2, 0.7, 1.5), glass);
}

void addTree(const vector base) {
    vector trunk = set(0.32, 0.22, 0.12);
    vector leaf = set(0.16, 0.38, 0.16);
    addBox(base + set(-0.12, 0, -0.12), set(1,0,0), set(0,1,0), set(0,0,1), set(0.24, 2.4, 0.24), trunk);
    int sides = 6;
    vector apex = base + set(0, 5.2, 0);
    int top = addpoint(geoself(), apex);
    setpointattrib(geoself(), "Cd", top, leaf);
    int ring[];
    for (int i = 0; i < sides; i++) {
        float a = float(i) / float(sides) * 6.283185;
        int pt = addpoint(geoself(), base + set(cos(a) * 1.3, 2.6, sin(a) * 1.3));
        setpointattrib(geoself(), "Cd", pt, leaf);
        append(ring, pt);
    }
    for (int i = 0; i < sides; i++) {
        int nxt = (i + 1) % sides;
        int prim = addprim(geoself(), "poly", ring[nxt], ring[i], top);
        setprimattrib(geoself(), "Cd", prim, leaf);
    }
}

void addStrut(const vector a; const vector b; const float thick; const vector cd) {
    vector delta = b - a;
    float len = length(delta);
    if (len < 0.02) return;
    vector ax = normalize(delta);
    vector up = set(0, 1, 0);
    if (abs(dot(ax, up)) > 0.85) up = set(1, 0, 0);
    vector side = normalize(cross(ax, up));
    vector lift = normalize(cross(side, ax));
    addBox(a - lift * (thick * 0.5) - side * (thick * 0.5), ax, lift, side, set(len, thick, thick), cd);
}

// toward is horizontal and points from the sidewalk out over the roadway.
void addLight(const vector base; const vector toward; const float height) {
    vector pole = set(0.16, 0.17, 0.18);
    vector lamp = set(0.95, 0.9, 0.7);
    vector dir = normalize(set(toward.x, 0, toward.z));
    vector side = normalize(cross(set(0, 1, 0), dir));
    addBox(base - set(0.09, 0, 0.09), set(1,0,0), set(0,1,0), set(0,0,1), set(0.18, height, 0.18), pole);
    float arm = 3.6;
    vector armStart = base + set(0, height - 0.15, 0);
    addStrut(armStart, armStart + dir * arm, 0.11, pole);
    vector head = armStart + dir * (arm - 0.2);
    addBox(head - dir * 0.32 - side * 0.2 - set(0, 0.22, 0), dir, set(0,1,0), side, set(0.7, 0.16, 0.42), lamp);
    // Underside faces the pavement, so the head reads as aimed down at the street.
    addCard(head - set(0, 0.24, 0), dir, side, 0.55, 0.32, set(1.0, 0.93, 0.62));
}

void addSignal(const vector base; const int armX) {
    vector black = set(0.07, 0.07, 0.08);
    vector pole = set(0.18, 0.18, 0.2);
    addBox(base, set(1,0,0), set(0,1,0), set(0,0,1), set(0.22, 5.4, 0.22), pole);
    float arm = 3.2;
    float x0 = armX > 0 ? base.x : base.x - arm;
    addBox(set(x0, base.y + 4.7, base.z - 0.08), set(1,0,0), set(0,1,0), set(0,0,1), set(arm, 0.16, 0.16), pole);
    float hx = armX > 0 ? base.x + arm - 0.45 : base.x - arm;
    vector head = set(hx, base.y + 3.15, base.z - 0.2);
    addBox(head, set(1,0,0), set(0,1,0), set(0,0,1), set(0.42, 1.25, 0.42), black);
    addBox(head + set(0.02, 0.82, 0.02), set(1,0,0), set(0,1,0), set(0,0,1), set(0.28, 0.28, 0.28), set(0.85, 0.08, 0.07));
    addBox(head + set(0.02, 0.48, 0.02), set(1,0,0), set(0,1,0), set(0,0,1), set(0.28, 0.28, 0.28), set(0.9, 0.55, 0.1));
    addBox(head + set(0.02, 0.14, 0.02), set(1,0,0), set(0,1,0), set(0,0,1), set(0.28, 0.28, 0.28), set(0.15, 0.65, 0.22));
    addBox(base + set(-0.05, 2.3, -0.05), set(1,0,0), set(0,1,0), set(0,0,1), set(0.28, 0.45, 0.12), black);
    addBox(base + set(0.02, 2.48, 0.02), set(1,0,0), set(0,1,0), set(0,0,1), set(0.16, 0.16, 0.06), set(0.95, 0.95, 0.9));
}

void addStop(const vector base) {
    vector pole = set(0.55, 0.55, 0.58);
    addBox(base, set(1,0,0), set(0,1,0), set(0,0,1), set(0.12, 2.5, 0.12), pole);
    addBox(base + set(-0.32, 2.15, -0.04), set(1,0,0), set(0,1,0), set(0,0,1), set(0.76, 0.76, 0.08), set(0.75, 0.08, 0.08));
}

// Diamond pantograph. The crossed braces are the "star" that reaches the contact wire.
void addPantograph(const vector roof; const vector ax; const vector az; const float contact) {
    vector metal = set(0.72, 0.73, 0.75);
    vector shoe = set(0.82, 0.55, 0.12);
    float midY = roof.y + (contact - roof.y) * 0.52;
    vector lowL = roof - ax * 0.45;
    vector lowR = roof + ax * 0.45;
    vector midL = set(roof.x, midY, roof.z) - ax * 0.85;
    vector midR = set(roof.x, midY, roof.z) + ax * 0.85;
    vector top = set(roof.x, contact - 0.04, roof.z);
    addStrut(lowL, lowR, 0.05, metal);
    addStrut(lowL, midL, 0.055, metal);
    addStrut(lowR, midR, 0.055, metal);
    addStrut(lowL, midR, 0.045, metal);
    addStrut(lowR, midL, 0.045, metal);
    addStrut(midL, top, 0.05, metal);
    addStrut(midR, top, 0.05, metal);
    addStrut(top - az * 0.55, top + az * 0.55, 0.07, shoe);
}

void addStreetcar(const vector origin; const vector ax; const vector az; const float contact) {
    vector red = set(0.7, 0.09, 0.11);
    vector roof = set(0.86, 0.86, 0.88);
    vector glass = set(0.1, 0.14, 0.18);
    vector ay = set(0, 1, 0);
    float len = 28.0;
    float wid = 2.54;
    addBox(origin, ax, ay, az, set(len, 2.35, wid), red);
    addBox(origin + ay * 2.35, ax, ay, az, set(len, 1.05, wid * 0.92), roof);
    vector roofC = origin + ax * (len * 0.58) + az * (wid * 0.46) + ay * 3.42;
    addPantograph(roofC, ax, az, contact);
    for (int w = 0; w < 7; w++) {
        float u = 2.2 + float(w) * 3.5;
        addCard(origin + ax * u + az * (-0.05) + ay * 1.7, ay, ax, 1.15, 2.3, glass);
        addCard(origin + ax * u + az * (wid + 0.05) + ay * 1.7, ax, ay, 2.3, 1.15, glass);
    }
}

void build_street() {
int streets = chi("../../TOWN_CONTROLS/streets");
float block = ch("../../TOWN_CONTROLS/block_size");
float road = ch("../../TOWN_CONTROLS/road_width");
float mainw = ch("../../TOWN_CONTROLS/main_road_width");
float sidew = ch("../../TOWN_CONTROLS/sidewalk");
int blocks = max(1, streets - 1);
int main = streets / 2;
float extent = blocks * block;
float origin = -extent * 0.5;

vector white = set(0.9, 0.9, 0.86);
vector tactile = set(0.85, 0.68, 0.12);
vector concrete = set(0.62, 0.6, 0.56);
vector rail = set(0.22, 0.2, 0.18);
vector shelterC = set(0.55, 0.08, 0.1);
vector glassS = set(0.45, 0.62, 0.68);

// Continuous streetcar rails on the two main streets. TTC gauge is about
// 1.5 m; the two tracks sit either side of the centerline.
float gauge = 0.75;
float track = 1.85;
float contactY = 5.55;
float spanY = 6.9;
for (int rail_i = 0; rail_i < 4; rail_i++) {
    float offset = (rail_i < 2 ? -track : track) + (rail_i % 2 == 0 ? -gauge : gauge);
    float z = origin + main * block + offset;
    float x = origin + main * block + offset;
    addBox(set(origin, 0.13, z - 0.05), set(1,0,0), set(0,1,0), set(0,0,1), set(extent, 0.08, 0.1), rail);
    addBox(set(x - 0.05, 0.13, origin), set(1,0,0), set(0,1,0), set(0,0,1), set(0.1, 0.08, extent), rail);
}

// Overhead catenary on both streetcar streets: contact wire, messenger, droppers.
vector wireC = set(0.18, 0.18, 0.2);
vector messengerC = set(0.28, 0.28, 0.3);
float zMain = origin + main * block;
float xMain = origin + main * block;
float messengerY = contactY + 0.85;
addStrut(set(origin, contactY, zMain - track), set(origin + extent, contactY, zMain - track), 0.045, wireC);
addStrut(set(origin, contactY, zMain + track), set(origin + extent, contactY, zMain + track), 0.045, wireC);
addStrut(set(origin, messengerY, zMain - track), set(origin + extent, messengerY, zMain - track), 0.035, messengerC);
addStrut(set(origin, messengerY, zMain + track), set(origin + extent, messengerY, zMain + track), 0.035, messengerC);
addStrut(set(xMain - track, contactY + 0.12, origin), set(xMain - track, contactY + 0.12, origin + extent), 0.045, wireC);
addStrut(set(xMain + track, contactY + 0.12, origin), set(xMain + track, contactY + 0.12, origin + extent), 0.045, wireC);
addStrut(set(xMain - track, messengerY + 0.12, origin), set(xMain - track, messengerY + 0.12, origin + extent), 0.035, messengerC);
addStrut(set(xMain + track, messengerY + 0.12, origin), set(xMain + track, messengerY + 0.12, origin + extent), 0.035, messengerC);
int drops = max(4, int(extent / 7.5));
for (int d = 1; d < drops; d++) {
    float t = origin + extent * float(d) / float(drops);
    addStrut(set(t, contactY, zMain - track), set(t, messengerY, zMain - track), 0.025, wireC);
    addStrut(set(t, contactY, zMain + track), set(t, messengerY, zMain + track), 0.025, wireC);
    addStrut(set(xMain - track, contactY + 0.12, t), set(xMain - track, messengerY + 0.12, t), 0.025, wireC);
    addStrut(set(xMain + track, contactY + 0.12, t), set(xMain + track, messengerY + 0.12, t), 0.025, wireC);
}

// Streetcars stopped farside of a corner, clear of the intersection box.
float sideHalf = road * 0.5;
float carLen = 28.0;
for (int n = 0; n < 2; n++) {
    int seg = n == 0 ? 1 : max(1, blocks - 2);
    float x0 = origin + seg * block + sideHalf + 2.0;
    float x1 = origin + (seg + 1) * block - sideHalf;
    if (x1 - x0 > carLen + 4.0) {
        float zTrack = origin + main * block + (n == 0 ? -track : track);
        addStreetcar(set(x0 + 1.5, 0.16, zTrack - 1.27), set(1, 0, 0), set(0, 0, 1), contactY);
        float stopX = x0 + 6.0;
        float walkZ = origin + main * block + mainw * 0.5 + 0.15;
        addBox(set(stopX, 0.08, walkZ), set(1,0,0), set(0,1,0), set(0,0,1), set(6.5, 2.4, sidew - 0.3), glassS);
        addBox(set(stopX, 2.35, walkZ), set(1,0,0), set(0,1,0), set(0,0,1), set(6.5, 0.18, sidew - 0.3), shelterC);
        addBox(set(stopX + 0.4, 0.1, walkZ + 0.35), set(1,0,0), set(0,1,0), set(0,0,1), set(1.8, 0.45, 0.45), set(0.25, 0.22, 0.2));
        addRect(x0, x0 + 8.0, origin + main * block + mainw * 0.5 - 0.35, origin + main * block + mainw * 0.5 + 0.05, 0.17, tactile);
    }
}
if (blocks > 2) {
    float z0 = origin + 1 * block + sideHalf + 2.0;
    float z1 = origin + 2 * block - sideHalf;
    if (z1 - z0 > carLen + 4.0) {
        float xTrack = origin + main * block - track;
        addStreetcar(set(xTrack - 1.27, 0.16, z0 + 1.5), set(0, 0, 1), set(1, 0, 0), contactY + 0.12);
    }
}

for (int j = 0; j < streets; j++) {
    for (int i = 0; i < streets; i++) {
        float x = origin + i * block;
        float z = origin + j * block;
        float hx = rw(i, main, mainw, road) * 0.5;
        float hz = rw(j, main, mainw, road) * 0.5;
        int signal = (i == main || j == main);

        // East and west legs: pedestrians cross a street that runs along X.
        float band = hz * 2.0 - 1.4;
        int bars = max(4, int(band / 0.85));
        for (int side = -1; side <= 1; side += 2) {
            float near = side > 0 ? x + hx + 0.9 : x - hx - 4.3;
            float far = near + 3.4;
            for (int s = 0; s < bars; s++) {
                float tz = z - hz + 0.7 + (float(s) + 0.5) * (band / float(bars));
                if (signal)
                    addRect(near, far, tz - 0.16, tz + 0.16, 0.165, white);
            }
            if (!signal) {
                addRect(near, far, z - hz + 0.45, z - hz + 0.75, 0.165, white);
                addRect(near, far, z + hz - 0.75, z + hz - 0.45, 0.165, white);
            }
            float stop = side > 0 ? far + 0.7 : near - 1.05;
            addRect(stop, stop + 0.35, z - hz + 0.55, z + hz - 0.55, 0.17, white);
        }
        // North and south legs.
        band = hx * 2.0 - 1.4;
        bars = max(4, int(band / 0.85));
        for (int side = -1; side <= 1; side += 2) {
            float near = side > 0 ? z + hz + 0.9 : z - hz - 4.3;
            float far = near + 3.4;
            for (int s = 0; s < bars; s++) {
                float tx = x - hx + 0.7 + (float(s) + 0.5) * (band / float(bars));
                if (signal)
                    addRect(tx - 0.16, tx + 0.16, near, far, 0.165, white);
            }
            if (!signal) {
                addRect(x - hx + 0.45, x - hx + 0.75, near, far, 0.165, white);
                addRect(x + hx - 0.75, x + hx - 0.45, near, far, 0.165, white);
            }
            float stop = side > 0 ? far + 0.7 : near - 1.05;
            addRect(x - hx + 0.55, x + hx - 0.55, stop, stop + 0.35, 0.17, white);
        }

        // Curb ramps and yellow tactile pads, one per corner.
        for (int sx = -1; sx <= 1; sx += 2) {
            for (int sz = -1; sz <= 1; sz += 2) {
                float cx = x + sx * (hx + 0.15);
                float cz = z + sz * (hz + 0.15);
                addRect(cx - 0.7, cx + 0.7, cz - 0.7, cz + 0.7, 0.075, concrete);
                float tx = x + sx * (hx + 1.15);
                float tz = z + sz * (hz + 1.15);
                addRect(tx - 0.55, tx + 0.55, tz - 0.45, tz + 0.45, 0.09, tactile);
                addBox(set(x + sx * (hx + 1.6) - 0.15, 0.08, z + sz * (hz + 0.35) - 0.15), set(1,0,0), set(0,1,0), set(0,0,1), set(0.32, 0.7, 0.28), set(0.7, 0.1, 0.08));
            }
        }

        if (signal) {
            addSignal(set(x + hx + 0.85, 0.08, z + hz + 0.7), -1);
            addSignal(set(x - hx - 1.15, 0.08, z - hz - 0.7), 1);
            addSignal(set(x + hx + 0.7, 0.08, z - hz - 1.15), -1);
            addSignal(set(x - hx - 1.0, 0.08, z + hz + 0.85), 1);
        } else {
            addStop(set(x + hx + 0.8, 0.08, z - hz - 0.9));
            addStop(set(x - hx - 0.9, 0.08, z + hz + 0.7));
            addStop(set(x + hx + 0.7, 0.08, z + hz + 0.8));
            addStop(set(x - hx - 0.8, 0.08, z - hz - 0.7));
        }
    }
}

// Lights, trees, and curb parking along each block, kept out of the corner clearance.
for (int j = 0; j < streets; j++) {
    float z = origin + j * block;
    float hz = rw(j, main, mainw, road) * 0.5;
    int arterial = j == main;
    for (int i = 0; i < blocks; i++) {
        float a = origin + i * block + rw(i, main, mainw, road) * 0.5;
        float b = origin + (i + 1) * block - rw(i + 1, main, mainw, road) * 0.5;
        if (b - a < 12.0) continue;
        float clear0 = (i == main || arterial) ? 15.0 : 9.0;
        float clear1 = (i + 1 == main || arterial) ? 15.0 : 9.0;
        float span = b - a;
        int lights = max(1, int(span / (arterial ? 22.0 : 28.0)));
        for (int L = 0; L < lights; L++) {
            float u = a + span * (float(L) + 0.5) / float(lights);
            if (arterial) {
                float northZ = z + hz + 0.45;
                float southZ = z - hz - 0.45;
                addLight(set(u, 0.08, northZ), set(0, 0, -1), 9.2);
                addLight(set(u, 0.08, southZ), set(0, 0, 1), 9.2);
                addStrut(set(u, spanY, southZ), set(u, spanY, northZ), 0.035, wireC);
                addStrut(set(u, contactY, z - track), set(u, spanY, z - track), 0.028, wireC);
                addStrut(set(u, contactY, z + track), set(u, spanY, z + track), 0.028, wireC);
                if ((i + L) % 2 == 0)
                    addTree(set(u + 5.0, 0.08, z + hz + sidew * 0.55));
            } else if ((i + j + L) % 2 == 0) {
                addLight(set(u, 0.08, z + hz + 0.45), set(0, 0, -1), 6.8);
                addTree(set(u + 4.5, 0.08, z + hz + sidew * 0.62));
            } else {
                addLight(set(u, 0.08, z - hz - 0.45), set(0, 0, 1), 6.8);
                addTree(set(u - 2.0, 0.08, z - hz - sidew * 0.62));
            }
        }
        if (!arterial) {
            float park0 = a + clear0;
            float park1 = b - clear1;
            int slots = int((park1 - park0) / 6.2);
            for (int ncar = 0; ncar < slots && ncar < 6; ncar++) {
                float cursor = park0 + float(ncar) * 6.2;
                if (rand(float(i * 17 + j * 5 + ncar) + 0.3) > 0.25) {
                    addCar(set(cursor, 0.14, z - hz + 0.35), set(1,0,0), set(0,0,1), carPaint(i + j + ncar));
                }
                if (rand(float(i * 9 + j * 13 + ncar) + 1.7) > 0.25) {
                    addCar(set(cursor + 0.4, 0.14, z + hz - 2.15), set(1,0,0), set(0,0,1), carPaint(i * 3 + ncar + 2));
                }
            }
        } else if ((i + j) % 2 == 0 && b - a > 20.0) {
            float lane = hz - 2.3;
            addCar(set((a + b) * 0.5, 0.14, z + lane - 0.9), set(1,0,0), set(0,0,1), carPaint(i + 4));
            addCar(set((a + b) * 0.5 + 7.0, 0.14, z - lane - 0.9), set(1,0,0), set(0,0,1), carPaint(j + 1));
        }
    }
}

for (int i = 0; i < streets; i++) {
    float x = origin + i * block;
    float hx = rw(i, main, mainw, road) * 0.5;
    int nsArterial = i == main;
    for (int j = 0; j < blocks; j++) {
        float a = origin + j * block + rw(j, main, mainw, road) * 0.5;
        float b = origin + (j + 1) * block - rw(j + 1, main, mainw, road) * 0.5;
        if (b - a < 12.0) continue;
        if (nsArterial) {
            float span = b - a;
            int lights = max(1, int(span / 22.0));
            for (int L = 0; L < lights; L++) {
                float u = a + span * (float(L) + 0.5) / float(lights);
                if (abs(u - zMain) < mainw * 0.5 + 4.0) continue;
                float eastX = x + hx + 0.45;
                float westX = x - hx - 0.45;
                addLight(set(eastX, 0.08, u), set(-1, 0, 0), 9.2);
                addLight(set(westX, 0.08, u), set(1, 0, 0), 9.2);
                addStrut(set(westX, spanY, u), set(eastX, spanY, u), 0.035, wireC);
                addStrut(set(x - track, contactY + 0.12, u), set(x - track, spanY, u), 0.028, wireC);
                addStrut(set(x + track, contactY + 0.12, u), set(x + track, spanY, u), 0.028, wireC);
            }
        } else {
            if (b - a < 18.0) continue;
            float clear0 = (j == main) ? 15.0 : 9.0;
            float clear1 = (j + 1 == main) ? 15.0 : 9.0;
            int slots = int((b - clear1 - (a + clear0)) / 6.4);
            for (int ncar = 0; ncar < slots && ncar < 5; ncar++) {
                float cursor = a + clear0 + float(ncar) * 6.4;
                if (rand(float(i * 11 + j * 19 + ncar) + 2.2) > 0.3) {
                    addCar(set(x - hx + 0.35, 0.14, cursor), set(0,0,1), set(-1,0,0), carPaint(i + ncar + 3));
                }
            }
            if ((i + j) % 2 == 0) {
                addLight(set(x + hx + 0.45, 0.08, (a + b) * 0.5), set(-1, 0, 0), 6.8);
                addTree(set(x - hx - sidew * 0.55, 0.08, (a + b) * 0.5 + 5.0));
            }
        }
    }
}
}
