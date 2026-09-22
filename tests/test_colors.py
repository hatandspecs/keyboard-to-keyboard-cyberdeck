"""The color schemes, and the two properties that are easy to get wrong.

Both were real faults, and neither is visible from reading the code:

  * every scheme needs its OWN curses pair numbers. ncurses rewrites a cell
    only when its character or its attribute changed, and an attribute holds
    the pair NUMBER, not the pair's definition. Redefining pair 3 in place
    leaves every cell's attribute identical, ncurses skips the repaint, and
    fbcon keeps the colors it already baked into the glyphs. The symptom was
    switching to Hal and seeing only the digits that happened to change value
    come out red.
  * the palette slots a scheme redefines are determined by its ANSI index and
    are not free choices. A console pair can name entries 0-7 only; 8-15 are
    reachable for a foreground through A_BOLD and not at all for a background.
    An earlier version redefined 8 and 9 on the reasoning that nothing used
    them, which was true including of this program — so every scheme rendered
    as its ANSI approximation and Deckard's amber came out yellow.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
import colors
import config


if __name__ == "__main__":
    print("Color schemes")

    equals("five schemes", len(colors.ORDER), 5)
    check("Ripley is one of them", "ripley" in colors.ORDER, colors.ORDER)
    check("every scheme in ORDER has a definition",
          all(k in colors.SCHEMES for k in colors.ORDER), colors.ORDER)
    check("config accepts exactly the schemes that exist",
          tuple(config.COLORS) == tuple(colors.ORDER),
          (config.COLORS, colors.ORDER))

    # Ripley is white: no hue, just intensity.
    ripley = colors.SCHEMES["ripley"]
    equals("Ripley is white on black", ripley["bright"], "FFFFFF")
    check("with a grey dim variant, not a colored one",
          len(set(ripley["dim"][i:i + 2] for i in (0, 2, 4))) == 1,
          ripley["dim"])
    equals("and it uses the white ANSI index", ripley["ansi"], 7)

    # The repaint property: no two schemes may share a pair number.
    seen = {}
    for key in colors.ORDER:
        for number in colors._pairs(key):
            check(f"pair {number} belongs to {key} alone",
                  number not in seen, f"also used by {seen.get(number)}")
            seen[number] = key
    check("and none of them is pair 0, which curses reserves",
          0 not in seen, sorted(seen))

    # The slot property: a scheme's slots follow from its ANSI index.
    for key in colors.ORDER:
        ansi = colors.SCHEMES[key]["ansi"]
        equals(f"{key} redefines the entries its pairs will land on",
               colors._slots(ansi), (ansi, ansi + 8))
        check(f"{key}'s dim slot is nameable by a console pair",
              0 <= ansi <= 7, ansi)

    # The bar slot is given over to the scheme's bright hue, so it must not
    # collide with any scheme's own entries.
    used = {colors.SCHEMES[k]["ansi"] for k in colors.ORDER}
    check("the bar slot is not an entry any scheme redefines",
          colors._SLOT_BAR not in used, (colors._SLOT_BAR, sorted(used)))

    # Cycling visits every scheme once and returns to the start.
    seen_order, key = [], colors.ORDER[0]
    for _ in colors.ORDER:
        seen_order.append(key)
        key = colors.cycle(key)
    equals("F4 cycles through every scheme", tuple(seen_order), colors.ORDER)
    equals("and wraps back to the first", key, colors.ORDER[0])

    sys.exit(report())
