#!/usr/bin/env python3
"""Generate every static SVG in assets/ plus scripts/fonts.css.

Requirements: Python 3.9+, Node/npm, and `pip install fonttools brotli`.
Usage: python3 scripts/build-assets.py

Fonts and icons come from pinned npm packages, installed once into .cache/build.
The language card is not built here: see scripts/languages.mjs.
"""
import base64
import html
import io
import random
import re
import subprocess
from pathlib import Path

from fontTools import subset

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
CACHE = ROOT / ".cache" / "build"
MODULES = CACHE / "node_modules"

PACKAGES = [
    "@fontsource/jetbrains-mono@5.3.0",
    "@fontsource/space-grotesk@5.3.0",
    "simple-icons@16.37.0",
]

# Basic Latin + Latin-1, plus the em dash used in the terminal title.
UNICODES = list(range(0x20, 0x7F)) + list(range(0xA0, 0x100)) + [0x2014]

MONO = "'JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"
SANS = "'Space Grotesk',-apple-system,'Segoe UI',Helvetica,Arial,sans-serif"
MONO_ADVANCE = 0.6  # JetBrains Mono advance width, in em.

FACES = {
    "mono400": ("JetBrains Mono", 400, "jetbrains-mono"),
    "mono700": ("JetBrains Mono", 700, "jetbrains-mono"),
    "sans500": ("Space Grotesk", 500, "space-grotesk"),
    "sans700": ("Space Grotesk", 700, "space-grotesk"),
}

THEMES = {
    "dark": {
        "card": "#0d1117", "card2": "#111823", "border": "#262f3b", "text": "#e6edf3",
        "muted": "#8b949e", "dim": "#4b5563", "a1": "#3ddc97", "a2": "#8b7bff",
        "a3": "#ff7a59", "blue": "#3a9df0", "grid": "#1b2430", "comment": "// dark mode. naturally.",
    },
    "light": {
        "card": "#ffffff", "card2": "#f6f8fa", "border": "#d0d7de", "text": "#1f2328",
        "muted": "#59636e", "dim": "#9aa4af", "a1": "#12925e", "a2": "#5b4be0",
        "a3": "#d4502c", "blue": "#1a65a8", "grid": "#eef1f4", "comment": "// light mode? bold move.",
    },
}

# Base styles hold each element's final state, so reduced motion and renderers
# without CSS animation still show the finished card.
BASE_CSS = (
    f".m{{font-family:{MONO}}}.s{{font-family:{SANS}}}"
    "@media (prefers-reduced-motion:reduce){*{animation:none!important}}"
)
RISE = "@keyframes rise{from{opacity:0;transform:translateY(14px)}}"
FADE = "@keyframes fade{from{opacity:0}}"
BLINK = "@keyframes blink{50%{opacity:0}}"
PULSE = "@keyframes pulse{from{transform:scale(1);opacity:.7}to{transform:scale(2.6);opacity:0}}"
PULSE_CLASS = ".ring{transform-box:fill-box;transform-origin:center;opacity:0;animation:pulse 1.8s ease-out infinite}"


def esc(text):
    return html.escape(text, quote=False)


def mono_width(chars, size):
    return chars * size * MONO_ADVANCE


def fmt(value):
    return f"{value:.2f}".rstrip("0").rstrip(".")


def install_packages():
    if not all((MODULES / re.sub(r"@[^@/]+$", "", p)).exists() for p in PACKAGES):
        CACHE.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["npm", "install", "--no-save", "--no-package-lock", "--prefix", str(CACHE), *PACKAGES],
            check=True,
        )


def subset_face(package, weight):
    source = MODULES / "@fontsource" / package / "files" / f"{package}-latin-{weight}-normal.woff2"
    options = subset.Options()
    options.flavor = "woff2"
    options.layout_features = ["kern"]  # Drops JetBrains Mono's code ligatures.
    options.hinting = False
    options.desubroutinize = True
    font = subset.load_font(str(source), options)
    font.recalcTimestamp = False
    subsetter = subset.Subsetter(options)
    subsetter.populate(unicodes=UNICODES)
    subsetter.subset(font)
    buffer = io.BytesIO()
    subset.save_font(font, buffer, options)
    return buffer.getvalue()


def build_font_css():
    css = {}
    for key, (family, weight, package) in FACES.items():
        data = base64.b64encode(subset_face(package, weight)).decode("ascii")
        css[key] = (
            f"@font-face{{font-family:'{family}';font-weight:{weight};font-style:normal;"
            f"src:url(data:font/woff2;base64,{data}) format('woff2')}}"
        )
    return css


class Builder:
    def __init__(self, fonts):
        self.fonts = fonts

    def write(self, name, width, height, title, faces, css, defs, body):
        font_css = "".join(self.fonts[face] for face in faces)
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img"><title>{esc(title)}</title>'
            f"<style>{font_css}{BASE_CSS}{css}</style><defs>{defs}</defs>{body}</svg>\n"
        )
        (ASSETS / name).write_text(svg, encoding="utf-8")


def typing_css(name, delay, duration, steps, x):
    """CSS that reveals a mono string one character at a time."""
    return (
        f"@keyframes {name}{{from{{transform:scaleX(0)}}}}"
        f".{name}{{transform-origin:{fmt(x)}px 0;"
        f"animation:{name} {duration}s steps({steps},end) {delay}s both}}"
    )


def globe(cx, cy, radius, color):
    meridians = "".join(
        f'<ellipse class="spin" cx="{cx}" cy="{cy}" rx="{radius}" ry="{radius}" '
        f'style="animation-delay:{delay}s"/>'
        for delay in (0, -1.5, -3)
    )
    parallels = "".join(
        f'<ellipse cx="{cx}" cy="{cy + offset}" rx="{fmt(rx)}" ry="{fmt(rx * 0.22)}"/>'
        for offset, rx in ((-radius * 0.55, radius * 0.83), (0, radius), (radius * 0.55, radius * 0.83))
    )
    return (
        f'<g fill="none" stroke="{color}" stroke-width="1.3">'
        f'<circle cx="{cx}" cy="{cy}" r="{radius}"/>{parallels}{meridians}</g>'
    )


def hero(builder, theme_name, t):
    cmd = "node hello.js"
    size = 20
    cmd_x = 48 + mono_width(2, size)
    cmd_w = mono_width(len(cmd), size)
    char = mono_width(1, size)
    type_start, type_time = 0.5, 1.0
    radius = 11
    hello = "Olá, Mundo!"

    css = (
        RISE + FADE + BLINK + PULSE + PULSE_CLASS
        + typing_css("type", type_start, type_time, len(cmd), cmd_x)
        + "@keyframes cur{from{transform:translateX(0)}"
        f"to{{transform:translateX({fmt(cmd_w)}px)}}}}"
        f".cur{{transform:translateX({fmt(cmd_w)}px);"
        f"animation:cur {type_time}s steps({len(cmd)},end) {type_start}s both}}"
        "@keyframes life{0%,99.9%{opacity:1}100%{opacity:0}}"
        ".life{opacity:0;animation:life 1.75s linear}"
        ".blink{animation:blink 1s step-end infinite}"
        ".rise{animation:rise .7s cubic-bezier(.2,.7,.2,1) both}"
        ".fade{animation:fade .5s ease-out both}"
        f"@keyframes spin{{0%,100%{{rx:0;animation-timing-function:ease-out}}"
        f"50%{{rx:{radius}px;animation-timing-function:ease-in}}}}"
        ".spin{animation:spin 4.5s infinite}"
        "@keyframes sheen{0%{transform:translateX(-420px)}45%,100%{transform:translateX(1320px)}}"
        ".sheen{animation:sheen 7s ease-in-out 1s infinite}"
    )
    defs = (
        '<clipPath id="card"><rect x="1" y="1" width="958" height="398" rx="14"/></clipPath>'
        f'<clipPath id="typed"><rect class="type" x="{fmt(cmd_x)}" y="74" '
        f'width="{fmt(cmd_w)}" height="34"/></clipPath>'
        f'<pattern id="grid" width="32" height="32" patternUnits="userSpaceOnUse">'
        f'<path d="M32 0H0V32" fill="none" stroke="{t["grid"]}"/></pattern>'
        f'<radialGradient id="glow1"><stop offset="0" stop-color="{t["a1"]}" stop-opacity=".16"/>'
        f'<stop offset=".55" stop-color="{t["a1"]}" stop-opacity=".05"/>'
        f'<stop offset="1" stop-color="{t["a1"]}" stop-opacity="0"/></radialGradient>'
        f'<radialGradient id="glow2"><stop offset="0" stop-color="{t["a2"]}" stop-opacity=".16"/>'
        f'<stop offset=".55" stop-color="{t["a2"]}" stop-opacity=".05"/>'
        f'<stop offset="1" stop-color="{t["a2"]}" stop-opacity="0"/></radialGradient>'
        f'<linearGradient id="name"><stop offset="0" stop-color="{t["a1"]}"/>'
        f'<stop offset="1" stop-color="{t["a2"]}"/></linearGradient>'
        f'<linearGradient id="shine"><stop offset="0" stop-color="{t["text"]}" stop-opacity="0"/>'
        f'<stop offset=".5" stop-color="{t["text"]}" stop-opacity=".07"/>'
        f'<stop offset="1" stop-color="{t["text"]}" stop-opacity="0"/></linearGradient>'
    )

    dots = "".join(
        f'<circle cx="{x}" cy="23" r="6" fill="{color}"/>'
        for x, color in ((24, "#ff5f57"), (44, "#febc2e"), (64, "#28c840"))
    )

    chip_y, chip_h, chip_size = 312, 38, 14
    text_y = chip_y + 24
    chips = []
    x = 48

    def chip(width, delay, content):
        nonlocal x
        chips.append(
            f'<g class="rise" style="animation-delay:{delay}s">'
            f'<rect x="{fmt(x)}" y="{chip_y}" width="{fmt(width)}" height="{chip_h}" rx="19" '
            f'fill="{t["card2"]}" stroke="{t["border"]}"/>{content}</g>'
        )
        x += width + 12

    width = 32 + mono_width(6, chip_size) + 16
    dot_x = x + 19
    chip(
        width, 3.2,
        f'<circle class="ring" cx="{fmt(dot_x)}" cy="{chip_y + 19}" r="4" fill="{t["a1"]}"/>'
        f'<circle cx="{fmt(dot_x)}" cy="{chip_y + 19}" r="4" fill="{t["a1"]}"/>'
        f'<text class="m" x="{fmt(x + 32)}" y="{text_y}" font-size="{chip_size}" fill="{t["text"]}">online</text>',
    )
    label = "Senior+ IC @ Deel"
    chip(
        32 + mono_width(len(label), chip_size), 3.32,
        f'<text class="m" x="{fmt(x + 16)}" y="{text_y}" font-size="{chip_size}" fill="{t["text"]}">{esc(label)}</text>',
    )
    chip(
        32 + mono_width(19, chip_size), 3.44,
        f'<text class="m" x="{fmt(x + 16)}" y="{text_y}" font-size="{chip_size}" fill="{t["text"]}">'
        f'shipping since <tspan fill="{t["a1"]}" font-weight="700">2013</tspan></text>',
    )

    globe_x = int(48 + mono_width(len(hello), size) + 24)
    body = (
        f'<rect x="1" y="1" width="958" height="398" rx="14" fill="{t["card"]}"/>'
        '<g clip-path="url(#card)">'
        '<rect y="45" width="960" height="355" fill="url(#grid)"/>'
        '<circle cx="800" cy="110" r="300" fill="url(#glow1)"/>'
        '<circle cx="120" cy="380" r="320" fill="url(#glow2)"/>'
        '<rect class="sheen" y="-80" width="240" height="560" fill="url(#shine)" '
        'style="transform-box:view-box"/>'
        f'<rect width="960" height="45" fill="{t["card2"]}"/>'
        f'<path d="M0 45H960" stroke="{t["border"]}"/></g>'
        f'<rect x="1" y="1" width="958" height="398" rx="14" fill="none" stroke="{t["border"]}"/>'
        f"{dots}"
        f'<text class="m" x="480" y="28" font-size="13" text-anchor="middle" fill="{t["muted"]}">'
        "vinicius@cardozo: ~/github — zsh</text>"
        f'<text class="m" x="48" y="98" font-size="{size}" font-weight="700" fill="{t["a1"]}">$</text>'
        f'<text class="m" x="{fmt(cmd_x)}" y="98" font-size="{size}" fill="{t["text"]}" '
        f'clip-path="url(#typed)">{cmd}</text>'
        f'<g class="life"><g class="cur"><rect class="blink" x="{fmt(cmd_x)}" y="81" '
        f'width="{fmt(char)}" height="23" fill="{t["a1"]}"/></g></g>'
        '<g class="fade" style="animation-delay:1.8s">'
        f'<text class="m" x="48" y="134" font-size="{size}" fill="{t["text"]}">{hello}</text>'
        f'{globe(globe_x, 127, radius, t["a1"])}</g>'
        '<text class="s rise" x="46" y="224" font-size="66" font-weight="700" fill="url(#name)" '
        'style="animation-delay:2.3s">Vinícius Cardozo</text>'
        f'<text class="s rise" x="48" y="270" font-size="24" font-weight="500" fill="{t["muted"]}" '
        'style="animation-delay:2.7s">I work with technical stuff to '
        f'<tspan fill="{t["text"]}">solve real-life problems.</tspan></text>'
        f'{"".join(chips)}'
        f'<text class="m fade" x="912" y="{text_y}" font-size="14" text-anchor="end" fill="{t["dim"]}" '
        f'style="animation-delay:3.7s">{esc(t["comment"])}</text>'
    )
    builder.write(
        f"hero-{theme_name}.svg", 960, 400,
        "Terminal printing Olá, Mundo! and introducing Vinícius Cardozo",
        ["mono400", "mono700", "sans500", "sans700"], css, defs, body,
    )


ROLES = [
    ("Deel", "Software Engineer", "building product", "a1", "running"),
    ("Alura", "Instructor", "teaching devs", "blue", "paused"),
    ("Rocketseat", "Creator", "creating content", "a2", "paused"),
]


def roles(builder, theme_name, t):
    gap = 16
    card_w = (958 - 2 * gap) / 3
    card_y, card_h = 46, 208
    rng = random.Random(2013)

    css = (
        RISE + PULSE + PULSE_CLASS
        + ".card{animation:rise .7s cubic-bezier(.2,.7,.2,1) both}"
        "@keyframes eq{0%,100%{transform:scaleY(1)}35%{transform:scaleY(.28)}70%{transform:scaleY(.68)}}"
        ".bar{transform-box:fill-box;transform-origin:50% 100%;animation:eq 1.4s ease-in-out infinite}"
    )
    defs = (
        f'<clipPath id="c"><rect width="{fmt(card_w)}" height="{card_h}" rx="12"/></clipPath>'
    )
    cards = []
    for index, (company, role, verb, accent_key, status) in enumerate(ROLES):
        accent = t[accent_key]
        x = 1 + index * (card_w + gap)
        dot_x = card_w - 20 - mono_width(len(status), 12) - 11
        ring = (
            f'<circle class="ring" cx="{fmt(dot_x)}" cy="30" r="3.5" fill="{accent}"/>'
            if status == "running"
            else ""
        )
        bars_left, bars_right, bar_w, bar_h, bar_y = 20, card_w - 20, 9, 36, 156
        pitch = (bars_right - bars_left - bar_w) / 17
        bars = "".join(
            f'<rect class="bar" x="{fmt(bars_left + b * pitch)}" y="{bar_y}" width="{bar_w}" '
            f'height="{bar_h}" rx="2" fill="{accent}" fill-opacity=".72" '
            f'style="animation-duration:{rng.uniform(1.0, 1.9):.2f}s;'
            f'animation-delay:-{rng.uniform(0, 2):.2f}s"/>'
            for b in range(18)
        )
        cards.append(
            f'<g transform="translate({fmt(x)} {card_y})"><g class="card" '
            f'style="animation-delay:{0.3 + index * 0.25:.2f}s">'
            f'<rect width="{fmt(card_w)}" height="{card_h}" rx="12" fill="{t["card"]}" stroke="{t["border"]}"/>'
            f'<rect width="{fmt(card_w)}" height="4" fill="{accent}" clip-path="url(#c)"/>'
            f'<text class="m" x="20" y="34" font-size="12" fill="{t["muted"]}">pid 0{index + 1}</text>'
            f"{ring}"
            f'<circle cx="{fmt(dot_x)}" cy="30" r="3.5" fill="{accent}"/>'
            f'<text class="m" x="{fmt(card_w - 20)}" y="34" font-size="12" text-anchor="end" fill="{t["muted"]}">{status}</text>'
            f'<text class="s" x="20" y="84" font-size="36" font-weight="700" fill="{t["text"]}">{company}</text>'
            f'<text class="s" x="20" y="110" font-size="16" font-weight="500" fill="{t["muted"]}">{role}</text>'
            f'<path d="M20 134H31M26.5 129.5L31 134L26.5 138.5" fill="none" stroke="{accent}" '
            'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>'
            f'<text class="m" x="39" y="139" font-size="14" fill="{accent}">{verb}</text>'
            f"{bars}</g></g>"
        )
    body = (
        f'<text class="m" x="4" y="26" font-size="16" fill="{t["text"]}">'
        f'<tspan fill="{t["a1"]}" font-weight="700">$</tspan> ps --current-roles</text>'
        f'<text class="m" x="956" y="26" font-size="13" text-anchor="end" fill="{t["muted"]}">'
        "3 processes · all healthy</text>"
        f'{"".join(cards)}'
    )
    builder.write(
        f"roles-{theme_name}.svg", 960, 256,
        "Current roles: Software Engineer at Deel, Instructor at Alura, Creator at Rocketseat",
        ["mono400", "mono700", "sans500", "sans700"], css, defs, body,
    )


def footer(builder, theme_name, t):
    cmd = 'echo "thanks for stopping by" && exit'
    exit_text = "process exited with code 0 · see you around"
    size, exit_size = 15, 14
    x = 24
    cmd_x = x + mono_width(2, size)
    cmd_w = mono_width(len(cmd), size)
    type_start, type_time = 0.4, 1.6
    exit_delay = type_start + type_time + 0.25
    cursor_x = x + mono_width(len(exit_text), exit_size) + 5

    css = (
        FADE + BLINK
        + typing_css("type", type_start, type_time, len(cmd), cmd_x)
        + ".fade{animation:fade .4s ease-out both}"
        ".blink{animation:blink 1s step-end infinite}"
    )
    defs = (
        f'<clipPath id="typed"><rect class="type" x="{fmt(cmd_x)}" y="12" '
        f'width="{fmt(cmd_w)}" height="26"/></clipPath>'
    )
    body = (
        f'<rect x="1" y="1" width="958" height="70" rx="12" fill="{t["card"]}" stroke="{t["border"]}"/>'
        f'<text class="m" x="{x}" y="30" font-size="{size}" font-weight="700" fill="{t["a1"]}">$</text>'
        f'<text class="m" x="{fmt(cmd_x)}" y="30" font-size="{size}" fill="{t["text"]}" '
        f'clip-path="url(#typed)">{esc(cmd)}</text>'
        f'<g class="fade" style="animation-delay:{exit_delay}s">'
        f'<text class="m" x="{x}" y="54" font-size="{exit_size}" fill="{t["muted"]}">{esc(exit_text)}</text>'
        f'<rect class="blink" x="{fmt(cursor_x)}" y="42" width="8" height="15" fill="{t["a1"]}"/></g>'
    )
    builder.write(
        f"footer-{theme_name}.svg", 960, 72,
        "Thanks for stopping by. See you around.",
        ["mono400", "mono700"], css, defs, body,
    )


def instagram_icon():
    source = (MODULES / "simple-icons" / "icons" / "instagram.svg").read_text(encoding="utf-8")
    path = re.search(r'<path d="([^"]+)"', source).group(1)
    return f'<path transform="translate(18 16)" d="{path}" fill="#fff"/>'


def linkedin_icon():
    return (
        '<rect x="18" y="16" width="24" height="24" rx="5" fill="#fff"/>'
        '<text class="s" x="30" y="34" font-size="16" font-weight="700" text-anchor="middle" '
        'fill="#0a66c2">in</text>'
    )


def site_icon():
    return (
        '<g fill="none" stroke="#fff" stroke-width="1.8">'
        '<circle cx="30" cy="28" r="11"/><ellipse cx="30" cy="28" rx="4.8" ry="11"/>'
        '<path d="M19 28H41"/></g>'
    )


def button(builder, name, start, end, icon, label, subtitle):
    defs = (
        f'<linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{start}"/>'
        f'<stop offset="1" stop-color="{end}"/></linearGradient>'
    )
    body = (
        '<rect width="220" height="56" rx="28" fill="url(#g)"/>'
        f"{icon}"
        f'<text class="s" x="54" y="25" font-size="16" font-weight="700" fill="#fff">{label}</text>'
        f'<text class="m" x="54" y="42" font-size="11.5" fill="#fff" fill-opacity=".85">{esc(subtitle)}</text>'
        '<path d="M194 22L200 28L194 34" fill="none" stroke="#fff" stroke-width="2.2" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
    )
    builder.write(f"btn-{name}.svg", 220, 56, f"{label}: {subtitle}", ["mono400", "sans700"], "", defs, body)


def main():
    install_packages()
    ASSETS.mkdir(exist_ok=True)
    fonts = build_font_css()
    (ROOT / "scripts" / "fonts.css").write_text("\n".join(fonts.values()) + "\n", encoding="utf-8")

    builder = Builder(fonts)
    for theme_name, theme in THEMES.items():
        hero(builder, theme_name, theme)
        roles(builder, theme_name, theme)
        footer(builder, theme_name, theme)

    button(builder, "instagram", "#f58529", "#dd2a7b", instagram_icon(), "Instagram", "@_vcardozo")
    button(builder, "linkedin", "#0a66c2", "#0b4f96", linkedin_icon(), "LinkedIn", "in/vcardozo")
    button(builder, "site", "#3a3f4b", "#1f232b", site_icon(), "Website", "vinicius.cardozo.io")


if __name__ == "__main__":
    main()
