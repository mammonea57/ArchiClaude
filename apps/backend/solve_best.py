"""
Definitive best-achievable search. Connected-by-construction L-shapes.
Analytic area/overlap/contact/cover (fast); shapely verifies the winner.

Topology (XN = 08 thin-col left edge):
  05 = B(0,y05,10,16) U B(0,0,fx,y05)             foot top = y05 -> connected
  06 = B(10,s6,XN,16) U B(10,dy,dxb,s6)           dip connects at y=s6 over x[10,dxb]
  08 = B(XN,10,18,16) U B(ax,10,XN,at)            arm connects at x=XN over y[10,16]; at<16
  10 = B(xc2,0,18,10) U B(bx,0,xc2,by)            foot connects at x=xc2; bx>=fx (no 05 clash)

Non-overlap enforced analytically. Objective: prefer C5-feasible, else maximize min then min ratio.
"""
import itertools
import time
from shapely.geometry import box, LineString
from shapely.ops import unary_union

XN = 17.7   # 08 col width 0.3 -> buffer-safe top-touch < 0.5
_T0 = time.time()
_BUDGET = 400.0
FAC = {
    "05": LineString([(0, 16), (10, 16)]),
    "06": LineString([(10, 16), (18, 16)]),
    "08": LineString([(18, 10), (18, 16)]),
    "10": LineString([(18, 0), (18, 10)]),
}


def rects(P):
    return {
        "05": [(0.0, P["y05"], 10.0, 16.0), (0.0, 0.0, P["fx"], P["y05"])],
        "06": [(10.0, P["s6"], XN, 16.0), (10.0, P["dy"], P["dxb"], P["s6"])],
        "08": [(XN, 10.0, 18.0, 16.0), (P["ax"], 10.0, XN, P["at"])],
        "10": [(P["xc2"], 0.0, 18.0, 10.0), (P["bx"], 0.0, P["xc2"], P["by"])],
    }


def rov(r1, r2):
    ix = max(0.0, min(r1[2], r2[2]) - max(r1[0], r2[0]))
    iy = max(0.0, min(r1[3], r2[3]) - max(r1[1], r2[1]))
    return ix * iy


def rar(r):
    return max(0.0, r[2] - r[0]) * max(0.0, r[3] - r[1])


def union_len(ivs):
    if not ivs:
        return 0.0
    ivs = sorted(ivs)
    tot = 0.0
    cs, ce = ivs[0]
    for a, b in ivs[1:]:
        if a > ce:
            tot += ce - cs
            cs, ce = a, b
        else:
            ce = max(ce, b)
    tot += ce - cs
    return tot


def top_contact(rs, x0, x1):
    return union_len([(max(r[0], x0), min(r[2], x1)) for r in rs
                      if abs(r[3] - 16.0) < 1e-9 and min(r[2], x1) > max(r[0], x0)])


def right_contact(rs, y0, y1):
    return union_len([(max(r[1], y0), min(r[3], y1)) for r in rs
                      if abs(r[2] - 18.0) < 1e-9 and min(r[3], y1) > max(r[1], y0)])


def apt_area(rs):
    return rar(rs[0]) + rar(rs[1]) - rov(rs[0], rs[1])


def check(P, need_cover=True):
    R = rects(P)
    apts = ["05", "06", "08", "10"]
    ar = {a: apt_area(R[a]) for a in apts}
    if min(ar.values()) <= 0:
        return None
    ov = 0.0
    for i, a in enumerate(apts):
        for b in apts[i + 1:]:
            for r1 in R[a]:
                for r2 in R[b]:
                    ov += rov(r1, r2)
    if ov >= 0.5:
        return None
    cc = {"05": top_contact(R["05"], 0, 10), "06": top_contact(R["06"], 10, 18),
          "08": right_contact(R["08"], 10, 16), "10": right_contact(R["10"], 0, 10)}
    for a in apts:
        if cc[a] <= 0.6:
            return None
    cross = [top_contact(R["08"], 10, 18), right_contact(R["06"], 10, 16),
             right_contact(R["10"], 10, 16), right_contact(R["08"], 0, 10),
             top_contact(R["05"], 10, 18), top_contact(R["06"], 0, 10),
             top_contact(R["10"], 0, 18)]
    for v in cross:
        if v >= 0.5:
            return None
    cover = sum(ar.values()) - ov
    if need_cover and cover < 259:
        return None
    mn, mx = min(ar.values()), max(ar.values())
    return {"ar": ar, "ov": ov, "cover": cover, "ratio": mx / mn, "min": mn}


def R_(lo, hi, s=0.5):
    n = int(round((hi - lo) / s))
    return [round(lo + s * i, 3) for i in range(n + 1)]


def search():
    best = None       # cover>=259
    besteff = None    # ignore cover, max(min)
    tried = 0
    stop = False
    for xc2 in R_(11.0, 14.0):
        if stop:
            break
        for by in R_(2.0, 10.0):
            if time.time() - _T0 > _BUDGET:
                stop = True
                break
            for bx in R_(2.0, xc2 - 0.5):
                if stop:
                    break
                A10 = (18 - xc2) * 10 + (xc2 - bx) * by
                if A10 < 40 or A10 > 130:
                    continue
                if stop:
                    break
                for y05 in R_(11.0, 14.0):
                    if stop:
                        break
                    for fx in R_(0.5, bx + 0.001):   # 05 foot ends at/left of 10 foot start
                        A05 = 10 * (16 - y05) + fx * y05
                        if A05 < 40 or A05 > 130:
                            continue
                        if time.time() - _T0 > _BUDGET:
                            stop = True
                            break
                        for s6 in R_(13.0, 15.5):        # 06 top-strip bottom (high -> thin strip, frees arm band)
                            for dxb in R_(10.5, 13.0):   # 06 center-dip right edge (<= ax, <= xc2)
                                if dxb > xc2:
                                    continue
                                for dy in R_(1.0, 10.0):  # 06 dip bottom (can go below y=10 in center)
                                    if dy >= s6:
                                        continue
                                    A06 = (XN - 10) * (16 - s6) + (dxb - 10) * (s6 - dy)
                                    if A06 < 30 or A06 > 95:
                                        continue
                                    for ax in R_(max(dxb, 10.0), 14.0):   # 08 arm left (low -> wide arm)
                                        for at in R_(12.0, s6 + 0.001):   # arm top <= strip bottom (no overlap)
                                            A08 = (18 - XN) * 6 + (XN - ax) * (at - 10)
                                            if A08 < 30 or A08 > 95:
                                                continue
                                            P = dict(y05=y05, fx=fx, s6=s6, dxb=dxb, dy=dy,
                                                     ax=ax, at=at, xc2=xc2, bx=bx, by=by)
                                            r = check(P, need_cover=False)
                                            if r is None:
                                                continue
                                            tried += 1
                                            keff = (round(r["min"], 2), -round(r["ratio"], 3))
                                            if besteff is None or keff > besteff[0]:
                                                besteff = (keff, dict(P), r)
                                            if r["cover"] >= 259:
                                                # minimize ratio, tiebreak higher min
                                                kb = (-round(r["ratio"], 3), round(r["min"], 2))
                                                if best is None or kb > best[0]:
                                                    best = (kb, dict(P), r)
    print(f"[C1-C3 valid={tried}]")
    return best, besteff


def verify(P):
    """shapely re-check all 5 constraints, return dict."""
    R = rects(P)
    pieces = {a: unary_union([box(*R[a][0]), box(*R[a][1])]) for a in R}
    apts = ["05", "06", "08", "10"]
    out = {}
    c1 = all(pieces[a].geom_type == "Polygon" and len(pieces[a].exterior.coords) - 1 <= 10
             and not pieces[a].interiors for a in apts)
    c2 = True
    for a in apts:
        if pieces[a].boundary.buffer(0.10).intersection(FAC[a]).length <= 0.6:
            c2 = False
        for b in apts:
            if b != a and pieces[a].boundary.buffer(0.10).intersection(FAC[b]).length >= 0.5:
                c2 = False
    ov = sum(pieces[a].intersection(pieces[b]).area for a, b in itertools.combinations(apts, 2))
    cov = unary_union(list(pieces.values())).area
    areas = {a: pieces[a].area for a in apts}
    mn, mx = min(areas.values()), max(areas.values())
    out.update(pieces=pieces, c1=c1, c2=c2, ov=ov, cov=cov, areas=areas, ratio=mx / mn, mn=mn)
    return out


def report(P, label):
    print(f"\n===== {label} =====")
    v = verify(P)
    apts = ["05", "06", "08", "10"]
    print("params:", P)
    print(f"cover={v['cov']:.2f} ({100*v['cov']/288:.1f}%)  overlap={v['ov']:.4f}  "
          f"ratio={v['ratio']:.3f}  min={v['mn']:.2f}")
    for a in apts:
        p = v["pieces"][a]
        coords = [(round(x, 1), round(y, 1)) for x, y in p.exterior.coords]
        sc = p.boundary.buffer(0.10).intersection(FAC[a]).length
        oth = {b: round(p.boundary.buffer(0.10).intersection(FAC[b]).length, 3) for b in apts if b != a}
        print(f"apt {a}: area={p.area:.2f} verts={len(coords)-1} self={sc:.2f} others={oth}")
        print(f"        coords={coords}")
    print("--- constraint checks ---")
    print(f"C1 single/ortho/<=10v : {'PASS' if v['c1'] else 'FAIL'}")
    print(f"C2 facade contacts    : {'PASS' if v['c2'] else 'FAIL'}")
    print(f"C3 disjoint (ov={v['ov']:.4f}): {'PASS' if v['ov'] < 0.5 else 'FAIL'}")
    print(f"C4 cover>=259 ({v['cov']:.1f}) : {'PASS' if v['cov'] >= 259 else 'FAIL'}")
    ar = list(v["areas"].values())
    print(f"C5 ratio<=1.45&min>=55: {'PASS' if (max(ar)/min(ar) <= 1.45 and min(ar) >= 55) else 'FAIL'}")
    print(f"   (relaxed min>=50)  : {'PASS' if min(ar) >= 50 else 'FAIL'}  "
          f"min={min(ar):.1f} ratio={max(ar)/min(ar):.3f}")


if __name__ == "__main__":
    best, besteff = search()
    if best is not None:
        report(best[1], "BEST (all 5 hard constraints incl cover>=259)")
    else:
        print("\nNo config satisfies C1-C4 with cover>=259.")
    if besteff is not None:
        report(besteff[1], "BEST-EFFORT (max min-area, cover may be <259)")
