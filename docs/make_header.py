"""Generate the README header SVG. Self-hosted on purpose.

Badge/header services time out through GitHub's camo proxy often enough to leave
a broken image on the front page, so the header is generated here and committed.
Regenerate with:  python docs/make_header.py

The grid on the right is the real audit result (October 2026): one row per
image, one cell per emulated CPU model, coral = the server crashed.
Validates as XML before writing - a bare '&' in SVG text is invalid XML and
GitHub renders it as "Invalid image source" with no other warning.
"""
import pathlib
import xml.dom.minidom

W, H = 1200, 340
BG = "#0A0A14"
AMBER, CORAL, PINK = "#FFB020", "#FF6B4A", "#FF4E88"
LIME, BLUE, DIM = "#A3E635", "#5B9BFF", "#8B8BA7"

CPUS = ["Nehalem", "Sandy", "Ivy", "Haswell", "A53", "A72", "N1"]
# 0 = runs, 1 = crashes (any suite), per CPU model above
ROWS = [
    ("pgvector (official)", [0, 0, 0, 0, 0, 0, 0]),
    ("CloudNativePG", [0, 0, 0, 0, 0, 0, 0]),
    ("Supabase", [0, 0, 0, 0, 0, 0, 0]),
    ("Immich / VectorChord", [0, 0, 0, 0, 0, 0, 0]),
    ("TimescaleDB-HA", [1, 1, 1, 0, 0, 0, 0]),
    ("Tecnativa", [1, 1, 1, 0, 1, 1, 1]),
    ("Bitnami", [1, 1, 1, 1, 1, 1, 0]),
]
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"
SANS = "-apple-system,Segoe UI,Helvetica,sans-serif"


def grid_svg(x0, y0, cell=22, gap=5, label_w=150):
    out = []
    for j, cpu in enumerate(CPUS):
        cx = x0 + label_w + j * (cell + gap) + cell / 2
        lx = cx - 3
        out.append(f'<text x="{lx:.1f}" y="{y0 - 8}" font-family="{MONO}" font-size="10" '
                   f'fill="{DIM}" text-anchor="start" transform="rotate(-40 {lx:.1f} {y0 - 8})">{cpu}</text>')
    sep = x0 + label_w + 4 * (cell + gap) - gap / 2 - 0.5
    out.append(f'<line x1="{sep:.1f}" y1="{y0 - 4}" x2="{sep:.1f}" y2="{y0 + len(ROWS) * (cell + gap)}" '
               f'stroke="#FFFFFF" stroke-opacity="0.18" stroke-dasharray="3 3"/>')
    for i, (name, cells) in enumerate(ROWS):
        y = y0 + i * (cell + gap)
        crashed = any(cells)
        out.append(f'<text x="{x0 + label_w - 12}" y="{y + cell / 2 + 4:.1f}" font-family="{MONO}" '
                   f'font-size="12" fill="{"#FFFFFF" if crashed else DIM}" text-anchor="end">{name}</text>')
        for j, bad in enumerate(cells):
            x = x0 + label_w + j * (cell + gap)
            if bad:
                out.append(f'<rect x="{x}" y="{y:.1f}" width="{cell}" height="{cell}" rx="4" fill="url(#grad)"/>')
            else:
                out.append(f'<rect x="{x + 0.5}" y="{y + 0.5:.1f}" width="{cell - 1}" height="{cell - 1}" rx="4" '
                           f'fill="{LIME}" fill-opacity="0.10" stroke="{LIME}" stroke-opacity="0.45"/>')
    return "\n    ".join(out)


def pill(x, w, color, text):
    return (f'<rect x="{x}" y="262" width="{w}" height="28" rx="14" fill="none" stroke="{color}" stroke-opacity="0.55"/>'
            f'<text x="{x + w / 2}" y="281" fill="{color}" text-anchor="middle">{text}</text>')


SVG = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}"
     viewBox="0 0 {W} {H}" role="img"
     aria-label="pgvector-cpu-check: find which CPUs crash your PostgreSQL or pgvector Docker image with
     Illegal instruction. Grid of the audit: the official pgvector, CloudNativePG, Supabase and Immich
     images run on every CPU model; TimescaleDB-HA, Tecnativa and Bitnami crash on several.">
  <defs>
    <linearGradient id="grad" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="{AMBER}"/>
      <stop offset="55%" stop-color="{CORAL}"/>
      <stop offset="100%" stop-color="{PINK}"/>
    </linearGradient>
    <linearGradient id="fade" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{CORAL}" stop-opacity="0.22"/>
      <stop offset="100%" stop-color="{BG}" stop-opacity="0"/>
    </linearGradient>
    <pattern id="grid" width="28" height="28" patternUnits="userSpaceOnUse">
      <path d="M28 0 L0 0 0 28" fill="none" stroke="#FFFFFF" stroke-opacity="0.04" stroke-width="1"/>
    </pattern>
  </defs>

  <rect width="{W}" height="{H}" fill="{BG}"/>
  <rect width="{W}" height="{H}" fill="url(#grid)"/>
  <circle cx="{W - 160}" cy="70" r="240" fill="url(#fade)"/>

  <text x="64" y="86" font-family="{MONO}" font-size="13" letter-spacing="3.5" fill="{LIME}">POSTGRESQL &#183; PGVECTOR &#183; SIGILL</text>

  <text x="60" y="160" font-family="Georgia,'Times New Roman',serif" font-size="60" font-weight="700"
        fill="url(#grad)">pgvector-cpu-check</text>

  <text x="64" y="202" font-family="{SANS}" font-size="19" fill="#E8E8F0">Which CPUs crash your Postgres image, before your users find out.</text>
  <text x="64" y="230" font-family="{SANS}" font-size="19" fill="{DIM}">7 CPU models &#8594; the faulting instruction &#8594; the build fix.</text>

  <g font-family="{MONO}" font-size="12">
    {pill(64, 104, AMBER, "13 IMAGES")}
    {pill(180, 122, LIME, "7 CPU MODELS")}
    {pill(314, 162, BLUE, "3 BUILD BUGS FOUND")}
    {pill(488, 184, PINK, "EXACT FAULTING OPCODE")}
  </g>

  <text x="764" y="58" font-family="{MONO}" font-size="11" letter-spacing="2" fill="{DIM}">CRASHES &#183; amd64 | arm64</text>
  <g>
    {grid_svg(764, 124)}
  </g>
</svg>
"""

if __name__ == "__main__":
    out = pathlib.Path(__file__).parent / "header.svg"
    xml.dom.minidom.parseString(SVG)          # fails loudly on a bare '&'
    out.write_text(SVG, encoding="utf-8")
    print(f"wrote {out} ({len(SVG)} bytes, valid XML)")
