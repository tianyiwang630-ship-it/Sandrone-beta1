"""
✅ 数据验证脚本
- 用两个不同方法获取同一数据交叉验证
- 检查财务报告最新数据
"""
import yfinance as yf
import json, sys
sys.stdout.reconfigure(encoding='utf-8')

TICKERS = {
    'SMCI': 'Super Micro - AI服务器',
    'MU': 'Micron - HBM存储',
    'CEG': 'Constellation Energy - AI核电',
    'HUBB': 'Hubbell - 配电/变压器',
    'LII': 'Lennox - 液冷散热',
    'TEL': 'TE Connectivity - 连接器',
    'AAOI': 'Applied Opto - 光模块',
    'CRDO': 'Credo - AI网络互联',
    'ENS': 'EnerSys - 备用电池',
    'JBL': 'Jabil - 光模块代工',
    'VST': 'Vistra - AI电力',
    'QRVO': 'Qorvo - 射频',
    'GEV': 'GE Vernova - 燃气发电机',
}

def deep_verify(ticker):
    """深度验证一个标的的所有指标"""
    print(f"\n{'='*70}")
    print(f"🔍 深度验证: {ticker} ({TICKERS.get(ticker, '')})")
    print(f"{'='*70}")
    
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        
        # === 1. 基础数据双重验证 ===
        price1 = info.get('currentPrice')
        price2 = info.get('regularMarketPrice')
        price3 = info.get('previousClose')
        price = price1 or price2 or price3 or 0
        
        mcap1 = info.get('marketCap')
        mcap2 = info.get('enterpriseValue')
        
        pe1 = info.get('trailingPE')
        pe2 = info.get('forwardPE')
        
        # 验证PE的可靠性
        pe_verified = False
        if pe1:
            # 用净利和市值反推PE验证
            ni = info.get('netIncomeToCommon')
            shares = info.get('sharesOutstanding')
            if ni and shares and price:
                implied_pe = mcap1 / ni if mcap1 and ni else None
                diff = abs(implied_pe/pe1 - 1) if implied_pe and pe1 else 999
                pe_verified = diff < 0.15  # 误差15%以内
                print(f"  ✅ PE验证: 报表PE={pe1:.1f}x | 反推PE={implied_pe:.1f}x | 差异={diff*100:.1f}% | {'✅通过' if pe_verified else '⚠️需注意'}")
        
        print(f"  💰 股价: ${price:.2f} (来源: currentPrice={price1}, marketPrice={price2}, prevClose={price3})")
        print(f"  🏢 市值: ${mcap1/1e9:.2f}B | 企业价值: ${mcap2/1e9:.2f}B" if mcap2 else f"  🏢 市值: ${mcap1/1e9:.2f}B")
        
        # === 2. 利润表详细分析 ===
        inc = stock.financials
        if inc is not None:
            print(f"\n  📋 利润表最近4期:")
            for col in inc.columns[:4]:
                date = col.strftime('%Y-%m') if hasattr(col, 'strftime') else str(col)[:7]
                rev = inc.loc['Total Revenue'][col] if 'Total Revenue' in inc.index else None
                ni_val = inc.loc['Net Income'][col] if 'Net Income' in inc.index else None
                gp = inc.loc['Gross Profit'][col] if 'Gross Profit' in inc.index else None
                rev_s = f"${rev/1e6:.1f}M" if rev and rev < 1e9 else (f"${rev/1e9:.2f}B" if rev else 'N/A')
                ni_s = f"${ni_val/1e6:.1f}M" if ni_val and abs(ni_val) < 1e9 else (f"${ni_val/1e9:.2f}B" if ni_val else 'N/A')
                gm_s = f"{(gp/rev*100):.1f}%" if rev and gp else 'N/A'
                print(f"    {date}: 营收={rev_s} | 毛利={gm_s} | 净利={ni_s}")
        
        # === 3. 资产负债表/现金流 ===
        bs = stock.balance_sheet
        if bs is not None:
            print(f"\n  🏦 资产负债表(最新):")
            latest = bs.columns[0]
            cash = bs.loc['Cash And Cash Equivalents'][latest] if 'Cash And Cash Equivalents' in bs.index else None
            debt = bs.loc['Total Debt'][latest] if 'Total Debt' in bs.index else None
            equity = bs.loc['Stockholders Equity'][latest] if 'Stockholders Equity' in bs.index else None
            print(f"    现金: {f'${cash/1e9:.2f}B' if cash else 'N/A'}")
            print(f"    债务: {f'${debt/1e9:.2f}B' if debt else 'N/A'}")
            net_cash = (cash or 0) - (debt or 0)
            print(f"    净现金: {f'${net_cash/1e9:.2f}B' if abs(net_cash) > 1 else 'N/A'}")
            print(f"    股东权益: {f'${equity/1e9:.2f}B' if equity else 'N/A'}")
        
        # === 4. 增长数据验证 ===
        rev_g = info.get('revenueGrowth')
        earn_g = info.get('earningsGrowth')
        print(f"\n  📈 增长验证:")
        print(f"    报表营收增速: {f'{rev_g*100:.1f}%' if rev_g else 'N/A'} (yfinance字段)")
        print(f"    报表盈利增速: {f'{earn_g*100:.1f}%' if earn_g else 'N/A'}")
        
        # 验证营收增速：用利润表反推
        if inc is not None and 'Total Revenue' in inc.index and len(inc.columns) >= 2:
            latest_rev = inc.loc['Total Revenue'].iloc[0]
            prev_rev = inc.loc['Total Revenue'].iloc[1]
            if latest_rev and prev_rev and prev_rev > 0:
                calc_g = (latest_rev - prev_rev) / prev_rev
                print(f"    利润表计算增速: {calc_g*100:.1f}% (最新vs上期)")
        
        # === 5. 估值验证 ===
        print(f"\n  💎 估值验证:")
        fpe = info.get('forwardPE')
        peg = info.get('pegRatio')
        pb = info.get('priceToBook')
        ps = info.get('priceToSalesTrailing12Months')
        ev_ebitda = info.get('enterpriseToEbitda')
        print(f"    PE(TTM): {pe1:.1f}x" if pe1 else "    PE(TTM): N/A")
        print(f"    Forward PE: {fpe:.1f}x" if fpe else "    Forward PE: N/A")
        print(f"    PEG: {peg:.2f}" if peg else "    PEG: N/A")
        print(f"    PB: {pb:.2f}x" if pb else "    PB: N/A")
        print(f"    PS(TTM): {ps:.2f}x" if ps else "    PS: N/A")
        print(f"    EV/EBITDA: {ev_ebitda:.1f}x" if ev_ebitda else "    EV/EBITDA: N/A")
        
        # === 6. 行业位置验证 ===
        sector = info.get('sector')
        industry = info.get('industry')
        country = info.get('country')
        employees = info.get('fullTimeEmployees')
        print(f"\n  🏭 公司信息:")
        print(f"    行业: {sector} > {industry}")
        print(f"    国家: {country} | 员工: {employees or 'N/A'}")
        
        # 验证AI关联度
        biz_desc = info.get('longBusinessSummary', '')[:300]
        ai_keywords = ['AI', 'artificial intelligence', 'data center', 'machine learning', 'HBM', 'GPU', 'NVIDIA']
        found_keywords = [kw for kw in ai_keywords if kw.lower() in biz_desc.lower()]
        print(f"    AI关联关键词: {found_keywords if found_keywords else '⚠️未找到直接AI关键词'}")
        print(f"    业务描述: {biz_desc[:200]}...")
        
        return {
            'ticker': ticker,
            'price': price,
            'market_cap': mcap1,
            'pe': pe1,
            'fwd_pe': fpe,
            'pb': pb,
            'rev_growth': rev_g,
            'gross_margin': info.get('grossMargins'),
            'net_margin': info.get('profitMargins'),
            'rev': info.get('totalRevenue'),
            'net_income': ni,
            'debt': debt,
            'cash': cash,
            'pe_verified': pe_verified,
            'ai_signals': found_keywords,
        }
        
    except Exception as e:
        print(f"  ❌ 验证错误: {e}")
        return None

results = []
for ticker in TICKERS:
    r = deep_verify(ticker)
    if r:
        results.append(r)

# === 验证汇总 ===
print("\n\n" + "="*80)
print("📊 数据验证汇总表")
print("="*80)
print(f"{'标的':<8} {'股价':<10} {'市值':<12} {'PE(TTM)':<10} {'Fwd PE':<10} {'PB':<8} {'增速':<10} {'PE验证':<10} {'AI关联度'}")
print("-"*80)
for r in results:
    pe_s = f"{r['pe']:.1f}x" if r['pe'] else 'N/A'
    fpe_s = f"{r['fwd_pe']:.1f}x" if r['fwd_pe'] else 'N/A'
    pb_s = f"{r['pb']:.1f}x" if r['pb'] else 'N/A'
    g_s = f"{r['rev_growth']*100:.1f}%" if r['rev_growth'] else 'N/A'
    pe_v = '✅通过' if r.get('pe_verified') else ('⚠️' if r['pe'] else '❌N/A')
    ai_s = f"{len(r['ai_signals'])}个" if r['ai_signals'] else '⚠️无'
    mc_s = f"${r['market_cap']/1e9:.2f}B" if r['market_cap'] else 'N/A'
    price_s = f"${r['price']:.2f}"
    print(f"{r['ticker']:<8} {price_s:<10} {mc_s:<12} {pe_s:<10} {fpe_s:<10} {pb_s:<8} {g_s:<10} {pe_v:<10} {ai_s}")

print(f"\n{'='*80}")
print("数据源: yfinance (Yahoo Finance API)")
print(f"验证时间: 2026-06-10")
print("注：PE验证=用市值/净利反推确认数据一致性")
