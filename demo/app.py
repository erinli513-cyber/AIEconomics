import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import yfinance as yf
from fredapi import Fred
from google import genai
from google.genai import types

# -------------------------------------------------------------
# 頁面基本配置
# -------------------------------------------------------------
st.set_page_config(page_title="總體經濟與金融即時儀表板", layout="wide")
st.title("🌐 全球總體經濟與金融指標即時儀表板")

# -------------------------------------------------------------
# 側邊欄：API 金鑰與控制
# -------------------------------------------------------------
st.sidebar.header("⚙️ 設定與金鑰")

# 1. FRED 金鑰讀取
if "FRED_API_KEY" in st.secrets:
    fred_key = st.secrets["FRED_API_KEY"]
    st.sidebar.success("已自動讀取 FRED API Key")
else:
    fred_key = st.sidebar.text_input("請輸入 FRED API Key:", type="password")

# 2. Gemini 金鑰讀取
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
        "10年期美債殖利率": fred.get_series("DGS10"),
        "2年期美債殖利率": fred.get_series("DGS2"),
        "日本10年期國債殖利率": fred.get_series("IRLTLT01JPM156N"),
        "美國失業率": fred.get_series("UNRATE"),
        "聯邦基金利率": fred.get_series("FEDFUNDS")
    }
    df = pd.DataFrame(data).ffill().tail(365)
    # 計算 10Y - 2Y 美債利差
    df["10Y-2Y 美債利差"] = df["10年期美債殖利率"] - df["2年期美債殖利率"]
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
    
    # 處理 yfinance 多層索引
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

        # 擷取最新總經數值與前期值
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

        # 殖利率曲線倒掛警示
        if latest_spread < 0:
            st.error(
                f"🚨 **殖利率曲線倒掛警示 (Yield Curve Inverted)**：當前 10Y-2Y 利差為 **{latest_spread:+.2f}%**（低於 0），請留意經濟衰退訊號。"
            )
        else:
            st.info(
                f"💡 **殖利率曲線維持正斜率**：當前 10Y-2Y 利差為 **{latest_spread:+.2f}%**。"
            )

        # 核心 KPI 卡片 (6 欄整齊排列)
        st.subheader("📊 關鍵總體經濟與公債指標 (FRED)")
        col1, col2, col3, col4, col5, col6 = st.columns(6)
        col1.metric("10年期美債", f"{latest_10y:.2f}%", f"{latest_10y - prev_10y:+.2f}%")
        col2.metric("2年期美債", f"{latest_2y:.2f}%", f"{latest_2y - prev_2y:+.2f}%")
        col3.metric("10Y-2Y 利差", f"{latest_spread:.2f}%", f"{latest_spread - spread_prev:+.2f}%")
        col4.metric("日本10Y國債", f"{latest_jp:.3f}%", f"{latest_jp - jp_prev:+.3f}%")
        col5.metric("CPI 物價指數", f"{latest_cpi:.1f}")
        col6.metric("美國失業率", f"{latest_unemp:.1f}%")

        # 圖表區塊
        st.write("---")
        st.subheader("📈 市場走勢與總體指標折線圖")

        tab1, tab2 = st.tabs(["金融市場走勢 (yfinance)", "總體經濟趨勢 (FRED)"])

        with tab1:
            market_choice = st.selectbox("選擇金融市場標的：", market_df.columns, key="market_select")
            fig1 = px.line(market_df, y=market_choice, title=f"{market_choice} 近一年走勢")
            fig1.update_layout(hovermode="x unified", xaxis_title="日期", yaxis_title="價格 / 點數")
            st.plotly_chart(fig1, use_container_width=True)

        with tab2:
            macro_choice = st.selectbox("選擇總體經濟指標：", macro_df.columns, key="macro_select")
            fig2 = px.line(macro_df, y=macro_choice, title=f"{macro_choice} 近一年走勢")
            fig2.update_layout(hovermode="x unified", xaxis_title="日期", yaxis_title="數值 / %")
            st.plotly_chart(fig2, use_container_width=True)

        # -------------------------------------------------------------
        # AI 總體經濟即時短評 (原生支援 AQ. 格式金鑰)
        # -------------------------------------------------------------
        st.write("---")
        st.subheader("🤖 AI 總體經濟即時觀點")
        st.caption("點擊按鈕調用 Gemini 依據當前最新總經與公債數據生成 200 字精簡市場短評。")

        if st.button("產生 AI 總體經濟摘要", type="primary"):
            active_key = gemini_key.strip().replace('"', '').replace("'", "") if gemini_key else ""
            
            if not active_key:
                st.warning("⚠️ 請先在側邊欄輸入 Gemini API Key，或於 secrets.toml 中配置 GEMINI_API_KEY。")
            else:
                with st.spinner("AI 正在分析總經指標並撰寫短評..."):
                    try:
                        # 1. 建立 Client（完全相容 AQ. 開頭的新金鑰）
                        client = genai.Client(api_key=active_key)

                        # 2. 構建 Prompt
                        prompt = f"""
你是一位專業的全球宏觀經濟與資產配置分析師。請依據以下儀表板抓取到的最新總經數據，撰寫一份繁體中文的總體經濟短評（嚴格控制在 200 字左右）：

【當前最新總體經濟指標數據】
- 美國 CPI 物價指數：{latest_cpi:.1f}（前值 {cpi_prev:.1f}）
- 美國失業率：{latest_unemp:.1f}%
- 聯邦基金利率：{latest_fed:.2f}%
- 10 年期美債殖利率：{latest_10y:.2f}%
- 2 年期美債殖利率：{latest_2y:.2f}%
- 10Y-2Y 美債利差：{latest_spread:+.2f}%（{'倒掛狀態' if latest_spread < 0 else '正常正斜率'}）
- 日本 10 年期國債殖利率：{latest_jp:.3f}%

【短評要求】
1. 綜合通膨動能、就業市場彈性與聯準會貨幣政策路徑進行簡要評估。
2. 針對美債殖利率曲線態勢（利差狀態）對總體景氣或風險資產的意涵給出一句話總結。
3. 語氣客觀專業，條理分明，不要包含無效客套話，總字數約 200 字。
"""

                        # 3. 呼叫模型
                        response = client.models.generate_content(
                            model="gemini-2.5-flash",
                            contents=prompt,
                            config=types.GenerateContentConfig(
                                temperature=0.3,
                                max_output_tokens=400,
                            )
                        )

                        # 4. 渲染結果
                        st.success("✅ AI 總經短評生成完畢：")
                        st.markdown(response.text)

                    except Exception as ai_err:
                        st.error(f"調用 Gemini 生成失敗，錯誤訊息：{ai_err}")

    except Exception as e:
        st.error(f"數據讀取失敗，請確認 FRED API Key 是否正確。錯誤訊息: {e}")
else:
    st.info("👈 請在左側輸入您的 FRED API Key 以開啟儀表板。")
