"""
深度AI产业链小众标的扫描 — 聚焦隐蔽环节
"""
import yfinance as yf
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# 更隐蔽的AI产业链环节候选
DEEP_CANDIDATES = {
    # === 电力配电（变压器/开关柜）===
    'POWL': 'Powell Industries - 数据中心电力配电柜',
    'ENS': 'EnerSys - 数据中心备用电池/储能',
    'HUBB': 'Hubbell - 电气设备/变压器',
    
    # === 精密冷却 ===
    'SPXC': 'SPX Technologies - 冷却塔/热交换',
    'LII': 'Lennox Intl - 数据中心精密空调',
    'AOS': 'A.O. Smith - 热水/热管理',
    
    # === 电源模块 ===
    'VICR': 'Vicor - 高性能电源模块(AI芯片供电)',
    'BELFB': 'Bel Fuse - 电源/连接器',
    
    # === 光学精密制造 ===
    'FN': 'Fabrinet - 光模块精密制造(泰国)',
    'VIAV': 'Viavi Solutions - 光学测试',
    'NPTN': 'NeoPhotonics - 光通信(被收购)',
    
    # === 半导体先进封装 ===
    'AMKR': 'Amkor - 芯片封装',
    'ACMR': 'ACM Research - 半导体清洗设备',
    
    # === 屏蔽/电磁 ===
    'LITT': 'Littlefuse - 电路保护/传感器',
    
    # === 精密运动控制（芯片制造）===
    'AERI': 'Aerovironment - 精密控制',
    
    # === 数据中心布线和机架 ===
    'CHTR': 'Charter - 布线',
    
    # === 铜/铝加工(AI线缆需求) ===
    'HWM': 'Howmet Aerospace - 精密金属',
    
    # === 备份发电 ===
    'GEV': 'GE Vernova - 燃气发电机',
    'PCG': 'PG&E - 电网',
    
    # === 光纤连接器 ===
    'IIVI': 'Coherent (旧II-VI) - 已查',
    
    # === EDA软件(AI芯片设计必需) ===
    'CDNS': 'Cadence Design - EDA',
    'SNPS': 'Synopsys - EDA',
    
    # === AI数据标注/处理 ===
    'SCNW': 'Scanwave - AI数据',
    
    # === AI推理芯片(边缘) ===
}

# 补充之前扫描中接近PE<30的候选
NEAR_VALUE = {
    'QRVO': 'Qorvo - 射频芯片(5G+AI互联)',
    'SWKS': 'Skyworks - 射频',
    'TXN': 'TI - 模拟芯片(AI电源管理)',
    'MU': 'Micron - 内存/HBM',
    'WDC': 'Western Digital - 存储',
    'SMCI': 'Super Micro - AI服务器',
    'DELL': 'Dell - AI服务器',
    'HPE': 'HPE - AI服务器',
    'JBL': 'Jabil - 光模块代工',
}

ALL = {**DEEP_CANDIDATES, **NEAR_VALUE}

def fmt(v, prefix='$'):
    if v is None: return 'N/A'
    if abs(v) >= 1e12: return f'{prefix}{v/1e12:.2f}T'
    if abs(v) >= 1e9: return f'{prefix}{v/1e9:.2f}B'
    if abs(v) >= 1e6: return f'{prefix}{v/1e6:.2f}M'
    return f'{prefix}{v:,.0f}'

def pct(v):
    if v is None: return 'N/A'
    return f'{v*100:.1f}%'

results = []
for i, (ticker, desc) in enumerate(ALL.items()):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        price = info.get('currentPrice') or info.get('regularMarketPrice') or info.get('previousClose') or 0
        pe = info.get('trailingPE')
        fpe = info.get('forwardPE')
        pb = info.get('priceToBook')
        revenue = info.get('totalRevenue')
        net_income = info.get('netIncomeToCommon')
        gm = info.get('grossMargins')
        rev_g = info.get('revenueGrowth')
        mcap = info.get('marketCap')
        
        r = {'代码': ticker, '描述': desc, '股价': price, 'PE': pe, 'FPE': fpe, 'PB': pb, 
             '营收': revenue, '净利': net_income, '毛利率': gm, '营收增速': rev_g, '市值': mcap}
        results.append(r)
        
        pe_s = f"{pe:.1f}x" if pe else 'N/A'
        fpe_s = f"{fpe:.1f}x" if fpe else 'N/A'
        
        tag = '✅' if pe and pe < 20 else ('🟡' if pe and pe < 30 else ('⭐' if pe and pe < 40 else '❌'))
        
        print(f"\n[{i+1}] {tag} {ticker} - {desc}")
        print(f"    💰 ${price:.2f} | 市值: {fmt(mcap)} | PE: {pe_s} | Fwd: {fpe_s} | PB: {pb or 'N/A'}")
        print(f"    📊 营收: {fmt(revenue)} | 利润: {fmt(net_income)} | 毛利率: {pct(gm)} | 增速: {pct(rev_g)}")
        
    except Exception as e:
        print(f"\n[{i+1}] ❌ {ticker} - Error: {str(e)[:50]}")
        results.append({'代码': ticker, '描述': desc, 'PE': 999})

# === PE<30 的全部标的 ===
print("\n\n" + "="*100)
print("🏆 PE<30 的AI产业链标的（按营收增速排序）")
print("="*100)

good = [r for r in results if r.get('PE') and r['PE'] < 30 and r['PE'] > 0]
good.sort(key=lambda x: x.get('营收增速') or 0, reverse=True)

print(f"\n{'排名':<4} {'代码':<8} {'PE':<8} {'FPE':<8} {'营收增速':<10} {'毛利率':<10} {'市值':<14} {'AI供应链位置'}")
print("-"*100)
for i, r in enumerate(good, 1):
    pe = f"{r['PE']:.1f}x"
    fpe = f"{r['FPE']:.1f}x" if r.get('FPE') else 'N/A'
    g = pct(r['营收增速'])
    m = pct(r['毛利率'])
    mc = fmt(r['市值'])
    print(f"{i:<4} {r['代码']:<8} {pe:<8} {fpe:<8} {g:<10} {m:<10} {mc:<14} {r['描述'][:30]}")

# PE 30-40的
print("\n\n📊 PE 30-40 (可关注)")
mid = [r for r in results if r.get('PE') and 30 <= r['PE'] < 40]
mid.sort(key=lambda x: x.get('营收增速') or 0, reverse=True)
for r in mid:
    pe = f"{r['PE']:.1f}x"
    g = pct(r['营收增速'])
    print(f"  {r['代码']:<8} PE={pe:<8} 增速={g:<10} {r['描述'][:35]}")

print("\n\n✅ 全部数据拉取完成")
