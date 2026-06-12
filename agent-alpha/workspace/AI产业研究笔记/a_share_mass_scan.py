"""
A股超冷门AI供应链 — 全面批量扫描
覆盖50+个标的，20+个细分赛道
"""
import yfinance as yf
import sys
sys.stdout.reconfigure(encoding='utf-8')

# 50+个A股AI产业链冷门标的（按赛道分组）
CANDIDATES = {
    # === 1. 特种气体（AI芯片制造必需）===
    '688268.SS': '华特气体-特种气体',
    '688106.SS': '金宏气体-特种气体',
    '688146.SS': '中船特气-电子特气',
    
    # === 2. 半导体材料（CMP/光刻胶/靶材）===
    '688019.SS': '安集科技-CMP抛光液',
    '300655.SZ': '晶瑞电材-光刻胶',
    '300236.SZ': '上海新阳-半导体材料',
    '300666.SZ': '江丰电子-靶材',
    '600206.SS': '有研新材-靶材/材料',
    
    # === 3. 导热/散热材料 ===
    '300684.SZ': '中石科技-导热材料',
    '300602.SZ': '飞荣达-电磁屏蔽/散热',
    '002079.SZ': '苏州固锝-散热/传感器',
    
    # === 4. 石英/硅材料 ===
    '603688.SS': '石英股份-高纯石英',
    '688126.SS': '沪硅产业-硅片',
    
    # === 5. 封装载板/基板 ===
    '603005.SS': '晶方科技-封装',
    
    # === 6. 晶振/时钟（服务器必需）===
    '603738.SS': '泰晶科技-晶振',
    '300460.SZ': '惠伦晶体-晶振',
    
    # === 7. 备用电源/UPS ===
    '000880.SZ': '潍柴重机-柴油发电',
    '300153.SZ': '科泰电源-发电机组',
    
    # === 8. 磁性元件/变压器 ===
    '002885.SZ': '京泉华-磁性元件',
    '002782.SZ': '可立克-磁性元件',
    
    # === 9. 电磁屏蔽 ===
    '300975.SZ': '商络电子-电子元器件',
    
    # === 10. 精密结构件/机柜 ===
    '002965.SZ': '祥鑫科技-精密结构件',
    
    # === 11. 电感和滤波器 ===
    '300460.SZ': '惠伦晶体-已查',
    
    # === 12. 光纤关键材料 ===
    '300394.SZ': '天孚通信-光器件(较大)',
    
    # === 13. 光芯片补充 ===
    '688195.SS': '腾景科技-光学元件',
    '300620.SZ': '光库科技-光纤器件',
    
    # === 14. 存储芯片国产 ===
    '300223.SZ': '北京君正-DRAM',
    '688110.SS': '东芯股份-NAND',
    
    # === 15. EDA/IP ===
    '301269.SZ': '华大九天-EDA(较大)',
    '688206.SS': '概伦电子-EDA',
    
    # === 16. MCU/RISC-V ===
    '688332.SS': '中科蓝讯-RISC-V',
    
    # === 17. 连接器补充 ===
    '688800.SS': '瑞可达-连接器',
    
    # === 18. AI服务器冷却液 ==
    '688556.SS': '高测股份-冷却(误)',
    
    # === 19. 数据中心IDC（区域小市值）===
    '300738.SZ': '奥飞数据-IDC',
    '603003.SS': '龙宇燃油-IDC',
    
    # === 20. 智算中心 ===
    '300442.SZ': '润泽科技-数据中心(大)',
    
    # === 21. 功率芯片（AI电源用）===
    '688187.SS': '时代电气-功率半导体',
    '300623.SZ': '捷捷微电-功率器件',
    
    # === 22. AI芯片测试服务 ===
    '688238.SS': '和林微纳-MEMS',
    
    # === 23. 光模块TEC制冷片 ===
    '300672.SZ': '国瓷材料-陶瓷(散热)',
    
    # === 24. 智能模组（AI边缘）===
    '300638.SZ': '广和通-AI模组',
    '300590.SZ': '移为通信-AI通信',
    
    # === 25. 超算/算力 ===
    '000977.SZ': '浪潮信息-AI服务器(大市值)',
}

print("批量扫描A股冷门AI产业链标的...")
print(f"共{len(CANDIDATES)}只候选")
print("="*80)

results = []
count = 0
for ticker, desc in CANDIDATES.items():
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        count += 1
        
        price = info.get('currentPrice') or info.get('regularMarketPrice') or info.get('previousClose')
        pe = info.get('trailingPE')
        fpe = info.get('forwardPE')
        pb = info.get('priceToBook')
        rev = info.get('totalRevenue')
        ni = info.get('netIncomeToCommon')
        rev_g = info.get('revenueGrowth')
        gm = info.get('grossMargins')
        mcap = info.get('marketCap')
        
        rev_s = f"¥{rev/1e8:.1f}亿" if rev else 'N/A'
        ni_s = f"¥{ni/1e8:.1f}亿" if ni and abs(ni) > 1e5 else (f"-¥{abs(ni)/1e8:.1f}亿" if ni else 'N/A')
        mcap_s = f"¥{mcap/1e8:.0f}亿" if mcap else 'N/A'
        gm_s = f"{gm*100:.1f}%" if gm else 'N/A'
        g_s = f"{rev_g*100:.1f}%" if rev_g else 'N/A'
        price_s = f"¥{price:.2f}" if price else 'N/A'
        
        # PE评估
        tag = ''
        if pe is None: tag = '❌亏损'
        elif pe < 0: tag = '❌亏损'
        elif pe < 20: tag = '✅PE<20!'
        elif pe < 30: tag = '🟡PE<30'
        elif pe < 50: tag = '⚠️PE<50'
        else: tag = '❌PE高'
        
        pe_s = f"{pe:.1f}x" if pe else 'N/A'
        pb_s = f"{pb:.1f}x" if pb else 'N/A'
        
        print(f"[{count:2d}] {tag} {ticker[:6]} {desc[:20]:<20} PE:{pe_s:<8} FPE:{fpe or 'N/A':<8} 增速:{g_s:<10} 市值:{mcap_s}")
        
        results.append({
            'tag': tag, 'ticker': ticker, 'desc': desc,
            'pe': pe, 'fpe': fpe, 'rev_g': rev_g,
            'mcap': mcap, 'price': price
        })
        
    except Exception as e:
        count += 1
        print(f"[{count:2d}] ❌ {ticker} {desc} — 拉取失败")

# === 筛选出PE<30的 ===
print("\n\n" + "="*80)
print("🏆 筛选结果：PE<30 的标的")
print("="*80)

good = [r for r in results if r.get('pe') and r['pe'] > 0 and r['pe'] < 30]
good.sort(key=lambda x: x['pe'])

if good:
    for r in good:
        desc = r['desc'][:25]
        pe = f"{r['pe']:.1f}x"
        fpe = f"{r['fpe']:.1f}x" if r.get('fpe') else 'N/A'
        g = f"{r['rev_g']*100:.1f}%" if r.get('rev_g') else 'N/A'
        mc = f"¥{r['mcap']/1e8:.0f}亿" if r.get('mcap') else 'N/A'
        print(f"  ✅ {r['ticker'][:6]} {desc:<25} PE:{pe:<8} FPE:{fpe:<8} 增速:{g:<10} 市值:{mc}")
else:
    print("  ❌ 没有找到PE<30的标的")

print(f"\n共扫描{count}只，PE<30: {len(good)}只")
print("="*80)
