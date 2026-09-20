"""One definition of what a check is, shared by every test file.

There were two, with the same name and different meanings:

    check(name, cond, detail="")   # the third argument is diagnostic text
    check(name, got, want)         # the third argument is the expected value

Both read identically at the call site. A comparison written in a file using
the first form passes whenever the value is merely truthy — which happened,
and the tests reported PASS for the wrong reason until an empty string
happened to fail.

So the semantics are in the name now, not the position:

    check(name, cond, detail="")   asserts a condition
    equals(name, got, want)        asserts a value, and prints both on failure

Neither can be mistaken for the other, and a wrong third argument is a type
error rather than a silent change of meaning.
"""

FAILED = []


def check(name, cond, detail=""):
    """Assert a condition. `detail` is printed only when it fails."""
    ok = bool(cond)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}"
          + ("" if ok or not detail else f"\n          {detail}"))
    if not ok:
        FAILED.append(name)
    return ok


def equals(name, got, want):
    """Assert a value. Both sides are printed when they differ."""
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        print(f"          got  {got!r}\n          want {want!r}")
        FAILED.append(name)
    return ok


def report():
    """Print the summary every test file ends with. Returns an exit status."""
    if FAILED:
        print(f"\n{len(FAILED)} FAILED: {FAILED}")
        return 1
    print("\nALL PASS")
    return 0
