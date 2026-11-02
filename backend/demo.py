"""Synthetic manuscript, not a scan or OCR result from a supplied book."""
from html import escape
from .store import DEMO_SOURCE, DEMO_TARGET


def manuscript(category: str, number: int) -> str:
    text = []
    if category == "ch":
        for i, line in enumerate(DEMO_SOURCE):
            for j, char in enumerate(line):
                text.append(f'<text x="{678-i*94}" y="{247+j*75}">{escape(char)}</text>')
    else:
        text = [f'<text x="95" y="{269+i*105}" text-anchor="start" font-size="24">{escape(line)}</text>' for i,line in enumerate(DEMO_TARGET)]
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="800" height="1100" viewBox="0 0 800 1100">
    <defs><filter id="paper"><feTurbulence type="fractalNoise" baseFrequency=".58" numOctaves="3" stitchTiles="stitch"/><feColorMatrix type="saturate" values="0"/><feComponentTransfer><feFuncA type="linear" slope=".12"/></feComponentTransfer><feBlend in="SourceGraphic" mode="multiply"/></filter><radialGradient id="age"><stop stop-color="#f4e8c9"/><stop offset="1" stop-color="#dfc79c"/></radialGradient></defs>
    <rect width="800" height="1100" fill="url(#age)"/><rect width="800" height="1100" fill="#ead7af" filter="url(#paper)" opacity=".65"/>
    <g stroke="#68533c" fill="none" opacity=".62"><rect x="64" y="135" width="672" height="775" stroke-width="2"/><rect x="70" y="141" width="660" height="763"/>
    {''.join(f'<path d="M{x} 142V904"/>' for x in range(165,730,94)) if category=='ch' else ''}</g>
    <g fill="#382c24" text-anchor="middle" font-family="KaiTi, DFKai-SB, SimSun, serif" font-size="46">{''.join(text)}</g>
    <text x="400" y="98" text-anchor="middle" fill="#715e42" font-family="serif" font-size="25" letter-spacing="15">千 字 文</text>
    <rect x="81" y="946" width="66" height="66" fill="none" stroke="#994d3b" stroke-width="3" opacity=".6"/><text x="114" y="991" font-family="serif" text-anchor="middle" font-size="40" fill="#994d3b" opacity=".65">文</text>
    <text x="400" y="1034" text-anchor="middle" fill="#826e51" font-size="15" font-family="serif">BẢN DỰNG MINH HỌA · {number:03d}</text></svg>'''
