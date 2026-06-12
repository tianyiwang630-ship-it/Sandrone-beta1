"""
AI隐藏gem标的 - 财务数据批量拉取
拉取美股11只标的 + 可参考的对比标的
"""

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import json
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ========== 标的列表 ==========
TICKERS = {
    'CRDO': 'Credo Technology',
    'RMBS': 'Rambus',
    'AAOI': 'Applied Optoelectronics',
    'CLS': 'Celestica',
    'LITE': 'Lumentum',
    'STX': 'Seagate Technology',
    'MRVL': 'Marvell Technology',
    'VRT': 'Vertiv',
    'COHR': 'Coherent',
    'GEV': 'GE Vernova',
    'PWR': 'Quanta Services',
}

# 对比标的
BENCHMARKS = {
    'NVDA': 'NVIDIA',
    'AMD': 'AMD',
    'AVGO': 'Broadcom',
    'GOOGL': 'Google/Alphabet',
}

all_tickers = list(TICKERS.keys()) + list(BENCHMARKS.keys())

def fetch_stock_data(ticker_list):
    """拉取实时股价和估值数据"""
    results = []
    
    for t in ticker_list:
        try:
            stock = yf.Ticker(t)
            info = stock.info
            
            # 实时价格
            price = info.get('currentPrice') or info.get('regularMarketPrice') or info.get('previousClose')
            market_cap = info.get('marketCap')
            
            # 财务数据
            revenue = info.get('totalRevenue')
            gross_profit = info.get('grossProfits')
            net_income = info.get('netIncomeToCommon')
            
            # 利润率
            gross_margin = info.get('grossMargins')
            net_margin = info.get('profitMargins')
            op_margin = info.get('operatingMargins')
            
            # 估值
            pe_ratio = info.get('trailingPE')
            forward_pe = info.get('forwardPE')
            ps_ratio = info.get('priceToSalesTrailing12Months')
            pb_ratio = info.get('priceToBook')
            ev_to_revenue = info.get('enterpriseToRevenue')
            ev_to_ebitda = info.get('enterpriseToEbitda')
            
            # 增长
            rev_growth = info.get('revenueGrowth')
            earnings_growth = info.get('earningsGrowth')
            
            # 分红
            div_yield = info.get('dividendYield')
            
            # 52周高/低
            high_52w = info.get('fiftyTwoWeekHigh')
            low_52w = info.get('fiftyTwoWeekLow')
            
            # 分析师目标
            target_mean = info.get('targetMeanPrice')
            target_high = info.get('targetHighPrice')
            target_low = info.get('targetLowPrice')
            
            # 股权结构
            shares_out = info.get('sharesOutstanding')
            float_shares = info.get('floatShares')
            inst_own = info.get('heldPercentInstitutions')
            
            results.append({
                '代码': t,
                '公司名': info.get('longName') or info.get('shortName') or t,
                '股价': price,
                '市值': market_cap,
                '营收(TTM)': revenue,
                '毛利润': gross_profit,
                '净利润': net_income,
                '毛利率': gross_margin,
                '净利率': net_margin,
                '经营利润率': op_margin,
                'PE(TTM)': pe_ratio,
                'Forward PE': forward_pe,
                'PS(TTM)': ps_ratio,
                'PB': pb_ratio,
                'EV/营收': ev_to_revenue,
                'EV/EBITDA': ev_to_ebitda,
                '营收增速': rev_growth,
                '净利润增速': earnings_growth,
                '股息率': div_yield,
                '52周最高': high_52w,
                '52周最低': low_52w,
                '目标均价': target_mean,
                '目标最高': target_high,
                '目标最低': target_low,
                '流通股': shares_out,
                '机构持仓': inst_own,
                '行业': info.get('industry'),
                '板块': info.get('sector'),
            })
            print(f"✅ {t} ({TICKERS.get(t, BENCHMARKS.get(t, ''))}) - 数据获取成功")
            
        except Exception as e:
            print(f"❌ {t} - 错误: {e}")
            results.append({
                '代码': t,
                '公司名': TICKERS.get(t, BENCHMARKS.get(t, t)),
                '错误': str(e)
            })
    
    return pd.DataFrame(results)

def fetch_quarterly_revenue(ticker_list):
    """拉取季度营收数据，追踪增长趋势"""
    results = []
    
    for t in ticker_list:
        try:
            stock = yf.Ticker(t)
            
            # 获取季度财报
            financials = stock.quarterly_financials
            
            if financials is not None and not financials.empty:
                # 取最近4个季度
                recent_q = financials.iloc[:, :4]
                if 'Total Revenue' in recent_q.index:
                    rev_q = recent_q.loc['Total Revenue']
                    results.append({
                        '代码': t,
                        '公司': TICKERS.get(t, BENCHMARKS.get(t, t)),
                        '最近季度营收': rev_q.values.tolist(),
                        '最近季度日期': [str(d.date()) for d in rev_q.index],
                    })
                    print(f"✅ {t} - 季度营收: {rev_q.values.tolist()}")
            
        except Exception as e:
            print(f"❌ {t} - 季度数据错误: {e}")
    
    return results

def format_currency(value):
    """格式化货币值"""
    if value is None:
        return 'N/A'
    if abs(value) >= 1e12:
        return f'${value/1e12:.2f}T'
    if abs(value) >= 1e9:
        return f'${value/1e9:.2f}B'
    if abs(value) >= 1e6:
        return f'${value/1e6:.2f}M'
    return f'${value:,.0f}'

def format_pct(value):
    """格式化百分比"""
    if value is None:
        return 'N/A'
    return f'{value*100:.1f}%'

def main():
    print("=" * 80)
    print("📊 AI隐藏gem标的 - 财务数据批量拉取")
    print(f"⏰ 数据时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 80)
    
    # 1. 拉取基础数据
    print("\n📥 正在拉取基础财务数据...\n")
    df = fetch_stock_data(all_tickers)
    
    # 2. 整理输出
    print("\n" + "=" * 80)
    print("📋 完整财务数据")
    print("=" * 80)
    
    # 核心指标
    display_cols = ['代码', '公司名', '股价', '市值', '营收(TTM)', '净利润', 
                    '毛利率', '净利率', '经营利润率', 'PE(TTM)', 'Forward PE', 
                    'PS(TTM)', '营收增速', '净利润增速', '目标均价']
    
    for col in display_cols:
        if col not in df.columns:
            continue
    
    # 分组显示
    print("\n" + "-" * 80)
    print("📌 AI隐藏gem标的")
    print("-" * 80)
    gem_df = df[df['代码'].isin(TICKERS.keys())].copy()
    for _, row in gem_df.iterrows():
        name = f"{row['代码']} ({row.get('公司名', '')})"
        print(f"\n{'='*60}")
        print(f"  {name}")
        print(f"{'='*60}")
        print(f"  💰 股价: ${row.get('股价', 'N/A')}  |  市值: {format_currency(row.get('市值'))}")
        print(f"  📊 营收(TTM): {format_currency(row.get('营收(TTM)'))}  |  净利润: {format_currency(row.get('净利润'))}")
        print(f"  📈 毛利率: {format_pct(row.get('毛利率'))}  |  净利率: {format_pct(row.get('净利率'))}  |  经营利润率: {format_pct(row.get('经营利润率'))}")
        print(f"  🔢 PE(TTM): {row.get('PE(TTM)', 'N/A')}  |  Forward PE: {row.get('Forward PE', 'N/A')}  |  PS: {row.get('PS(TTM)', 'N/A')}")
        print(f"  🚀 营收增速: {format_pct(row.get('营收增速'))}  |  净利润增速: {format_pct(row.get('净利润增速'))}")
        print(f"  🎯 分析师目标: ${row.get('目标均价', 'N/A')}  |  最高: ${row.get('目标最高', 'N/A')}  |  最低: ${row.get('目标最低', 'N/A')}")
        print(f"  🏢 行业: {row.get('行业', 'N/A')}  |  板块: {row.get('板块', 'N/A')}")
        print(f"  📐 PB: {row.get('PB', 'N/A')}  |  EV/EBITDA: {row.get('EV/EBITDA', 'N/A')}")
        print(f"  🏛️  机构持仓: {format_pct(row.get('机构持仓'))}")

    print("\n" + "-" * 80)
    print("📌 对比标杆")
    print("-" * 80)
    bench_df = df[df['代码'].isin(BENCHMARKS.keys())].copy()
    for _, row in bench_df.iterrows():
        name = f"{row['代码']} ({row.get('公司名', '')})"
        print(f"\n  {name}")
        print(f"  💰 股价: ${row.get('股价', 'N/A')}  |  市值: {format_currency(row.get('市值'))}")
        print(f"  📊 营收(TTM): {format_currency(row.get('营收(TTM)'))}  |  净利润: {format_currency(row.get('净利润'))}")
        print(f"  📈 毛利率: {format_pct(row.get('毛利率'))}  |  净利率: {format_pct(row.get('净利率'))}")
        print(f"  🔢 PE(TTM): {row.get('PE(TTM)', 'N/A')}  |  Forward PE: {row.get('Forward PE', 'N/A')}  |  PS: {row.get('PS(TTM)', 'N/A')}")
        print(f"  🚀 营收增速: {format_pct(row.get('营收增速'))}")
        print(f"  🎯 分析师目标: ${row.get('目标均价', 'N/A')}")

    # 3. 季度营收追踪
    print("\n\n" + "=" * 80)
    print("📅 季度营收趋势")
    print("=" * 80)
    
    q_results = fetch_quarterly_revenue(list(TICKERS.keys()))
    for q in q_results:
        print(f"\n  {q['代码']} ({q['公司']}):")
        for date, rev in zip(q['最近季度日期'], q['最近季度营收']):
            print(f"    {date}: {format_currency(rev)}")
    
    # 4. 关键估值对比表
    print("\n\n" + "=" * 80)
    print("📊 关键指标对比矩阵")
    print("=" * 80)
    
    # 按PS排序
    sorted_df = df[df['代码'].isin(TICKERS.keys())].sort_values('PS(TTM)', ascending=True)
    print(f"\n{'代码':<8} {'公司':<25} {'PS':<10} {'PE':<10} {'FwdPE':<10} {'营收增速':<12} {'毛利率':<10} {'市值':<15}")
    print("-" * 100)
    for _, row in sorted_df.iterrows():
        ps = f"{row.get('PS(TTM)', 'N/A'):.1f}x" if isinstance(row.get('PS(TTM)'), (int, float)) else 'N/A'
        pe = f"{row.get('PE(TTM)', 'N/A'):.1f}x" if isinstance(row.get('PE(TTM)'), (int, float)) else 'N/A'
        fpe = f"{row.get('Forward PE', 'N/A'):.1f}x" if isinstance(row.get('Forward PE'), (int, float)) else 'N/A'
        g = format_pct(row.get('营收增速'))
        gm = format_pct(row.get('毛利率'))
        mc = format_currency(row.get('市值'))
        print(f"{row['代码']:<8} {str(row.get('公司名', ''))[:24]:<25} {ps:<10} {pe:<10} {fpe:<10} {g:<12} {gm:<10} {mc:<15}")

    print("\n\n✅ 数据拉取完成！")

if __name__ == '__main__':
    main()
