# Appended to hairswap.py: Marina's accessories from her profile.
import bmesh, math
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree

def lin(c):
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c)

def toon(name, base, shade, rim=(0.0, 0.0, 0.0), rim_power=5.0):
    m = bpy.data.materials.new(name)
    m1 = m.vrm_addon_extension.mtoon1
    m1.enabled = True
    m1.pbr_metallic_roughness.base_color_factor = (*lin(base), 1.0)
    m1.emissive_factor = (0.0, 0.0, 0.0)
    e = m1.extensions.vrmc_materials_mtoon
    e.shade_color_factor = lin(shade)
    e.shading_toony_factor = 0.95
    e.parametric_rim_color_factor = lin(rim)
    e.parametric_rim_fresnel_power_factor = rim_power
    e.parametric_rim_lift_factor = 0.0
    e.rim_lighting_mix_factor = 1.0
    e.outline_width_mode = "worldCoordinates"
    e.outline_width_factor = 0.0002
    e.outline_color_factor = (0.02, 0.018, 0.03)
    return m

SILVER = toon("Marina_acc_silver", (0.86, 0.86, 0.92), (0.50, 0.50, 0.60), rim=(0.9, 0.9, 1.0), rim_power=3.0)
BLACK = toon("Marina_acc_black", (0.08, 0.08, 0.10), (0.04, 0.04, 0.06), rim=(0.25, 0.25, 0.32))
ENAMEL = toon("Marina_acc_enamel", (0.80, 0.76, 0.90), (0.58, 0.54, 0.70))

arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
dg = bpy.context.evaluated_depsgraph_get()
def bvh_of(name):
    ob = bpy.data.objects[name]
    me = ob.evaluated_get(dg).to_mesh()
    return BVHTree.FromPolygons([ob.matrix_world @ v.co for v in me.vertices], [p.vertices[:] for p in me.polygons]), me, ob
BODY, BODY_ME, BODY_OB = bvh_of("Body")
FACE, FACE_ME, FACE_OB = bvh_of("Face")

class Part:
    def __init__(self):
        self.bm = bmesh.new(); self.mats = []
    def slot(self, m):
        if m not in self.mats: self.mats.append(m)
        return self.mats.index(m)
    def face(self, verts, m):
        f = self.bm.faces.new(verts); f.material_index = self.slot(m); return f
    def finish(self, name, bone, follow_body=False):
        bmesh.ops.recalc_face_normals(self.bm, faces=self.bm.faces)
        me = bpy.data.meshes.new(name); self.bm.to_mesh(me); self.bm.free()
        for m in self.mats: me.materials.append(m)
        for p in me.polygons: p.use_smooth = True
        ob = bpy.data.objects.new(name, me)
        bpy.data.objects["Body"].users_collection[0].objects.link(ob)
        ob.parent = arm
        if follow_body:
            from mathutils.kdtree import KDTree
            src = BODY_OB.data
            kd = KDTree(len(src.vertices))
            for v in src.vertices: kd.insert(BODY_OB.matrix_world @ v.co, v.index)
            kd.balance()
            names = {g.index: g.name for g in BODY_OB.vertex_groups}
            groups = {}
            for v in me.vertices:
                _, idx, _ = kd.find(v.co)
                for g in src.vertices[idx].groups:
                    if g.weight > 0.001 and g.group in names:
                        n = names[g.group]
                        if n not in groups: groups[n] = ob.vertex_groups.new(name=n)
                        groups[n].add([v.index], g.weight, "REPLACE")
        else:
            vg = ob.vertex_groups.new(name=bone)
            vg.add(list(range(len(me.vertices))), 1.0, "REPLACE")
        ob.modifiers.new("Armature", "ARMATURE").object = arm
        print("built", name, len(me.vertices), "verts on", bone)

def torus(P, c, n, R, r, m, segs=14, rsegs=6):
    """Ring centred at c, lying in the plane with normal n."""
    n = n.normalized()
    a = n.orthogonal().normalized(); b = n.cross(a)
    rings = []
    for i in range(segs):
        t = 2 * math.pi * i / segs
        d = a * math.cos(t) + b * math.sin(t)
        rings.append([P.bm.verts.new(c + d * (R + r * math.cos(2 * math.pi * k / rsegs)) + n * (r * math.sin(2 * math.pi * k / rsegs))) for k in range(rsegs)])
    for i in range(segs):
        for k in range(rsegs):
            P.face((rings[i][k], rings[(i + 1) % segs][k], rings[(i + 1) % segs][(k + 1) % rsegs], rings[i][(k + 1) % rsegs]), m)

def sphere(P, c, r, m, segs=10, rings_=6):
    vs = []
    for j in range(1, rings_):
        ph = math.pi * j / rings_
        vs.append([P.bm.verts.new(c + Vector((math.sin(ph) * math.cos(2 * math.pi * i / segs), math.sin(ph) * math.sin(2 * math.pi * i / segs), math.cos(ph))) * r) for i in range(segs)])
    top = P.bm.verts.new(c + Vector((0, 0, r))); bot = P.bm.verts.new(c - Vector((0, 0, r)))
    for i in range(segs):
        n_ = (i + 1) % segs
        P.face((top, vs[0][i], vs[0][n_]), m)
        P.face((bot, vs[-1][n_], vs[-1][i]), m)
        for j in range(len(vs) - 1):
            P.face((vs[j][i], vs[j + 1][i], vs[j + 1][n_], vs[j][n_]), m)

def chain(P, pts, m, R=0.0032, r=0.0007):
    """Links along a polyline, alternating orientation."""
    path = []
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        steps = max(1, int((b - a).length / (R * 1.55)))
        for s in range(steps): path.append(a.lerp(b, s / steps))
    path.append(pts[-1])
    side = Vector((0, -1, 0))
    for i, p in enumerate(path):
        t = (path[min(i + 1, len(path) - 1)] - path[max(i - 1, 0)]).normalized()
        n1 = t.cross(side).normalized()
        n = n1 if i % 2 else t.cross(n1).normalized()
        # stretch the ring along the chain a little: oval links
        torus(P, p, n, R, r, m, segs=12, rsegs=5)

def flat_shape(P, outline, origin, n, up, depth, m, scale=1.0):
    """Extrude a 2D outline (x right, y up) onto a surface frame."""
    n = n.normalized(); up = (up - n * up.dot(n)).normalized(); right = up.cross(n)
    front = [P.bm.verts.new(origin + (right * x + up * y) * scale - n * 0.0) for x, y in outline]
    back = [P.bm.verts.new(origin + (right * x + up * y) * scale - n * depth) for x, y in outline]
    # n points out of the hoodie; front face sits furthest out
    front = [P.bm.verts.new(v.co + n * depth) for v in back]
    for v in back: pass
    P.face(list(reversed(back)), m)
    P.face(front, m)
    k = len(outline)
    for i in range(k):
        P.face((back[i], back[(i + 1) % k], front[(i + 1) % k], front[i]), m)

def crescent(R=1.0, r=0.80, off=0.42, n=40):
    """Outer arc through the left, inner arc back: horns point right."""
    x = (R * R - r * r + off * off) / (2 * off)
    th = math.acos(x / R)
    ph = math.atan2(math.sqrt(max(R * R - x * x, 0)), x - off)
    pts = []
    for i in range(n + 1):
        t = th + (2 * math.pi - 2 * th) * i / n
        pts.append((R * math.cos(t), R * math.sin(t)))
    for i in range(1, n):
        t = (2 * math.pi - ph) - (2 * math.pi - 2 * ph) * i / n
        pts.append((off + r * math.cos(t), r * math.sin(t)))
    return pts

def star(R=1.0, r=0.45):
    return [((R if i % 2 == 0 else r) * math.cos(math.pi / 2 + math.pi * i / 5),
             (R if i % 2 == 0 else r) * math.sin(math.pi / 2 + math.pi * i / 5)) for i in range(10)]

def hit_front(x, z):
    loc, nrm, *_ = BODY.ray_cast(Vector((x, -1, z)), Vector((0, 1, 0)))
    return loc, nrm

# ---- choker: thin black band, small silver ring at the front ----
P = Part()
cz = 1.378
skin_i = [i for i, m in enumerate(BODY_ME.materials) if "Body_00_SKIN" in m.name][0]
neck = [BODY_OB.matrix_world @ BODY_ME.vertices[vi].co for p in BODY_ME.polygons if p.material_index == skin_i
        for vi in p.vertices]
neck = [c for c in neck if abs(c.z - cz) < 0.008 and abs(c.x) < 0.06]
cy = sum(c.y for c in neck) / len(neck)
centre = Vector((0, cy, cz))
N = 64
radii = []
for k in range(N):
    a = 2 * math.pi * k / N
    d = Vector((math.sin(a), -math.cos(a), 0))
    loc = BODY.ray_cast(centre, d, 0.2)[0]
    radii.append((loc - centre).length if loc else None)
good = [r for r in radii if r]
radii = [r if r else sum(good) / len(good) for r in radii]
# smooth so the band doesn't pick up mesh facets
for _ in range(3):
    radii = [(radii[k - 1] + 2 * radii[k] + radii[(k + 1) % N]) / 4 for k in range(N)]
print("neck radius min/max", min(radii), max(radii), "centre y", cy)
rows = []
for k in range(N):
    a = 2 * math.pi * k / N
    d = Vector((math.sin(a), -math.cos(a), 0))
    p = centre + d * (radii[k] + 0.0012)
    rows.append([P.bm.verts.new(p + Vector((0, 0, dz)) + d * o) for dz, o in ((-0.0032, 0), (0.0032, 0), (0.0032, 0.0012), (-0.0032, 0.0012))])
for k in range(N):
    a_, b_ = rows[k], rows[(k + 1) % N]
    for q in range(4):
        P.face((a_[q], a_[(q + 1) % 4], b_[(q + 1) % 4], b_[q]), BLACK)
ry = radii[0]
front = Vector((0, cy - ry - 0.0024, cz - 0.0032))
torus(P, front + Vector((0, 0, -0.0034)), Vector((0, 1, 0)), 0.0032, 0.0007, SILVER, segs=20, rsegs=6)
P.finish("Choker", "J_Bip_C_Neck")

# ---- pins on her left chest (viewer's right), just under the hood edge ----
P = Part()
for (x, z, shape, size, tilt, fill) in ((0.058, 1.205, "crescent", 0.0085, 55, ENAMEL),
                                         (0.068, 1.178, "star", 0.0058, 12, SILVER)):
    loc, nrm = hit_front(x, z)
    if loc is None: print("missed pin", x, z); continue
    print("pin", shape, loc, nrm)
    up = Matrix.Rotation(math.radians(tilt), 3, nrm) @ Vector((0, 0, 1))
    outline = crescent() if shape == "crescent" else star()
    base = loc + nrm * 0.0018
    # silver backing a touch bigger, then the face
    flat_shape(P, outline, base, nrm, up, 0.0009, SILVER, scale=size * 1.16)
    flat_shape(P, outline, base + nrm * 0.0009, nrm, up, 0.0006, fill, scale=size)
P.finish("Pins", "J_Bip_C_UpperChest", follow_body=True)

# ---- chain looping off the hoodie front, by the pocket on her right ----
P = Part()
a_loc, a_n = hit_front(-0.14, 1.02)
b_loc, b_n = hit_front(-0.05, 0.985)
if a_loc and b_loc:
    pts = []
    for i in range(21):
        t = i / 20
        p = a_loc.lerp(b_loc, t)
        p.z -= 0.035 * math.sin(math.pi * t)          # sag
        h, hn = hit_front(p.x, p.z)
        if h: p.y = h.y - 0.004
        pts.append(p)
    chain(P, pts, SILVER)
    torus(P, a_loc + a_n * 0.002, Vector((1, 0, 0)), 0.0045, 0.0009, SILVER, segs=16)
    torus(P, b_loc + b_n * 0.002, Vector((1, 0, 0)), 0.0045, 0.0009, SILVER, segs=16)
P.finish("HoodieChain", "J_Bip_C_Hips", follow_body=True)

# ---- ear piercings: helix studs and a lobe hoop with a short chain ----
P = Part()
skin = [i for i, m in enumerate(FACE_ME.materials) if "Face_00_SKIN" in m.name][0]
ear = {}
for p in FACE_ME.polygons:
    if p.material_index != skin: continue
    for vi in p.vertices:
        c = FACE_OB.matrix_world @ FACE_ME.vertices[vi].co
        if abs(c.x) > 0.075 and 1.40 < c.z < 1.52 and c.y > -0.01:
            ear[vi] = c
for side in (1, -1):
    pts = [c for c in ear.values() if c.x * side > 0]
    if not pts: print("no ear", side); continue
    top = max(pts, key=lambda c: c.z); low = min(pts, key=lambda c: c.z)
    outer = max(pts, key=lambda c: abs(c.x))
    print("ear", side, "top", top, "low", low, "outer", outer)
    # lobe: small hoop with three links hanging off it
    lobe = low + Vector((side * 0.002, -0.002, 0.004))
    torus(P, lobe + Vector((0, 0, -0.004)), Vector((0, 1, 0)), 0.0042, 0.0007, SILVER, segs=18)
    if side > 0:
        dangle = [lobe + Vector((0, 0, -0.0085 - 0.0045 * k)) for k in range(4)]
        chain(P, dangle, SILVER, R=0.0018, r=0.00045)
        sphere(P, dangle[-1] + Vector((0, 0, -0.0028)), 0.0016, SILVER)
    # helix: three studs following the rim from the top down
    rim = sorted([c for c in pts if abs(c.x) > abs(outer.x) - 0.006 and c.z > (top.z + low.z) / 2], key=lambda c: -c.z)
    for k, frac in enumerate((0.12, 0.35, 0.58)):
        if not rim: break
        c = rim[min(int(frac * len(rim)), len(rim) - 1)]
        sphere(P, c + Vector((side * 0.0012, 0, 0)), 0.0014, SILVER if k != 1 else BLACK)
P.finish("Piercings", "J_Bip_C_Head")
