"""taxivm.py - a small stack-machine assembler that targets the Taxi esolang.

taximap.py gives legal driving directions between locations; this module turns a
readable instruction stream into Taxi statements and keeps the taxi fuelled.

VM model
--------
* Data stack = Narrow Path Park (LIFO), the control-flow "home".
* A permanent "coin" passenger rides in the taxi tagged to Sunny Skies Park, so
  nearly every drive carries >=2 passengers and earns more fare than the gas it
  burns.  `fuel()` drops the coin at Sunny Skies (realising its fare), re-picks
  it, and tops the tank up at Zoom Zoom (cheapest gas).
* Every `Switch to plan [L]` is preceded by a drive to HOME, and every label is
  entered with the taxi at HOME, so all routes are statically computable.  A
  conditional `Switch ... if` cannot be preceded by a drive, so it jumps to a
  per-site trampoline that first drives HOME and then switches to the real label.

Values are Taxi passengers: numbers (doubles) or strings.  Bytes flow in as one
decimal integer per line at the Post Office (the launcher frames stdin that way),
and out as characters (Charboil Grill turns a code into a 1-char string).
"""

import taximap as M

HOME = "Narrow Path Park"        # data stack (LIFO)
COIN_BANK = "Sunny Skies Park"   # fare coin realised here
GAS = "Zoom Zoom"
TRASH = "Riverview Bridge"
PO = "Post Office"
BABEL = "The Babelfishery"
CHAR = "Charboil Grill"
WDEP = "Writer's Depot"
SNUM = "Starchild Numerology"
ADD = "Addition Alley"
SUB = "What's The Difference"
EQNUM = "Equal's Corner"
KAT = "KonKat's"
GARAGE = "Taxi Garage"


class Asm:
    def __init__(self):
        self.lines = []
        self.cur = GARAGE
        self.tramps = []       # (tname, from_loc, target_label)
        self.fails = []        # (label, message)
        self._t = 0
        self.miles = 0.0       # miles since the last refuel (for auto-fuel)
        self._autofuel_on = False
        self.THRESH = 120.0    # refuel before the ~360-mile tank empties

    # ---- primitive emitters ------------------------------------------
    def raw(self, s):
        self.lines.append(s)

    def drive(self, dest):
        if dest == self.cur:
            return
        miles, spec = M.find_route(self.cur, dest)
        self.lines.append("Go to %s: %s." % (dest, M.fmt_route(spec)))
        self.cur = dest
        self.miles += miles

    def _autofuel(self):
        """Refuel at a safe point (only the coin aboard) if the tank is getting
        low.  Called at the clean end of VM ops."""
        if self._autofuel_on and self.miles >= self.THRESH:
            self.fuel()

    def wait(self, value, where):
        self.lines.append('%s is waiting at %s.' % (value, where))

    def pickup(self, going_to):
        self.lines.append("Pickup a passenger going to %s." % going_to)

    # ---- fuel / coin --------------------------------------------------
    def make_coin(self):
        self.wait('1', SNUM)
        self.drive(SNUM)
        self.pickup(COIN_BANK)       # coin rides, tagged to Sunny Skies
        self.drive(HOME)
        self.miles = 0.0
        self._autofuel_on = True

    def fuel(self):
        """Realise the coin's fare and top up.  Call at loop boundaries with no
        other passengers aboard."""
        self.drive(COIN_BANK)        # drop coin -> pays fare
        self.pickup(COIN_BANK)       # pick it back up
        self.drive(GAS)              # refuel on the credits just earned
        self.drive(HOME)
        self.miles = 0.0

    # ---- string quoting ----------------------------------------------
    @staticmethod
    def _wdep_literal(chunk):
        # writers_depot un-escapes \\ \n \r \t only; source lines are joined
        # without newlines, so real control chars must be written as escapes.
        out = []
        for c in chunk:
            if c == '\\':
                out.append('\\\\')
            elif c == '\n':
                out.append('\\n')
            elif c == '\r':
                out.append('\\r')
            elif c == '\t':
                out.append('\\t')
            else:
                out.append(c)
        return '"' + ''.join(out) + '"'   # delimit with " (chunk has no quotes)

    # ---- stack pushes -------------------------------------------------
    def push_empty(self):
        """Push the empty string.  (An empty Writer's Depot literal would be the
        token "" , and the Taxi parser's get_token returns "" for that and then
        stops parsing, so build "" by trimming a space instead.)"""
        self.wait(self._wdep_literal(" "), WDEP)
        self.drive(WDEP)
        self.pickup("Tom's Trims")
        self.drive("Tom's Trims")     # " " -> ""
        self.pickup(HOME)
        self.drive(HOME)
        self._autofuel()

    def push_wdep(self, chunk):
        """Push a string literal containing no ' or " onto the stack."""
        if chunk == "":
            self.push_empty()
            return
        self.wait(self._wdep_literal(chunk), WDEP)
        self.drive(WDEP)
        self.pickup(HOME)
        self.drive(HOME)

    def push_char_code(self, code):
        """Push the 1-char string for a byte code (used for ' and ")."""
        self.wait(str(code), SNUM)
        self.drive(SNUM)
        self.pickup(CHAR)
        self.drive(CHAR)             # number -> 1-char string
        self.pickup(HOME)
        self.drive(HOME)

    def pushnum(self, n):
        self.wait(str(n), SNUM)
        self.drive(SNUM)
        self.pickup(HOME)
        self.drive(HOME)

    # ---- output -------------------------------------------------------
    def outstr(self):
        """Pop a string from the stack and print it at the Post Office.
        Every op starts and ends at HOME so that `pickup` always acts on the
        stack; outstr therefore returns to HOME when done."""
        self.pickup(PO)              # pop TOS (at HOME), tag to Post Office
        self.drive(PO)               # printed exactly
        self.drive(HOME)
        self._autofuel()

    def out_text(self, s):
        """Print fixed text, splitting out the quote characters.  Refuels every
        few pieces so long preambles do not run the tank dry."""
        run = []
        for c in s:
            if c in ("'", '"'):
                if run:
                    self.push_wdep(''.join(run)); self.outstr(); run = []; self._autofuel()
                self.push_char_code(39 if c == "'" else 34); self.outstr(); self._autofuel()
            else:
                run.append(c)
        if run:
            self.push_wdep(''.join(run)); self.outstr(); self._autofuel()

    # ---- input --------------------------------------------------------
    def inbyte(self):
        """Read one framed line, convert to a number, push it on the stack."""
        self.drive(PO)
        self.pickup(BABEL)           # read a line -> string, tag to Babelfishery
        self.drive(BABEL)            # string -> number
        self.pickup(HOME)
        self.drive(HOME)
        self._autofuel()

    def dup(self):
        """Duplicate TOS using the Cyclone."""
        self.pickup("Cyclone")
        self.drive("Cyclone")        # 1 in -> original + 1 copy out
        self.pickup(HOME)
        self.pickup(HOME)
        self.drive(HOME)
        self._autofuel()

    def print_char_pop(self):
        """Pop a numeric byte code and print it as a character."""
        self.pickup(CHAR)            # pop TOS (at HOME), tag Charboil
        self.drive(CHAR)             # number -> 1-char string
        self.pickup(PO)
        self.drive(PO)
        self.drive(HOME)
        self._autofuel()

    # ---- scratch benches ---------------------------------------------
    def to_bench(self, bench):
        """Pop TOS and stash it in a single-slot bench; return to HOME."""
        self.pickup(bench)
        self.drive(bench)
        self.drive(HOME)

    def from_bench(self, bench):
        """Push the value stashed in a bench back onto the stack."""
        self.drive(bench)
        self.pickup(HOME)
        self.drive(HOME)

    # ---- string / value ops ------------------------------------------
    def drop(self):
        """Pop TOS and discard it (Riverview Bridge)."""
        self.pickup(TRASH)
        self.drive(TRASH)
        self.drive(HOME)

    JOY = "Joyless Park"

    def concat2(self):
        """Pop a (top) and b (below); push b concatenated with a.
        Uses Joyless Park as a one-slot temp (so Bird's Bench stays free)."""
        self.pickup(self.JOY)              # pop a (TOS) at HOME, tag Joyless
        self.drive(self.JOY)               # stash a in Joyless
        self.drive(HOME)                   # back to the stack
        self.pickup(KAT)                   # pop b, tag KonKat (b is first)
        self.drive(self.JOY)               # fetch a
        self.pickup(KAT)                   # a second
        self.drive(KAT)                    # KonKat: b + a
        self.pickup(HOME)
        self.drive(HOME)
        self._autofuel()

    # ---- arithmetic (numbers) ----------------------------------------
    def addk(self, k):
        """TOS <- TOS + k."""
        self.pickup(ADD)
        self.wait(str(k), SNUM)
        self.drive(SNUM)
        self.pickup(ADD)
        self.drive(ADD)
        self.pickup(HOME)
        self.drive(HOME)
        self._autofuel()

    def mulk(self, k):
        """TOS <- TOS * k."""
        MUL = "Multiplication Station"
        self.pickup(MUL)
        self.wait(str(k), SNUM)
        self.drive(SNUM)
        self.pickup(MUL)
        self.drive(MUL)
        self.pickup(HOME)
        self.drive(HOME)
        self._autofuel()

    def add2(self):
        """Pop a and b, push a+b."""
        self.pickup(ADD)
        self.pickup(ADD)
        self.drive(ADD)
        self.pickup(HOME)
        self.drive(HOME)
        self._autofuel()

    def floordiv_k(self, k):
        """TOS <- trunc(TOS / k)  (floor for non-negative values)."""
        DIV = "Divide and Conquer"
        TRUNC = "Trunkers"
        self.pickup(DIV)
        self.wait(str(k), SNUM)
        self.drive(SNUM)
        self.pickup(DIV)
        self.drive(DIV)              # TOS / k (float)
        self.pickup(TRUNC)
        self.drive(TRUNC)            # truncate to integer
        self.pickup(HOME)
        self.drive(HOME)
        self._autofuel()

    def swap(self):
        """Swap the top two stack items: [.., b, a] -> [.., a, b]."""
        self.to_bench("Bird's Bench")     # stash a (returns to HOME)
        self.pickup(self.JOY)             # pop b, tag Joyless
        self.drive(self.JOY)              # stash b
        self.drive("Bird's Bench")        # fetch a
        self.pickup(HOME)                 # push a
        self.drive(HOME)
        self.drive(self.JOY)              # fetch b
        self.pickup(HOME)                 # push b
        self.drive(HOME)
        self._autofuel()

    def push_literal_str(self, s):
        """Build an arbitrary string literal (quotes allowed) on the stack."""
        first = True
        run = []

        def flush():
            nonlocal first
            if not run:
                return
            self.push_wdep(''.join(run))
            if not first:
                self.concat2()
            first = False
            run.clear()

        for c in s:
            if c in ("'", '"'):
                flush()
                self.push_char_code(39 if c == "'" else 34)
                if not first:
                    self.concat2()
                first = False
            else:
                run.append(c)
        flush()
        if first:          # empty string
            self.push_wdep("")

    def s2n(self):
        """Pop a string, push its numeric value (Babelfishery)."""
        self.pickup(BABEL)
        self.drive(BABEL)
        self.pickup(HOME)
        self.drive(HOME)

    def n2s(self):
        """Pop a number, push its string form (Babelfishery)."""
        self.pickup(BABEL)
        self.drive(BABEL)
        self.pickup(HOME)
        self.drive(HOME)

    def ord_op(self):
        """Pop a 1-char string, push its byte code (Charboil Grill)."""
        self.pickup(CHAR)
        self.drive(CHAR)
        self.pickup(HOME)
        self.drive(HOME)

    def chr_op(self):
        """Pop a number, push the 1-char string (Charboil Grill)."""
        self.pickup(CHAR)
        self.drive(CHAR)
        self.pickup(HOME)
        self.drive(HOME)

    # ---- lookahead register (Rob's Rest holds the current byte) -------
    ROB = "Rob's Rest"

    def rc_init(self):
        """Seed the lookahead register with the first framed byte."""
        self.inbyte()
        self.pickup(self.ROB)
        self.drive(self.ROB)         # current byte now parked at Rob's Rest
        self.drive(HOME)

    def rc_advance(self):
        """Discard the current byte and read the next framed byte into Rob's."""
        self.drive(self.ROB)
        self.pickup(TRASH)           # remove the old current byte
        self.drive(TRASH)
        self.drive(PO)
        self.pickup(BABEL)           # read a line -> string
        self.drive(BABEL)            # -> number
        self.pickup(self.ROB)
        self.drive(self.ROB)         # park as the new current byte
        self.drive(HOME)
        self._autofuel()

    def rc_get(self):
        """Push a copy of the current byte onto the stack (non-destructive)."""
        self.drive(self.ROB)
        self.pickup("Cyclone")       # take the current byte out
        self.drive("Cyclone")        # -> two copies
        self.pickup(self.ROB)        # one copy back to the register
        self.pickup(HOME)            # the other to the stack
        self.drive(self.ROB)
        self.drive(HOME)
        self._autofuel()

    # ---- control flow -------------------------------------------------
    def label(self, name):
        self.raw("[%s]" % name)
        self.cur = HOME

    def loop_label(self, name):
        """A label that is a loop-back target: always refuel on entry, because the
        body runs many times at runtime even though it is generated once."""
        self.raw("[%s]" % name)
        self.cur = HOME
        if self._autofuel_on:
            self.fuel()

    def jmp(self, name):
        self.drive(HOME)
        self.raw('Switch to plan "%s".' % name)

    def _tramp(self, target):
        self._t += 1
        t = "t%d_%s" % (self._t, target)
        self.tramps.append((t, self.cur, target))
        return t

    def bne_num(self, n, label):
        """Pop TOS (a number); jump to label if TOS != n, else fall through.
        Uses Equal's Corner; clears its outgoing on the equal path."""
        self.pickup(EQNUM)           # pop TOS, tag to Equal's Corner
        self.wait(str(n), SNUM)
        self.drive(SNUM)
        self.pickup(EQNUM)           # second operand
        self.drive(EQNUM)            # equal -> outgoing value, else none
        t = self._tramp(label)
        self.raw('Switch to plan "%s" if no one is waiting.' % t)   # jump if NOT equal
        # fall-through: equal -> clear the leftover outgoing value
        self.pickup(TRASH)
        self.drive(TRASH)
        self.drive(HOME)
        self._autofuel()

    def beq_num(self, n, label):
        """Pop TOS; jump to label if TOS == n, else fall through."""
        skip = "skip%d" % (self._t + 1)
        self._t += 1
        self.bne_num(n, skip)        # not-equal -> skip (fall through target)
        self.jmp(label)              # equal path reaches here
        self.label(skip)

    def bge_num(self, n, label):
        """Pop TOS (a number); jump to label if TOS >= n, else fall through.
        Uses Magic Eight (TOS < n -> outgoing TOS, else none)."""
        ME = "Magic Eight"
        self.pickup(ME)              # pop TOS, tag to Magic Eight (first operand)
        self.wait(str(n), SNUM)
        self.drive(SNUM)
        self.pickup(ME)              # n as second operand
        self.drive(ME)               # TOS<n -> outgoing TOS, else none
        t = self._tramp(label)
        self.raw('Switch to plan "%s" if no one is waiting.' % t)   # jump if TOS>=n
        # fall-through: TOS<n -> clear the leftover outgoing value
        self.pickup(TRASH)
        self.drive(TRASH)
        self.drive(HOME)
        self._autofuel()

    def blt_num(self, n, label):
        """Pop TOS; jump to label if TOS < n, else fall through."""
        skip = "skip%d" % (self._t + 1)
        self._t += 1
        self.bge_num(n, skip)        # >=n -> skip
        self.jmp(label)              # <n path
        self.label(skip)

    def bne_str(self, literal, label):
        """Pop TOS (a string); jump to label if it differs from literal.
        Uses Crime Lab (string equality)."""
        self.pickup("Crime Lab")           # pop TOS, tag to Crime Lab
        if literal == "":
            self.wait(self._wdep_literal(" "), WDEP)
            self.drive(WDEP)
            self.pickup("Tom's Trims")
            self.drive("Tom's Trims")      # " " -> "" (empty literal token is illegal)
            self.pickup("Crime Lab")
        else:
            self.wait(self._wdep_literal(literal), WDEP)
            self.drive(WDEP)
            self.pickup("Crime Lab")       # literal as second operand
        self.drive("Crime Lab")            # all-equal -> outgoing value, else none
        t = self._tramp(label)
        self.raw('Switch to plan "%s" if no one is waiting.' % t)   # jump if differ
        # equal path: clear the leftover outgoing value
        self.pickup(TRASH)
        self.drive(TRASH)
        self.drive(HOME)
        self._autofuel()

    # ---- failure ------------------------------------------------------
    def fail(self, msg):
        """Abort: print the message (no end marker) and drive to the garage."""
        self._t += 1
        lab = "fail%d" % self._t
        self.fails.append((lab, msg))
        self.jmp(lab)

    # ---- termination --------------------------------------------------
    def terminate(self):
        self.drive(GARAGE)           # taxi_garage arrival -> exit(0)

    def finalize(self):
        """Emit trampolines and fail blocks after the garage call (dead code)."""
        for t, frm, target in self.tramps:
            self.lines.append("[%s]" % t)
            self.cur = frm
            self.drive(HOME)
            self._autofuel()
            self.lines.append('Switch to plan "%s".' % target)
        for lab, msg in self.fails:
            self.lines.append("[%s]" % lab)
            self.cur = HOME
            self.out_text("json2dir: " + msg + "\n")
            self.terminate()
        return "\n".join(self.lines) + "\n"
