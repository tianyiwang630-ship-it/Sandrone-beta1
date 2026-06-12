import os, json

js = r'''
const fs = require('fs');
const { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
        Header, Footer, AlignmentType, LevelFormat,
        HeadingLevel, BorderStyle, WidthType, ShadingType,
        VerticalAlign, PageNumber, PageBreak } = require('docx');

const F = "Arial", M = "Consolas";
const B = {style:BorderStyle.SINGLE,size:1,color:"BBBBBB"};
const CB = {top:B,bottom:B,left:B,right:B};
const HF = {fill:"1F3864",type:ShadingType.CLEAR};
const AF = {fill:"F2F7FB",type:ShadingType.CLEAR};
const WF = {fill:"FFFFFF",type:ShadingType.CLEAR};

const h1 = t => new Paragraph({heading:HeadingLevel.HEADING_1,children:[new TextRun(t)]});
const h2 = t => new Paragraph({heading:HeadingLevel.HEADING_2,children:[new TextRun(t)]});
const h3 = t => new Paragraph({heading:HeadingLevel.HEADING_3,children:[new TextRun(t)]});
const p = (t,o) => new Paragraph({spacing:{after:120},children:[new TextRun({text:t,size:22,font:F,...o||{}})]});
const pb = () => new Paragraph({children:[new PageBreak()]});
const sp = () => new Paragraph({spacing:{after:60},children:[]});
const cd = (t) => new Paragraph({spacing:{before:80,after:80},indent:{left:360},
  shading:{fill:"F5F5F5",type:ShadingType.CLEAR},
  children:[new TextRun({text:t,font:M,size:18,color:"333333"})]});

function hdr(cc, ww) {
  return new TableRow({tableHeader:true,
    children: cc.map((c,i)=>new TableCell({borders:CB,width:{size:ww[i],type:WidthType.DXA},
      shading:HF,verticalAlign:VerticalAlign.CENTER,
      children:[new Paragraph({alignment:AlignmentType.CENTER,
        children:[new TextRun({text:c,bold:true,size:20,color:"FFFFFF",font:F})]})]}))});
}
function dR(cc, ww, sh) {
  return new TableRow({children: cc.map((c,i)=>new TableCell({borders:CB,width:{size:ww[i],type:WidthType.DXA},
    shading:sh||WF,verticalAlign:VerticalAlign.CENTER,
    children:[new Paragraph({children:[new TextRun({text:String(c),size:20,font:F})]})]}))});
}
function tbl(hds, rows, ww) {
  const ws = Object.values(ww);
  return new Table({columnWidths:ws,rows:[hdr(hds,ws),...rows.map((r,i)=>dR(r,ws,i%2===0?WF:AF))]});
}

const C = [];

C.push(
  new Paragraph({alignment:AlignmentType.CENTER,spacing:{after:40},
    children:[new TextRun({text:"AI产业链小众标的",bold:true,size:44,font:F})]}),
  new Paragraph({alignment:AlignmentType.CENTER,spacing:{after:200},
    children:[new TextRun({text:"\u2014\u2014 \u5b8c\u6574\u7814\u7a76\u62a5\u544a\uff08\u542b\u94fe\u5f0f\u903b\u8f91\u63a8\u5bfc\uff09",size:24,color:"555555",font:F})]}),
  sp(),
  p("研究方法：CDP浏览器搜索(50+轮) + yfinance数据验证(80+只标的，20+细分赛道)"),
  p("搜索来源：Yahoo Finance、CNBC、Seeking Alpha、财联社、证券时报、东方财富、雪球、Reuters、Forbes等"),
  p("生成日期：2026年"),
  sp(),
  p("免责声明：本报告不构成投资建议。数据来源为公开信息，仅供参考。"),
  pb()
);

C.push(h1("一、核心结论"), sp());
C.push(p("A股没有同时满足[PE<30 + AI卡脖子 + 小众]三重要求的标的。美股发现了4只符合标准的标的。"), sp());
C.push(tbl(["市场","扫描数量","PE<30数量","逻辑+估值双符合"],
  [["A股","60+只冷门，20+赛道","3只（中科蓝讯/时代电气/润泽科技）","0只 X"],
   ["美股","20+只","6只","4只 Y"]], {a:1440,b:1800,c:1700,d:1420}), sp());

C.push(h1("二、美股完整逻辑推演"), sp());

// ===== SMCI =====
C.push(h2("标的1：超微电脑 SMCI"), h3("第一性原理变量 \u2192 需求保证的链式推导"), sp());
C.push(cd(`变量：AI训练/推理算力需求每12-18个月翻10倍
  \u2193
GPU从H100\u2192B200\u2192Rubin，单GPU功耗从350W\u21921500W+
  \u2193
单台服务器从8 GPU\u219272 GPU(NVL72)，功耗从3kW\u2192130kW+
  \u2193
传统风冷散热无法支撑 \u2192 DLC液冷从[可选]变[必选]
  \u2193
SMCI是全球最早大规模量产DLC液冷AI服务器的厂商（技术壁垒）
  \u2193
超大规模云厂商(AWS/Azure/GCP)的液冷服务器订单向SMCI倾斜
  \u2193
SMCI营收: FY24 $150亿 \u2192 FY25 $236亿(+57%) \u2192 FY26指引$360亿(+52%)`), sp());

C.push(h3("数据支撑"), sp());
C.push(tbl(["环节","具体数据","数据来源"],
  [["AI服务器营收占比",">70%（FY2025），且仍在提升","长江证券研报"],
   ["DLC液冷渗透率","从FY24的20% \u2192 FY26预期的70%+","CNBC报道"],
   ["FY26营收指引","$360亿（管理层保守指引，分析师预期更高）","Yahoo Finance"],
   ["Q3 FY26业绩","营收略miss但AI积压订单创历史新高","CNBC/Earnings Call"],
   ["PE","21.4x - 按传统服务器代工商估值","yfinance"],
   ["Fwd PE","12.5x - 利润增速远未被消化","yfinance"],
   ["毛利率","12-14%（偏低，但DLC方案高5-8pct）","财报"]], {a:1400,b:2300,c:2000}), sp());

C.push(h3("为什么存在定价错误"), sp());
C.push(p("Hindenburg Research在2024年8月发布做空报告后："));
C.push(p("1. 做空指控：关联交易、出口管制风险、审计问题"));
C.push(p("2. 审计延迟：年报从8月推迟到11月，引发退市恐慌"));
C.push(p("3. 市场思维定势：认为AI服务器是[量大利薄]的代工生意"), sp());
C.push(p("实际三点证伪："));
C.push(p("Y 审计已完成，无退市风险"));
C.push(p("Y DLC液冷技术有壁垒(100+专利)，不是简单组装"));
C.push(p("Y Blackwell Ultra/Rubin架构下液冷是唯一方案，SMCI是少数能量产厂商"), sp());

C.push(h3("AI利润弹性量化"), sp());
C.push(cd(`FY26 $360亿营收 x 13%毛利率 = $46.8亿毛利
扣除$20亿费用后约 $26.8亿净利 \u2192 Fwd PE约 360亿/26.8亿 = 13.4x
如果毛利率改善到15%（DLC占比提升）\u2192 净利$34亿 \u2192 PE仅10.6x`), sp());

// ===== MU =====
C.push(pb(), h2("标的2：美光科技 MU"), h3("第一性原理变量 \u2192 需求保证的链式推导"), sp());
C.push(cd(`变量：AI大模型参数量每18个月翻100倍（GPT-3 175B\u2192GPT-4 1.8T\u2192GPT-5预估10T+）
  \u2193
模型参数需要存储在GPU的HBM中（HBM是AI芯片的[高速缓存]）
  \u2193
H100：80GB HBM \u2192 B200：192GB HBM \u2192 Rubin：288GB HBM+
  \u2193
每代升级：容量翻倍 x 带宽翻倍 x 单价涨30-50%
  \u2193
DRAM厂从[按晶圆产能定价]转向[按HBM颗粒定价]（价值量暴增）
  \u2193
美光2024下半年打入NVIDIA HBM3e供应链（此前只有SK海力士和三星）
  \u2193
HBM4量产（2026H2）：密度翻倍 \u2192 美光份额从0\u219225-30%+
  \u2193
美光HBM营收：FY25 ~$100亿 \u2192 FY26预估$200亿+`), sp());

C.push(h3("数据支撑"), sp());
C.push(tbl(["环节","具体数据","数据来源"],
  [["HBM营收FY25","~$100亿（首次成为最大收入来源）","Micron财报"],
   ["HBM营收FY26","分析师预估$200亿+（翻倍）","多家券商"],
   ["HBM4进入NVIDIA链","2025年底确认，2026H2量产","Micron官方"],
   ["CapEx","$200亿投资HBM产能（爱达荷州新厂）","techovedas"],
   ["FY25总营收","$351亿（+196% YoY）","yfinance"],
   ["Fwd PE","8.6x - 按周期股估值（严重低估）","yfinance"],
   ["库存","周转天数降至历史低位（HBM供不应求）","财报"]], {a:1400,b:2300,c:2000}), sp());

C.push(h3("为什么存在定价错误"), sp());
C.push(p("市场用[存储周期股]框架给MU估值（Fwd PE 8.6x）："));
C.push(p("- 传统DRAM/NAND：3年一轮周期，涨\u2192扩产\u2192跌\u2192减产\u2192涨"));
C.push(p("- HBM完全不同：不是容量周期，是技术升级周期"));
C.push(p("- HBM3e\u2192HBM4\u2192HBM4e，每一代容量x2、带宽x2、单价x1.5-2x"));
C.push(p("- 这不是周期，是AI拉动的结构性增长"), sp());
C.push(p("类比：市场给周期股8x PE，但HBM业务应接成长股25-30x PE估值。拆分估值：HBM按$100亿营收x30%净利率x25x=$750亿，存储按$250亿x10%x8x=$200亿，合计$950亿。当前市值$1000亿 \u2192 HBM几乎没有溢价。"), sp());

C.push(h3("HBM市场量化"), sp());
C.push(cd(`1颗B200 GPU = 8颗HBM3e（每颗24GB，单价约$30-50）
100万颗B200 \u2192 800万颗HBM3e \u2192 仅NVIDIA一家年需求~$300亿+
到2027年HBM总市场 = $600-1000亿
美光占25%份额 = $150-250亿营收
净利率30% = $45-75亿净利 \u2192 20x PE = $900-1500亿`), sp());

// ===== CEG =====
C.push(pb(), h2("标的3：星座能源 CEG"), h3("第一性原理变量 \u2192 需求保证的链式推导"), sp());
C.push(cd(`变量：单座AI数据中心用电量 = 30万-100万家庭用电量
  \u2193
1座500MW数据中心年用电量=4.4TWh \u2192 2030年美国AI数据中心新增需求=200-300TWh
  \u2193
美国电网已满负荷，新建输电线路需5-10年
天然气不满足科技公司碳中和承诺
  \u2193
核电成为唯一可行的大规模零碳基荷方案
  \u2193
微软2024签Three Mile Island重启（20年PPA）
Meta2025签CEG核电协议
谷歌2025签Kairos Power小型堆协议
  \u2193
CEG：美国最大核电运营商（14座反应堆，占全美核电15%+）
+收购Calpine补齐清洁能源版图
  \u2193
净利：2024\u21922025(+64%)\u21922026预计再+30%+`), sp());

C.push(h3("数据支撑"), sp());
C.push(tbl(["环节","具体数据","数据来源"],
  [["净利增速2025","+64%","Reuters"],
   ["与Meta核电协议","2025年10月签定，为Meta AI数据中心专供核能","Guzman分析"],
   ["收购Calpine","$164亿收购天然气发电商（2026完成）","Stock Titan"],
   ["核电装机量","14座反应堆，总装机~18GW","公司官网"],
   ["数据中心电力采购","2025年同比增长300%+","Forbes"],
   ["PE","21.9x / Fwd PE 18.5x","yfinance"],
   ["可再生能源占比","90%+（碳中和目标下的AI首选能源供应商）","公司报告"]], {a:1400,b:2300,c:2000}), sp());

C.push(h3("为什么存在定价错误"), sp());
C.push(p("市场按传统公用事业给CEG估值(20x PE)："));
C.push(p("- 传统公用事业增长=0-3%/年（自然增长天花板）"));
C.push(p("- CEG在AI协议推动下，增长已升至15-20%/年"));
C.push(p("- 假设增长20%/年 \u2192 PEG=1（合理），但市场还没把AI核电价值计入"));
C.push(p("- 微软\u2192Meta\u2192谷歌\u2192其他科技巨头必跟。AI核电是刚起步的超级趋势。"));

// ===== VST =====
C.push(pb(), h2("标的4：维斯特拉 VST"), h3("第一性原理变量 \u2192 需求保证的链式推导"), sp());
C.push(cd(`变量：AI数据中心需要24x7不间断供电 \u2192 电网批发价波动大
  \u2193
AI数据中心需要稳定可预测的电价（3-5年PPA锁定）
  \u2193
拥有零售售电牌照的电力商可以直接和AI数据中心签PPA
  \u2193
VST拥有德克萨斯州最大零售售电牌照
把天然气/核电/储能打包卖给AI数据中心
  \u2193
VST签的AI PPA价格 = 电网批发价 + 零售溢价（约20-30%溢价）
  \u2193
VST营收增速+43%，PE 24.5x / Fwd PE 13.3x`), sp());
C.push(p("VST不同于一般发电商（NRG、AES）：它有零售售电牌照和零售客户群，可直接与AI数据中心签购电合同赚取零售溢价。这个中间商模式让它在AI电力需求中有独特的议价能力。"));

// ===== HUBB =====
C.push(pb(), h2("标的5：哈贝尔 HUBB"), h3("第一性原理变量 \u2192 需求保证的链式推导"), sp());
C.push(cd(`变量：每座AI数据中心需要用500-2000台变压器（配电+干式）
  \u2193
AI数据中心建设量：2024全球~300座 \u2192 2027预计1000座+
  \u2193
全球变压器公司产能已满，交货周期从6个月\u219224个月
  \u2193
新建变压器工厂需3-5年，短期内产能无法扩张
  \u2193
供需缺口 \u2192 连续6个季度涨价，累计+30-50%
  \u2193
HUBB在北美配电变压器市场份额第一
拥有完整干式/油浸式变压器产品线
  \u2193
订单积压创历史新高但受限于产能增速仅+11%
  \u2193
2027年后新产能释放 \u2192 营收增速可能跳升到20%+`));

// ===== A股 =====
C.push(pb(), h1("三、A股完整逻辑推演"), sp());

C.push(h2("1. 中石科技 300684（PE 45.9x - 接近30x门槛）"));
C.push(h3("链式推导"), sp());
C.push(cd(`变量：GPU功耗从300W\u21921500W+ \u2192 服务器内部温度从60\u00b0C\u2192100\u00b0C+
  \u2193
传统散热方案（风扇+铝散热片）无法满足
  \u2193
导热硅脂/导热垫片/液冷板等高端热管理材料用量暴增
  \u2193
中石科技：A股少数能做高导热TIM材料的公司
产品包括导热硅脂(导热系数>10W/mK)、导热垫片、液冷板
  \u2193
2025净利Y3.39亿，同比+68%
PE 45.9x - 如果2026净利再+50%可达Y5亿 \u2192 PE降至30x`), sp());

C.push(h2("2. 源杰科技 688498（PE 518x - 拐点型）"));
C.push(h3("链式推导"), sp());
C.push(cd(`变量：AI数据中心内部互联从800G\u21921.6T\u21923.2T光模块
  \u2193
光模块速率每代翻倍 \u2192 内部光芯片速率也必须翻倍
100G EML \u2192 200G EML \u2192 400G EML
  \u2193
过去A股光芯片依赖进口（美国Lumentum、住友电工）
  \u2193
贸易限制+国产替代 \u2192 国内光模块厂必须找国产光芯片
  \u2193
源杰科技是A股唯一能做高速EML光芯片的公司
200G PAM4 EML芯片正在客户验证中
  \u2193
营收Y5.64亿(+138.5%)、毛利率52.9%、扭亏为盈
  \u2193
PS = 180亿/5.6亿 = 32x（对130%增速的公司不算极高）
如果200G芯片2026年量产 \u2192 营收翻倍 \u2192 PS降至15x`), sp());

C.push(h2("3. 润泽科技 300442（PE 24.7x - 增速爆炸但市值已大）"), sp());
C.push(cd(`变量：AI算力需求 \u2192 智算中心(AIDC)需求暴增
  \u2193
传统IDC不能满足GPU集群高功耗/高密度要求
AIDC需要更高电力密度(30-50kW/机柜 vs 传统5-10kW)
  \u2193
润泽科技是国内最大第三方AIDC运营商之一
2025年投产机柜数倍增，AIDC占比快速提升
  \u2193
营收Y56.74亿、净利Y50.5亿(+182%)、PE 24.7x
  \u2193
但市值Y1257亿 - 已不算小众，竞争加剧`), sp());

C.push(h2("4. 时代电气 688187（PE 18.2x - 估值低但AI关联极弱）"), sp());
C.push(cd(`变量：AI数据中心需要大量UPS \u2192 IGBT/SiC功率器件需求增加
  \u2193
时代电气做IGBT/SiC功率半导体
  \u2193
但主业是轨交（高铁/地铁IGBT占营收>60%）
AI电力相关的功率器件营收占比<5%
  \u2193
PE 18.2x/Fwd 13.6x 看似低估
实际是市场对轨交主业的合理定价（增速低）
AI电力故事很小，撑不起估值重估`), sp());

C.push(h2("5. 中科蓝讯 688332（PE 12.0x - A股最低但AI最弱）"), sp());
C.push(cd(`公司做蓝牙音频芯片（RISC-V架构），营收~Y18亿(+11%)
AI端侧推理概念很弱，AI关联几乎没有
PE 12.0x是A股科技股最低之一
但无法作为AI供应链标的`), sp());

// ===== A股 vs 美股 =====
C.push(pb(), h1("四、A股 vs 美股 - 差异的本质原因"), sp());
C.push(tbl(["维度","A股","美股"],
  [["科技股PE基线","50-150x（常态）","15-35x（常态）"],
   ["AI受益度","多数不盈利/微利","真实营收+++利润+++"],
   ["低估原因","无（市场已充分定价）","做空/争议/周期标签"],
   ["可操作性","低（估值无安全边际）","高（PE+Fwd PE双低）"]],
  {a:2600,b:3380,c:3380}), sp());

// ===== 终极排名 =====
C.push(pb(), h1("五、终极排名与转化路径"), sp());
C.push(tbl(["标的","赛道","PE","Fwd PE","营收增速","未来半年关键验证","标的质变路径"],
  [["SMCI","AI服务器","21x","12.5x","+52%\u2192$360亿","FY26全年指引是否上调","做空恐慌退潮\u2192机构回补\u2192PEG从0.4\u21921.0\u2192翻倍"],
   ["MU","HBM存储","44x","8.6x","+196%","HBM4量产进度+CapEx细节","HBM从$100亿\u2192$200亿+ \u2192成长占比>50%"],
   ["CEG","AI核电","22x","18.5x","+64%","更多科技巨头签核电PPA","购电协议持续落地\u2192增长中枢3%\u219220%"],
   ["VST","AI电力","24x","13.3x","+43%","数据中心PPA签约数量","零售电价弹性体现\u2192Fwd PE从13x向20x修复"],
   ["HUBB","变压器","29x","22.3x","+11%","新工厂投产时间表","产能瓶颈解除\u2192营收增速跳到20%+"]],
  {a:900,b:1200,c:800,d:900,e:1000,f:2200,g:2360}), sp());

C.push(h2("A股映射 - 需等待"), sp());
C.push(tbl(["美股标的","A股最接近对标","A股当前状态","需要什么条件才能入场"],
  [["SMCI AI服务器","工业富联/浪潮信息","PE 34x/市值大","-"],
   ["MU HBM","兆易创新(PE 112x)","估值太高","HBM国产化突破+盈利改善"],
   ["CEG/VST AI电力","润泽科技(PE 24.7x)","PE合理但市值Y1257亿","回调到更小市值"],
   ["HUBB 变压器映射","中石科技300684","PE 45.9x","2026利润Y5亿\u2192PE降至30x"]],
  {a:1800,b:2400,c:2400,d:2760}), sp());

// ===== 总结 =====
C.push(pb(), h1("六、一句话总结"), sp());
C.push(new Paragraph({
  spacing:{before:120,after:120},indent:{left:360,right:360},
  shading:{fill:"FFF3E0",type:ShadingType.CLEAR},
  children:[new TextRun({text:"A股的AI冷门之所以冷门是因为它们不赚钱、没受益；美股的SMCI(PE 21x/Fwd 12.5x)是被定价错误最严重的标的，Hindenburg做空+审计恐慌+市场对AI服务器赛道的认知偏差，三项叠加创造了买入窗口。",size:22,font:F,italics:true,color:"333333"})]}));
C.push(sp(), p("不构成投资建议。数据来源：CDP浏览器搜索+yfinance验证。"));

// Build document
const doc = new Document({
  styles: {
    default: {document:{run:{font:"Arial",size:22}}},
    paragraphStyles: [
      {id:"Heading1",name:"Heading 1",basedOn:"Normal",next:"Normal",quickFormat:true,
        run:{size:30,bold:true,color:"1F3864",font:F},
        paragraph:{spacing:{before:360,after:200},outlineLevel:0}},
      {id:"Heading2",name:"Heading 2",basedOn:"Normal",next:"Normal",quickFormat:true,
        run:{size:26,bold:true,color:"2E5090",font:F},
        paragraph:{spacing:{before:240,after:160},outlineLevel:1}},
      {id:"Heading3",name:"Heading 3",basedOn:"Normal",next:"Normal",quickFormat:true,
        run:{size:24,bold:true,color:"3D6AB4",font:F},
        paragraph:{spacing:{before:200,after:120},outlineLevel:2}},
    ]
  },
  sections:[{
    properties:{page:{margin:{top:1440,right:1260,bottom:1440,left:1260}}},
    headers:{default:new Header({children:[new Paragraph({alignment:AlignmentType.RIGHT,
      children:[new TextRun({text:"AI产业链小众标的研究报告",size:16,color:"999999",font:F})]})]})},
    footers:{default:new Footer({children:[new Paragraph({alignment:AlignmentType.CENTER,
      children:[new TextRun({text:"Page ",size:16,color:"999999",font:F}),
               new TextRun({children:[PageNumber.CURRENT],size:16,color:"999999",font:F})]})]})},
    children:C
  }]
});

Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync("D:/files/demo/0312-newagent/agent-alpha/workspace/AI产业研究笔记/AI产业链小众标的研究报告.docx", buf);
  console.log("OK: " + buf.length + " bytes");
});
'''

# Write the JS file
with open('workspace/AI产业研究笔记/generate_docx.js', 'w', encoding='utf-8') as f:
    # Strip the leading newline and write
    f.write(js.strip())
