import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from curl_cffi import requests
from datetime import datetime
import time
import os
import json

# --- 1. 基础配置 ---
current_dir = os.path.dirname(os.path.abspath(__file__))
SELECTED_JSON = os.path.join(current_dir, "selected_sectors.json")

st.set_page_config(page_title="A股主力资金流向监控", layout="wide")

# 优雅的暗黑/科技感视觉
st.markdown("""
    <style>
    .stApp { background-color: #0e1117; color: #ffffff; }
    .stButton>button { 
        padding: 6px 10px; font-size: 13px; border-radius: 4px; 
        margin-bottom: 2px; text-align: left; width: 100%;
        background-color: #1a1c23; color: #ffffff; border: 1px solid #2d3139;
    }
    .stButton>button:hover { border-color: #ff4b4b; background-color: #262930; }
    h4 { font-size: 1.2rem !important; font-weight: 600; margin-top: 15px; margin-bottom: 10px; color: #e0e0e0; }
    div[data-testid="stMetricValue"] { font-size: 1.8rem !important; }
    </style>
""", unsafe_allow_html=True)

# --- 2. 工具函数：判断交易时间 ---
def is_trading_time():
    """判断当前是否为A股交易时间段（周一至周五 09:15-11:35, 12:55-15:05）"""
    now = datetime.now()
    if now.weekday() >= 5:  # 周六日
        return False
    tm = now.strftime("%H:%M")
    if ("09:15" <= tm <= "11:35") or ("12:55" <= tm <= "15:05"):
        return True
    return False

# --- 3. 核心 API 抓取引擎（带 st.cache_data 缓存优化避免封号） ---
@st.cache_data(ttl=60) # 核心：限制每分钟内相同的请求只请求一次
def get_secid(sector_name):
    """根据板块名称模糊匹配 secid"""
    search_url = "https://searchapi.eastmoney.com/api/suggest/get"
    params = {"input": sector_name, "type": "14", "count": "1"}
    try:
        r = requests.get(search_url, params=params, impersonate="chrome", timeout=5)
        data = r.json().get('QuotationCodeTable', {}).get('Data', [])
        if data:
            return f"{data[0]['QuoteID']}"
    except:
        return None
    return None

@st.cache_data(ttl=50) # 实盘分钟线数据缓存 50 秒
def fetch_history_flow(sector_name):
    """抓取该板块今日 09:30 至今的所有分钟数据"""
    secid = get_secid(sector_name)
    if not secid: return pd.DataFrame()
    url = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
    params = {
        "lmt": "0", "klt": "1",
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52",
        "secid": secid,
        "ut": "b28a551da2492160d297a76059d04221"
    }
    try:
        r = requests.get(url, params=params, impersonate="chrome", timeout=5)
        klines = r.json().get('data', {}).get('klines', [])
        data_list = []
        for kl in klines:
            t, val = kl.split(',')
            data_list.append({
                "Time": t.split(' ')[1][:5], 
                "Sector": sector_name,
                "Amount": round(float(val) / 100000000, 2)
            })
        return pd.DataFrame(data_list)
    except:
        return pd.DataFrame()

@st.cache_data(ttl=30) # 大列表数据缓存 30 秒
def fetch_current_list(is_concept=False, is_outflow=False):
    fs_code = "m:90+t:3" if is_concept else "m:90+t:2"
    po_code = "0" if is_outflow else "1"
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": "1", "pz": "100", "po": po_code, "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2", "invt": "2", "fid": "f62", "fs": fs_code,
        "fields": "f12,f14,f62"
    }
    try:
        r = requests.get(url, params=params, impersonate="chrome", timeout=5)
        data = r.json().get('data', {}).get('diff', [])
        if not data: return pd.DataFrame(columns=['Sector', 'Amount'])
        df = pd.DataFrame(data)
        df['Amount'] = pd.to_numeric(df.get('f62'), errors='coerce').fillna(0) / 100000000
        return df.rename(columns={'f14': 'Sector'})[['Sector', 'Amount']]
    except:
        return pd.DataFrame(columns=['Sector', 'Amount'])

# --- 4. 初始化和数据加载 ---
if 'selected_sectors' not in st.session_state:
    if os.path.exists(SELECTED_JSON):
        with open(SELECTED_JSON, 'r', encoding='utf-8') as f:
            st.session_state.selected_sectors = json.load(f)
    else:
        st.session_state.selected_sectors = ["电池", "国防军工", "半导体"]

# 实时大盘列表数据
ind_in = fetch_current_list(False, False)
ind_out = fetch_current_list(False, True)
con_in = fetch_current_list(True, False)
con_out = fetch_current_list(True, True)

# 合并生成下拉搜索列表
all_current = pd.concat([ind_in, ind_out, con_in, con_out], ignore_index=True)
all_names = sorted(all_current['Sector'].unique().tolist()) if not all_current.empty else []

# --- 5. 顶栏指标看板 ---
st.title("🚀 A股主力资金流向 - 全天分钟回溯")
colA, colB, colC = st.columns([2, 2, 3])
with colA: 
    # 计算当前红盘（净流入）的行业个数
    in_count = len(ind_in[ind_in['Amount'] > 0]) if not ind_in.empty else 0
    st.metric("主力流入行业数", f"{in_count} 个", help="当前主力资金净流入为正的行业板块数量")
with colB: 
    # 估算市场整体行业板块的净合力
    total_flow = ind_in['Amount'].sum() - ind_out['Amount'].abs().sum() if not ind_in.empty else 0.0
    st.metric("行业预计总合力", f"{total_flow:+.2f} 亿", delta_color="inverse")
with colC: 
    st.info(f"💡 自动刷新中 | 当前系统时间: {datetime.now().strftime('%H:%M:%S')}\n\n折线图末端直接标注了最新金额，可在左侧增减监控。")

# --- 6. 核心：生成标准 A 股交易时间轴 (解决 Plotly 绘图断层老老大难问题) ---
def generate_stock_timeline():
    """生成A股标准分钟级时间序列(共242个点)"""
    t_range = []
    for h in range(9, 16):
        for m in range(60):
            tm = f"{h:02d}:{m:02d}"
            if ("09:30" <= tm <= "11:30") or ("13:00" <= tm <= "15:00"):
                t_range.append(tm)
    return sorted(list(set(t_range)))

timeline = generate_stock_timeline()

# --- 7. 动态生成折线图 ---
fig = go.Figure()
colors = ["#FF4B4B", "#1F77B4", "#2CA02C", "#FF7F0E", "#9467BD", "#8C564B", "#E377C2", "#17BECF"]

# 循环请求已选板块并合并至标准时间轴
has_data = False
for idx, s in enumerate(st.session_state.selected_sectors):
    s_data = fetch_history_flow(s)
    if not s_data.empty:
        has_data = True
        # 核心修复：通过 merge 强行对齐标准 A 股 242 根分钟线，缺失值向前填充(ffill)，防止 Plotly 画线崩溃
        base_df = pd.DataFrame({"Time": timeline})
        s_data = pd.merge(base_df, s_data, on="Time", how="left")
        s_data['Amount'] = s_data['Amount'].ffill().fillna(0.0) # 补齐开盘前的空值
        
        c = colors[idx % len(colors)]
        last_val = s_data['Amount'].iloc[-1]
        
        # 仅在最后一个有效点上打上文字标签，避免密密麻麻
        text_labels = [None] * (len(s_data) - 1) + [f"<b>{s} {last_val:+.2f}亿</b>"]
        
        fig.add_trace(go.Scatter(
            x=s_data['Time'], y=s_data['Amount'],
            mode='lines+text', name=s,
            line=dict(width=2.5, color=c),
            text=text_labels, textfont=dict(color=c, size=13),
            textposition="middle right", cliponaxis=False
        ))

# 图表视觉调优
fig.update_layout(
    height=500, margin=dict(r=150, b=40, l=40, t=20), showlegend=False,
    plot_bgcolor='#131722', paper_bgcolor='#0e1117',
    xaxis=dict(
        type='category',
        tickmode='array',
        tickvals=['09:30', '10:00', '10:30', '11:00', '11:30', '13:00', '13:30', '14:00', '14:30', '15:00'],
        showgrid=True, gridcolor='#222632', tickangle=0, tickfont=dict(color='#8f929d')
    ),
    yaxis=dict(
        zeroline=True, zerolinecolor='#4f525e', zerolinewidth=1,
        gridcolor='#222632', ticksuffix=" 亿", tickfont=dict(color='#8f929d')
    ),
    hovermode="x unified"
)

if has_data:
    st.plotly_chart(fig, use_container_width=True)
else:
    st.warning("暂无历史趋势数据，请检查网络或确认当前是否为开盘日。")

# --- 8. 四大交互看板（精简为前 10 个，降低渲染负担） ---
st.markdown("---")
cols = st.columns(4)
titles = [("🔥 行业流入 Top10", ind_in, False), ("❄️ 行业流出 Top10", ind_out, True),
          ("🚀 概念流入 Top10", con_in, False), ("🧊 概念流出 Top10", con_out, True)]

for i, (title, df, is_out) in enumerate(titles):
    with cols[i]:
        st.markdown(f"#### {title}")
        if not df.empty:
            display_df = df.sort_values('Amount', ascending=is_out).head(10)
            for _, row in display_df.iterrows():
                # 优化展现：流入显示红色加号，流出显示绿色减号
                color_symbol = "🔴" if row['Amount'] >= 0 else "🟢"
                btn_label = f"{color_symbol} {row['Sector']} {row['Amount']:+.2f}亿"
                
                if st.button(btn_label, key=f"bd_{title}_{row['Sector']}"):
                    if row['Sector'] not in st.session_state.selected_sectors:
                        if len(st.session_state.selected_sectors) >= 8:
                            st.toast("⚠️ 最多同时监控 8 个板块，请先删除一些", icon="⏳")
                        else:
                            st.session_state.selected_sectors.append(row['Sector'])
                            with open(SELECTED_JSON, 'w', encoding='utf-8') as f:
                                json.dump(st.session_state.selected_sectors, f, ensure_ascii=False)
                            st.rerun()
        else:
            st.caption("暂无数据")

# --- 9. 侧边栏交互与控制 ---
st.sidebar.header("🔍 监控面板配置")

selected = st.sidebar.selectbox(
    "搜索并添加板块/概念", 
    ["输入或选择..."] + all_names, 
    key="s_box"
)

if selected != "输入或选择..." and selected not in st.session_state.selected_sectors:
    if len(st.session_state.selected_sectors) >= 8:
        st.sidebar.error("最多同时监控 8 个板块！")
    else:
        st.session_state.selected_sectors.append(selected)
        with open(SELECTED_JSON, 'w', encoding='utf-8') as f:   
            json.dump(st.session_state.selected_sectors, f, ensure_ascii=False)
        st.rerun()

st.sidebar.write("---")
st.sidebar.subheader(f"📍 已监控板块 ({len(st.session_state.selected_sectors)}/8)")

for s in list(st.session_state.selected_sectors):
    if st.sidebar.button(f"🗑️ {s}", key=f"del_{s}"):
        st.session_state.selected_sectors.remove(s)
        with open(SELECTED_JSON, 'w', encoding='utf-8') as f:
            json.dump(st.session_state.selected_sectors, f, ensure_ascii=False)
        st.rerun()

# --- 10. 智能心跳刷新机制 ---
if is_trading_time():
    time.sleep(30) # 交易时间内每 30 秒高频刷新
    st.rerun()
else:
    time.sleep(300) # 非交易时间（收盘/周末）每 5 分钟极低频挂机即可，防止无意义空刷
    st.rerun()
