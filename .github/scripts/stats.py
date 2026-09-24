"""Generate self-hosted GitHub stat cards (SVG) for the profile README.

Uses only public data via the GitHub GraphQL API, so the default
Actions GITHUB_TOKEN is enough. Writes to ./out/.
"""

import datetime as dt
import json
import os
import urllib.request
from html import escape

USER = os.environ.get("GH_USER", "ISOLATEDMAN")
TOKEN = os.environ["GITHUB_TOKEN"]
OUT = "out"

# Languages that are build/scaffold noise (Flutter runners, configs) rather than code I write.
IGNORED_LANGS = {
    "HTML", "CSS", "SCSS", "Shell", "Dockerfile", "Makefile", "C", "C++", "CMake",
    "Swift", "Kotlin", "Objective-C", "Ruby", "PowerShell", "Batchfile", "Procfile",
    "Jupyter Notebook", "Mustache", "EJS",
}

BG = "#0d1117"
BORDER = "#30363d"
ACCENT = "#38bdf8"
ACCENT_2 = "#818cf8"
TEXT = "#e6edf3"
MUTED = "#8b949e"
FONT = "'Segoe UI', Ubuntu, 'Helvetica Neue', Arial, sans-serif"


def gql(query, variables=None):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables or {}}).encode(),
        headers={"Authorization": f"bearer {TOKEN}", "User-Agent": "profile-stats"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        body = json.load(r)
    if body.get("errors"):
        raise RuntimeError(body["errors"])
    return body["data"]


def fetch():
    base = gql(
        """query($u:String!){ user(login:$u){
            createdAt
            followers{ totalCount }
            repositories(ownerAffiliations:OWNER, privacy:PUBLIC, isFork:false, first:100){
              totalCount
              nodes{ name stargazerCount languages(first:10, orderBy:{field:SIZE, direction:DESC}){
                edges{ size node{ name color } } } }
            }
            pullRequests{ totalCount }
        } }""",
        {"u": USER},
    )["user"]

    start_year = int(base["createdAt"][:4])
    now = dt.datetime.now(dt.timezone.utc)
    days, commits, total = {}, 0, 0
    for year in range(start_year, now.year + 1):
        frm = f"{year}-01-01T00:00:00Z"
        to = now.isoformat() if year == now.year else f"{year}-12-31T23:59:59Z"
        c = gql(
            """query($u:String!,$f:DateTime!,$t:DateTime!){ user(login:$u){
                contributionsCollection(from:$f, to:$t){
                  totalCommitContributions restrictedContributionsCount
                  contributionCalendar{ totalContributions weeks{ contributionDays{ date contributionCount } } }
                } } }""",
            {"u": USER, "f": frm, "t": to},
        )["user"]["contributionsCollection"]
        commits += c["totalCommitContributions"] + c["restrictedContributionsCount"]
        total += c["contributionCalendar"]["totalContributions"]
        for w in c["contributionCalendar"]["weeks"]:
            for d in w["contributionDays"]:
                days[d["date"]] = d["contributionCount"]
    return base, days, commits, total


def streaks(days):
    ordered = sorted(days.items())
    longest = run = 0
    for _, n in ordered:
        run = run + 1 if n > 0 else 0
        longest = max(longest, run)
    current = 0
    for i, (date, n) in enumerate(reversed(ordered)):
        if n > 0:
            current += 1
        elif i == 0:
            continue  # today with no contributions yet doesn't break the streak
        else:
            break
    return current, longest


def fmt(n):
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def card(width, height, body):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" fill="none">
<style>
  .t {{ font: 600 17px {FONT}; fill: {ACCENT}; }}
  .l {{ font: 400 13.5px {FONT}; fill: {MUTED}; }}
  .v {{ font: 700 13.5px {FONT}; fill: {TEXT}; }}
  .big {{ font: 700 30px {FONT}; fill: {TEXT}; }}
  .cap {{ font: 500 12px {FONT}; fill: {MUTED}; }}
</style>
<rect x="0.5" y="0.5" rx="10" width="{width - 1}" height="{height - 1}" fill="{BG}" stroke="{BORDER}"/>
{body}
</svg>
"""


def stats_svg(base, days, commits, total):
    current, longest = streaks(days)
    stars = sum(r["stargazerCount"] for r in base["repositories"]["nodes"])
    rows = [
        ("Total contributions", fmt(total)),
        ("Commits", fmt(commits)),
        ("Pull requests", fmt(base["pullRequests"]["totalCount"])),
        ("Public repositories", fmt(base["repositories"]["totalCount"])),
        ("Stars earned", fmt(stars)),
        ("Longest streak", f"{longest} days"),
    ]
    body = [f'<text x="25" y="38" class="t">GitHub Stats</text>']
    for i, (label, value) in enumerate(rows):
        y = 72 + i * 24
        body.append(
            "<g>"
            f'<circle cx="31" cy="{y - 4.5}" r="3.5" fill="{ACCENT if i % 2 == 0 else ACCENT_2}"/>'
            f'<text x="44" y="{y}" class="l">{label}</text>'
            f'<text x="275" y="{y}" class="v" text-anchor="end">{value}</text></g>'
        )
    # streak ring
    cx, cy, r = 395, 112, 52
    body.append(
        f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="{ACCENT}"/><stop offset="1" stop-color="{ACCENT_2}"/></linearGradient></defs>'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" stroke="{BORDER}" stroke-width="7"/>'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" stroke="url(#g)" stroke-width="7" stroke-linecap="round" '
        f'stroke-dasharray="{2 * 3.1416 * r:.1f}" transform="rotate(-90 {cx} {cy})"/>'
        f'<text x="{cx}" y="{cy + 10}" class="big" text-anchor="middle">{current}</text>'
        f'<text x="{cx}" y="{cy + r + 26}" class="cap" text-anchor="middle">Current streak</text>'
    )
    return card(495, 215, "\n".join(body))


def languages_svg(base):
    sizes, colors = {}, {}
    for repo in base["repositories"]["nodes"]:
        for e in repo["languages"]["edges"]:
            name = e["node"]["name"]
            if name in IGNORED_LANGS:
                continue
            sizes[name] = sizes.get(name, 0) + e["size"]
            colors[name] = e["node"]["color"] or MUTED
    grand = sum(sizes.values()) or 1
    top = [kv for kv in sorted(sizes.items(), key=lambda kv: -kv[1]) if kv[1] / grand >= 0.01][:8]
    total = sum(s for _, s in top) or 1

    body = [f'<text x="25" y="38" class="t">Most Used Languages</text>']
    # stacked bar
    body.append('<mask id="m"><rect x="25" y="56" width="445" height="10" rx="5" fill="#fff"/></mask>')
    x = 25.0
    bars = []
    for name, s in top:
        w = 445 * s / total
        bars.append(f'<rect x="{x:.2f}" y="56" width="{w + 0.5:.2f}" height="10" fill="{colors[name]}"/>')
        x += w
    body.append(f'<g mask="url(#m)">{"".join(bars)}</g>')
    # legend, two columns
    for i, (name, s) in enumerate(top):
        col, row = i % 2, i // 2
        lx, ly = 25 + col * 230, 96 + row * 26
        body.append(
            "<g>"
            f'<circle cx="{lx + 5}" cy="{ly - 4.5}" r="5" fill="{colors[name]}"/>'
            f'<text x="{lx + 18}" y="{ly}" class="v">{escape(name)}</text>'
            f'<text x="{lx + 200}" y="{ly}" class="l" text-anchor="end">{100 * s / total:.1f}%</text></g>'
        )
    rows = (len(top) + 1) // 2
    return card(495, max(215, 96 + rows * 26 + 8), "\n".join(body))


def main():
    base, days, commits, total = fetch()
    os.makedirs(OUT, exist_ok=True)
    with open(f"{OUT}/stats.svg", "w") as f:
        f.write(stats_svg(base, days, commits, total))
    with open(f"{OUT}/languages.svg", "w") as f:
        f.write(languages_svg(base))
    print("contributions", total, "commits", commits, "streaks", streaks(days))


if __name__ == "__main__":
    main()
