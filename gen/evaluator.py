"""The json2dir evaluator, written against the Taxi stack VM (taxivm.Asm) and
compiled to Taxi routes by that assembler.  This file is the *readable source*;
`python3 evaluator.py > json2dir.taxi` emits the Taxi program.

Transport: the launcher frames stdin as one decimal byte per line, ending with a
256 sentinel.  The current byte is held in the lookahead register (Rob's Rest).

Memory: Narrow Path Park is the stack.  At the bottom sits a sentinel (byte 0x01,
which can never appear in a JSON string); above it, one *quoted* path-prefix per
open object (root = "", deeper levels end in "/").  A member's shell path body is
prefix + quoted-name, so names are escaped once, as they are scanned, and the
whole path prints as a single stack string.
"""

import sys
from taxivm import Asm

PREAMBLE = (
    "set -eu\n"
    "_j2d_fail() { printf 'json2dir: cannot create %s\\n' \"$1\" >&2; exit 1; }\n"
    "_j2d_clear() {\n"
    "  if [ -L \"$1\" ]; then rm -f -- \"$1\" || _j2d_fail \"$1\"\n"
    "  elif [ -d \"$1\" ]; then printf 'json2dir: a directory is in the way: %s\\n' \"$1\" >&2; exit 1\n"
    "  elif [ -e \"$1\" ]; then rm -f -- \"$1\" || _j2d_fail \"$1\"\n"
    "  fi\n"
    "}\n"
    "_j2d_dir() {\n"
    "  if [ -L \"$1\" ] || { [ -e \"$1\" ] && [ ! -d \"$1\" ]; }; then rm -f -- \"$1\" || _j2d_fail \"$1\"; fi\n"
    "  if [ ! -d \"$1\" ]; then mkdir -- \"$1\" || _j2d_fail \"$1\"; fi\n"
    "}\n"
    "_j2d_file() {\n"
    "  _j2d_clear \"$1\"\n"
    "  _j2d_path=$1; shift\n"
    "  {\n"
    "    printf '%s' \"$1\"; shift\n"
    "    for _j2d_part in \"$@\"; do printf '\\000%s' \"$_j2d_part\"; done\n"
    "  } > \"$_j2d_path\" || _j2d_fail \"$_j2d_path\"\n"
    "}\n"
    "_j2d_script() { _j2d_file \"$@\"; chmod a+x -- \"$1\" || _j2d_fail \"$1\"; }\n"
    "_j2d_link() { _j2d_clear \"$1\"; ln -s -- \"$2\" \"$1\" || _j2d_fail \"$1\"; }\n"
)

WS = (32, 9, 10, 13)
SENT = chr(1)             # stack-bottom sentinel (never a valid JSON string byte)
QUOTE_LIT = "'\\''"       # the 4 shell chars  ' \ ' '  for a literal single quote


def build():
    a = Asm()

    def lab():
        a._t += 1
        return a._t

    # ---- small reusable pieces ---------------------------------------
    def skipws():
        i = lab()
        top, end = "ws%d" % i, "wsx%d" % i
        a.loop_label(top)
        for w in WS:
            j = lab()
            nxt = "wsn%d" % j
            a.rc_get(); a.bne_num(w, nxt)
            a.rc_advance(); a.jmp(top)
            a.label(nxt)
        a.label(end)

    def expect(code, msg):
        i = lab(); ok = "ok%d" % i
        a.rc_get(); a.beq_num(code, ok)
        a.fail(msg)
        a.label(ok)

    # emit_utf8: codepoint on stack -> UTF-8 bytes, each passed to sink().
    # The codepoint is parked in Bird's Bench between bytes, so when sink() runs
    # only the one working byte is on the stack (above any accumulator).
    def emit_utf8(sink):
        i = lab()
        u1, u2, u3, done = "u1_%d" % i, "u2_%d" % i, "u3_%d" % i, "ud_%d" % i
        leads = {1: 0, 2: 0xC0, 3: 0xE0, 4: 0xF0}

        def gen(w):
            a.to_bench("Bird's Bench")            # stash cp
            for idx in range(w):
                a.from_bench("Bird's Bench")      # cp on stack
                last = idx == w - 1
                if not last:
                    a.dup(); a.to_bench("Bird's Bench")   # keep a copy stashed
                shift = 6 * (w - 1 - idx)
                prefix = leads[w] if idx == 0 else 0x80
                if shift:
                    a.floordiv_k(1 << shift)
                if idx > 0:                       # continuation byte: value % 64
                    a.dup(); a.floordiv_k(64); a.mulk(-64); a.add2()
                a.addk(prefix)
                sink()

        a.dup(); a.blt_num(0x80, u1)
        a.dup(); a.blt_num(0x800, u2)
        a.dup(); a.blt_num(0x10000, u3)
        gen(4); a.jmp(done)
        a.label(u3); gen(3); a.jmp(done)
        a.label(u2); gen(2); a.jmp(done)
        a.label(u1); gen(1)
        a.label(done)

    # scan_string(sink): cur == opening '"'.  Decode the JSON string, calling
    # sink() once per decoded byte (byte on stack top).  Leaves cur after the
    # closing quote.
    def scan_string(sink):
        i = lab()
        sloop, sdone, sesc = "sl%d" % i, "sd%d" % i, "se%d" % i
        a.rc_advance()                      # consume opening quote
        a.loop_label(sloop)
        a.rc_get(); a.beq_num(256, a_fail("unterminated string"))
        a.rc_get(); a.beq_num(34, sdone)    # closing quote
        a.rc_get(); a.blt_num(32, a_fail("invalid character in a string"))
        a.rc_get(); a.beq_num(92, sesc)     # backslash
        # normal byte: ASCII, or a strict-UTF-8 multi-byte sequence
        badutf = a_fail("invalid UTF-8")

        def lead_and_advance():
            a.rc_get(); sink(); a.rc_advance()

        def cont(lo, hi):
            a.rc_get(); a.blt_num(lo, badutf)       # continuation < lo
            a.rc_get(); a.bge_num(hi + 1, badutf)   # continuation > hi
            a.rc_get(); sink(); a.rc_advance()

        m = lab()
        ascii_, mb2, mb3, mb4 = "as%d" % m, "m2_%d" % m, "m3_%d" % m, "m4_%d" % m
        e0, ed, f0, f4 = "e0_%d" % m, "ed_%d" % m, "f0_%d" % m, "f4_%d" % m
        a.rc_get(); a.blt_num(0x80, ascii_)         # 0x00..0x7F -> ASCII
        a.rc_get(); a.blt_num(0xC2, badutf)         # 0x80..0xC1 -> invalid
        a.rc_get(); a.blt_num(0xE0, mb2)            # 0xC2..0xDF -> 2 bytes
        a.rc_get(); a.blt_num(0xF0, mb3)            # 0xE0..0xEF -> 3 bytes
        a.rc_get(); a.blt_num(0xF5, mb4)            # 0xF0..0xF4 -> 4 bytes
        a.jmp(badutf)                               # 0xF5..0xFF -> invalid
        a.label(ascii_); a.rc_get(); sink(); a.rc_advance(); a.jmp(sloop)
        a.label(mb2); lead_and_advance(); cont(0x80, 0xBF); a.jmp(sloop)
        a.label(mb3)
        a.rc_get(); a.beq_num(0xE0, e0)
        a.rc_get(); a.beq_num(0xED, ed)
        lead_and_advance(); cont(0x80, 0xBF); cont(0x80, 0xBF); a.jmp(sloop)
        a.label(e0); lead_and_advance(); cont(0xA0, 0xBF); cont(0x80, 0xBF); a.jmp(sloop)
        a.label(ed); lead_and_advance(); cont(0x80, 0x9F); cont(0x80, 0xBF); a.jmp(sloop)
        a.label(mb4)
        a.rc_get(); a.beq_num(0xF0, f0)
        a.rc_get(); a.beq_num(0xF4, f4)
        lead_and_advance(); cont(0x80, 0xBF); cont(0x80, 0xBF); cont(0x80, 0xBF); a.jmp(sloop)
        a.label(f0); lead_and_advance(); cont(0x90, 0xBF); cont(0x80, 0xBF); cont(0x80, 0xBF); a.jmp(sloop)
        a.label(f4); lead_and_advance(); cont(0x80, 0x8F); cont(0x80, 0xBF); cont(0x80, 0xBF); a.jmp(sloop)
        # --- escape ---
        a.label(sesc)
        a.rc_advance()                      # consume backslash
        simple = {34: 34, 92: 92, 47: 47, 98: 8, 102: 12, 110: 10, 114: 13, 116: 9}
        for ec, byte in simple.items():
            j = lab(); nx = "esn%d" % j
            a.rc_get(); a.bne_num(ec, nx)
            a.pushnum(byte); sink(); a.rc_advance(); a.jmp(sloop)
            a.label(nx)
        # \u
        k = lab(); nu = "esu%d" % k
        a.rc_get(); a.bne_num(117, nu)
        scan_u(sink); a.jmp(sloop)
        a.label(nu)
        a.jmp(a_fail("invalid escape in a string"))
        a.label(sdone)
        a.rc_advance()                      # consume closing quote

    # scan_u: cur == 'u'.  Parse \uXXXX (+ surrogate pair), push one codepoint,
    # UTF-8 encode via emit_utf8(sink).  Leaves cur after the last hex digit.
    def scan_u(sink):
        read_hex4()                         # -> cp on stack
        i = lab()
        enc, hi, lone = "en%d" % i, "hi%d" % i, "lo%d" % i
        a.dup(); a.blt_num(0xD800, enc)
        a.dup(); a.blt_num(0xDC00, hi)
        a.dup(); a.blt_num(0xE000, lone)
        a.jmp(enc)
        a.label(lone)
        a.jmp(a_fail("lone surrogate"))
        a.label(hi)
        # need \u low surrogate (cur is already past the high's 4th hex digit)
        a.rc_get(); a.bne_num(92, lone)     # backslash
        a.rc_advance()
        a.rc_get(); a.bne_num(117, lone)    # u
        read_hex4()                         # -> cp2 on stack; stack [.., hi, cp2]
        a.dup(); a.blt_num(0xDC00, lone)
        a.dup(); a.bge_num(0xE000, lone)
        # combine: cp = 0x10000 + (hi-0xD800)*0x400 + (cp2-0xDC00)
        a.addk(-0xDC00)                     # cp2'
        a.to_bench("Bird's Bench")          # stash cp2'
        a.addk(-0xD800); a.mulk(0x400)      # hi'
        a.from_bench("Bird's Bench")        # cp2'
        a.add2(); a.addk(0x10000)
        a.label(enc)
        emit_utf8(sink)

    # read_hex4: cur is 'u' OR the first hex digit position.  Reads 4 hex digits
    # starting at the NEXT byte, leaving cur on the last digit.  Pushes the value.
    def read_hex4():
        a.rc_advance()                      # consume 'u' (or previous digit)
        a.pushnum(0)
        for d in range(4):
            a.mulk(16)
            read_hexdigit()                 # pushes digit value (no advance)
            a.add2()
            a.rc_advance()                  # move to the next byte (past 4th too)

    def read_hexdigit():
        i = lab()
        bad = a_fail("invalid \\u escape")
        is09, isAF, isaf, done = "h09%d" % i, "hAF%d" % i, "haf%d" % i, "hd%d" % i
        a.rc_get()                          # byte
        a.dup(); a.blt_num(48, bad)
        a.dup(); a.blt_num(58, is09)
        a.dup(); a.blt_num(65, bad)
        a.dup(); a.blt_num(71, isAF)
        a.dup(); a.blt_num(97, bad)
        a.dup(); a.blt_num(103, isaf)
        a.jmp(bad)
        a.label(is09); a.addk(-48); a.jmp(done)
        a.label(isAF); a.addk(-55); a.jmp(done)
        a.label(isaf); a.addk(-87)
        a.label(done)

    # ---- sinks --------------------------------------------------------
    def sink_content():
        """Byte on stack -> emit into a single-quoted shell word."""
        i = lab()
        q39, q0, end = "c39%d" % i, "c0%d" % i, "ce%d" % i
        a.dup(); a.beq_num(39, q39)
        a.dup(); a.beq_num(0, q0)
        a.print_char_pop(); a.jmp(end)
        a.label(q39); a.drop(); a.out_text(QUOTE_LIT); a.jmp(end)
        a.label(q0); a.drop(); a.out_text("' '")
        a.label(end)

    def sink_target():
        i = lab()
        q39, end = "g39%d" % i, "ge%d" % i
        a.dup(); a.beq_num(0, a_fail("link targets must not contain NUL"))
        a.dup(); a.beq_num(39, q39)
        a.print_char_pop(); a.jmp(end)
        a.label(q39); a.drop(); a.out_text(QUOTE_LIT)
        a.label(end)

    def sink_name():
        """Byte on stack, accumulator string directly below -> append (quoted)."""
        i = lab()
        q39, norm, end = "n39%d" % i, "nn%d" % i, "ne%d" % i
        a.dup(); a.beq_num(0, a_fail("names must not contain / or NUL"))
        a.dup(); a.beq_num(47, a_fail("names must not contain / or NUL"))
        a.dup(); a.bne_num(39, norm)
        a.drop(); a.push_literal_str(QUOTE_LIT); a.concat2(); a.jmp(end)
        a.label(norm); a.chr_op(); a.concat2()
        a.label(end)

    def sink_raw():
        """Byte on stack, accumulator below -> append the raw character."""
        a.chr_op(); a.concat2()

    # ---- deferred fail labels ----------------------------------------
    fail_cache = {}

    def a_fail(msg):
        if msg not in fail_cache:
            a._t += 1
            labn = "F%d" % a._t
            a.fails.append((labn, msg))
            fail_cache[msg] = labn
        return fail_cache[msg]

    # =================================================================
    a.make_coin()
    a.rc_init()
    skipws()
    expect(ord('{'), "the root of the document must be an object")
    a.out_text(PREAMBLE)
    a.rc_advance()                          # consume '{'

    a.push_literal_str(SENT)                # stack bottom sentinel
    a.push_wdep("")                         # root prefix
    a.jmp("mloop")

    # ---- member loop -------------------------------------------------
    a.loop_label("mloop")                   # top of stack = current prefix
    skipws()
    i = lab(); notclose = "nc%d" % i
    a.rc_get(); a.bne_num(ord('}'), notclose)
    a.jmp("close")
    a.label(notclose)

    a.label("member")                       # parse one  "name": value
    skipws()
    a.rc_get(); a.bne_num(ord('"'), a_fail("expected a member name"))
    a.push_wdep("")                         # name accumulator
    scan_string(sink_name)                  # [.., prefix, name]
    # reject "", ".", ".."
    i = lab(); c1, c2, c3 = "v1%d" % i, "v2%d" % i, "v3%d" % i
    a.dup(); a.bne_str("", c1); a.jmp(a_fail("names must not be empty"))
    a.label(c1); a.dup(); a.bne_str(".", c2); a.jmp(a_fail("names must not be . or .."))
    a.label(c2); a.dup(); a.bne_str("..", c3); a.jmp(a_fail("names must not be . or .."))
    a.label(c3)
    # pathbody = prefix + name  (keep prefix)
    a.to_bench("Bird's Bench")              # stash name
    a.dup()                                 # copy prefix
    a.from_bench("Bird's Bench")            # name back
    a.concat2()                             # [.., prefix, pathbody]

    skipws()
    a.rc_get(); a.bne_num(ord(':'), a_fail("expected :"))
    a.rc_advance()
    skipws()
    i = lab(); isobj, isstr, isarr = "io%d" % i, "is%d" % i, "ia%d" % i
    a.rc_get(); a.beq_num(ord('{'), isobj)
    a.rc_get(); a.beq_num(ord('"'), isstr)
    a.rc_get(); a.beq_num(ord('['), isarr)
    a.jmp(a_fail("only objects, strings and [kind, payload] arrays are allowed"))

    # object value
    a.label(isobj)
    a.out_text("_j2d_dir '"); a.dup(); a.outstr(); a.out_text("'\n")
    a.push_literal_str("/"); a.concat2()    # childprefix = pathbody + "/"
    a.rc_advance()                          # consume '{'
    a.jmp("mloop")

    # string value (file)
    a.label(isstr)
    a.out_text("_j2d_file '"); a.outstr(); a.out_text("' '")
    scan_string(sink_content)
    a.out_text("'\n")
    a.jmp("aftval")

    # array value (link / script)
    a.label(isarr)
    a.rc_advance(); skipws()                # consume '['
    a.rc_get(); a.bne_num(ord('"'), a_fail("arrays must be [kind, payload] with a string kind"))
    a.push_wdep("")                         # kind accumulator
    scan_string(sink_raw)                   # [.., prefix, pathbody, kind]
    i = lab(); notlink, isscript, afterk = "al%d" % i, "ap%d" % i, "ak%d" % i
    a.dup(); a.bne_str("link", notlink)
    a.drop()                                # drop kind
    emit_array(a, "_j2d_link", sink_target, scan_string, skipws, a_fail, lab)
    a.jmp("aftval")
    a.label(notlink)
    a.bne_str("script", a_fail("the array kind must be \"link\" or \"script\""))
    emit_array(a, "_j2d_script", sink_content, scan_string, skipws, a_fail, lab)
    a.jmp("aftval")

    # after a value
    a.label("aftval")
    skipws()
    i = lab(); notcomma = "xc%d" % i
    a.rc_get(); a.bne_num(ord(','), notcomma)
    a.rc_advance(); a.jmp("member")
    a.label(notcomma)
    a.rc_get(); a.bne_num(ord('}'), a_fail("expected , or }"))
    a.jmp("close")

    # close current object
    a.label("close")
    a.rc_advance()                          # consume '}'
    a.drop()                                # pop current prefix
    i = lab(); notroot = "nr%d" % i
    a.dup(); a.bne_str(SENT, notroot)       # sentinel -> root fully closed
    skipws()
    a.rc_get(); a.bne_num(256, a_fail("trailing data after the document"))
    a.out_text("# json2dir: end\n")
    a.terminate()
    a.label(notroot)
    a.jmp("aftval")

    return a.finalize()


def emit_array(a, cmd, payload_sink, scan_string, skipws, a_fail, lab):
    """Shared tail for [kind, payload]: pathbody is on the stack."""
    a.drop() if False else None             # (kind already dropped by caller)
    skipws()
    a.rc_get(); a.bne_num(ord(','), a_fail("arrays must have exactly two elements"))
    a.rc_advance(); skipws()
    a.rc_get(); a.bne_num(ord('"'), a_fail("the array payload must be a string"))
    a.out_text(cmd + " '"); a.outstr(); a.out_text("' '")
    scan_string(payload_sink)
    a.out_text("'\n")
    skipws()
    a.rc_get(); a.bne_num(ord(']'), a_fail("arrays must have exactly two elements"))
    a.rc_advance()


if __name__ == "__main__":
    sys.stdout.write(build())
