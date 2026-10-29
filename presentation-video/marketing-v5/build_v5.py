"""Génère le projet HyperFrames V5 (UML Factory LLM) à partir des FICHIERS RÉELS : examples/banque_grand.puml,
demo-output/ (sortie réelle de l'outil), capture/real_run.jsonl (journal réel), script_v5.py (voix ElevenLabs)."""
from pathlib import Path
import html, json, re, wave, math, subprocess
from script_v5 import SCRIPT as BLOCKS

P = Path(__file__).resolve().parent
PUML = (P / 'examples' / 'banque_grand.puml').read_text(encoding='utf-8')
OUT = P / 'demo-output'
RUN = [json.loads(l) for l in (P / 'capture' / 'real_run.jsonl').read_text(encoding='utf-8').splitlines()]
(P / 'compositions').mkdir(exist_ok=True)

EG = {}
INK, PAPER, ORANGE, LIME = '#18211f', '#f0f3ef', '#f34d28', '#dcff66'
TEAL, GOLD = '#2fb59b', '#ffc83d'
NS = 11
def T(s, **kw):
    for k, v in kw.items(): s = s.replace('@' + k + '@', str(v))
    return s

# ---------------------------------------------------------------- voix : durées réelles
def wav_len(n):
    with wave.open(str(P / 'assets' / 'voice' / f'scene-{n}.wav')) as w:
        return w.getnframes() / w.getframerate()
VOICE = {n: wav_len(n) for n in range(1, NS + 1)}
VO = 0.45
TAIL = {n: 0.7 for n in range(1, NS + 1)}
TAIL[4] = 0.9; TAIL[11] = 3.6; TAIL[3] = 0.9; TAIL[10] = 2.4
MINDUR = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0, 8: 0, 9: 0, 10: 0, 11: 0}
DUR = {n: round(max(VO + VOICE[n] + TAIL[n], MINDUR[n]) + 0.05, 2) for n in range(1, NS + 1)}
START = {}; t = 0.0
for n in range(1, NS + 1):
    START[n] = round(t, 3); t += DUR[n]
TOTAL = round(t, 3)

def silences(n):
    r = subprocess.run(['ffmpeg', '-hide_banner', '-i', str(P / 'assets' / 'voice' / f'scene-{n}.wav'), '-af', 'silencedetect=noise=-38dB:d=0.12', '-f', 'null', '-'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace').stderr
    st = [float(x) for x in re.findall(r'silence_start: ([\d.]+)', r)]
    en = [float(x) for x in re.findall(r'silence_end: ([\d.]+)', r)]
    return list(zip(st, en))

def clean(s): return len(re.sub(r'\[[^\]]*\]|\s', '', s))
CUES = {}      # CUES[n] = [(début, fin) de chaque bloc], en secondes DANS LA SCÈNE (VO inclus)
for n in range(1, NS + 1):
    bl = BLOCKS[n]; k = len(bl); L = VOICE[n]
    w = [clean(t_) for _, t_ in bl]; tot = sum(w)
    exp = [L * sum(w[:i + 1]) / tot for i in range(k - 1)]
    sil = [(a, e) for a, e in silences(n) if a > .3 and e < L - .05]
    bounds = []; prev = 0.0
    for e_ in exp:
        cand = [s for s in sil if s[0] > prev + .5 and abs((s[0] + s[1]) / 2 - e_) < max(.9, .22 * L)]
        if cand:
            s = min(cand, key=lambda z: abs((z[0] + z[1]) / 2 - e_)); bounds.append((s[0], s[1])); prev = s[1]
        else:
            bounds.append((e_ - .05, e_ + .05)); prev = e_ + .05
    starts = [0.0] + [b[1] for b in bounds]; ends = [b[0] for b in bounds] + [L]
    CUES[n] = [(round(VO + starts[i], 3), round(VO + ends[i], 3)) for i in range(k)]
def cue(n, i): return CUES[n][i][0]
# ---------------------------------------------------------------- modèle lu dans le .puml réel
classes = {}; order = []
cur = None
for line in PUML.splitlines():
    m = re.match(r'\s*(abstract class|class|interface|enum)\s+(\w+)\s*\{', line)
    if m:
        cur = {'name': m.group(2), 'kind': m.group(1), 'attrs': [], 'ops': []}
        classes[cur['name']] = cur; order.append(cur['name']); continue
    if cur and line.strip() == '}':
        cur = None; continue
    if cur and line.strip():
        s = line.strip()
        if cur['kind'] == 'enum': cur['attrs'].append(s)
        elif '(' in s: cur['ops'].append(s)
        else: cur['attrs'].append(s)
notes = dict(re.findall(r'note right of (\w+)\n\s*(.+?)\nend note', PUML))
edges = []
for line in PUML.splitlines():
    m = re.match(r'(\w+)\s+(?:"([^"]*)"\s+)?(<\|--|<\|\.\.|--)\s+(?:"([^"]*)"\s+)?(\w+)(?:\s*:\s*(.+))?$', line.strip())
    if m:
        a, ma, arrow, mb, b, lab = m.groups()
        if arrow == '--': edges.append({'a': a, 'b': b, 'ma': ma, 'mb': mb, 'label': lab, 'kind': 'assoc'})
        else: edges.append({'a': a, 'b': b, 'kind': 'impl' if '..' in arrow else 'inh'})
assert len(classes) == 11 and len(edges) == 10, (len(classes), len(edges))
edges.append({'a': 'Transaction', 'b': 'TypeTransaction', 'kind': 'type', 'label': 'type'})  # attribut « type : TypeTransaction »

POS = {'Agence': (210, 115), 'Banque': (650, 115), 'Client': (1090, 115), 'Portefeuille': (1530, 115),
       'Transaction': (210, 470), 'CompteBancaire': (870, 470), 'Carte': (1530, 470),
       'TypeTransaction': (210, 820), 'CompteCourant': (650, 820), 'CompteEpargne': (1090, 820), 'IPaiement': (1530, 820)}
LH, HDR = 32, 50
def box_size(c):
    k = classes[c]; n = max([len(x) for x in k['attrs'] + k['ops'] + [k['name'] + ('  «interface»' if k['kind'] == 'interface' else '  «enum»' if k['kind'] == 'enum' else '')]] + [8])
    w = max(300, int(10.8 * n + 40), int(16.5 * len(k['name']) + (110 if k['kind'] in ('interface', 'enum') else 0) + 44))
    h = HDR + (len(k['attrs']) * LH + 14 if k['attrs'] else 0) + (len(k['ops']) * LH + 14 if k['ops'] else 0) + 6
    return w, h
SIZE = {c: box_size(c) for c in classes}
RECT = {c: (POS[c][0] - SIZE[c][0] / 2, POS[c][1] - SIZE[c][1] / 2, SIZE[c][0], SIZE[c][1]) for c in classes}
DW, DH = 1740, 930

def clip(c, toward):
    x, y, w, h = RECT[c]; cx, cy = x + w / 2, y + h / 2; dx, dy = toward[0] - cx, toward[1] - cy
    s = min((w / 2) / abs(dx) if dx else 1e9, (h / 2) / abs(dy) if dy else 1e9)
    return cx + dx * s, cy + dy * s

def diagram(p, cls=''):
    """Le diagramme de classes, rendu depuis le .puml (positions manuelles, contenu 100 % lu)."""
    svg, labels = [], []
    for i, e in enumerate(edges):
        pa, pb = POS[e['a']], POS[e['b']]
        x1, y1 = clip(e['a'], pb); x2, y2 = clip(e['b'], pa)
        dash = ' stroke-dasharray="12 9"' if e['kind'] in ('impl', 'type') else ''
        col = '#8a9a93' if e['kind'] == 'type' else INK
        EG[i] = (x1, y1, x2, y2)
        g = f'<g id="{p}-e{i}" class="edge"><line class="ln" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{col}" stroke-width="4"{dash}/>'
        if e['kind'] in ('inh', 'impl'):      # triangle creux côté parent (a)
            ang = math.atan2(y1 - y2, x1 - x2) if False else math.atan2(y2 - y1, x2 - x1)
            L, W = 30, 17
            bx, by = x1 + math.cos(ang) * L, y1 + math.sin(ang) * L
            px, py = -math.sin(ang) * W, math.cos(ang) * W
            g += f'<polygon class="tri" points="{x1:.1f},{y1:.1f} {bx+px:.1f},{by+py:.1f} {bx-px:.1f},{by-py:.1f}" fill="{PAPER}" stroke="{INK}" stroke-width="4"/>'
        g += '</g>'; svg.append(g)
        ang = math.atan2(y2 - y1, x2 - x1); nx, ny = -math.sin(ang), math.cos(ang)
        if e['kind'] == 'assoc':
            for (qx, qy, txt, f) in ((x1, y1, e['ma'], .13), (x2, y2, e['mb'], .87)):
                if txt:
                    sg = 1 if f < .5 else -1; L_ = math.hypot(x2 - x1, y2 - y1) or 1
                    lx = (x1 if f < .5 else x2) + sg * (x2 - x1) / L_ * 34 + nx * 22; ly = (y1 if f < .5 else y2) + sg * (y2 - y1) / L_ * 34 + ny * 22
                    labels.append(f'<span class="mult" style="left:{lx:.0f}px;top:{ly:.0f}px">{html.escape(txt)}</span>')
        if e.get('label'):
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            labels.append(f'<span id="{p}-l{i}" class="role" style="left:{mx:.0f}px;top:{my:.0f}px">{html.escape(e["label"])}</span>')
    boxes = []
    for c in order:
        k = classes[c]; x, y, w, h = RECT[c]
        title = html.escape(c) + ('<i> «interface»</i>' if k['kind'] == 'interface' else '<i> «enum»</i>' if k['kind'] == 'enum' else '')
        hs = ' abs' if k['kind'] == 'abstract' else ''
        body = ''
        for key, items in (('a', k['attrs']), ('o', k['ops'])):
            if items:
                body += '<div class="sec">' + ''.join(f'<div class="mem" id="{p}-m-{c}-{key}{j}">{html.escape(s)}</div>' for j, s in enumerate(items)) + '</div>'
        boxes.append(f'<div id="{p}-{c}" class="cls" style="left:{x:.0f}px;top:{y:.0f}px;width:{w}px;height:{h}px">'
                     f'<div class="hd{hs}">{title}</div>{body}<b class="bk" id="{p}-{c}-K">✔</b><b class="bp" id="{p}-{c}-P">PHP</b></div>')
    labels = [l for l in labels if 'class="mult"' not in l] + [l for l in labels if 'class="mult"' in l]
    return (f'<div id="{p}-dg" class="dg {cls}" data-layout-ignore data-layout-allow-overlap="true" style="width:{DW}px;height:{DH}px"><svg width="{DW}" height="{DH}">{"".join(svg)}</svg>'
            f'{"".join(boxes)}{"".join(labels)}</div>')

CSS = f'''
@font-face{{font-family:Inter;src:url('assets/fonts/Inter-400.woff2');font-weight:400}}
@font-face{{font-family:Inter;src:url('assets/fonts/Inter-700.woff2');font-weight:700}}
@font-face{{font-family:'JetBrains Mono';src:url('assets/fonts/JetBrainsMono-400.woff2');font-weight:400}}
@font-face{{font-family:'JetBrains Mono';src:url('assets/fonts/JetBrainsMono-700.woff2');font-weight:700}}
*{{box-sizing:border-box}}#root{{position:absolute;inset:0;overflow:hidden;font-family:Inter;color:{INK}}}
.stage{{position:absolute;inset:0;overflow:hidden;background:{PAPER}}}.dark{{background:{INK};color:{PAPER}}}.orange{{background:{ORANGE}}}
h1,h2,h3,p{{margin:0}}.abs{{position:absolute}}
.dg{{position:absolute;left:0;top:0;transform-origin:0 0}}.dg svg{{position:absolute;left:0;top:0;overflow:visible}}
.cls{{position:absolute;background:#fbfcfa;border:3px solid {INK};border-radius:10px;overflow:visible;box-shadow:6px 7px 0 {INK}}}
.hd{{height:{HDR - 3}px;display:flex;align-items:center;padding:0 16px;font-weight:700;font-size:28px;background:#dfe6e1;border-bottom:3px solid {INK};border-radius:7px 7px 0 0;white-space:nowrap}}
.hd i{{font-weight:400;font-size:19px;margin-left:8px}}.hd.abs{{font-style:italic}}
.sec{{padding:7px 14px;border-bottom:2px solid #9aa9a2}}.sec:last-of-type{{border-bottom:0}}
.mem{{font-size:20px;line-height:{LH}px;height:{LH}px;white-space:nowrap;border-radius:5px;padding:0 4px;margin:0 -4px}}
.mult{{position:absolute;transform:translate(-50%,-50%);font-size:22px;font-weight:700;background:{PAPER};padding:0 4px;color:{INK}}}
.role{{position:absolute;transform:translate(-50%,-50%);font-size:20px;background:{PAPER};padding:1px 8px;border:2px solid #9aa9a2;border-radius:12px;font-style:italic}}
.bk{{position:absolute;top:-17px;right:8px;font-size:19px;padding:1px 12px;border-radius:12px;background:{LIME};color:{INK};border:2px solid {INK};opacity:0}}
.bj,.bp{{position:absolute;top:-17px;font-size:17px;padding:2px 10px;border-radius:12px;background:{INK};color:{LIME};opacity:0}}
.bj{{right:70px}}.bp{{right:6px;color:{PAPER};background:#5a4fcf}}
.st{{position:absolute;left:-14px;right:-14px;top:46%;height:9px;background:{INK};display:block;text-decoration:none;opacity:1}}
.st.o{{background:{ORANGE};top:62%}}
.win{{position:absolute;background:{INK};color:{PAPER};border-radius:18px;border:3px solid #57675f;overflow:hidden;box-shadow:10px 12px 0 rgba(24,33,31,.35)}}
.win .tb{{height:54px;display:flex;align-items:center;gap:10px;padding:0 22px;background:#26332f;font-size:30px;color:#a8bcb2;border-bottom:2px solid #3b4a45}}
.win .tb s{{width:15px;height:15px;border-radius:50%;background:#57675f;display:inline-block}}
.mono{{font-family:'JetBrains Mono';white-space:pre}}.code{{font-family:'JetBrains Mono';font-size:34px;line-height:46px;white-space:pre-wrap;word-break:break-word}}
.kw{{color:#ff916e}}.ty{{color:{LIME}}}.cm{{color:#8fa59b}}.lime{{color:{LIME}}}.or{{color:{ORANGE}}}.mu{{color:#a8bcb2}}
.hl{{display:block;margin:0 -18px;padding:0 18px;border-left:8px solid transparent;border-radius:4px}}
.tag{{display:inline-block;padding:10px 22px;background:{INK};color:{PAPER};font-size:30px;font-weight:700;border-radius:8px}}
.chip{{position:absolute;font-size:30px;font-weight:700;padding:10px 24px;border-radius:30px;background:{INK};color:{PAPER}}}
.sub{{position:absolute;left:0;right:0;bottom:30px;display:flex;justify-content:center;pointer-events:none;z-index:50}}
.sub span{{position:absolute;bottom:0;max-width:1640px;text-align:center;font-size:36px;line-height:1.2;font-weight:700;background:rgba(24,33,31,.95);color:{PAPER};padding:8px 26px;border-radius:12px;opacity:0}}
'''

# ================================================================ sous-titres / scène
def subs(n):
    """Un sous-titre par bloc du script (texte affiché sans balises), calé sur les pauses réelles de la voix."""
    out = []; bl = BLOCKS[n]; i = 0
    while i < len(bl):
        a, b = CUES[n][i]; txt = bl[i][0]
        while b - a < 1.5 and i + 1 < len(bl):
            i += 1; b = CUES[n][i][1]; txt += ' ' + bl[i][0]
        out.append((a, min(b + .2, DUR[n] - .05), txt)); i += 1
    return out

def sub_html_js(n, sid):
    items = subs(n)
    if n == 10: items = items[:-1]          # la note du bas EST le dernier sous-titre : pas de doublon
    h = '<div class="sub">'; js = ''
    for i, (a, b, c) in enumerate(items):
        h += f'<span id="{sid}-s{i}">{html.escape(c)}</span>'
        js += (f"tl.fromTo('#{sid}-s{i}',{{opacity:0}},{{opacity:1,duration:.3,ease:'none'}},{a:.3f});"
               f"tl.to('#{sid}-s{i}',{{opacity:0,duration:.3,ease:'none'}},{max(a + .35, b - .3):.3f});\n")
    return h + '</div>', js

def write_srt():
    def ts(x):
        ms = int(round(x * 1000)); return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}'
    out, k = [], 1
    for n in range(1, NS + 1):
        for a, b, c in subs(n):
            out.append(f'{k}\n{ts(START[n]+a)} --> {ts(START[n]+b)}\n{c}\n'); k += 1
    (P / 'UML_Factory_LLM_Marketing_V5.srt').write_text('\n'.join(out), encoding='utf-8')

scenes = []
def scene(n, sid, body, anim, bg=''):
    sh, sj = sub_html_js(n, sid)
    d = DUR[n]
    scenes.append((sid, START[n], d))
    (P / 'compositions' / f'{sid}.html').write_text(
        f'<template><style>{CSS}{CSS2}</style><div id="root" data-composition-id="{sid}" data-duration="{d}" data-width="1920" data-height="1080">'
        f'<div class="stage {bg}">{body}{sh}</div></div><script>\nconst tl=gsap.timeline({{paused:true}});\n{anim}\n{sj}\nwindow.__timelines[\'{sid}\']=tl;\n</script></template>', encoding='utf-8')

CSS2 = f'''
.slot{{position:absolute;width:250px;height:34px;border:3px solid {INK};border-radius:8px;background:#fbfcfa;font-family:'JetBrains Mono';font-size:19px;line-height:28px;padding-left:10px;white-space:nowrap;opacity:0;overflow:hidden}}
.colh{{position:absolute;width:250px;text-align:center;font-weight:700;font-size:30px;padding:6px 0;border-radius:10px;background:{INK};color:{LIME};opacity:0}}
.step{{position:absolute;font-size:30px;font-weight:700;padding:10px 24px;border-radius:30px;border:3px solid {INK};background:{PAPER};color:{INK}}}
.row{{height:46px;line-height:46px;white-space:pre;position:relative;padding-left:14px}}
.tln{{min-height:38px;line-height:38px;font-size:26px;white-space:pre-wrap;word-break:break-word;display:none}}
.card{{position:absolute;border:4px solid {INK};border-radius:16px;background:#fbfcfa;padding:20px 28px;box-shadow:8px 9px 0 {INK}}}
.card h3{{font-size:44px;letter-spacing:-1px}}.card p{{font-size:31px;line-height:1.28;margin-top:8px}}
.okc{{position:absolute;right:22px;top:20px;width:52px;height:52px;border-radius:50%;background:{LIME};color:{INK};font-size:34px;font-weight:700;text-align:center;line-height:50px;border:3px solid {INK};opacity:0}}
.nd{{position:absolute;border:4px solid {INK};border-radius:14px;padding:12px 20px}}
.nd b{{display:block;font-size:38px;letter-spacing:-1px;white-space:nowrap}}.nd span{{display:block;font-size:28px;line-height:1.25;margin-top:4px}}
'''
def dg_tr(x, y, s): return f"x:{x},y:{y},scale:{s}"
_u = [0]
def typer(sel, text, t, dur):
    _u[0] += 1
    return T("const ty@v@={n:0};tl.to(ty@v@,{n:@len@,duration:@d@,ease:'none',onUpdate:()=>{document.querySelector('@sel@').textContent=@txt@.slice(0,Math.round(ty@v@.n))}},@t@);\n",
             v=_u[0], len=len(text), d=round(dur, 3), sel=sel, txt=json.dumps(text, ensure_ascii=False), t=round(t, 3))
def counter(sel, vals_times):
    return ''.join(f"tl.call(()=>{{document.querySelector('{sel}').textContent={json.dumps(v)}}},null,{t:.3f});\n" for v, t in vals_times)

# ---------------------------------------------------------------- frappe « humaine » + sons de clavier
import random
KEYS = []            # (scène, instant dans la scène, 'k' touche | 'e' entrée)
def key(n, t, kind='k'): KEYS.append((n, round(t, 3), kind))
def human_times(text, dur, seed):
    """Instants (relatifs) de chaque caractère : rythme irrégulier, pauses après espaces et ponctuation."""
    rng = random.Random(seed)
    w = []
    for ch in text:
        base = .6 + .8 * rng.random()
        if ch in ' /.-_': base *= 1.5
        if rng.random() < .07: base += 1.1              # petite hésitation
        w.append(base)
    tot = sum(w); acc = 0.0; out = []
    for x in w:
        acc += x; out.append(acc / tot * dur)
    return out
def human_type(n, sel, text, t0, dur, seed=1, prefix='', enter=False, html_fn=None, blink=1.6):
    """Frappe caractère par caractère (curseur ▌ clignotant à la fin ; « entrée » = curseur retiré + son plus marqué)."""
    ts = human_times(text, dur, seed); js = ''
    setter = 'innerHTML' if html_fn else 'textContent'
    def put(t, shown, cursor):
        val = (html_fn(shown) if html_fn else prefix + shown) + ('▌' if cursor else '')
        return f"tl.call(()=>{{document.querySelector('{sel}').{setter}={json.dumps(val, ensure_ascii=False)}}},null,{t:.3f});\n"
    js += put(t0, '', True)
    for k, ct in enumerate(ts, 1):
        t = t0 + ct; js += put(t, text[:k], True); key(n, t, 'k')
    tend = t0 + ts[-1]
    if enter:
        js += put(tend + .3, text, False); key(n, tend + .3, 'e')
    else:
        for j in range(int(blink / .5)):
            js += put(tend + .5 * (j + 1), text, j % 2 == 1)
    return js
def width_type(n, sel, text, t0, dur, seed=1):
    """Même frappe, pour une ligne révélée par sa largeur (conserve la coloration syntaxique) + curseur au bout."""
    ts = human_times(text, dur, seed); js = f"tl.set('{sel}',{{borderRightColor:'{ORANGE}'}},{t0:.3f});\n"
    for k, ct in enumerate(ts, 1):
        js += f"tl.set('{sel}',{{width:'{k}ch'}},{t0 + ct:.3f});\n"; key(n, t0 + ct, 'k')
    js += f"tl.set('{sel}',{{borderRightColor:'transparent'}},{t0 + ts[-1] + .15:.3f});\n"; key(n, t0 + ts[-1] + .15, 'e')
    return js
def make_keys(path, total):
    """Piste de sons de touches (synthèse locale, volume bas) : clic court ; entrée plus marquée."""
    rate = 48000; rng = random.Random(5); buf = [0.0] * int(total * rate)
    for n, t, kind in KEYS:
        t_abs = START[n] + t; i0 = int(t_abs * rate)
        if kind == 'e': ln, amp, f0 = int(.05 * rate), .55, 150
        else: ln, amp, f0 = int(.016 * rate), .30 + .12 * rng.random(), 1700 + rng.randint(-250, 250)
        for k in range(ln):
            if i0 + k >= len(buf): break
            env = math.exp(-k / (ln / 5)); noise = rng.uniform(-1, 1)
            buf[i0 + k] += amp * env * (.6 * noise + .6 * math.sin(2 * math.pi * f0 * k / rate))
    pk = max(1e-9, max(abs(x) for x in buf)) if buf else 1
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(b''.join(int(max(-1, min(1, x / max(1, pk))) * 32000 * .9).to_bytes(2, 'little', signed=True) for x in buf))
def edge_draw(p, t0, dur=.5, step=.1):
    """Arêtes du diagramme qui se tracent depuis l'enfant (ou la source) vers le parent ; le triangle apparaît puis s'éclaire."""
    js = ''
    for i, e in enumerate(edges):
        x1, y1, x2, y2 = EG[i]; t = t0 + i * step
        js += f"tl.set('#{p}-e{i} .ln',{{attr:{{x1:{x2:.1f},y1:{y2:.1f}}}}},0);\n"
        js += f"tl.to('#{p}-e{i} .ln',{{attr:{{x1:{x1:.1f},y1:{y1:.1f}}},duration:{dur},ease:'power2.out'}},{t:.3f});\n"
        if e['kind'] in ('inh', 'impl'):
            js += (f"tl.set('#{p}-e{i} .tri',{{opacity:0,transformOrigin:'{x1:.1f}px {y1:.1f}px',scale:.3}},0);\n"
                   f"tl.to('#{p}-e{i} .tri',{{opacity:1,scale:1,duration:.22,ease:'back.out(2)'}},{t + dur - .05:.3f});\n"
                   f"tl.fromTo('#{p}-e{i} .tri',{{fill:'{ORANGE}'}},{{fill:'{PAPER}',duration:.7}},{t + dur:.3f});\n")
    return js
def jhl(s):
    s = html.escape(s).replace('/*', '/&#42;')
    return re.sub(r'\b(public|private|abstract|class|final|void|boolean|double|String|if|return|new|extends|implements|interface|enum|function|namespace)\b', r'<span class="kw">\1</span>', s)
def read(p): return (OUT / p).read_text(encoding='utf-8').splitlines()
def find(lines_, pat, n=1, before=0):
    for i, l in enumerate(lines_):
        if re.search(pat, l): return lines_[i - before:i + n]
    raise KeyError(pat)
def codeblock(lines_, hl=None, col=None):
    out = ''
    for l in lines_:
        on = hl and col and re.search(hl, l)
        st = f' style="border-left-color:{col};background:{col}38"' if on else ''
        out += f'<span class="hl"{st}>{jhl(l) if l.strip() else "&nbsp;"}</span>'
    return out
def win(id_, x, y, w, h, title, inner, extra=''):
    return (f'<div id="{id_}" class="win" style="left:{x}px;top:{y}px;width:{w}px;height:{h}px;{extra}"><div class="tb"><s></s><s></s><s></s>&nbsp;{title}</div>{inner}</div>')

SMALL_ = (40, 190, .5)          # diagramme réduit, gauche
BIG = (281, 190, .78)
CLS_IDX = {c: i for i, c in enumerate(order)}
EXT = {'J': '.java', 'Y': '.py', 'P': '.php'}

# ================================================================ S1 PROBLÈME
c = lambda i: cue(1, i)
body = f'''<div id="s1-bg" class="abs" style="inset:0">{diagram('s1')}</div>
<h1 id="s1-t1" class="abs" style="left:96px;top:26px;font-size:84px;letter-spacing:-4px;line-height:1.05;white-space:nowrap"><span id="s1-a">11 classes.</span> <span id="s1-b" class="or">Votre conception est prête.</span></h1>
<div id="s1-t2" class="abs" style="left:96px;top:250px;background:{INK};color:{PAPER};padding:22px 40px;border-radius:14px;box-shadow:10px 12px 0 {ORANGE}">
<div style="font-size:78px;font-weight:700;letter-spacing:-3px;line-height:1.05">Maintenant,<br>il faut tout retaper.</div>
<div class="mono" style="font-size:36px;margin-top:18px;color:{LIME}">11 classes × 3 langages = <span id="s1-n">0</span> fichiers</div></div>
<div id="s1-chip" class="chip" style="left:96px;top:122px;font-size:28px;background:{PAPER};color:{INK};border:3px solid {INK}">examples/banque_grand.puml</div>'''
anim = T('''tl.set('#s1-dg',{@big@},0);
tl.fromTo('#s1-dg .cls',{y:40,opacity:0},{y:0,opacity:1,duration:.5,stagger:.06,ease:'power3.out'},.1);
tl.fromTo('#s1-a',{x:-120,opacity:0},{x:0,opacity:1,duration:.5,ease:'expo.out'},@c0@);
tl.fromTo('#s1-b',{x:-60,opacity:0},{x:0,opacity:1,duration:.5,ease:'expo.out'},@c1@);
tl.fromTo('#s1-chip',{opacity:0},{opacity:1,duration:.4},@c1@);
tl.to('#s1-dg .cls',{y:-8,duration:.22,yoyo:true,repeat:1,stagger:.12,ease:'power2.out'},@c1b@);
tl.to('#s1-t1,#s1-chip',{opacity:0,duration:.35},@c2m@);
tl.to('#s1-dg',{@small@,duration:.7,ease:'power3.inOut'},@c2m@);
tl.fromTo('#s1-t2',{x:-80,opacity:0},{x:0,opacity:1,duration:.45,ease:'power4.out'},@c2@);
const c1={v:0};tl.to(c1,{v:33,duration:1.3,ease:'steps(33)',onUpdate:()=>{document.querySelector('#s1-n').textContent=Math.round(c1.v)}},@c2n@);
''', big=dg_tr(*BIG), small=dg_tr(900, 120, .54), c0=c(0) - .1, c1=c(1) - .05, c1b=c(1) + .4, c2m=c(2) - .45, c2=c(2) + .15, c2n=c(2) + 1.4)
scene(1, 's1', body, anim + edge_draw('s1', .7))

# ================================================================ S2 SANS L'OUTIL : redondance
cc = lambda i: cue(2, i)
real_java = read('java/CompteBancaire.java')
typed = [l for l in real_java if l.strip() and not l.startswith(('import', '/**', ' *', ' */'))]
typed = [l for l in typed if len(l) <= 40][:7]
tyhtml = ''.join(f'<div id="s2-L{i}" style="height:44px;overflow:hidden;white-space:pre;width:0;box-sizing:content-box;border-right:3px solid transparent">{jhl(l)}</div>' for i, l in enumerate(typed))
COLX = {'J': 1000, 'Y': 1270, 'P': 1540}; ROW0, ROWH = 205, 40
D2 = SMALL_
def center_page(cl, tr):
    x, y, w, h = RECT[cl]; return tr[0] + (x + w / 2) * tr[2], tr[1] + (y + h / 2) * tr[2]
def arrow_geom(cl, tgt_page, tr):
    tgt_d = ((tgt_page[0] - tr[0]) / tr[2], (tgt_page[1] - tr[1]) / tr[2])
    sx, sy = clip(cl, tgt_d); return tr[0] + sx * tr[2], tr[1] + sy * tr[2]
slots = ''; arrows = ''
for col in 'JYP':
    for i, cl in enumerate(order):
        sx_, sy_ = COLX[col], ROW0 + i * ROWH
        slots += f'<div id="s2-sl-{col}{i}" class="slot" style="left:{sx_}px;top:{sy_}px;border-left:10px solid {dict(J=LIME,Y=GOLD,P="#5a4fcf")[col]}">{cl}{EXT[col]}</div>'
        x1, y1 = arrow_geom(cl, (sx_ - 4, sy_ + 17), D2); x2, y2 = sx_ - 4, sy_ + 17
        ang = math.atan2(y2 - y1, x2 - x1); L, W = 22, 11
        bx, by = x2 - math.cos(ang) * L, y2 - math.sin(ang) * L; px, py = -math.sin(ang) * W, math.cos(ang) * W
        arrows += (f'<path id="s2-a-{col}{i}" d="M{x1:.1f} {y1:.1f} L{bx:.1f} {by:.1f}" pathLength="1" stroke="{ORANGE}" stroke-width="4" fill="none" stroke-dasharray="1 1" stroke-dashoffset="1" opacity="0"/>'
                   f'<polygon id="s2-ah-{col}{i}" points="{x2:.1f},{y2:.1f} {bx+px:.1f},{by+py:.1f} {bx-px:.1f},{by-py:.1f}" fill="{ORANGE}" opacity="0"/>')
heads = ''.join(f'<div id="s2-h-{col}" class="colh" style="left:{COLX[col]}px;top:140px;color:{dict(J=LIME,Y=GOLD,P="#c9c2ff")[col]}">{dict(J="Java",Y="Python",P="PHP")[col]}</div>' for col in 'JYP')
body = f'''<div class="abs" style="inset:0">{diagram('s2')}</div>
<svg class="abs" style="left:0;top:0;pointer-events:none" width="1920" height="1080">{arrows}</svg>
{heads}{slots}
{win('s2-win', 960, 120, 900, 560, 'CompteBancaire.java · frappe ×8', f'<div class="code" style="padding:22px 22px;font-size:30px">{tyhtml}</div>')}
<div id="s2-cnt" class="abs mono" style="left:40px;top:716px;font-size:38px">recopiés à la main : <b id="s2-n" class="or">0</b></div>
<div id="s2-same" class="abs" style="left:1000px;top:690px;font-size:50px;font-weight:700;letter-spacing:-2px;line-height:1.1">Même diagramme.<br><span class="or">Trois fois le même travail.</span></div>
<div id="s2-est" class="abs" style="left:40px;top:790px;width:880px;font-size:30px;line-height:1.3;border-left:8px solid {ORANGE};padding-left:22px"><b>ESTIMATION, pas une mesure</b> : des heures de frappe, sans compter les erreurs.</div>'''
a = T("tl.set('#s2-dg',{x:900,y:120,scale:.54},0);\ntl.to('#s2-dg',{@d@,duration:.7,ease:'power3.inOut'},.1);\ntl.fromTo('#s2-win',{x:300,opacity:0},{x:0,opacity:1,duration:.5,ease:'expo.out'},.2);\ntl.fromTo('#s2-cnt',{opacity:0},{opacity:1,duration:.4},.8);\n", d=dg_tr(*D2))
# frappe réelle de CompteBancaire (la classe est « développée » puis envoyée)
tt = .8; cbi = CLS_IDX['CompteBancaire']
a += "tl.set('#s2-CompteBancaire .hd',{backgroundColor:'%s'},.7);tl.to('#s2-CompteBancaire',{scale:1.1,duration:.3,ease:'back.out(2)'},.7);\n" % ORANGE
for i, l in enumerate(typed):
    d = max(.18, len(l) / 36)
    a += width_type(2, f'#s2-L{i}', l, tt, d, seed=100 + i); tt += d + .12
tend = max(tt + .2, cc(1) - 1.0)
# la fenêtre se « range » en fichier : flèche CompteBancaire → fichier Java
cb_slot = (COLX['J'], ROW0 + cbi * ROWH)
a += T("tl.to('#s2-win',{x:@dx@,y:@dy@,scaleX:.278,scaleY:.06,transformOrigin:'0 0',duration:.55,ease:'power3.inOut'},@t@);\ntl.to('#s2-win',{opacity:0,duration:.15},@t2@);\n",
       dx=cb_slot[0] - 960, dy=cb_slot[1] - 120, t=tend, t2=tend + .45)
a += T("tl.to('#s2-CompteBancaire',{scale:1,duration:.25},@t@);tl.set('#s2-CompteBancaire .hd',{backgroundColor:'#dfe6e1'},@t@);\n", t=tend + .3)
a += T("tl.fromTo('#s2-h-J',{opacity:0,y:-20},{opacity:1,y:0,duration:.3},@t@);\n", t=tend)
count = 0; cnt_calls = []
def proc(col, i, t):
    global count, a
    cl = order[i]; count += 1
    a += (f"tl.set('#s2-{cl} .hd',{{backgroundColor:'{ORANGE}'}},{t:.3f});tl.set('#s2-{cl} .hd',{{backgroundColor:'#dfe6e1'}},{t+.28:.3f});\n"
          f"tl.to('#s2-{cl}',{{scale:1.09,duration:.1,yoyo:true,repeat:1}},{t:.3f});\n"
          f"tl.set('#s2-a-{col}{i}',{{opacity:1}},{t:.3f});tl.to('#s2-a-{col}{i}',{{strokeDashoffset:0,duration:.16,ease:'power2.out'}},{t:.3f});\n"
          f"tl.fromTo('#s2-ah-{col}{i}',{{opacity:0}},{{opacity:1,duration:.05}},{t+.15:.3f});\n"
          f"tl.fromTo('#s2-sl-{col}{i}',{{opacity:0,x:-14}},{{opacity:1,x:0,duration:.18}},{t+.15:.3f});\n"
          f"tl.to('#s2-a-{col}{i},#s2-ah-{col}{i}',{{opacity:0,duration:.2}},{t+.3:.3f});\n")
    cnt_calls.append((count, t + .15))
# passe Java (la classe CompteBancaire est déjà rangée par la fenêtre)
cnt_calls.append((1, tend + .5)); count = 1
t = max(cc(1) + .1, tend + .6); step = max(.12, (cc(2) - .5 - t) / (NS - 1))
for i in range(NS):
    if i == cbi: continue
    proc('J', i, t); t += step
a += "tl.set('#s2-dg .bk',{opacity:0},0);\n"
for cl in order: a += f"tl.fromTo('#s2-{cl}-K',{{opacity:0,scale:.4}},{{opacity:1,scale:1,duration:.2}},{t:.3f});\n"
# passe Python puis PHP : plus vite, même diagramme
t = cc(2) + .1
a += f"tl.fromTo('#s2-h-Y',{{opacity:0,y:-20}},{{opacity:1,y:0,duration:.3}},{t - .1:.3f});\n"
step = max(.08, (cc(3) - .8 - t - .5) / (2 * NS))
for i in range(NS): proc('Y', i, t); t += step
a += f"tl.fromTo('#s2-h-P',{{opacity:0,y:-20}},{{opacity:1,y:0,duration:.3}},{t:.3f});\n"; t += .15
for i in range(NS): proc('P', i, t); t += step
a += counter('#s2-n', cnt_calls)
a += T("tl.to('#s2-cnt',{scale:1.25,transformOrigin:'0 50%',duration:.3,ease:'back.out(2)'},@t@);\ntl.fromTo('#s2-same',{x:60,opacity:0},{x:0,opacity:1,duration:.5,ease:'power3.out'},@t@);\ntl.fromTo('#s2-est',{opacity:0},{opacity:1,duration:.4},@t3@);\n",
       t=cc(3) + .1, t3=cc(3) + 1.2)
scene(2, 's2', body, a)

# ================================================================ S3 MARQUE
cc = lambda i: cue(3, i)
body = f'''<div class="abs" data-layout-allow-overlap="true" style="inset:0">{diagram('s3')}</div>
<div id="s3-veil" class="abs" style="inset:0;background:{ORANGE};opacity:0"></div>
<div id="s3-grp" class="abs" style="inset:0">
<h1 id="s3-uml" class="abs" style="left:110px;top:150px;font-size:190px;letter-spacing:-10px;line-height:.95;color:{INK};white-space:nowrap">UML Factory</h1>
<div id="s3-llm" class="abs" style="left:1330px;top:170px;font-size:96px;font-weight:700;letter-spacing:-5px;padding:16px 34px;background:{INK};color:{PAPER};border-radius:8px">LLM</div>
<p id="s3-p" class="abs" style="left:116px;top:480px;font-size:84px;font-weight:700;letter-spacing:-3px;line-height:1.12;color:{INK}">Votre diagramme PlantUML.<br><span style="background:{INK};color:{LIME};padding:0 20px">Le code, écrit et vérifié.</span></p>
<div id="s3-tags" class="abs" style="left:116px;top:790px;display:flex;gap:18px"><span class="tag">Java</span><span class="tag">Python</span><span class="tag" style="background:transparent;color:{INK};border:3px dashed {INK}">Autre langage…</span></div></div>'''
anim = T('''tl.set('#s3-dg',{@d@,opacity:1},0);
tl.set('#s3-dg .bk',{opacity:1},0);tl.to('#s3-dg .bk',{opacity:0,duration:.3},.2);
tl.to('#s3-dg',{@big@,duration:.7,ease:'power3.inOut'},.2);
tl.fromTo('#s3-veil',{opacity:0},{opacity:.97,duration:.7,ease:'power2.out'},.3);
tl.fromTo('#s3-uml',{y:-60,opacity:0},{y:0,opacity:1,duration:.55,ease:'back.out(1.1)'},@c0@);
tl.fromTo('#s3-llm',{scale:2.6,rotation:10,opacity:0},{scale:1,rotation:0,opacity:1,duration:.5,ease:'power4.out'},@c0b@);
tl.fromTo('#s3-p',{opacity:0,y:40},{opacity:1,y:0,duration:.6,ease:'power3.out'},@c1@);
tl.fromTo('#s3-tags',{opacity:0},{opacity:1,duration:.4},@c1t@);
tl.to('#s3-veil',{opacity:0,duration:.6,ease:'power2.inOut'},@end@);
tl.to('#s3-grp',{opacity:0,duration:.6},@end@);
''', d=dg_tr(*SMALL_), big=dg_tr(*BIG), c0=.6, c0b=max(.9, cc(0) + .5), c1=cc(1), c1t=cc(1) + 2.2, end=DUR[3] - .75)
scene(3, 's3', body, anim + edge_draw('s3', .3, .08))

# ================================================================ S4 FONCTIONNEMENT interactif (générique)
cc = lambda i: cue(4, i)
JL = []; seen = False
for r in RUN:
    s = r.get('line')
    if s is None or not s.strip(): continue
    if "plus d'une seconde" in s or 'PHP' in s or '.php' in s or 'Durée' in s: continue
    if 'Conforme' in s:
        if seen: continue
        seen = True
    s = re.sub(r'(dans|→) [A-Z]:\\.*$', r'\1 …\\sortie', s)
    JL.append([r['t'], s])
tmax = 43.6
for k_, it in enumerate(JL):
    if it[0] > tmax: it[0] = tmax + .15 * (k_ - len(JL))   # résumé final regroupé à la fin du journal Java
JL.sort(key=lambda z: z[0])
T0 = cc(3) + 2.3; span = max(3.0, CUES[4][3][1] - T0 - .4)
SC = span / (JL[-1][0] - JL[0][0]); ACC = 1 / SC
def mt(tj): return T0 + (tj - JL[0][0]) * SC
logs = ''; lanim = ''; nlit = 0; litcalls = []
for i, (tj, s) in enumerate(JL):
    col = 'lime' if s.lstrip().startswith('✔') or 'Conforme' in s else ('mu' if s.startswith('Java :') or s.startswith(' ') and 'caract' not in s else '')
    logs += f'<div class="tln {col}" id="s4-T{i}">{html.escape(s)}</div>'
    lanim += f"tl.set('#s4-T{i}',{{display:'block'}},{mt(tj):.3f});\n"
    m = re.match(r'\s*✔\s+(\w+)\.java', s)
    if m and m.group(1) in classes:
        cl = m.group(1); nlit += 1; t_ = mt(tj)
        lanim += (f"tl.set('#s4-{cl} .hd',{{backgroundColor:'{LIME}'}},{t_:.3f});tl.fromTo('#s4-{cl}-K',{{opacity:0,scale:.4}},{{opacity:1,scale:1,duration:.2}},{t_:.3f});\n"
                  f"tl.fromTo('#s4-{cl}',{{scale:1.07}},{{scale:1,duration:.3}},{t_:.3f});\n")
        litcalls.append((f"{nlit}", t_))
assert nlit == 11, nlit
S4_EVENTS = [t_ for _, t_ in litcalls]
menu1 = ('banque_grand.puml', 'model.puml', 'Autre fichier…')
panel1 = f'''<div id="s4-p1" class="abs mono" style="left:0;top:54px;right:0;bottom:0;padding:26px 30px;font-size:30px">
<div class="mu" style="margin-bottom:14px">Quel diagramme convertir ?</div>
<div id="s4-sel1" class="abs" style="left:30px;right:30px;top:86px;height:46px;border-radius:8px;background:#2f4a42"></div>
<div class="row" style="margin-top:6px;position:relative"><span id="s4-m1a">examples/banque_grand.puml</span></div>
<div class="row"><span class="mu">examples/model.puml</span></div>
<div class="row"><span class="mu">Autre fichier…</span></div>
<div id="s4-ok1" class="lime" style="margin-top:20px;opacity:0">✔  examples/banque_grand.puml</div></div>'''
panel1 = panel1.replace('\n', '')
panel2 = f'''<div id="s4-p2" class="abs mono" style="left:0;top:54px;right:0;bottom:0;padding:26px 30px;font-size:30px;opacity:0">
<div class="mu" style="margin-bottom:14px">Langage(s) cible(s) ?  <span class="mu" style="font-size:24px">(espace = cocher)</span></div>
<div id="s4-sel2" class="abs" style="left:30px;right:30px;top:86px;height:46px;border-radius:8px;background:#2f4a42"></div>
<div class="row" style="margin-top:6px"><span id="s4-lA"></span></div>
<div class="row"><span id="s4-lB"></span></div>
<div class="row"><span class="mu" id="s4-lC">[ ] Autre langage… (ajouter)</span></div>
<div id="s4-ok2" class="lime" style="margin-top:20px;opacity:0">✔  1 langage choisi : Java</div></div>'''
panel2 = panel2.replace('\n', '')
panel3 = f'''<div id="s4-p3" class="abs mono" style="left:0;top:54px;right:0;bottom:0;opacity:0">
<div id="s4-cmdline" class="abs" style="left:20px;right:20px;top:14px;font-size:22px;color:#a8bcb2"><span class="or">$</span> <span id="s4-cmdtx"></span></div>
<div id="s4-log" class="abs" style="left:0;right:0;top:54px;bottom:0;overflow:hidden;padding:0 20px 14px;display:flex;flex-direction:column;justify-content:flex-end">{logs}</div></div>'''
panel3 = panel3.replace('\n', '')
steps = ''.join(f'<span id="s4-st{i}" class="step" style="left:{40 + i * 330}px;top:40px;opacity:0">{lab}</span>' for i, lab in enumerate(['① Diagramme', '② Langage cible', '③ Lancer']))
body = f'''<div class="abs" style="inset:0">{diagram('s4')}</div>{steps}
{win('s4-win', 1000, 100, 860, 770, 'terminal', panel1 + panel2 + panel3)}
<div id="s4-cnts" class="abs mono" style="left:40px;top:690px;font-size:52px;font-weight:700;line-height:1.35">Fichiers <span id="s4-cj" class="or">0</span>/11</div>
<div id="s4-acc" class="chip" style="left:40px;top:790px;background:{ORANGE};font-size:26px">journal réel · accéléré ×{ACC:.1f}</div>
'''
a = T('''tl.set('#s4-dg',{@big@,opacity:1},0);
tl.to('#s4-dg',{@d@,opacity:.12,duration:.7,ease:'power3.inOut'},.1);
tl.fromTo('#s4-win',{x:300,opacity:0},{x:0,opacity:1,duration:.5,ease:'expo.out'},.3);
tl.fromTo('#s4-st0',{y:-30,opacity:0},{y:0,opacity:1,duration:.4},@c0@);
tl.fromTo('#s4-st1',{y:-30,opacity:0},{y:0,opacity:1,duration:.4},@c0b@);
tl.fromTo('#s4-st2',{y:-30,opacity:0},{y:0,opacity:1,duration:.4},@c0c@);
tl.set('#s4-st0',{backgroundColor:'@lime@'},@c1@);tl.set('#s4-st0',{backgroundColor:'@paper@'},@c2@);
tl.set('#s4-st1',{backgroundColor:'@lime@'},@c2@);tl.set('#s4-st1',{backgroundColor:'@paper@'},@c3@);
tl.set('#s4-st2',{backgroundColor:'@lime@'},@c3@);
tl.fromTo('#s4-sel1',{opacity:0},{opacity:1,duration:.3},@c1a@);
tl.to('#s4-m1a',{color:'@lime@',duration:.2},@c1e@);
tl.to('#s4-sel1',{backgroundColor:'#3d6a38',duration:.2},@c1e@);
tl.fromTo('#s4-ok1',{opacity:0,y:10},{opacity:1,y:0,duration:.3},@c1e@);
tl.to('#s4-dg',{opacity:1,duration:.6},@c1e@);
tl.to('#s4-p1',{opacity:0,duration:.3},@c2m@);
tl.to('#s4-p2',{opacity:1,duration:.3},@c2m@);
tl.fromTo('#s4-ok2',{opacity:0,y:10},{opacity:1,y:0,duration:.3},@c2a@);
tl.to('#s4-sel2',{backgroundColor:'#3d6a38',duration:.2},@c2a@);
tl.to('#s4-sel2',{y:46,backgroundColor:'#2f4a42',duration:.25},@c2b@);
tl.to('#s4-sel2',{y:0,duration:.25},@c2b3@);
tl.to('#s4-p2',{opacity:0,duration:.3},@c3m@);
tl.to('#s4-p3',{opacity:1,duration:.3},@c3m@);
''', d=dg_tr(40, 150, .52), big=dg_tr(*BIG), lime=LIME, paper=PAPER, c0=cc(0) + .2, c0b=cc(0) + .9, c0c=cc(0) + 1.5, c1=cc(1), c2=cc(2), c3=cc(3),
   c1a=cc(1) + .5, c1e=cc(1) + 1.6, c2m=cc(2) - .45, c2a=cc(2) + 1.0, c2b=cc(2) + 2.3, c2b2=cc(2) + 2.7, c2b3=cc(2) + 3.9, c3m=cc(3) - .35)
a += counter('#s4-lA', [('[ ] Java', 0.01), ('[x] Java', cc(2) + 1.0)]) + counter('#s4-lB', [('[ ] Python', 0.01), ('[x] Python', cc(2) + 2.7), ('[ ] Python', cc(2) + 3.9)])
a += lanim + counter('#s4-cj', litcalls)
a += human_type(4, '#s4-cmdtx', 'python -m umlfactory.cli examples/banque_grand.puml', cc(3) + .3, 1.7, seed=7, enter=True)
for _t, _k in ((cc(1) + 1.6, 'e'), (cc(2) + 1.0, 'k'), (cc(2) + 2.3, 'k'), (cc(2) + 2.7, 'k'), (cc(2) + 3.9, 'k'), (cc(3) - .35, 'e')): key(4, _t, _k)
scene(4, 's4', body, a)

# ================================================================ S5 PREUVE (exemple Java)
cc = lambda i: cue(5, i)
jcc = find(read('java/CompteCourant.java'), r'^public class CompteCourant', 9)
jca = find(read('java/Carte.java'), r'^public class Carte', 1)
jpay = find(read('java/Carte.java'), r'@Override', 7)
jcalc = find(read('java/CompteEpargne.java'), r'public double calculerInterets', 3)
jbc1 = find(read('java/CompteBancaire.java'), r'private final List<Carte>', 2)
BEATS = [
 ('Héritage → extends', ['CompteBancaire', 'CompteCourant'], ORANGE,
  [('#{p}-e0 .ln', 'stroke'), ('#{p}-e0 .tri', 'fill'), ('#{p}-CompteCourant', 'box'), ('#{p}-CompteBancaire .hd', 'hd')],
  [('exemple en Java', jcc[:1], ORANGE)], 'extends'),
 ('Interface → implements', ['IPaiement', 'Carte'], '#e6b800',
  [('#{p}-e2 .ln', 'stroke'), ('#{p}-e2 .tri', 'fill'), ('#{p}-IPaiement', 'box'), ('#{p}-m-IPaiement-o0', 'mem'), ('#{p}-m-Carte-o0', 'mem')],
  [('exemple en Java', jca + [''] + jpay[:3], '#e6b800')], 'implements|@Override'),
 ('Attributs → champs + accesseurs', ['CompteEpargne', 'CompteCourant'], TEAL,
  [('#{p}-m-CompteCourant-a0', 'mem'), ('#{p}-m-CompteEpargne-a0', 'mem'), ('#{p}-m-CompteEpargne-o0', 'mem'), ('#{p}-CompteCourant', 'box'), ('#{p}-CompteEpargne', 'box')],
  [('CompteCourant.java', [jcc[1]] + find(read('java/CompteCourant.java'), r'public double getDecouvert', 3) + find(read('java/CompteCourant.java'), r'public void setDecouvert', 3), TEAL), ('CompteEpargne.java', jcalc[:3], TEAL)],
  'decouvertAutorise|tauxInteret|getSolde|getDecouvert|setDecouvert'),
 ('Relations → listes', ['Client', 'CompteBancaire', 'Carte'], '#8b7bff',
  [('#{p}-e3 .ln', 'stroke'), ('#{p}-e4 .ln', 'stroke'), ('#{p}-CompteBancaire', 'box')],
  [('exemple en Java', jbc1, '#8b7bff')], r'List<'),
]
PW, PH, PX, PY = 760, 760, 60, 110
def beat_view(targets):
    xs = [RECT[c][0] for c in targets]; ys = [RECT[c][1] for c in targets]
    xe = [RECT[c][0] + RECT[c][2] for c in targets]; ye = [RECT[c][1] + RECT[c][3] for c in targets]
    x0, y0, x1, y1 = min(xs) - 50, min(ys) - 60, max(xe) + 50, max(ye) + 50
    s = min(PW / (x1 - x0), PH / (y1 - y0), 1.45)
    return PX + (PW - (x1 - x0) * s) / 2 - x0 * s, PY + (PH - (y1 - y0) * s) / 2 - y0 * s, s
BEAT_T = [cc(1) - .1, cc(2) - .1, cc(3) - .1, cc(4) - .1]; BEAT_END = BEAT_T[1:] + [DUR[5] - .2]
blocks = ''; banim = ''
for bi, (title, targets, col, hls, codes, hlre) in enumerate(BEATS):
    t0, t1 = BEAT_T[bi], BEAT_END[bi]
    inner = ''
    for lab, cl, cc_ in codes:
        inner += (f'<div style="font-size:30px;color:#a8bcb2;margin:10px 0 2px"><b style="color:{cc_}">●</b> {html.escape(lab)}</div>'
                  f'<div class="code" style="padding-left:20px">{codeblock(cl, hlre, cc_)}</div>')
    blocks += (f'<div id="s5-B{bi}" class="abs" style="left:0;top:0;right:0;opacity:0"><div class="chip" style="position:static;display:inline-block;background:{col};color:{INK};margin-bottom:6px">{bi + 1}/4 · {html.escape(title)}</div>{inner}</div>')
    x, y, s = beat_view(targets)
    banim += f"tl.to('#s5-dg',{{x:{x:.1f},y:{y:.1f},scale:{s:.3f},duration:.6,ease:'power3.inOut'}},{t0 - .2:.2f});\n"
    banim += f"tl.fromTo('#s5-B{bi}',{{opacity:0,x:40}},{{opacity:1,x:0,duration:.4,ease:'power3.out'}},{t0:.2f});\n"
    if bi < len(BEATS) - 1: banim += f"tl.to('#s5-B{bi}',{{opacity:0,duration:.3}},{t1 - .32:.2f});\n"
    for sel, kind in hls:
        sel = sel.replace('{p}', 's5')
        if kind == 'stroke': banim += f"tl.to('{sel}',{{attr:{{stroke:'{col}','stroke-width':9}},duration:.3}},{t0:.2f});tl.to('{sel}',{{attr:{{stroke:'{INK}','stroke-width':4}},duration:.3}},{t1 - .3:.2f});\n"
        elif kind == 'fill': banim += f"tl.to('{sel}',{{attr:{{fill:'{col}'}},duration:.3}},{t0:.2f});tl.to('{sel}',{{attr:{{fill:'{PAPER}'}},duration:.3}},{t1 - .3:.2f});\n"
        elif kind == 'box': banim += f"tl.to('{sel}',{{boxShadow:'0 0 0 8px {col}',duration:.3}},{t0:.2f});tl.to('{sel}',{{boxShadow:'6px 7px 0 {INK}',duration:.3}},{t1 - .3:.2f});\n"
        elif kind == 'hd': banim += f"tl.to('{sel}',{{backgroundColor:'{col}',duration:.3}},{t0:.2f});tl.to('{sel}',{{backgroundColor:'#dfe6e1',duration:.3}},{t1 - .3:.2f});\n"
        else: banim += f"tl.to('{sel}',{{backgroundColor:'{col}',duration:.3}},{t0:.2f});tl.to('{sel}',{{backgroundColor:'rgba(0,0,0,0)',duration:.3}},{t1 - .3:.2f});\n"
body = f'''<div id="s5-panel" class="abs" style="left:0;top:0;width:1920px;height:1080px;clip-path:inset(0 0 0 0)">{diagram('s5')}</div>
<div id="s5-code" class="abs dark" style="left:860px;top:96px;width:964px;height:800px;border-radius:18px;padding:22px 34px;overflow:hidden;box-shadow:10px 12px 0 rgba(24,33,31,.35)">{blocks}</div>'''
anim = T('''tl.set('#s5-dg',{x:40,y:150,scale:.52},0);
tl.set('#s5-dg .hd',{backgroundColor:'@lime@'},0);
tl.set('#s5-dg .bk',{opacity:1},0);
tl.fromTo('#s5-panel',{clipPath:'inset(0px 0px 0px 0px)'},{clipPath:'inset(96px 1090px 170px 40px round 18px)',duration:.7},@p@);
tl.set('#s5-panel',{clipPath:'inset(96px 1090px 170px 40px round 18px)'},@p7@);
tl.fromTo('#s5-code',{x:1000,opacity:0},{x:0,opacity:1,duration:.5,ease:'expo.out'},@cd@);
tl.to('#s5-dg .hd',{backgroundColor:'#dfe6e1',duration:.4},@p@);
tl.to('#s5-dg .bk',{opacity:0,duration:.3},@p@);
''', lime=LIME, p=cc(0) + .5, p7=cc(0) + 1.21, cd=cc(1) - .6) + banim
scene(5, 's5', body, anim)

# ================================================================ S6 ARCHITECTURE (fonctionnelle)
cc = lambda i: cue(6, i)
def nd(id_, x, y, w, h, title, sub='', style=''):
    return f'<div id="{id_}" class="nd" style="left:{x}px;top:{y}px;width:{w}px;height:{h}px;{style}"><b>{title}</b><span>{sub}</span></div>'
body = f'''<h1 class="abs" style="left:96px;top:50px;font-size:84px;letter-spacing:-4px">Sous le capot, <span class="or">trois idées.</span></h1>
<svg class="abs" style="left:0;top:0" width="1920" height="1080" fill="none" stroke="{INK}" stroke-width="5">
<defs><marker id="ah6" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="{INK}" stroke="none"/></marker></defs>
<path id="s6-l1" d="M420 520H520" marker-end="url(#ah6)"/>
<path id="s6-l2" d="M700 640V730" marker-end="url(#ah6)"/>
<path id="s6-l3" d="M940 470H1160" marker-end="url(#ah6)" stroke="{ORANGE}"/><path id="s6-l3b" d="M940 540H1160" marker-end="url(#ah6)" stroke="{ORANGE}"/><path id="s6-l3c" d="M940 610H1160" marker-end="url(#ah6)" stroke="{ORANGE}" stroke-dasharray="14 10"/>
<path id="s6-l4" d="M1480 540H1580" marker-end="url(#ah6)"/></svg>
{nd('s6-cli', 70, 440, 350, 160, 'Interface CLI', 'questions interactives', 'background:#fbfcfa')}
{nd('s6-co', 520, 400, 420, 240, 'Coordinateur', 'répartit le travail', f'background:{LIME}')}
{nd('s6-mcp', 440, 730, 520, 140, 'Serveur MCP', 'lit le .puml · écrit les fichiers', 'background:#fbfcfa')}
{nd('s6-ag1', 1160, 410, 320, 120, 'Agent Java', 'un fichier d\'agent', f'background:{INK};color:{LIME}')}
{nd('s6-ag2', 1160, 480+60, 320, 120, 'Agent Python', 'un fichier d\'agent', 'background:#5a4fcf;color:#fff')}
{nd('s6-new', 1160, 680, 320, 120, 'Votre langage', '= un fichier de plus', 'background:transparent;border-style:dashed')}
{nd('s6-llm', 1580, 410, 270, 390, 'API du LLM', 'écrit chaque fichier à partir du diagramme', f'background:{GOLD}')}
<div id="s6-a2a" class="chip" style="left:960px;top:330px;font-size:30px;background:{PAPER};color:{INK};border:3px solid {INK}">A2A · agent to agent</div>
<div id="s6-note" class="abs" style="left:96px;top:850px;font-size:36px;font-weight:700;border-left:10px solid {LIME};background:{INK};color:{PAPER};padding:10px 24px;border-radius:8px">Le noyau ne change pas : on ajoute un fichier.</div>'''
anim = T('''tl.fromTo('#s6-cli,#s6-co,#s6-mcp',{y:40,opacity:0},{y:0,opacity:1,duration:.45,stagger:.12,ease:'power3.out'},@c0@);
tl.fromTo('#s6-l1,#s6-l2',{opacity:0},{opacity:1,duration:.3,stagger:.1},@c0b@);
tl.fromTo('#s6-ag1,#s6-ag2',{x:140,opacity:0},{x:0,opacity:1,duration:.45,stagger:.15,ease:'expo.out'},@c1@);
tl.fromTo('#s6-l3,#s6-l3b,#s6-a2a',{opacity:0},{opacity:1,duration:.3},@c1b@);
tl.fromTo('#s6-llm',{x:100,opacity:0},{x:0,opacity:1,duration:.45,ease:'expo.out'},@c1b@);tl.fromTo('#s6-l4',{opacity:0},{opacity:1,duration:.3},@c1b@);
tl.to('#s6-co,#s6-ag1,#s6-ag2',{boxShadow:'0 0 0 10px @or@',duration:.3},@c1b@);tl.to('#s6-co,#s6-ag1,#s6-ag2',{boxShadow:'0 0 0 0px @or@',duration:.3},@c2m@);
tl.to('#s6-mcp',{boxShadow:'0 0 0 10px @or@',duration:.3},@c2@);tl.to('#s6-mcp',{boxShadow:'0 0 0 0px @or@',duration:.3},@c3m@);
tl.to('#s6-l2',{attr:{stroke:'@or@','stroke-width':9},duration:.3},@c2@);tl.to('#s6-l2',{attr:{stroke:'@ink@','stroke-width':5},duration:.3},@c3m@);
tl.fromTo('#s6-new',{scale:.85,opacity:0},{scale:1,opacity:1,duration:.5,ease:'back.out(1.3)'},@c3@);tl.fromTo('#s6-l3c',{opacity:0},{opacity:1,duration:.3},@c3@);
tl.to('#s6-new',{boxShadow:'0 0 0 10px @or@',duration:.3},@c3b@);
tl.fromTo('#s6-note',{x:-60,opacity:0},{x:0,opacity:1,duration:.45,ease:'power3.out'},@c3n@);
''', c0=.3, c0b=.9, c1=cc(1), c1b=cc(1) + 1.0, c2m=cc(2) - .3, c2=cc(2), c3m=cc(3) - .3, c3=cc(3), c3b=cc(3) + 1.6, c3n=cc(3) + 3.4, or_=ORANGE, ink=INK, **{'or': ORANGE})
scene(6, 's6', body, anim)

# ================================================================ S7 AJOUT D'UN LANGAGE (PHP absent du menu)
cc = lambda i: cue(7, i)
L7 = [  # (texte, couleur, instant)
 ('Quel est le langage cible ?', 'mu', .3),
 ('', '', .3),
 ('[ ] Java', '', .5), ('[ ] Python', '', .6), ('[ ] Autre langage… (ajouter un nouveau langage)', 'mu', .7),
]
rows = ['Langage(s) cible(s) ?', '  [ ] Java', '  [ ] Python', '  [ ] Autre langage… (ajouter un nouveau langage)']
lines7 = []
def L(text, cls, t): lines7.append((text, cls, t))
tA = cc(1) + 1.9; tB = cc(2)
L('? Nom du langage à ajouter : ', '', cc(1) + .9)
L('✔  Spécification de « PHP » rédigée', 'lime', tB + .4); L('     données uniquement : aucun code, rien d\'exécuté', 'mu', tB + .9)
L('✔  Outils nécessaires présents sur cet appareil', 'lime', tB + 1.8); L('     php', 'mu', tB + 2.1)
L('Contrôle du code PHP généré', 'bold', tB + 3.0)
L('  Cette commande sera lancée sur votre PC :', 'mu', tB + 3.4); L('  php -l {file}', 'cy', tB + 3.8)
L('? Autoriser cette commande ?  [O/n]', 'or', tB + 4.4); L('  O', 'lime', tB + 5.4)
tC = cc(3)
L('Test du nouveau langage PHP', 'bold', tC + .1)
L('  ✔  classe abstraite et héritage', 'lime', tC + .9); L('  ✔  interfaces et réalisation multiple', 'lime', tC + 1.5); L('  ✔  composition, agrégation et association', 'lime', tC + 2.1)
tD = cc(4)
L('✔  PHP validé : 3 diagramme(s) sur 3 conformes — disponible dans le menu.', 'lime', tD + .1)
L('   Fichier créé : umlfactory\\generators\\php.py', 'mu', tD + .9)
lg = ''; la = ''
for i, (tx, cls, t_) in enumerate(lines7):
    lg += f'<div class="tln {"lime" if cls=="lime" else "mu" if cls=="mu" else "or" if cls=="or" else ""}" id="s7-T{i}" style="{"font-weight:700;" if cls=="bold" else ""}{"color:#7fd6ff;" if cls=="cy" else ""}">{html.escape(tx)}</div>'
    la += f"tl.set('#s7-T{i}',{{display:'block'}},{t_:.3f});\n"
panelm = f'''<div id="s7-menu" class="abs mono" style="left:0;top:54px;right:0;padding:22px 26px;font-size:28px">
<div class="mu" style="margin-bottom:10px">Langage(s) cible(s) ?</div>
<div id="s7-sel" class="abs" style="left:26px;right:26px;top:72px;height:44px;border-radius:8px;background:#2f4a42;opacity:0"></div>
<div class="row"><span id="s7-r1">[ ] Java</span></div><div class="row"><span id="s7-r2">[ ] Python</span></div>
<div class="row"><span id="s7-r3" class="mu">[ ] Autre langage… (ajouter un nouveau langage)</span></div>
</div>
<div id="s7-menu2" class="abs mono" style="left:0;top:54px;right:0;padding:22px 26px;font-size:28px;opacity:0"><div class="mu" style="margin-bottom:10px">Langage(s) cible(s) ?</div>
<div class="row">[ ] Java</div><div class="row">[ ] Python</div><div class="row" style="background:#3d6a38;border-radius:8px"><span class="lime">[ ] PHP</span> <span class="or">← nouveau</span></div>
<div class="row"><span class="mu">[ ] Autre langage… (ajouter un nouveau langage)</span></div></div>'''
logbox = f'<div id="s7-log" class="abs mono" style="left:0;top:70px;right:0;bottom:0;padding:0 26px;overflow:hidden">{lg}</div>'
cards7 = f'''<div id="s7-ca" class="nd" style="left:1330px;top:140px;width:500px;height:120px;background:{INK};color:{LIME}"><b>Agent Java</b><span>✔ disponible</span></div>
<div id="s7-cb" class="nd" style="left:1330px;top:290px;width:500px;height:120px;background:#5a4fcf;color:#fff"><b>Agent Python</b><span>✔ disponible</span></div>
<div id="s7-cc" class="nd" style="left:1330px;top:440px;width:500px;height:120px;border-style:dashed;opacity:.7"><b>Agent PHP</b><span id="s7-ccs">absent</span></div>
<div id="s7-nopho" class="chip" style="left:1330px;top:600px;background:{ORANGE};font-size:30px">pas de PHP</div>
<div id="s7-rec" class="abs" style="left:1330px;top:700px;width:520px;font-size:28px;line-height:1.3;color:#44564f">Reconstitution fidèle des étapes de l'outil (spécification, outils, validation) ; fichier réel : <b>generators/php.py</b>.</div>'''
panelm = panelm.replace('\n', '')
body = f'''{win('s7-win', 96, 110, 1180, 790, 'terminal · Autre langage…', panelm + logbox)}{cards7}'''
a = T('''tl.fromTo('#s7-win',{x:-200,opacity:0},{x:0,opacity:1,duration:.5,ease:'expo.out'},.15);
tl.fromTo('#s7-ca,#s7-cb,#s7-cc',{x:140,opacity:0},{x:0,opacity:1,duration:.45,stagger:.12,ease:'expo.out'},.5);
tl.set('#s7-cc',{opacity:.7},1.4);
tl.fromTo('#s7-nopho,#s7-rec',{opacity:0},{opacity:1,duration:.4},@c0@);
tl.fromTo('#s7-sel',{opacity:0,y:0},{opacity:1,y:0,duration:.2},@c1m@);
tl.to('#s7-sel',{y:92,duration:.35,ease:'power2.inOut'},@c1m2@);
tl.to('#s7-sel',{backgroundColor:'#3d6a38',duration:.2},@c1m3@);
tl.to('#s7-menu',{opacity:0,duration:.35},@c1m4@);
tl.to('#s7-nopho',{opacity:0,duration:.3},@c1m3@);
''', c0=cc(0) + 2.2, c1m=cc(1) + .1, c1m2=cc(1) + .45, c1m3=cc(1) + .85, c1m4=cc(1) + .95)
a += la
# nom tapé : on remplace le texte de la ligne T0
a += human_type(7, '#s7-T0', 'PHP', cc(1) + 1.0, .9, seed=3, prefix='? Nom du langage à ajouter : ', enter=True)
key(7, cc(1) + .1, 'k'); key(7, cc(1) + .45, 'k'); key(7, cc(1) + .85, 'e')
a += T('''tl.set('#s7-ccs',{opacity:1},0);
tl.fromTo('#s7-T8',{backgroundColor:'rgba(243,77,40,0)'},{backgroundColor:'rgba(243,77,40,.35)',duration:.3},@tok@);
''', tok=tB + 4.4)
# fin : PHP rejoint le menu
tE = cc(4) + 1.4
a += counter('#s7-ccs', [('absent', 0.01), ('✔ disponible', tE)])
a += T('''tl.to('#s7-cc',{backgroundColor:'@c@',color:'@ink@',borderStyle:'solid',opacity:1,duration:.4},@t@);
tl.to('#s7-cc',{scale:1.06,duration:.25,yoyo:true,repeat:1},@t@);
tl.to('#s7-log',{opacity:0,duration:.3},@t@);tl.fromTo('#s7-menu2',{opacity:0},{opacity:1,duration:.4},@t@);
''', c='#c9c2ff', ink=INK, t=tE)
scene(7, 's7', body, a)

# ================================================================ S8 LE MÊME DIAGRAMME, EN PHP (sortie réelle)
cc = lambda i: cue(8, i)
PEV = []   # événements réels PHP
for r in RUN:
    m = re.match(r'\s*✔\s+(\w+)\.php ', r.get('line') or '')
    if m: PEV.append((r['t'], m.group(1)))
assert len(PEV) == 11
pt0 = PEV[0][0]; span8 = 2.4; k8 = span8 / (PEV[-1][0] - pt0)
tt8 = cc(0) + .9
def snippet(fname, keep, hl):
    """Extrait RÉEL d'un fichier PHP généré (lignes utiles, sans lignes vides)."""
    src = [l for l in read('php/' + fname) if l.strip()]
    lines_ = [l for l in src if keep(l)]
    while lines_ and lines_[-1].strip() == '{': lines_.pop()      # accolade d'une méthode coupée
    if lines_[-1].strip() != '}': lines_.append('}')
    return codeblock(lines_, hl, ORANGE), len(lines_)
SNIP = [('IPaiement.php', lambda l: not l.lstrip().startswith(('/**', '*', '*/')), 'interface'),
        ('CompteCourant.php', lambda l: not l.lstrip().startswith(('/**', '*', '*/')), 'extends'),
        ('Client.php', lambda l: l.startswith('class') or l.strip() == '{' or '@var' in l or 'array' in l or 'Banque' in l, 'list<')]
LINE8 = 34; TB8 = 44; GAP8 = 12
sn_html = ''; sn_y = 96; sn_boxes = []
for i, (fname, keep, hl) in enumerate(SNIP):
    code_, nl_ = snippet(fname, keep, hl)
    h_ = TB8 + nl_ * LINE8 + 18
    sn_html += (f'<div id="s8-sn{i}" class="win" style="left:1000px;top:{sn_y}px;width:860px;height:{h_}px;opacity:0">'
                f'<div class="tb" style="height:{TB8}px;font-size:26px"><s></s><s></s><s></s>&nbsp;{fname} · sortie réelle</div>'
                f'<div class="code" style="padding:8px 22px;font-size:26px;line-height:{LINE8}px">{code_}</div></div>')
    sn_boxes.append((sn_y, h_)); sn_y += h_ + GAP8
names8 = [cl for _, cl in PEV]
lst = ''.join(f'<div class="row8" id="s8-f{i}">✔ {cl}.php</div>' for i, cl in enumerate(names8))
final8 = (f'<div id="s8-fin" class="win" style="left:1000px;top:96px;width:860px;height:640px;opacity:0">'
          f'<div class="tb" style="height:{TB8}px;font-size:24px"><s></s><s></s><s></s>&nbsp;PHP · 11 fichiers générés</div>'
          f'<div class="mono" style="position:absolute;left:30px;top:62px;right:20px;display:grid;grid-template-columns:1fr 1fr;gap:2px 10px;font-size:26px;line-height:38px;color:{LIME}">{lst}</div>'
          f'<div id="s8-v1" class="abs mono" style="left:30px;top:500px;font-size:28px;color:{LIME};opacity:0">✔  PHP : 11 fichier(s) écrits</div>'
          f'<div id="s8-v2" class="abs mono" style="left:30px;top:548px;font-size:36px;font-weight:700;color:{LIME};opacity:0">✔ Conforme au diagramme</div></div>')
body = f'''<div class="abs" style="inset:0">{diagram('s8')}</div>
{sn_html}{final8}
<div id="s8-cnts" class="abs mono" style="left:40px;top:690px;font-size:52px;font-weight:700;line-height:1.35">PHP <span id="s8-cp" style="color:#5a4fcf">0</span>/11</div>'''
a = T("tl.set('#s8-dg',{@d@},0);\ntl.fromTo('#s8-dg .cls',{y:30,opacity:0},{y:0,opacity:1,duration:.4,stagger:.04,ease:'power3.out'},0.05);\ntl.set('#s8-dg .hd',{backgroundColor:'#dfe6e1'},0);tl.set('#s8-dg .bk',{opacity:0},0);\n", d=dg_tr(40, 150, .52))
S8_EVENTS = []; calls8 = []
for i, (tj, cl) in enumerate(PEV):
    t_ = tt8 + (tj - pt0) * k8; S8_EVENTS.append(t_)
    a += (f"tl.set('#s8-{cl}',{{backgroundColor:'#e3dfff'}},{t_:.3f});tl.set('#s8-{cl} .hd',{{backgroundColor:'{LIME}'}},{t_:.3f});\n"
          f"tl.fromTo('#s8-{cl}-P',{{opacity:0,scale:.4}},{{opacity:1,scale:1,duration:.2}},{t_:.3f});\n"
          f"tl.fromTo('#s8-{cl}',{{scale:1.07}},{{scale:1,duration:.3}},{t_:.3f});\n")
    calls8.append((str(i + 1), t_))
a += counter('#s8-cp', calls8)
# les extraits s'ajoutent un à un (1, puis 2, puis 3), au fil des fichiers réellement écrits
for i, dt_ in enumerate((.45, 1.25, 2.05)):
    t_ = cc(0) + dt_
    a += f"tl.fromTo('#s8-sn{i}',{{opacity:0,y:-40,scale:.96}},{{opacity:1,y:0,scale:1,duration:.45,ease:'power3.out'}},{t_:.3f});\n"
# fin : les extraits se replient, la liste des 11 fichiers prend leur place
tF = cc(1) + .65
a += T("tl.to('#s8-sn0,#s8-sn1,#s8-sn2',{opacity:0,y:-30,duration:.35,stagger:.06},@t@);\ntl.fromTo('#s8-fin',{opacity:0,y:30},{opacity:1,y:0,duration:.45,ease:'power3.out'},@t2@);\n", t=tF - .4, t2=tF - .1)
a += "tl.fromTo('.row8',{opacity:0,x:-14},{opacity:1,x:0,duration:.25,stagger:.07},%.3f);\n" % (tF + .1)
a += T("tl.fromTo('#s8-v1',{opacity:0,x:-30},{opacity:1,x:0,duration:.35},@t1@);tl.fromTo('#s8-v2',{opacity:0,scale:.8},{opacity:1,scale:1,duration:.4,ease:'back.out(1.5)'},@t2@);\ntl.to('#s8-cnts',{scale:1.15,transformOrigin:'0 50%',duration:.3,yoyo:true,repeat:1},@t2@);\n", t1=tF + 1.0, t2=tF + 1.6)
scene(8, 's8', body, a + edge_draw('s8', .4, .08))

# ================================================================ S9 CONTRAINTES TENUES (3 cartes avec visuels animés)
cc = lambda i: cue(9, i)
GREEN = '#1f6b3a'          # vert foncé : contraste >= 4,5:1 avec le blanc
CARDS9 = [('Évolutivité', 'Un langage de plus, sans toucher au noyau. Exemple : PHP.'),
          ('Pertinence', 'Héritage, interfaces, attributs et relations repris du diagramme.'),
          ('Fiabilité', 'Code compilé, puis verdict de conformité au diagramme.')]
pos9 = [96, 690, 1284]
CW, CH, CY = 540, 690, 190
body = '<h1 id="s9-h" class="abs" style="left:96px;top:50px;font-size:96px;letter-spacing:-5px">Les contraintes <span class="or">sont tenues.</span></h1>'
a = "tl.fromTo('#s9-h',{x:-80,opacity:0},{x:0,opacity:1,duration:.5,ease:'expo.out'},.2);\n"
def box(id_, x, y, w, h, style, inner=''):
    return f'<div id="{id_}" class="abs" style="left:{x}px;top:{y}px;width:{w}px;height:{h}px;{style}">{inner}</div>'
# --- visuel 1 : évolution — Java et Python en place, PHP s'ajoute, le noyau ne bouge pas
v1 = (box('s9-ev-chip', 30, 262, 250, 44, f'background:{ORANGE};color:{PAPER};border-radius:22px;font-size:26px;font-weight:700;text-align:center;line-height:44px;opacity:0', '+ php.py')
      + box('s9-ev-up', 410, 250, 100, 70, f'color:{ORANGE};font-size:64px;font-weight:700;text-align:center;line-height:70px;opacity:0', '↗')
      + box('s9-ev-j', 30, 360, 140, 100, f'background:{INK};color:{LIME};border-radius:12px;font-size:30px;font-weight:700;text-align:center;line-height:100px;opacity:0', 'Java')
      + box('s9-ev-p', 200, 360, 140, 100, 'background:#5a4fcf;color:#fff;border-radius:12px;font-size:30px;font-weight:700;text-align:center;line-height:100px;opacity:0', 'Python')
      + box('s9-ev-php', 370, 360, 140, 100, f'background:{ORANGE};color:{INK};border-radius:12px;font-size:30px;font-weight:700;text-align:center;line-height:100px;opacity:0', 'PHP')
      + ''.join(box(f's9-ev-l{k}', 96 + k * 170, 460, 6, 70, f'background:{INK};opacity:0;transform-origin:50% 0') for k in range(3))
      + box('s9-ev-core', 30, 530, 480, 80, f'background:{INK};color:{PAPER};border-radius:12px;font-size:30px;font-weight:700;text-align:center;line-height:80px', 'NOYAU')
      + box('s9-ev-ck', 330, 546, 170, 48, f'background:{LIME};color:{INK};border-radius:24px;font-size:24px;font-weight:700;text-align:center;line-height:48px;opacity:0', '✔ inchangé'))
# --- visuel 2 : pertinence — chaque élément du diagramme est retrouvé dans le code
rows2 = [('Compte', 'class Compte {', 310), ('-solde : double', '  double solde;', 350), ('+deposer()', '  void deposer()', 390)]
v2 = (box('s9-pe-uml', 30, 290, 200, 130, f'background:#fbfcfa;border:3px solid {INK};border-radius:8px;box-shadow:4px 5px 0 {INK}')
      + box('s9-pe-code', 300, 290, 210, 160, f'background:{INK};border-radius:8px')
      + ''.join(box(f's9-pe-u{k}', 40, y - 20 + (0 if k else 0), 190, 40, f'font-size:20px;line-height:40px;font-weight:{700 if k == 0 else 400};white-space:nowrap', html.escape(u)) for k, (u, c, y) in enumerate(rows2))
      + ''.join(box(f's9-pe-c{k}', 312, y - 20, 196, 40, f'font-family:JetBrains Mono;font-size:17px;line-height:40px;color:{PAPER};white-space:pre;opacity:0', html.escape(c)) for k, (u, c, y) in enumerate(rows2))
      + f'<svg class="abs" style="left:0;top:0;pointer-events:none" width="{CW}" height="{CH}">'
      + ''.join(f'<path id="s9-pe-w{k}" d="M232 {y} L298 {y}" pathLength="1" stroke="{ORANGE}" stroke-width="5" fill="none" stroke-dasharray="1 1" stroke-dashoffset="1"/>' for k, (u, c, y) in enumerate(rows2))
      + '</svg>'
      + ''.join(box(f's9-pe-k{k}', 252, y - 14, 28, 28, f'background:{GREEN};color:#fff;border-radius:50%;font-size:18px;font-weight:700;text-align:center;line-height:28px;opacity:0', '✔') for k, (u, c, y) in enumerate(rows2))
      + box('s9-pe-n', 30, 500, 480, 70, f'color:{INK};font-size:36px;font-weight:700;opacity:0', '<span id="s9-pe-num" class="or">0</span>/3 éléments retrouvés'))
# --- visuel 3 : fiabilité — compilation, comparaison, verdict
step = lambda id_, y, label: box(id_, 30, y, 480, 70, f'background:#fbfcfa;border:3px solid {INK};border-radius:12px;box-shadow:4px 5px 0 {INK};font-size:30px;font-weight:700;line-height:64px;padding-left:20px;opacity:0', label)
v3 = (step('s9-fi-r1', 290, '1 · Code compilé') + step('s9-fi-r2', 380, '2 · Verdict de conformité')
      + ''.join(box(f's9-fi-k{k}', 450, y, 44, 44, f'background:{GREEN};color:#fff;border-radius:50%;font-size:28px;font-weight:700;text-align:center;line-height:44px;opacity:0', '✔') for k, y in ((1, 303), (2, 393)))
      + box('s9-fi-v', 30, 500, 480, 110, f'background:{GREEN};color:#fff;border-radius:14px;font-size:31px;font-weight:700;text-align:center;line-height:110px;white-space:nowrap;opacity:0', '✔ Conforme au diagramme'))
for i, ((ti, tx), x, vis) in enumerate(zip(CARDS9, pos9, (v1, v2, v3))):
    body += (f'<div id="s9-c{i}" class="card" style="left:{x}px;top:{CY}px;width:{CW}px;height:{CH}px;opacity:0"><h3>{ti}</h3>'
             f'<p style="font-size:32px">{tx}</p><div class="okc" id="s9-k{i}">✔</div>{vis}</div>')
    t_ = cc(i + 1)
    a += (f"tl.fromTo('#s9-c{i}',{{y:50,opacity:0}},{{y:0,opacity:1,duration:.45,ease:'power3.out'}},{t_:.3f});\n"
          f"tl.fromTo('#s9-k{i}',{{opacity:0,scale:.3}},{{opacity:1,scale:1,duration:.35,ease:'back.out(2)'}},{t_ + .5:.3f});\n"
          f"tl.fromTo('#s9-c{i} h3',{{color:'{ORANGE}'}},{{color:'{INK}',duration:.8}},{t_ + .1:.3f});\n")
# animations des visuels
t1, t2, t3 = cc(1), cc(2), cc(3)
a += T("""tl.fromTo('#s9-ev-j,#s9-ev-p',{opacity:0,y:30},{opacity:1,y:0,duration:.4,stagger:.15,ease:'power3.out'},@a@);
tl.fromTo('#s9-ev-l0,#s9-ev-l1',{opacity:0,scaleY:0},{opacity:1,scaleY:1,duration:.3,stagger:.15},@a2@);
tl.fromTo('#s9-ev-chip',{opacity:0,x:-30},{opacity:1,x:0,duration:.35},@b@);
tl.fromTo('#s9-ev-php',{opacity:0,y:-90,scale:.7},{opacity:1,y:0,scale:1,duration:.55,ease:'bounce.out'},@b@);
tl.fromTo('#s9-ev-l2',{opacity:0,scaleY:0},{opacity:1,scaleY:1,duration:.3},@b2@);
tl.fromTo('#s9-ev-up',{opacity:0,y:30},{opacity:1,y:0,duration:.4,ease:'back.out(2)'},@b2@);
tl.fromTo('#s9-ev-ck',{opacity:0,scale:.5},{opacity:1,scale:1,duration:.35,ease:'back.out(2)'},@b3@);
""", a=t1 + .5, a2=t1 + .9, b=t1 + 3.2, b2=t1 + 3.6, b3=t1 + 4.1)
calls = []
for k in range(3):
    tk = t2 + .6 + k * .8
    a += (f"tl.fromTo('#s9-pe-c{k}',{{opacity:0,x:12}},{{opacity:1,x:0,duration:.3}},{tk:.3f});\n"
          f"tl.to('#s9-pe-w{k}',{{strokeDashoffset:0,duration:.35,ease:'power2.out'}},{tk:.3f});\n"
          f"tl.fromTo('#s9-pe-k{k}',{{opacity:0,scale:.3}},{{opacity:1,scale:1,duration:.25,ease:'back.out(2.5)'}},{tk + .3:.3f});\n")
    calls.append((str(k + 1), tk + .3))
a += f"tl.fromTo('#s9-pe-n',{{opacity:0,y:14}},{{opacity:1,y:0,duration:.4}},{t2 + .6:.3f});\n" + counter('#s9-pe-num', [('0', 0.01)] + calls)
a += T("""tl.fromTo('#s9-fi-r1',{opacity:0,x:-40},{opacity:1,x:0,duration:.4,ease:'power3.out'},@a@);
tl.fromTo('#s9-fi-k1',{opacity:0,scale:.3},{opacity:1,scale:1,duration:.3,ease:'back.out(2.5)'},@a2@);
tl.fromTo('#s9-fi-r2',{opacity:0,x:-40},{opacity:1,x:0,duration:.4,ease:'power3.out'},@b@);
tl.fromTo('#s9-fi-k2',{opacity:0,scale:.3},{opacity:1,scale:1,duration:.3,ease:'back.out(2.5)'},@b2@);
tl.fromTo('#s9-fi-v',{opacity:0,scale:.8,rotate:-3},{opacity:1,scale:1,rotate:-1.5,duration:.5,ease:'back.out(1.8)'},@c@);
""", a=t3 + .4, a2=t3 + .9, b=t3 + 1.5, b2=t3 + 2.0, c=t3 + 2.7)
scene(9, 's9', body, a)

# ================================================================ S10 LIMITES & RISQUES (honnêteté)
cc = lambda i: cue(10, i)
CARDS10 = [('Non déterministe', 'Deux exécutions peuvent donner deux codes différents.', 'LLM'),
           ('Comportement absent', 'Le diagramme ne dit pas ce que font les méthodes : elles restent en TODO.', 'TODO'),
           ('Pas de bac à sable', 'Le code est compilé et instancié avec vos droits. Garde-fous : dossier jetable, 10 s, scan d\'appels sensibles.', '!'),
           ('Données envoyées', 'Le diagramme part vers l\'API du modèle configuré.', 'API')]
body = f'<h1 id="s10-h" class="abs" style="left:96px;top:60px;font-size:96px;letter-spacing:-5px">Limites <span class="or">&amp; risques.</span></h1>'
a = "tl.fromTo('#s10-h',{x:-80,opacity:0},{x:0,opacity:1,duration:.5,ease:'expo.out'},.2);\n"
pos10 = [(96, 200), (1004, 200), (96, 490), (1004, 490)]
for i, ((ti, tx, tag), (x, y)) in enumerate(zip(CARDS10, pos10)):
    body += (f'<div id="s10-c{i}" class="card" style="left:{x}px;top:{y}px;width:820px;height:{250 if i != 2 else 270}px;opacity:0;border-color:{ORANGE};box-shadow:8px 9px 0 {ORANGE}">'
             f'<h3>{ti}</h3><p>{tx}</p><div class="okc" style="background:{ORANGE};color:{PAPER};font-size:22px;opacity:1">{tag}</div></div>')
    a += f"tl.fromTo('#s10-c{i}',{{y:50,opacity:0}},{{y:0,opacity:1,duration:.45,ease:'power3.out'}},{cc(i + 1) - .1:.3f});\n"
NOTE10 = "Pour un langage ajouté, le code est compilé et ses noms sont comparés au diagramme. Il n'est pas exécuté."
body += f'<div id="s10-note" class="abs" style="left:96px;top:790px;font-size:34px;line-height:1.3;max-width:1700px;border-left:10px solid {ORANGE};padding-left:20px;opacity:0">{html.escape(NOTE10)}</div>'
a += f"tl.fromTo('#s10-note',{{opacity:0,y:14}},{{opacity:1,y:0,duration:.6}},{cc(5) - .1:.3f});\n"
scene(10, 's10', body, a)

# ================================================================ S11 CTA
cc = lambda i: cue(11, i)
body = f'''<h1 id="s11-t" class="abs" style="left:100px;top:70px;font-size:176px;letter-spacing:-9px;line-height:.98">UML Factory <span style="background:{INK};color:{PAPER};padding:0 24px;border-radius:8px">LLM</span></h1>
<p id="s11-p" class="abs" style="left:106px;top:320px;font-size:84px;font-weight:700;letter-spacing:-3px;line-height:1.1">Du modèle au code.</p>
<p id="s11-p2" class="abs" style="left:106px;top:432px;font-size:50px;font-weight:700;letter-spacing:-1px;line-height:1.15;max-width:1500px">Et vous savez si le code correspond à votre diagramme.</p>
<div id="s11-cmd" class="abs mono" style="left:106px;top:590px;font-size:34px;line-height:50px;background:{INK};color:{PAPER};padding:22px 34px;border-radius:14px;white-space:pre-wrap;width:1500px"><span id="s11-ct"></span></div>
<p id="s11-fr" class="abs" style="left:106px;top:750px;font-size:46px;font-weight:700;color:{INK}">Essayez-le sur votre prochain diagramme.</p>
<div id="s11-credit" class="abs" style="left:106px;top:850px;font-size:28px;line-height:1.3;max-width:1700px">Musique : « Supernova » — Scott Buckley (CC BY 4.0) · www.scottbuckley.com.au</div>
<div id="s11-end" class="abs" style="inset:0;background:{INK};opacity:0;display:flex;flex-direction:column;align-items:center;justify-content:center;z-index:40"><div style="font-size:150px;font-weight:700;letter-spacing:-7px;color:{PAPER};line-height:1">UML Factory <span style="background:{ORANGE};color:{INK};padding:0 22px;border-radius:8px">LLM</span></div><div style="font-size:44px;color:#a8bcb2;margin-top:26px">Du modèle au code.</div></div>
<div id="s11-black" class="abs" style="inset:0;background:#000;opacity:0;z-index:45"></div>'''
a = T('''tl.fromTo('#s11-t',{y:-50,opacity:0},{y:0,opacity:1,duration:.55,ease:'back.out(1.1)'},.15);
tl.fromTo('#s11-p',{opacity:0,x:-60},{opacity:1,x:0,duration:.5,ease:'power3.out'},@c@);
tl.fromTo('#s11-p2',{opacity:0,x:-40},{opacity:1,x:0,duration:.5,ease:'power3.out'},@c1@);
tl.fromTo('#s11-cmd',{opacity:0,y:40},{opacity:1,y:0,duration:.5,ease:'power3.out'},@d@);
tl.fromTo('#s11-fr',{opacity:0,y:20},{opacity:1,y:0,duration:.5,ease:'power3.out'},@c2@);
tl.fromTo('#s11-credit',{opacity:0},{opacity:1,duration:.4},@e@);
tl.to('#s11-end',{opacity:1,duration:.9,ease:'power2.inOut'},@f@);
tl.to('#s11-black',{opacity:1,duration:.6,ease:'power1.in'},@g@);
''', c=cc(0) + .3, c1=cc(1), d=cc(1) + 1.2, c2=cc(2), e=cc(0) + 3.0, f=DUR[11] - 2.6, g=DUR[11] - .7)
a += human_type(11, '#s11-ct', 'python -m umlfactory.cli diagramme.puml', cc(1) + 1.8, 1.9, seed=11, enter=True,
                html_fn=lambda x: '<span class="lime">' + html.escape(x[:24]) + '</span>' + html.escape(x[24:]))
scene(11, 's11', body, a, 'orange')

# ================================================================ index.html
clips = ''
for i, (sid, st, d) in enumerate(scenes):
    clips += f'<div id="{sid}" class="clip" data-composition-id="{sid}" data-composition-src="compositions/{sid}.html" data-start="{st:.3f}" data-duration="{d}" data-width="1920" data-height="1080" data-track-index="1"></div>\n'
aud = f'<audio id="music" class="clip" src="assets/music_v5.wav" data-start="0" data-duration="{TOTAL:.3f}" data-volume="1" data-track-index="2"></audio>\n'
for n in range(1, NS + 1):
    aud += f'<audio id="voice-{n}" class="clip" src="assets/voice/scene-{n}.wav" data-start="{START[n] + VO:.3f}" data-duration="{VOICE[n]:.3f}" data-volume="1" data-track-index="3"></audio>\n'
make_keys(P / 'assets' / 'keys_v5.wav', TOTAL)
aud += f'<audio id="keys" class="clip" src="assets/keys_v5.wav" data-start="0" data-duration="{TOTAL:.3f}" data-volume="0.5" data-track-index="15"></audio>\n'
k = 0
for base, evs in ((START[4], S4_EVENTS), (START[8], S8_EVENTS)):
    for t_ in evs:
        aud += f'<audio id="sfx-{k}" class="clip" src="assets/short.mp3" data-start="{base + t_:.3f}" data-duration="0.6" data-volume="0.16" data-track-index="{4 + k % 5}"></audio>\n'; k += 1
for n, tt_ in ((2, .2), (3, .3), (4, .1), (5, .15), (6, .1), (7, .1), (8, .1), (9, .1), (10, .1)):
    aud += f'<audio id="whoosh-{n}" class="clip" src="assets/whoosh.mp3" data-start="{START[n] + tt_:.3f}" data-duration="0.57" data-volume="0.12" data-track-index="9"></audio>\n'
aud += f'<audio id="hit-3" class="clip" src="assets/impact.mp3" data-start="{START[3] + .6:.3f}" data-duration="2.1" data-volume="0.14" data-track-index="13"></audio>\n'
(P / 'index.html').write_text(f'''<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>UML Factory LLM — Marketing V5</title><script src="assets/gsap.min.js"></script><style>html,body{{margin:0;width:1920px;height:1080px;overflow:hidden;background:{PAPER}}}#root{{position:relative;width:1920px;height:1080px}}.clip{{position:absolute;inset:0}}</style></head><body><div id="root" data-composition-id="main" data-start="0" data-duration="{TOTAL:.3f}" data-width="1920" data-height="1080" data-fps="30">
{clips}{aud}</div><script>window.__timelines=window.__timelines||{{}};window.__timelines.main=gsap.timeline({{paused:true}});</script></body></html>''', encoding='utf-8')
(P / 'meta.json').write_text(json.dumps({'name': 'UML Factory LLM — Marketing V5', 'id': 'umlfactory-marketing-v5'}, ensure_ascii=False), encoding='utf-8')
write_srt()
json.dump({'total': TOTAL, 'start': START, 'dur': DUR, 'voice': VOICE, 'vo': VO, 'cues': CUES}, open(P / 'timing.json', 'w'), indent=1)
print('ok total', TOTAL, {n: DUR[n] for n in DUR})
