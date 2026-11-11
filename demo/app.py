import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import yfinance as yf
from fredapi import Fred
from google import genai
from google.genai import types
import time

# -------------------------------------------------------------
# 頁面基本配置
# -------------------------------------------------------------
st.set_page_config(page_title="全球總體經濟與金融指標即時儀表板", layout="wide")
st.title("🌐 全球總體經濟與金融指標即時儀表板")

# -------------------------------------------------------------
# 側邊欄：API 金鑰與控制
# -------------------------------------------------------------
st.sidebar.header("⚙️ 設定與金鑰")

if "FRED_API_KEY" in st.secrets:
    fred_key = st.secrets["FRED_API_KEY"]
    st.sidebar.success("已自動讀取 FRED API Key")
else:
    fred_key = st.sidebar.text_input("請輸入 FRED API Key:", type="password")

if "GEMINI_API_KEY" in st.secrets:
    gemini_key = st.secrets["GEMINI_API_KEY"]
    st.sidebar.success("已自動讀取 Gemini API Key")
else:
    gemini_key = st.sidebar.text_input("請輸入 Gemini API Key:", type="password")

if st.sidebar.button("手動刷新所有數據"):
    st.cache_data.clear()

# -------------------------------------------------------------
# 資料抓取函數 (快取優化)
# -------------------------------------------------------------
@st.cache_data(ttl=3600)
def get_fred_data(api_key):
    fred = Fred(api_key=api_key)
    data = {
        "CPI 物價指數": fred.get_series("CPIAUCSL"),
        "3個月期美債殖利率": fred.get_series("DGS3MO"),
        "2年期美債殖利率": fred.get_series("DGS2"),
        "5年期美債殖利率": fred.get_series("DGS5"),
        "10年期美債殖利率": fred.get_series("DGS10"),
        "30年期美債殖利率": fred.get_series("DGS30"),
        "日本10年期國債殖利率": fred.get_series("IRLTLT01JPM156N"),
        "美國失業率": fred.get_series("UNRATE"),
        "聯邦基金利率": fred.get_series("FEDFUNDS")
    }
    df = pd.DataFrame(data).ffill().tail(365)
    # 計算 10Y - 2Y 美債利差
    df["10Y-2Y 美債利差"] = df["10年期美債殖利率"] - df["2年期美債殖利率"]
    # 計算 美日 10Y 國債利差
    df["美日10Y利差"] = df["10年期美債殖利率"] - df["日本10年期國債殖利率"]
    return df

@st.cache_data(ttl=600)
def get_market_data():
    tickers = {
        "S&P 500": "^GSPC",
        "台灣加權指數": "^TWII",
        "黃金現貨 (GC=F)": "GC=F",
        "布蘭特原油": "BZ=F",
        "美元/台幣匯率": "TWD=X"
    }
    raw_df = yf.download(list(tickers.values()), period="1y")["Close"]
    
    if isinstance(raw_df.columns, pd.MultiIndex):
        raw_df.columns = raw_df.columns.get_level_values(-1)
        
    df = raw_df.rename(columns={v: k for k, v in tickers.items()})
    return df

# -------------------------------------------------------------
# 主畫面邏輯
# -------------------------------------------------------------
if fred_key:
    try:
        macro_df = get_fred_data(fred_key)
        market_df = get_market_data()

        # 關鍵數值擷取
        latest_cpi = macro_df["CPI 物價指數"].dropna().iloc[-1]
        cpi_prev = macro_df["CPI 物價指數"].dropna().iloc[-2]

        latest_10y = macro_df["10年期美債殖利率"].dropna().iloc[-1]
        prev_10y = macro_df["10年期美債殖利率"].dropna().iloc[-2]

        latest_2y = macro_df["2年期美債殖利率"].dropna().iloc[-1]
        prev_2y = macro_df["2年期美債殖利率"].dropna().iloc[-2]

        spread_series = macro_df["10Y-2Y 美債利差"].dropna()
        latest_spread = spread_series.iloc[-1]
        spread_prev = spread_series.iloc[-2] if len(spread_series) > 1 else latest_spread

        jp_series = macro_df["日本10年期國債殖利率"].dropna()
        latest_jp = jp_series.iloc[-1]
        jp_prev = jp_series.iloc[-2] if len(jp_series) > 1 else latest_jp

        latest_unemp = macro_df["美國失業率"].dropna().iloc[-1]
        latest_fed = macro_df["聯邦基金利率"].dropna().iloc[-1]

        # 殖利率曲線狀態警示條
        if latest_spread < 0:
            st.error(f"🚨 **殖利率曲線倒掛警示 (Yield Curve Inverted)**：當前 10Y-2Y 利差為 **{latest_spread:+.2f}%**（低於 0），請留意經濟衰退訊號。")
        else:
            st.info(f"💡 **殖利率曲線維持正斜率**：當前 10Y-2Y 利差為 **{latest_spread:+.2f}%**。")

        # 核心 KPI 卡片
        st.subheader("📊 關鍵總體經濟與公債指標 (FRED)")
        col1, col2, col3, col4, col5, col6 = st.columns(6)
        col1.metric("10年期美債", f"{latest_10y:.2f}%", f"{latest_10y - prev_10y:+.2f}%")
        col2.metric("2年期美債", f"{latest_2y:.2f}%", f"{latest_2y - prev_2y:+.2f}%")
        col3.metric("10Y-2Y 利差", f"{latest_spread:.2f}%", f"{latest_spread - spread_prev:+.2f}%")
        col4.metric("日本10Y國債", f"{latest_jp:.3f}%", f"{latest_jp - jp_prev:+.3f}%")
        col5.metric("CPI 物價指數", f"{latest_cpi:.1f}")
        col6.metric("美國失業率", f"{latest_unemp:.1f}%")

        # -------------------------------------------------------------
        # 深度圖表分析專區 (內容擴充)
        # -------------------------------------------------------------
        st.write("---")
        st.subheader("📈 深度市場走勢與結構圖表分析")

        tab1, tab2, tab3, tab4 = st.tabs([
            "📊 美國國債殖利率曲線結構", 
            "🌐 美日10Y利差與套利走勢", 
            "📈 金融資產多標的報酬率比較", 
            "📉 單一指標趨勢分析"
        ])

        # TAB 1: 殖利率曲線天期結構圖 (Yield Curve Shape)
        with tab1:
            st.markdown("#### 美國國債殖利率天期曲線 (當前 vs 一個月前)")
            maturities = ["3個月", "2年", "5年", "10年", "30年"]
            curve_cols = ["3個月期美債殖利率", "2年期美債殖利率", "5年期美債殖利率", "10年期美債殖利率", "30年期美債殖利率"]
            
            current_curve = [macro_df[c].dropna().iloc[-1] for c in curve_cols]
            prev_curve = [macro_df[c].dropna().iloc[-22] for c in curve_cols] if len(macro_df) >= 22 else current_curve
            
            fig_curve = go.Figure()
            fig_curve.add_trace(go.Scatter(x=maturities, y=current_curve, mode='lines+markers', name='當前曲線', line=dict(color='#00CC96', width=3)))
            fig_curve.add_trace(go.Scatter(x=maturities, y=prev_curve, mode='lines+markers', name='一個月前', line=dict(color='#AB63FA', width=2, dash='dash')))
            fig_curve.update_layout(xaxis_title="公債天期", yaxis_title="殖利率 (%)", hovermode="x unified")
            st.plotly_chart(fig_curve, use_container_width=True)

        # TAB 2: 美日利差走勢 (Carry Trade 監測)
        with tab2:
            st.markdown("#### 美國 vs 日本 10 年期公債殖利率及美日利差")
            fig_spread = go.Figure()
            fig_spread.add_trace(go.Scatter(x=macro_df.index, y=macro_df["10年期美債殖利率"], mode='lines', name='10年期美債 (%)', line=dict(color='#1f77b4')))
            fig_spread.add_trace(go.Scatter(x=macro_df.index, y=macro_df["日本10年期國債殖利率"], mode='lines', name='日本10年期國債 (%)', line=dict(color='#ff7f0e')))
            fig_spread.add_trace(go.Scatter(x=macro_df.index, y=macro_df["美日10Y利差"], mode='lines', name='美日利差 (%)', line=dict(color='#2ca02c', dash='dot')))
            fig_spread.update_layout(xaxis_title="日期", yaxis_title="殖利率 / 利差 (%)", hovermode="x unified")
            st.plotly_chart(fig_spread, use_container_width=True)

        # TAB 3: 資產標準化累積報酬率走勢比較 (Normalized Cumulative Return)
        with tab3:
            st.markdown("#### 跨市場資產相對漲跌幅比較（基準日設為 100）")
            selected_assets = st.multiselect(
                "選擇要比較的市場資產：", 
                options=market_df.columns.tolist(), 
                default=["S&P 500", "台灣加權指數", "黃金現貨 (GC=F)"]
            )
            if selected_assets:
                norm_df = market_df[selected_assets].dropna()
                norm_df = (norm_df / norm_df.iloc[0]) * 100
                fig_norm = px.line(norm_df, title="資產相對走勢對比 (基期=100)")
                fig_norm.update_layout(xaxis_title="日期", yaxis_title="標準化點數", hovermode="x unified")
                st.plotly_chart(fig_norm, use_container_width=True)
            else:
                st.warning("請至少勾選一個資產進行比較。")

        # TAB 4: 單一指標自由選
        with tab4:
            all_cols = list(market_df.columns) + list(macro_df.columns)
            choice = st.selectbox("選擇任一指標檢視近一年走勢：", all_cols)
            if choice in market_df.columns:
                target_series = market_df[choice]
            else:
                target_series = macro_df[choice]
            fig_single = px.line(target_series, title=f"{choice} 近一年歷史走勢")
            fig_single.update_layout(xaxis_title="日期", yaxis_title="數值", hovermode="x unified")
            st.plotly_chart(fig_single, use_container_width=True)

        # -------------------------------------------------------------
        # AI 總經短評 (精簡版：約 200 字直接給要點)
        # -------------------------------------------------------------
        st.write("---")
        st.subheader("🤖 AI 總體經濟即時觀點")
        st.caption("點擊按鈕調用 Gemini 依據當前最新總經與公債數據生成約 200 字精簡市場短評。")

        if st.button("產生 AI 總體經濟摘要", type="primary"):
            active_key = gemini_key.strip().replace('"', '').replace("'", "") if gemini_key else ""
            
            if not active_key:
                st.warning("⚠️ 請先在側邊欄輸入 Gemini API Key，或於 secrets.toml 中配置 GEMINI_API_KEY。")
            else:
                with st.spinner("AI 正在分析總經指標並撰寫短評..."):
                    try:
                        client = genai.Client(api_key=active_key)

                        prompt = f"""
你是一位資深總體經濟策略師。請依據以下指標數據，以繁體中文撰寫一份約 200 字以內的精準市場短評，直接列出 3 點結論（不要寒暄客套）：

【最新數據】
- 美國 CPI 物價指數：{latest_cpi:.1f}
- 美國失業率：{latest_unemp:.1f}%、聯邦基金利率：{latest_fed:.2f}%
- 10 年期美債：{latest_10y:.2f}%、2 年期美債：{latest_2y:.2f}%
- 10Y-2Y 利差：{latest_spread:+.2f}%（{'倒掛' if latest_spread < 0 else '正常正斜率'}）
- 日本 10 年期國債殖利率：{latest_jp:.3f}%

【短評要求】
1. 通膨與勞動市場景氣現況
2. 利率路徑與美日利差影響
3. 殖利率曲線對資產配置的一句話建議
"""

                        models_to_try = ["gemini-3.8-flash", "gemini-2.5-flash", "gemini-2.0-flash"]
                        full_report = None
                        last_error = None

                        for target_model in models_to_try:
                            for attempt in range(2):
                                try:
                                    response = client.models.generate_content(
                                        model=target_model,
                                        contents=prompt,
                                        config=types.GenerateContentConfig(
                                            temperature=0.2,
                                            max_output_tokens=600,
                                        )
                                    )
                                    if response and response.text:
                                        full_report = response.text
                                        break
                                except Exception as err:
                                    last_error = err
                                    time.sleep(1.2)
                                    continue
                            if full_report:
                                break

                        if full_report:
                            st.success("✅ AI 總經短評生成完畢：")
                            st.markdown(full_report)
                        else:
                            st.error(f"⚠️ 伺服器尖峰繁忙，生成失敗：{last_error}")

                    except Exception as ai_err:
                        st.error(f"調用 Gemini 生成失敗，錯誤訊息：{ai_err}")

    except Exception as e:
        st.error(f"數據讀取失敗，請確認 FRED API Key 是否正確。錯誤訊息: {e}")
else:
    st.info("👈 請在左側輸入您的 FRED API Key 以開啟儀表板。")
