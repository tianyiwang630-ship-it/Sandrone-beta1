"""
Serenity Chokepoint理论 + 第一性原理AI产业链深挖
获取2年财务数据，按PE<20严格筛选
"""
import yfinance as yf
import pandas as pd
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Serenity的卡脖子供应链7层：
# 1. 原材料(Ga/In/As) - AXTI
# 2. pBN坩埚 - Shin-Etsu(日本)
# 3. InP衬底 - AXTI
# 4. CW激光器(CPO) - SIVE
# 5. 光收发器 - AAOI/COHR/LITE
# 6. 测试设备 - AEHR
# 7. 光纤 - GLW

# 最新call: JBL (Jabil) - 合同制造商

SERENITY_PICKS = {
    'AXTI': 'AXT Inc - InP衬底/原材料(卡脖子第一层)',
    'SIVE': 'Sivers Semiconductors - CW激光器(CPO卡脖子)',
    'AEHR': 'Aehr Test Systems - 光子学测试',
    'POET': 'POET Technologies - SiPh/CPO',
    'JBL': 'Jabil - 光模块合同制造(最新call)',
    'AAOI': 'Applied Opto - 光收发器',
    'LITE': 'Lumentum - 光通信',
    'COHR': 'Coherent - 光通信',
}

# 低PE+AI受益候选（之前扫描发现）
VALUE_CANDIDATES = {
    'SMCI': 'Super Micro - AI服务器 (PE21x, Fwd12x, 营收+122%)',
    'CEG': 'Constellation Energy - 核电AI电力 (PE22x, Fwd19x)',
    'VST': 'Vistra - AI电力 (PE25x, Fwd13x)',
    'TEL': 'TE Connectivity - 连接器 (PE22x, Fwd17x)',
}

all_tickers = {**SERENITY_PICKS, **VALUE_CANDIDATES}

def get_2yr_financials(ticker):
    """获取2年财务数据"""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        
        # 当前数据
        price = info.get('currentPrice') or info.get('regularMarketPrice') or info.get('previousClose') or 0
        mkt_cap = info.get('marketCap')
        pe = info.get('trailingPE')
        forward_pe = info.get('forwardPE')
        pb = info.get('priceToBook')
        revenue = info.get('totalRevenue')
        net_income = info.get('netIncomeToCommon')
        gross_margin = info.get('grossMargins')
        rev_growth = info.get('revenueGrowth')
        
        # 获取历史财务
        bs = stock.balance_sheet
        inc = stock.financials
        
        # 提取近2年营收和利润
        rev_2yr_ago = None
        rev_1yr_ago = None
        ni_2yr_ago = None
        ni_1yr_ago = None
        
        if inc is not None and 'Total Revenue' in inc.index:
            revs = inc.loc['Total Revenue']
            if len(revs) >= 2:
                rev_1yr_ago = revs.iloc[1]  # 最近完整财年
            if len(revs) >= 3:
                rev_2yr_ago = revs.iloc[2]  # 2年前
                
        if inc is not None and 'Net Income' in inc.index:
            nis = inc.loc['Net Income']
            if len(nis) >= 2:
                ni_1yr_ago = nis.iloc[1]
            if len(nis) >= 3:
                ni_2yr_ago = nis.iloc[2]
        
        return {
            '代码': ticker,
            '公司': info.get('longName') or info.get('shortName') or ticker,
            '股价': price,
            '市值': mkt_cap,
            'PE(TTM)': pe,
            'Forward PE': forward_pe,
            'PB': pb,
            '营收(TTM)': revenue,
            '净利润(TTM)': net_income,
            '毛利率': gross_margin,
            '营收增速': rev_growth,
            '1年前营收': rev_1yr_ago,
            '2年前营收': rev_2yr_ago,
            '1年前净利': ni_1yr_ago,
            '2年前净利': ni_2yr_ago,
            '行业': info.get('industry'),
        }
    except Exception as e:
        return {'代码': ticker, '公司': 'ERROR', '错误': str(e)}

def fmt(v, prefix='$'):
    if v is None or v == 'N/A': return 'N/A'
    if isinstance(v, str): return v
    if abs(v) >= 1e12: return f'{prefix}{v/1e12:.2f}T'
    if abs(v) >= 1e9: return f'{prefix}{v/1e9:.2f}B'
    if abs(v) >= 1e6: return f'{prefix}{v/1e6:.2f}M'
    return f'{prefix}{v:,.0f}'

def pct(v):
    if v is None: return 'N/A'
    return f'{v*100:.1f}%'

print("="*110)
print("SERENITY卡脖子理论 + 低PE候选 — 2年财务数据深度分析")
print("="*110)

results = []
for ticker, desc in all_tickers.items():
    print(f"\n{'='*60}")
    print(f"📌 {ticker} - {desc}")
    print(f"{'='*60}")
    
    r = get_2yr_financials(ticker)
    results.append(r)
    
    if '错误' in r:
        print(f"  ❌ {r['错误']}")
        continue
    
    # 估值判断
    pe = r['PE(TTM)']
    fpe = r['Forward PE']
    growth = r['营收增速']
    
    is_value = pe and pe < 20
    is_near = pe and pe < 25
    
    if is_value: tag = '✅ PE<20 低估!'
    elif is_near: tag = '🟡 PE<25 接近'
    else: tag = '❌ PE>25 偏贵'
    
    price_str = f"${r['股价']:.2f}" if r['股价'] else 'N/A'
    pe_str = f"{pe:.1f}x" if pe else 'N/A'
    fpe_str = f"{fpe:.1f}x" if fpe else 'N/A'
    pb_str = f"{r['PB']:.1f}x" if r['PB'] else 'N/A'
    
    print(f"  💰 股价: {price_str} | 市值: {fmt(r['市值'])} | {tag}")
    print(f"  📈 PE: {pe_str} | Forward PE: {fpe_str} | PB: {pb_str}")
    print(f"  📊 营收: {fmt(r['营收(TTM)'])} | 净利润: {fmt(r['净利润(TTM)'])}")
    print(f"  💎 毛利率: {pct(r['毛利率'])} | 营收增速: {pct(growth)}")
    
    # 2年营收对比
    r1 = r['1年前营收']
    r2 = r['2年前营收']
    n1 = r['1年前净利']
    n2 = r['2年前净利']
    
    print(f"  📅 营收2年对比: TTM={fmt(r['营收(TTM)'])} | 去年={fmt(r1)} | 前年={fmt(r2)}")
    print(f"  📅 净利2年对比: TTM={fmt(r['净利润(TTM)'])} | 去年={fmt(n1)} | 前年={fmt(n2)}")
    print(f"  🏢 行业: {r['行业']}")
    
    # Forward PE vs Growth 性价比
    if fpe and growth:
        ratio = growth * 100 / fpe if growth > 0 else 0
        print(f"  ⚡ PEG-like: 增速{fpe:.0f}倍PE / 增速{growth*100:.0f}% = {ratio:.2f} (越高越好)")

# === 最终排名：按性价比 ===
print("\n\n" + "="*110)
print("🏆 最终排名：AI产业链卡脖子位置 × 估值性价比")
print("="*110)

# 按(Forward PE越低越好, 增速越高越好)排序
scored = []
for r in results:
    if '错误' in r: continue
    pe = r['PE(TTM)']
    fpe = r['Forward PE']
    growth = r['营收增速']
    if pe and fpe and growth is not None and growth > 0:
        score = growth * 100 / fpe  # PEG-like score
        scored.append((score, r))

scored.sort(key=lambda x: x[0], reverse=True)

print(f"\n{'排名':<6} {'代码':<8} {'Forward PE':<12} {'增速':<10} {'PEG得分':<10} {'AI产业链位置':<30} {'市值':<14}")
print("-"*110)
for i, (score, r) in enumerate(scored, 1):
    fpe = f"{r['Forward PE']:.1f}x" if r['Forward PE'] else 'N/A'
    g = pct(r['营收增速'])
    mc = fmt(r['市值'])
    # 找产业链位置描述
    desc = SERENITY_PICKS.get(r['代码'], VALUE_CANDIDATES.get(r['代码'], ''))
    print(f"{i:<6} {r['代码']:<8} {fpe:<12} {g:<10} {score:.2f}x{'':<6} {desc[:28]:<30} {mc:<14}")

# 按PE排序的全列表
print("\n\n📊 全列表按PE排序:")
all_sorted = sorted([r for r in results if '错误' not in r], key=lambda x: x.get('PE(TTM)') or 999)
for r in all_sorted:
    pe = r['PE(TTM)']
    fpe = r['Forward PE']
    g = r['营收增速']
    tag = '✅' if pe and pe < 20 else ('🟡' if pe and pe < 25 else '❌')
    fpe_s = f"{fpe:.1f}x" if fpe else 'N/A'
    desc = SERENITY_PICKS.get(r['代码'], VALUE_CANDIDATES.get(r['代码'], ''))
    print(f"  {tag} {r['代码']:<6} PE={pe or 'N/A':<8} Fwd={fpe_s:<10} 增速={pct(g):<10} {desc[:40]}")

print("\n\n✅ 完成！")
