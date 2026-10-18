"""Render the session chart from the published Douyin replay measurements."""
import argparse, json, math
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent
DEXSQL = '#16734a'
RASC = '#a45e70'
MUTED = '#58636e'


def style():
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 11, 'svg.fonttype': 'path',
                         'svg.hashsalt': 'dexsql-agent-audit-20261018', 'figure.facecolor': 'white',
                         'axes.facecolor': 'white', 'text.color': '#202830', 'axes.labelcolor': MUTED,
                         'xtick.color': MUTED, 'ytick.color': '#202830'})


def decorate(ax, grid='x'):
    for s in ['right', 'top'] + (['left'] if grid == 'x' else []):
        ax.spines[s].set_visible(False)
    ax.spines['bottom'].set_color('#bac2ca')
    if grid == 'y':
        ax.spines['left'].set_color('#bac2ca')
    ax.set_axisbelow(True)
    ax.grid(axis=grid, color='#e5e9ed', linewidth=.7)
    ax.tick_params(axis='y', length=0 if grid == 'x' else 3, pad=8)


def geomean(xs):
    return math.exp(sum(math.log(x) for x in xs) / len(xs))


def load():
    data = ROOT / 'data'
    dx = json.loads((data / 'dexsql_benchmark.json').read_text())
    rs = json.loads((data / 'rasc_benchmark.json').read_text())
    conf = json.loads((data / 'dexsql_thread_confirmation.json').read_text())
    whole = json.loads((data / 'dexsql_whole_suite.json').read_text())
    rwhole = json.loads((data / 'rasc_whole_suite.json').read_text())
    goals = list(dx['scenarios'])
    hot = [dx['scenarios'][g]['median_wall_ms'] for g in goals]
    rasc = [rs['scenarios'][g]['median_end_to_end_ms'] for g in goals]
    rasc_nostart = [max(rs['scenarios'][g]['median_minus_startup_ms_estimate'], 1e-3) for g in goals]
    opens = list(dx['thread_sweep']['16']['samples']['open_ms']) + list(conf['rows']['16']['samples']['open_ms'])
    return dict(goals=goals, hot=hot, rasc=rasc, rasc_nostart=rasc_nostart,
                open_ms=sorted(opens)[len(opens) // 2 - 1:len(opens) // 2 + 1], whole=whole, rwhole=rwhole,
                startup=dx['startup'], rasc_start=rs['startup_median_ms'])


def bars(ax, rows, limit, title):
    decorate(ax)
    ax.set_title(title, loc='left', fontsize=13, weight='bold', pad=10)
    ax.set_ylim(len(rows) - .4, -.6)
    ax.set_yticks(range(len(rows)), [r[0] for r in rows], fontsize=10)
    for y, (_, value, color, note) in enumerate(rows):
        ax.barh(y, value, height=.55, color=color, zorder=3)
        label = f'{value:,.1f} ms' + (f'  ·  {note}' if note else '')
        ax.annotate(label, (value, y), xytext=(5, 0), textcoords='offset points', va='center', fontsize=10,
                    weight='bold' if color == DEXSQL else 'normal')
    ax.set_xlim(0, limit)
    ax.set_xlabel('Milliseconds · linear scale from zero · lower is better', fontsize=10, labelpad=5)


def render(args):
    m = load()
    style()
    open_ms = sum(m['open_ms']) / 2
    n = len(m['goals'])
    fig = plt.figure(figsize=(11, 13.4))
    gs = fig.add_gridspec(3, 1, height_ratios=[1.0, 1.0, 1.5], hspace=.55, left=.27, right=.94, top=.875, bottom=.11)
    fig.text(.045, .965, 'Douyin 40.7.0 · replay of a real MCP session', fontsize=20, weight='bold', va='top')
    fig.text(.045, .935, f'{n} analysis goals, 47 tool calls · DexSQL 0.1.1 (one MCP session) vs rasc (one CLI process per step)',
             fontsize=11, color=MUTED, va='top')

    init = m['startup']['mcp_initialize_median_ms']
    per_goal = [
        ('Hot · DexSQL', geomean(m['hot']), DEXSQL, 'dataset already open'),
        ('Hot · rasc', geomean(m['rasc_nostart']), RASC, 'process start excluded; reads the APK'),
        ('Cold · DexSQL', geomean([init + open_ms + h for h in m['hot']]), DEXSQL, 'start MCP + open APK + goal'),
        ('Cold · rasc', geomean(m['rasc']), RASC, 'new process for every step'),
    ]
    bars(fig.add_subplot(gs[0]), per_goal, 640, 'Per goal · geometric mean of 17 goals')

    w = m['whole']['medians']
    setup = [
        ('DexSQL · open APK', open_ms, DEXSQL, 'once per session'),
        ('DexSQL · start MCP server', m['startup']['mcp_initialize_median_ms'], DEXSQL, None),
        ('rasc · start process', m['rasc_start'], RASC, 'each step reads the APK itself'),
        ('DexSQL · whole session', w['total_process_ms'], DEXSQL, f"open {w['open_ms']:.0f} + goals {w['hot_suite_ms']:.0f}"),
        ('rasc · whole session', m['rwhole']['median_total_process_ms'], RASC, '47 processes'),
    ]
    bars(fig.add_subplot(gs[1]), setup, 3900, 'Opening and the whole 17-goal session')

    ax = fig.add_subplot(gs[2])
    decorate(ax, grid='y')
    ax.set_title('Cumulative time as questions accumulate', loc='left', fontsize=13, weight='bold', pad=10)
    mean_hot = sum(m['hot']) / n
    mean_rasc = sum(m['rasc']) / n
    xs = list(range(0, 41))
    ax.plot(xs, [open_ms + x * mean_hot for x in xs], color=DEXSQL, linewidth=2.4, label='DexSQL: open once, then hot goals')
    ax.plot(xs, [x * mean_rasc for x in xs], color=RASC, linewidth=2.4, label='rasc: every goal from a new process')
    cross = open_ms / (mean_rasc - mean_hot)
    ax.axvline(cross, color='#bac2ca', linewidth=1, linestyle='--', zorder=1)
    ax.annotate(f'break-even ≈ {cross:.1f} goals', (cross, open_ms + cross * mean_hot), xytext=(-6, 95), ha="left",
                textcoords='offset points', fontsize=10, color=MUTED)
    for x in (n, 40):
        for y, color in ((open_ms + x * mean_hot, DEXSQL), (x * mean_rasc, RASC)):
            ax.plot(x, y, 'o', color=color, markersize=5)
            ax.annotate(f'{y / 1000:.2f} s', (x, y), xytext=(-8, 8), textcoords='offset points', ha='right', fontsize=10, color=color)
    ax.set_xlim(0, 41)
    ax.set_ylim(0, 40 * mean_rasc * 1.08)
    ax.set_xlabel('Goals asked in one session (mean goal time from this replay)', fontsize=10, labelpad=5)
    ax.set_ylabel('Cumulative milliseconds', fontsize=10)
    ax.legend(loc='upper left', frameon=False, fontsize=10)

    notes = ['Apple M3 Pro, macOS 26.5.1, warm OS file cache. Medians of 7 randomized runs; DexSQL open is the median of 8 runs (16 threads).',
             'DexSQL opens the APK once per session. rasc has no session mode, so each step starts a process and reads the APK again.',
             'Hot excludes start-up on both sides; cold includes it on both sides. The line chart extrapolates from mean goal times.']
    for i, line in enumerate(notes):
        fig.text(.045, .05 - i * .014, line, fontsize=9, color=MUTED)
    (ROOT / 'charts').mkdir(exist_ok=True)
    svg = ROOT / 'charts' / 'session.svg'
    fig.savefig(svg, metadata={'Date': None, 'Title': 'session'}, facecolor='white')
    svg.write_text('\n'.join(line.rstrip() for line in svg.read_text(encoding='utf-8').splitlines()) + '\n', encoding='utf-8')
    if args.preview_dir:
        args.preview_dir.mkdir(parents=True, exist_ok=True)
        fig.savefig(args.preview_dir / 'session.png', dpi=110)
    plt.close(fig)
    print('open', open_ms, 'cross', cross, [round(r[1], 1) for r in per_goal])


def render_goals(args):
    """One row per goal: DexSQL stacked (hot query + start/open), third-party tool beside it."""
    from matplotlib.patches import Patch
    m = load()
    style()
    open_ms = sum(m['open_ms']) / 2
    start = m['startup']['mcp_initialize_median_ms'] + open_ms
    rows = [('All 17 goals · geometric mean', geomean(m['hot']), geomean(m['rasc']))]
    rows += list(zip(m['goals'], m['hot'], m['rasc']))
    height = 2.6 + .62 * len(rows)
    fig, ax = plt.subplots(figsize=(11, height))
    fig.subplots_adjust(left=.3, right=.95, top=1 - 1.75 / height, bottom=1.25 / height)
    fig.text(.045, 1 - .3 / height, 'Douyin 40.7.0 · time per analysis goal', fontsize=20, weight='bold', va='top')
    fig.text(.045, 1 - .78 / height, 'Replay of a real MCP session · DexSQL 0.1.1 vs rasc · medians of 7 runs · lower is better',
             fontsize=11, color=MUTED, va='top')
    decorate(ax)
    bar = .34
    labels = []
    for y, (name, hot, rasc) in enumerate(rows):
        dy, ry = y - bar / 2 - .02, y + bar / 2 + .02
        ax.barh(dy, hot, height=bar, color=DEXSQL, zorder=3)
        ax.barh(dy, start, left=hot, height=bar, color=DEXSQL, alpha=.22, zorder=3)
        ax.annotate(f'{hot:,.1f} ms', (hot + start, dy), xytext=(5, 0), textcoords='offset points', va='center',
                    fontsize=9.5, weight='bold', color=DEXSQL)
        ax.barh(ry, rasc, height=bar, color=RASC, zorder=3)
        ax.annotate(f'{rasc:,.1f} ms', (rasc, ry), xytext=(5, 0), textcoords='offset points', va='center', fontsize=9.5, color=RASC)
        labels.append(name)
    ax.set_yticks(range(len(rows)), labels, fontsize=10)
    ax.get_yticklabels()[0].set_weight('bold')
    ax.axhline(.5, color='#bac2ca', linewidth=.8)
    ax.set_ylim(len(rows) - .45, -.55)
    ax.set_xlim(0, 480)
    ax.set_xlabel('Milliseconds · linear scale from zero', fontsize=10, labelpad=5)
    fig.legend(handles=[Patch(facecolor=DEXSQL, label='DexSQL query, dataset open'),
                        Patch(facecolor=DEXSQL, alpha=.22, label=f'DexSQL start + open APK, {start:.0f} ms once per session'),
                        Patch(facecolor=RASC, label='rasc, new process per step')],
               loc='upper left', bbox_to_anchor=(.04, 1 - 1.05 / height), ncol=3, frameon=False, fontsize=10)
    notes = ['Labels on DexSQL bars give the query time only; the light segment is the one-time start-up, the same for every row.',
             'rasc has no session mode: its bar includes process start and reading the APK for every step. Apple M3 Pro, warm OS file cache.']
    for i, line in enumerate(notes):
        fig.text(.045, (.62 - i * .3) / height, line, fontsize=9, color=MUTED)
    svg = ROOT / 'charts' / 'goals.svg'
    fig.savefig(svg, metadata={'Date': None, 'Title': 'goals'}, facecolor='white')
    svg.write_text('\n'.join(line.rstrip() for line in svg.read_text(encoding='utf-8').splitlines()) + '\n', encoding='utf-8')
    if args.preview_dir:
        fig.savefig(args.preview_dir / 'goals.png', dpi=110)
    plt.close(fig)


SEGMENTS = [('open', 'Start + open / prepare', '#7f97ad'),
            ('query', 'Queries in the tool', '#16734a'),
            ('external', 'Third-party tool calls (rg)', '#d08a2e')]
COMMON = ['manifest_exported_components', 'ttdownloader_provider_db', 'microgame_fileprovider_io',
          'gameres_uri_permissions', 'secshare_provider_paths', 'aic_gzip_decode_limits', 'widget_confirm_action',
          'luckycat_ssl_error_handling', 'lmhttp_tls_setup', 'cjpay_webview_config']


def tool_rows():
    """Open, first pass over the 10 common goals, and third-party calls for every tool."""
    data = ROOT / 'data'
    dx = json.loads((data / 'dexsql_benchmark.json').read_text())
    rs = json.loads((data / 'rasc_benchmark.json').read_text())
    m = load()
    rows = [('DexSQL 0.1.1', {'open': m['startup']['mcp_initialize_median_ms'] + sum(m['open_ms']) / 2,
                              'query': sum(dx['validation'][g]['wall_ms'] for g in COMMON), 'external': 0.0}, 10, 'MCP session'),
            ('rasc (ASC rust)', {'open': 0.0, 'query': sum(sum(rs['validation'][g]['step_ms']) for g in COMMON), 'external': 0.0},
             sum(not rs['validation'][g]['missing_tokens'] for g in COMMON), 'CLI process per step')]
    labels = {'dexdec': ('DexDec 1.0.2', 'MCP session'), 'jadx-api': ('JADX 1.5.6 API', 'resident JVM'),
              'ddc': ('ddc 0.1.29', 'MCP'), 'garlic': ('garlic 1.8', 'MCP + prepared DuckDB'),
              'droidsaw': ('droidsaw 2.0.0', 'CLI process per step')}
    for key, (label, mode) in labels.items():
        d = json.loads((data / 'tools' / f'{key}.json').read_text())
        calls = [c for g in COMMON for c in d['first_use'][g]['calls']]
        opened = (d.get('initialize_ms') or 0) + (d.get('open_ms') or 0) + (d.get('preparation') or {}).get('elapsed_ms', 0)
        parts = {'open': opened,
                 'query': sum(c['ms'] for c in calls if 'external_tool' not in c),
                 'external': sum(c['ms'] for c in calls if 'external_tool' in c)}
        rows.append((label, parts, sum(not d['validation'][g]['missing_tokens'] for g in COMMON), mode))
    return sorted(rows, key=lambda r: sum(r[1].values()))


def render_total(args):
    """One bar per tool: [open][queries][third-party calls] for 10 goals, log scale."""
    from matplotlib.patches import Patch
    style()
    rows = tool_rows()
    height = 3.0 + .78 * len(rows)
    fig, ax = plt.subplots(figsize=(11, height))
    fig.subplots_adjust(left=.19, right=.8, top=1 - 1.85 / height, bottom=1.75 / height)
    fig.text(.045, 1 - .3 / height, 'Douyin 40.7.0 · open once, then 10 analysis goals', fontsize=20, weight='bold', va='top')
    fig.text(.045, 1 - .78 / height, 'Replay of a real MCP reverse-engineering session · each goal answered once · log scale · lower is better',
             fontsize=11, color=MUTED, va='top')
    decorate(ax)
    xmin = 100
    for y, (name, parts, evidence, mode) in enumerate(rows):
        left = xmin
        total = 0.0
        for key, _, color in SEGMENTS:
            value = parts[key]
            if value <= 0:
                continue
            total += value
            right = max(total, xmin * 1.02)
            ax.barh(y, right - left, left=left, height=.56, color=color, zorder=3)
            left = right
        detail = ' + '.join(f"{parts[k] / 1000:.2f}" for k, _, _ in SEGMENTS if parts[k] > 0)
        ax.annotate(f'{total / 1000:,.2f} s', (total, y), xytext=(6, 4), textcoords='offset points', va='bottom', fontsize=10.5,
                    weight='bold' if name.startswith('DexSQL') else 'normal')
        ax.annotate(f'{mode} · evidence {evidence}/10', (total, y), xytext=(6, -3), textcoords='offset points', va='top',
                    fontsize=8.6, color=MUTED)
    ax.set_xscale('log')
    ax.set_xlim(xmin, 2e6)
    ticks = [100, 1000, 10000, 100000, 1000000]
    ax.set_xticks(ticks, ['0.1 s', '1 s', '10 s', '100 s', '1000 s'])
    ax.minorticks_off()
    ax.set_yticks(range(len(rows)), [r[0] for r in rows], fontsize=10.5)
    ax.set_ylim(len(rows) - .45, -.55)
    ax.set_xlabel('Total time · log scale', fontsize=10, labelpad=5)
    fig.legend(handles=[Patch(facecolor=c, label=l) for _, l, c in SEGMENTS], loc='upper left',
               bbox_to_anchor=(.04, 1 - 1.1 / height), ncol=3, frameon=False, fontsize=10)
    notes = ['On a log scale segment lengths are not proportional; totals and the split are in the report table.',
             'Evidence counts goals whose expected evidence tokens appeared; misses are under review and may be Java vs smali wording.',
             'Apple M3 Pro, warm OS file cache. droidsaw has one pass; the others are first passes from runs with 3 or 7 repeats.']
    for i, line in enumerate(notes):
        fig.text(.045, (.9 - i * .27) / height, line, fontsize=9, color=MUTED)
    svg = ROOT / 'charts' / 'total.svg'
    fig.savefig(svg, metadata={'Date': None, 'Title': 'total'}, facecolor='white')
    svg.write_text('\n'.join(line.rstrip() for line in svg.read_text(encoding='utf-8').splitlines()) + '\n', encoding='utf-8')
    if args.preview_dir:
        fig.savefig(args.preview_dir / 'total.png', dpi=110)
    plt.close(fig)
    for name, parts, evidence, _ in rows:
        print(f"{name:18s} open={parts['open']:9.0f} query={parts['query']:9.0f} ext={parts['external']:6.0f} total={sum(parts.values()):9.0f} evidence={evidence}")

if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--preview-dir', type=Path)
    args = ap.parse_args()
    render(args)
    render_goals(args)
    render_total(args)
