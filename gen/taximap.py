"""The Townsburg road map and the taxi's driving rules, copied from the reference
interpreter (taxi.cpp 1.7, road_map / node / taxi classes), plus a route finder that
produces "Go to" directions the interpreter will follow exactly."""

import heapq
import math

INTER = {
    1: (424, 145), 2: (596, 138), 3: (1120, 115), 4: (1285, 112), 5: (1370, 108),
    6: (1295, 84), 7: (1094, 78), 8: (355, 222), 9: (215, 376), 10: (482, 468),
    11: (379, 638), 12: (246, 529), 13: (291, 783), 14: (209, 916), 15: (501, 910),
    16: (50, 639), 17: (739, 557), 18: (702, 374), 19: (875, 740), 20: (991, 599),
    21: (1003, 825), 22: (1241, 963), 23: (1155, 709), 24: (1382, 716), 25: (1118, 683),
    26: (1132, 634), 27: (1437, 617), 28: (1171, 503), 29: (1061, 407), 30: (1061, 445),
    31: (1197, 414), 32: (1227, 313), 33: (1372, 314), 34: (1160, 920),
}
CORNER = {1: (510, 52), 2: (108, 492), 3: (682, 442), 4: (818, 710), 5: (1106, 724), 6: (1181, 847)}
DEST = {
    "Taxi Garage": (1246, 639), "Post Office": (910, 695), "Heisenberg's": (1372, 237),
    "Starchild Numerology": (278, 917), "Writer's Depot": (164, 433),
    "The Babelfishery": (949, 879), "Charboil Grill": (152, 702), "Addition Alley": (652, 211),
    "Multiplication Station": (1286, 888), "Divide and Conquer": (1117, 311),
    "What's The Difference": (176, 153), "KonKat's": (1262, 195), "Magic Eight": (797, 666),
    "Riverview Bridge": (888, 127), "Sunny Skies Park": (456, 412), "Joyless Park": (1361, 424),
    "Narrow Path Park": (1162, 78), "Auctioneer School": (246, 856),
    "Little League Field": (1267, 711), "Tom's Trims": (951, 648), "Trunkers": (692, 543),
    "Rounders Pub": (1063, 482), "Fueler Up": (1155, 557), "Go More": (258, 764),
    "Zoom Zoom": (546, 52), "Knots Landing": (1426, 314), "Bird's Bench": (197, 653),
    "Rob's Rest": (323, 473), "Firemouth Grill": (770, 440), "Cyclone": (272, 314),
    "Chop Suey": (1374, 169), "The Underground": (1182, 462), "Collator Express": (424, 351),
    "Crime Lab": (1031, 796), "Equal's Corner": (210, 976),
}
GAS = {"Fueler Up": 1.92, "Go More": 1.75, "Zoom Zoom": 1.45}

PIXELS_PER_MILE = 264.0


class Node:
    def __init__(self, name, xy):
        self.name = name
        self.x, self.y = xy
        self.nb = []  # list of [first, second]

    def __repr__(self):
        return self.name


NODES = {}
for k, v in INTER.items():
    NODES["i%d" % k] = Node("i%d" % k, v)
for k, v in CORNER.items():
    NODES["c%d" % k] = Node("c%d" % k, v)
for k, v in DEST.items():
    NODES[k] = Node(k, v)


def street(*names):
    p = None
    for nm in names:
        n = NODES[nm]
        if p is not None:
            p.nb[-1][1] = n
            n.nb.append([p, None])
        else:
            n.nb.append([None, None])
        p = n


street("Zoom Zoom", "c1", "i1", "i8", "Cyclone", "i9", "Writer's Depot", "c2", "i16")
street("What's The Difference", "i1", "i2", "Riverview Bridge", "i3", "i4", "i5")
street("i7", "i3")
street("i7", "Narrow Path Park", "i6")
street("i2", "Addition Alley")
street("i9", "i10", "Trunkers", "i17")
street("Rob's Rest", "i12", "Bird's Bench")
street("i12", "i11")
street("i16", "Charboil Grill", "Go More", "i13", "i15")
street("i8", "Collator Express", "Sunny Skies Park", "i10", "i11", "i13", "Auctioneer School", "i14", "Equal's Corner")
street("i14", "Starchild Numerology", "i15")
street("i29", "i30", "Rounders Pub")
street("i29", "i31", "Joyless Park")
street("i28", "i27")
street("i27", "i24", "Multiplication Station", "i22")
street("i23", "Little League Field", "i24")
street("i26", "Taxi Garage")
street("Divide and Conquer", "i32", "i33", "Knots Landing")
street("i18", "c3", "i17", "Magic Eight", "c4", "i19", "i21", "i34", "i22")
street("i23", "c6", "i34")
street("i18", "Firemouth Grill", "i20", "i25", "i23")
street("i20", "Tom's Trims", "Post Office", "i19")
street("The Babelfishery", "i21", "Crime Lab", "c5", "i25", "i26", "Fueler Up", "i28", "The Underground", "i31", "i32", "KonKat's", "i4", "i6")
street("i5", "Chop Suey", "Heisenberg's", "i33")


def dist(a, b):
    return math.hypot(a.x - b.x, a.y - b.y) / PIXELS_PER_MILE


def get_dir(node, d):
    for f, s in node.nb:
        for n in (f, s):
            if n is None:
                continue
            if (d == "n" and n.y < node.y) or (d == "s" and n.y > node.y) or \
               (d == "e" and n.x > node.x) or (d == "w" and n.x < node.x):
                return n
    return None


def straight(node, frm):
    for f, s in node.nb:
        if f is frm:
            return s
        if s is frm:
            return f
    return None


def can_turn(node, d, prev):
    for f, s in node.nb:
        if f is not prev and s is not prev:
            for n in (f, s):
                if n is None:
                    continue
                r = (node.x - prev.x) * (n.y - prev.y) + (node.y - prev.y) * (prev.x - n.x)
                if d == "l" and r < 0:
                    return n
                if d == "r" and r > 0:
                    return n
    return None


class Fail(Exception):
    pass


def drive(state):
    cur, nxt, miles = state
    if nxt is None:
        raise Fail()
    t = straight(nxt, cur)
    return (nxt, t, miles + dist(cur, nxt)), cur


def take_turn(state, num, d):
    t = None
    for _ in range(num):
        state, prev = drive(state)
        while True:
            t = can_turn(state[0], d, prev)
            if t is not None:
                break
            state, prev = drive(state)
            if state[2] > 100:
                raise Fail()
    return (state[0], t, state[2])


def finish(state, dest):
    while state[0] is not dest:
        state, _ = drive(state)
        if state[2] > 100:
            raise Fail()
    return state[2]


def simulate(src, dest, spec):
    """spec: (dir, [(num, 'l'|'r'), ...]) -> miles, raising Fail if illegal."""
    a = NODES[src]
    d, turns = spec
    st = (a, get_dir(a, d), 0.0)
    for num, lr in turns:
        st = take_turn(st, num, lr)
    return finish(st, NODES[dest])


ORD = {1: "1st", 2: "2nd", 3: "3rd"}


def fmt_route(spec):
    d, turns = spec
    words = {"n": "north", "s": "south", "e": "east", "w": "west"}[d]
    parts = []
    for num, lr in turns:
        parts.append("%s %s" % (ORD.get(num, "%dth" % num), "left" if lr == "l" else "right"))
    if parts:
        return words + " " + ", ".join(parts)
    return words


def find_route(src, dest):
    """Cheapest legal directions from src to dest: (miles, spec)."""
    if src == dest:
        return 0.0, ("n", [])
    a, b = NODES[src], NODES[dest]
    best = None
    pq = []
    cnt = 0
    seen = {}
    for d in "nsew":
        n = get_dir(a, d)
        if n is None:
            continue
        heapq.heappush(pq, (0.0, cnt, (a, n, 0.0), (d, [])))
        cnt += 1
    while pq:
        miles, _, st, spec = heapq.heappop(pq)
        if best is not None and miles >= best[0]:
            break
        key = (st[0].name, st[1].name if st[1] else None)
        if key in seen and seen[key] <= miles:
            continue
        seen[key] = miles
        try:
            m = finish(st, b)
            if best is None or m < best[0] or (m == best[0] and len(spec[1]) < len(best[1][1])):
                best = (m, spec)
        except Fail:
            pass
        if len(spec[1]) >= 12:
            continue
        for num in range(1, 6):
            for lr in "lr":
                try:
                    st2 = take_turn(st, num, lr)
                except Fail:
                    continue
                heapq.heappush(pq, (st2[2], cnt, st2, (spec[0], spec[1] + [(num, lr)])))
                cnt += 1
    if best is None:
        raise Fail("no route %s -> %s" % (src, dest))
    # double-check
    assert abs(simulate(src, dest, best[1]) - best[0]) < 1e-9
    return best


if __name__ == "__main__":
    import sys
    names = sys.argv[1:] or ["Cyclone", "Writer's Depot", "Collator Express", "Sunny Skies Park",
                             "Post Office", "Zoom Zoom", "Riverview Bridge", "Starchild Numerology",
                             "Charboil Grill", "Equal's Corner", "Magic Eight"]
    for s in names:
        row = []
        for t in names:
            m, sp = find_route(s, t)
            row.append("%5.2f" % m)
        print("%-22s %s" % (s[:22], " ".join(row)))
