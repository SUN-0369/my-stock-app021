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

# 视觉效果极佳的暗黑/科技感优化（专为手机全屏适配）
st.markdown("""
    <style>
    .stApp { background-color: #0e1117; color: #ffffff; }
    .stButton>button { 
        padding: 5px 8px; font-size: 12px; border-radius: 4px; 
        margin-bottom: 2px; text-align: left; width: 100%;
        background-color: #1a1c23; color: #ffffff; border: 1px solid #2d3139;
    }
    .stButton>button:hover { border-color: #ff4b4b; background-color: #262930; }
    h4 { font-size: 1.1rem !important; font-weight: 600; margin-top: 12px; margin-bottom: 8px; color: #e0e0e0; }
    div[data-testid="stMetricValue"] { font-size: 1.6rem !important; }
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .block-container {
        padding-top: 0.8rem !important;
        padding-bottom: 0.8rem !important;
        padding-left: 0.4rem !important;
        padding-right: 0.4rem !important;
    }
    </style>
""", unsafe_allow_html=True)

# --- 2. 工具函数：判断交易时间 ---
def is_trading_time():
    now = datetime.now()
    if now.weekday() >= 5:  # 周六日
        return False
    tm = now.strftime("%H:%M")
    if ("09:15" <= tm <= "11:35") or ("12:55" <= tm <= "15:05"):
        return True
    return False

# --- 3. 核心 API 抓取引擎（极速精简版，单次仅请求前20条最核心数据） ---
@st.cache_data(ttl=60)
def get_secid(sector_name):
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

@st.cache_data(ttl=45)
def fetch_history_flow(sector_name):
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

@st.cache_data(ttl=30)
def fetch_current_list(is_concept=False, is_outflow=False):
    fs_code = "m:90+t:3" if is_concept else "m:90+t:2"
    po_code = "0" if is_outflow else "1"
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    # 【性能核心优化】：将页面数据大小 pz 从 100 缩减至 20，大幅减少网络传输延迟
    params = {
        "pn": "1", "pz": "20", "po": po_code, "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2", "invt": "2", "fid": "f62", "fs": fs_code,
        "fields": "f12,f14,f62"
    }
    try:
        r = requests.get(url, params=params, impersonate="chrome", timeout=4)
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

ind_in = fetch_current_list(False, False)
ind_out = fetch_current_list(False, True)
con_in = fetch_current_list(True, False)
con_out = fetch_current_list(True, True)

all_current = pd.concat([ind_in, ind_out, con_in, con_out], ignore_index=True)
all_names = sorted(all_current['Sector'].unique().tolist()) if not all_current.empty else []

# --- 5. 顶栏指标看板 ---
st.title("🚀 A股主力资金流向")
colA, colB, colC = st.columns([2, 2, 3])
with colA: 
    in_count = len(ind_in[ind_in['Amount'] > 0]) if not ind_in.empty else 0
    st.metric("主力流入行业数", f"{in_count} 个")
with colB: 
    total_flow = ind_in['Amount'].sum() - ind_out['Amount'].abs().sum() if not ind_in.empty else 0.0
    st.metric("行业预计总合力", f"{total_flow:+.2f} 亿", delta_color="inverse")
with colC: 
    st.info(f"💡 自动刷新中 | 当前时间: {datetime.now().strftime('%H:%M:%S')}")

# --- 6. 生成标准 A 股交易时间轴 ---
def generate_stock_timeline():
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

has_data = False
for idx, s in enumerate(st.session_state.selected_sectors):
    s_data = fetch_history_flow(s)
    if not s_data.empty:
        has_data = True
        base_df = pd.DataFrame({"Time": timeline})
        s_data = pd.merge(base_df, s_data, on="Time", how="left")
        s_data['Amount'] = s_data['Amount'].ffill().fillna(0.0)
        
        c = colors[idx % len(colors)]
        last_val = s_data['Amount'].iloc[-1]
        
        text_labels = [None] * (len(s_data) - 1) + [f"<b>{s} {last_val:+.2f}亿</b>"]
        
        fig.add_trace(go.Scatter(
            x=s_data['Time'], y=s_data['Amount'],
            mode='lines+text', name=s,
            line=dict(width=2.5, color=c),
            text=text_labels, textfont=dict(color=c, size=12),
            textposition="middle right", cliponaxis=False
        ))

fig.update_layout(
    height=420, margin=dict(r=120, b=30, l=30, t=10), showlegend=False,
    plot_bgcolor='#131722', paper_bgcolor='#0e1117',
    xaxis=dict(
        type='category',
        tickmode='array',
        tickvals=['09:30', '10:30', '11:30', '13:30', '14:30', '15:00'],
        showgrid=True, gridcolor='#222632', tickangle=0, tickfont=dict(color='#8f929d', size=10)
    ),
    yaxis=dict(
        zeroline=True, zerolinecolor='#4f525e', zerolinewidth=1,
        gridcolor='#222632', ticksuffix=" 亿", tickfont=dict(color='#8f929d', size=10)
    ),
    hovermode="x unified"
)

if has_data:
    st.plotly_chart(fig, use_container_width=True)
else:
    st.warning("暂无历史趋势数据，请检查网络或确认当前是否为开盘日。")

# --- 8. 四大交互看板 ---
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
                color_symbol = "🔴" if row['Amount'] >= 0 else "🟢"
                btn_label = f"{color_symbol} {row['Sector']} {row['Amount']:+.2f}亿"
                
                if st.button(btn_label, key=f"bd_{title}_{row['Sector']}"):
                    if row['Sector'] not in st.session_state.selected_sectors:
                        if len(st.session_state.selected_sectors) >= 8:
                            st.toast("⚠️ 最多同时监控 8 个板块", icon="⏳")
                        else:
                            st.session_state.selected_sectors.append(row['Sector'])
                            with open(SELECTED_JSON, 'w', encoding='utf-8') as f:
                                json.dump(st.session_state.selected_sectors, f, ensure_ascii=False)
                            st.rerun()
        else:
            st.caption("暂无数据")

# --- 9. 侧边栏交互与控制 ---
st.sidebar.header("🔍 监控配置")

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
st.sidebar.subheader(f"📍 已监控 ({len(st.session_state.selected_sectors)}/8)")

for s in list(st.session_state.selected_sectors):
    if st.sidebar.button(f"🗑️ {s}", key=f"del_{s}"):
        st.session_state.selected_sectors.remove(s)
        with open(SELECTED_JSON, 'w', encoding='utf-8') as f:
            json.dump(st.session_state.selected_sectors, f, ensure_ascii=False)
        st.rerun()

# --- 10. 智能心跳刷新机制 ---
if is_trading_time():
    time.sleep(30)
    st.rerun()
else:
    time.sleep(300)
    st.rerun()
