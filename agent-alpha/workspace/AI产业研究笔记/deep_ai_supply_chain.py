"""
AI产业链 - 第一性原理深度挖掘
从产业链最底层向上分解，寻找PE < 20的被低估标的
"""
import yfinance as yf
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

print("="*100)
print("AI产业链第一性原理分解 - 底层扫描")
print("="*100)

# 根据第一性原理，AI产业链从底层到上层：
# 1. 原材料层 - 铜/光纤/稀土
# 2. 电力基础设施 - 变压器/开关设备/备用电源/母线槽
# 3. 散热层 - 液冷/精密空调
# 4. 连接器层 - 高速连接器/线缆
# 5. 测试测量层 - 芯片/光模块测试
# 6. 网络设备层 - 交换机/路由器
# 7. 存储层 - HDD/SSD/内存
# 8. 封装层 - IC载板/封装
# 9. AI芯片层 - ASIC/GPU

# 候选标的 - 关注估值合理 (PE<20或接近) 的AI产业链深度受益者
CANDIDATES = {
    # === 原材料层 ===
    'FCX': 'Freeport-McMoRan (铜) - AI数据中心铜需求',
    'SCCO': 'Southern Copper (铜)',
    
    # === 电力基础设施层 ===
    'ETN': 'Eaton (电力管理)',
    'HUBB': 'Hubbell (电气设备)',
    'NVT': 'nVent Electric (电气连接)',
    'PWR': 'Quanta Services (电力工程)',
    
    # === 连接器层 ===
    'APH': 'Amphenol (高速连接器) - 数据中心连接器龙头',
    'TEL': 'TE Connectivity (连接器/传感器)',
    'GLW': 'Corning (光纤/玻璃) - 数据中心光纤骨干',
    
    # === 测试测量层 ===
    'TER': 'Teradyne (芯片测试) - AI芯片测试需求',
    'COHU': 'Cohu (半导体测试)',
    'FORM': 'FormFactor (晶圆探针)',
    'KEYS': 'Keysight (测试测量)',
    
    # === 工业气体(芯片制造必需) ===
    'LIN': 'Linde (工业气体) - 芯片制造气体',
    'APD': 'Air Products (工业气体)',
    
    # === 网络设备 ===
    'CSCO': 'Cisco (网络设备) - AI数据中心交换机',
    'CIEN': 'Ciena (光网络)',
    'JNPR': 'Juniper Networks (网络)',
    'ANET': 'Arista Networks (数据中心交换机)',
    
    # === 存储/内存 ===
    'MU': 'Micron (HBM/内存) - AI HBM核心供应商',
    'WDC': 'Western Digital (HDD/SSD)',
    
    # === 传统芯片 ===
    'INTC': 'Intel (芯片)',
    'QRVO': 'Qorvo (射频)',
    'SWKS': 'Skyworks (射频)',
    'TXN': 'Texas Instruments (模拟芯片)',
    
    # === 散热 ===
    'TT': 'Trane Technologies (暖通空调)',
    'CARR': 'Carrier Global (暖通)',
    'JCI': 'Johnson Controls (楼宇控制/散热)',
    
    # === 封装 ===
    'AMKR': 'Amkor (芯片封装)',
    
    # === AI服务器 ===
    'DELL': 'Dell Technologies (AI服务器)',
    'HPE': 'Hewlett Packard Enterprise (AI服务器)',
    'HPQ': 'HP Inc (PC/打印)',
    'SMCI': 'Super Micro Computer (AI服务器)',
    
    # === 电力设备/能源(AI电力需求) ===
    'GEV': 'GE Vernova (电力)',
    'VRT': 'Vertiv (数据中心电源/散热)',
    'NRG': 'NRG Energy (电力)',
    'CEG': 'Constellation Energy (核电)',
    'TLN': 'Talen Energy (核电/AI数据中心)',
    'VST': 'Vistra Energy (电力)',
    
    # === 工业自动化 ===
    'ROK': 'Rockwell Automation',
    'EMR': 'Emerson Electric',
    
    # === 数据中心REITs ===
    'EQIX': 'Equinix (数据中心REIT)',
    'DLR': 'Digital Realty (数据中心REIT)',
    
    # === 半导体制造 ===
    'TSM': 'TSMC (晶圆代工)',
    'UMC': 'UMC (晶圆代工)',
    
    # === 半导体设备 ===
    'AMAT': 'Applied Materials (半导体设备)',
    'LRCX': 'Lam Research (半导体设备)',
    'KLAC': 'KLA Corp (半导体设备检测)',
    
    # === 日本AI相关 ===
    'SONY': 'Sony (半导体/AI)', 
    
    # === AI电力-天然气 ===
    'OKLO': 'Oklo (小型核电站)',
    'SMR': 'NuScale (小型核电站)',
}

def analyze(ticker):
    """分析单只股票"""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        
        price = info.get('currentPrice') or info.get('regularMarketPrice') or info.get('previousClose') or 0
        mkt_cap = info.get('marketCap')
        pe = info.get('trailingPE')
        forward_pe = info.get('forwardPE')
        pb = info.get('priceToBook')
        revenue = info.get('totalRevenue')
        net_income = info.get('netIncomeToCommon')
        gross_margin = info.get('grossMargins')
        net_margin = info.get('profitMargins')
        rev_growth = info.get('revenueGrowth')
        earnings_growth = info.get('earningsGrowth')
        sector = info.get('sector')
        industry = info.get('industry')
        
        # 获取历史财务数据 (2年)
        bs = stock.balance_sheet
        inc_stmt = stock.financials
        
        return {
            '代码': ticker,
            '公司': info.get('longName') or info.get('shortName') or ticker,
            '股价': price,
            '市值': mkt_cap,
            'PE': pe,
            'Forward PE': forward_pe,
            'PB': pb,
            '营收(TTM)': revenue,
            '净利润(TTM)': net_income,
            '毛利率': gross_margin,
            '净利率': net_margin,
            '营收增速': rev_growth,
            '净利润增速': earnings_growth,
            '行业': industry,
            '板块': sector,
        }
    except Exception as e:
        return {'代码': ticker, '错误': str(e)}

def fmt(v, prefix='$'):
    if v is None: return 'N/A'
    if isinstance(v, str): return v
    if abs(v) >= 1e12: return f'{prefix}{v/1e12:.2f}T'
    if abs(v) >= 1e9: return f'{prefix}{v/1e9:.2f}B'
    if abs(v) >= 1e6: return f'{prefix}{v/1e6:.2f}M'
    return f'{prefix}{v:,.0f}'

def pct(v):
    if v is None: return 'N/A'
    return f'{v*100:.1f}%'

results = []
for i, (ticker, desc) in enumerate(CANDIDATES.items()):
    print(f"\n[{i+1}/{len(CANDIDATES)}] {ticker} - {desc}")
    r = analyze(ticker)
    results.append(r)
    
    if '错误' in r:
        print(f"  ❌ 错误: {r['错误']}")
        continue
    
    pe_str = f"{r['PE']:.1f}x" if r['PE'] else 'N/A'
    fpe_str = f"{r['Forward PE']:.1f}x" if r.get('Forward PE') else 'N/A'
    # 判断是否值得关注 (PE < 20)
    is_value = r['PE'] and r['PE'] < 20
    is_near_value = r['PE'] and r['PE'] < 25
    tag = '✅ PE<20' if is_value else ('🟡 PE<25' if is_near_value else '❌ PE>25')
    
    price_str = f"${r['股价']:.2f}" if r['股价'] and r['股价'] > 0 else 'N/A'
    print(f"  💰 {price_str} | 市值: {fmt(r['市值'])}")
    print(f"  📊 营收: {fmt(r['营收(TTM)'])} | 利润: {fmt(r['净利润(TTM)'])}")
    pe_str = f"{r['PE']:.1f}x" if r['PE'] else 'N/A'
    fpe_str = f"{r['Forward PE']:.1f}x" if r.get('Forward PE') else 'N/A'
    pb_str = f"{r['PB']:.1f}x" if r['PB'] else 'N/A'
    print(f"  📈 PE: {pe_str} | Forward PE: {fpe_str} | PB: {pb_str}")
    print(f"  💎 毛利率: {pct(r['毛利率'])} | 净利率: {pct(r['净利率'])}")
    print(f"  🚀 营收增速: {pct(r['营收增速'])} | 利润增速: {pct(r['净利润增速'])}")
    print(f"  🏢 {r['板块']} / {r['行业']}")
    print(f"  {tag}")

# === 统计筛选 ===
print("\n\n" + "="*100)
print("📊 PE < 20 的AI产业链潜在标的（按营收增速排序）")
print("="*100)

value_plays = [r for r in results if r.get('PE') and r['PE'] < 20 and '错误' not in r]
value_plays.sort(key=lambda x: x.get('营收增速') or 0, reverse=True)

if value_plays:
    print(f"\n{'代码':<8} {'公司':<30} {'PE':<8} {'FwdPE':<10} {'营收增速':<10} {'利润率':<10} {'营收':<12} {'市值':<14}")
    print("-"*100)
    for r in value_plays:
        pe = f"{r['PE']:.1f}x"
        fpe = f"{r['Forward PE']:.1f}x" if r.get('Forward PE') else 'N/A'
        g = pct(r['营收增速'])
        m = pct(r['净利率'])
        rev = fmt(r['营收(TTM)'])
        mc = fmt(r['市值'])
        print(f"{r['代码']:<8} {str(r.get('公司',''))[:28]:<30} {pe:<8} {fpe:<10} {g:<10} {m:<10} {rev:<12} {mc:<14}")
else:
    print("没有找到PE<20的标的")

# PE 20-30的潜在关注
print("\n\n📊 PE 20-30的AI产业链标的（次优关注）")
print("-"*80)
near_value = [r for r in results if r.get('PE') and 20 <= r['PE'] < 30 and '错误' not in r]
near_value.sort(key=lambda x: x.get('营收增速') or 0, reverse=True)

if near_value:
    print(f"\n{'代码':<8} {'公司':<30} {'PE':<8} {'营收增速':<10} {'净利率':<10} {'营收':<12}")
    print("-"*80)
    for r in near_value:
        pe = f"{r['PE']:.1f}x"
        g = pct(r['营收增速'])
        m = pct(r['净利率'])
        rev = fmt(r['营收(TTM)'])
        print(f"{r['代码']:<8} {str(r.get('公司',''))[:28]:<30} {pe:<8} {g:<10} {m:<10} {rev:<12}")
        
print(f"\n\n📊 全列表按PE排序:")
all_sorted = sorted([r for r in results if '错误' not in r], key=lambda x: x.get('PE') or 999)
for r in all_sorted:
    pe = f"{r['PE']:.1f}x" if r.get('PE') else 'N/A'
    tag = '✅' if r.get('PE') and r['PE'] < 20 else ('🟡' if r.get('PE') and r['PE'] < 30 else '❌')
    g = pct(r['营收增速'])
    print(f"  {tag} {r['代码']:<6} PE={pe:<8} 营收增速={g:<10} {r.get('公司','')[:40]}")
