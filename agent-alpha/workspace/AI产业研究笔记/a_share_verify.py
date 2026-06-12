"""
A股 AI产业链小众标的 — yfinance数据验证
注意：yfinance对A股支持有限，会有一些数据缺失
"""
import yfinance as yf
import sys
sys.stdout.reconfigure(encoding='utf-8')

# A股候选标的列表 - 搜索发现的
A_CANDIDATES = {
    # 赛道1：光芯片（光模块上游）核心候选
    '688498.SS': '源杰科技 - 光芯片(EML激光器)',
    # 赛道2：AI液冷
    '300499.SZ': '高澜股份 - 数据中心液冷',
    # 赛道3：服务器电源
    '300870.SZ': '欧陆通 - AI服务器电源',
    # 赛道4：光器件/光纤连接器
    '300570.SZ': '太辰光 - 光纤连接器',
    # 赛道5：服务器连接器
    '688668.SS': '鼎通科技 - 服务器连接器',
    # 赛道6：光器件
    '300548.SZ': '博创科技(长芯博创) - 光分路器/WDM',
    # 赛道7：液冷-补充
    '002837.SZ': '英维克 - 数据中心精密空调',
    # 赛道8：PCB-微小市值
    '300476.SZ': '胜宏科技 - AI服务器PCB',
    # 赛道9：封装基板
    '002436.SZ': '兴森科技 - FCBGA封装基板',
    # 赛道10：检测
    '688001.SS': '华兴源创 - 半导体检测',
    # 赛道11：HBM存储国产
    '603986.SS': '兆易创新 - NOR闪存/MCU',
    # 赛道12：内存接口
    '688008.SS': '澜起科技 - 内存接口芯片',
    # 赛道13：光纤光缆
    '601869.SS': '长飞光纤 - 光纤光缆',
    # 赛道14：电源补充
    '002518.SZ': '科士达 - UPS/数据中心电源',
    # 赛道15：封装测试
    '600584.SS': '长电科技 - 先进封装',
    # 赛道16：封测补充
    '002156.SZ': '通富微电 - 先进封装',
    # 赛道17：电磁屏蔽
    '688020.SS': '方邦股份 - 电磁屏蔽膜',
    # 赛道18：散热基板
    '603186.SS': '华正新材 - 覆铜板',
    # 赛道19：光芯片补充
    '688048.SS': '长光华芯 - 激光芯片',
    # 赛道20：测试补充
    '300567.SZ': '精测电子 - 半导体检测',
}

print("="*90)
print("A股 AI产业链小众标的 — yfinance数据验证")
print("注意：yfinance对A股数据覆盖有限")
print("="*90)

for ticker, desc in A_CANDIDATES.items():
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        
        price = info.get('currentPrice') or info.get('regularMarketPrice') or info.get('previousClose')
        pe = info.get('trailingPE')
        fpe = info.get('forwardPE')
        pb = info.get('priceToBook')
        rev = info.get('totalRevenue')
        ni = info.get('netIncomeToCommon')
        rev_g = info.get('revenueGrowth')
        gm = info.get('grossMargins')
        mcap = info.get('marketCap')
        sector = info.get('sector')
        industry = info.get('industry')
        
        # 判断PE状态
        pe_status = ''
        if pe is None:
            pe_status = '❌N/A(亏损)'
        elif pe > 0 and pe < 20:
            pe_status = f'✅{pe:.1f}x(低估!)'
        elif pe > 0 and pe < 30:
            pe_status = f'🟡{pe:.1f}x(合理)'
        elif pe > 0 and pe < 50:
            pe_status = f'⚠️{pe:.1f}x(偏高)'
        else:
            pe_status = f'❌{pe:.1f}x(太高)' if pe else '❌N/A'
        
        rev_s = f"¥{rev/1e8:.1f}亿" if rev and rev > 1e6 else (f"${rev/1e6:.0f}M" if rev else 'N/A')
        ni_s = f"¥{ni/1e8:.1f}亿" if ni and abs(ni) > 1e6 else (f"${ni/1e6:.0f}M" if ni else 'N/A')
        mcap_s = f"¥{mcap/1e8:.0f}亿" if mcap else 'N/A'
        gm_s = f"{gm*100:.1f}%" if gm else 'N/A'
        g_s = f"{rev_g*100:.1f}%" if rev_g else 'N/A'
        price_s = f"¥{price:.2f}" if price else 'N/A'
        
        print(f"\n{[ticker]} {desc}")
        print(f"  股价:{price_s} | 市值:{mcap_s} | PE:{pe_status} | PB:{pb or 'N/A'}")
        print(f"  营收:{rev_s} | 净利:{ni_s} | 毛利率:{gm_s} | 增速:{g_s}")
        print(f"  行业:{sector} > {industry}" if sector else "")
        
    except Exception as e:
        print(f"\n[{ticker}] {desc} — ❌ 数据拉取失败: {str(e)[:60]}")

print("\n\n✅ 验证完成")
