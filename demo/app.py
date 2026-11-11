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

# 2. Gemini 金鑰讀取 (相容 AQ. 開頭之新版授權金鑰)
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

        # 擷取最新金融資產價格
        gold_price = market_df["黃金現貨 (GC=F)"].dropna().iloc[-1] if "黃金現貨 (GC=F)" in market_df else 0.0
        oil_price = market_df["布蘭特原油"].dropna().iloc[-1] if "布蘭特原油" in market_df else 0.0
        sp500_price = market_df["S&P 500"].dropna().iloc[-1] if "S&P 500" in market_df else 0.0
        twd_rate = market_df["美元/台幣匯率"].dropna().iloc[-1] if "美元/台幣匯率" in market_df else 0.0

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
        # AI 總體經濟深度戰略報告 (投行級完整長篇研報)
        # -------------------------------------------------------------
        st.write("---")
        st.subheader("🏛️ AI 全球總體經濟與跨資產配置深度戰略研報")
        st.caption("結合最新 FRED 總經指標與 yfinance 市場高頻價格，由 Gemini 生成結構化深度投資策略報告。")

        if st.button("生成全球總體經濟深度戰略研報", type="primary"):
            active_key = gemini_key.strip().replace('"', '').replace("'", "") if gemini_key else ""
            
            if not active_key:
                st.warning("⚠️ 請先在側邊欄輸入 Gemini API Key，或於 secrets.toml 中配置 GEMINI_API_KEY。")
            else:
                with st.spinner("AI 正在交叉計算利差、通膨預期與跨資產定價模型，撰寫深度研報中，請稍候約 10～15 秒..."):
                    try:
                        client = genai.Client(api_key=active_key)

                        prompt = f"""
你是一位任職於華爾街頂級投資銀行（如高盛、摩根士丹利）的全球首席宏觀策略師與資產配置主管。請依據以下儀表板最新抓取到的關鍵總經指標與跨市場資產價格，為機構投資委員會撰寫一份權威、深度且結構完備的**全球總體經濟與跨資產配置戰略研報**（約 800～1200 字繁體中文）：

【系統即時監控數據矩陣】
1. 貨幣與利率指標：
   - 聯邦基金利率 (Fed Funds Rate)：{latest_fed:.2f}%
   - 美國 10 年期國債殖利率 (DGS10)：{latest_10y:.2f}%（前值 {prev_10y:.2f}%）
   - 美國 2 年期國債殖利率 (DGS2)：{latest_2y:.2f}%（前值 {prev_2y:.2f}%）
   - 10Y-2Y 美債利差 (Yield Curve Spread)：{latest_spread:+.2f}%（曲線狀態：{'殖利率曲線倒掛 Inverted' if latest_spread < 0 else '殖利率曲線正斜率 Normal/Steepening'}）
   - 日本 10 年期國債殖利率 (JGB 10Y)：{latest_jp:.3f}%（前值 {jp_prev:.3f}%）
2. 通膨與實體景氣指標：
   - 美國 CPI 消費者物價指數：{latest_cpi:.1f}（前值 {cpi_prev:.1f}）
   - 美國失業率 (Unemployment Rate)：{latest_unemp:.1f}%
3. 金融市場即時資產價格：
   - 標普 500 指數 (S&P 500)：{sp500_price:.2f} 點
   - 黃金現貨 (Gold GC=F)：{gold_price:.2f} 美元/盎司
   - 布蘭特原油 (Brent Crude BZ=F)：{oil_price:.2f} 美元/桶
   - 美元兌新台幣 (USD/TWD)：{twd_rate:.3f}

---

【研報寫作格式與深度論述要求】
請嚴格全程使用正體中文，並依照以下五大結構區塊進行深度剖析：

## 一、即時總體經濟與資產價格監控表
請使用 Markdown 表格整理以上數據，包含「指標項目」、「最新數值」、「前期/對照數值」、「總經意涵評估」四個欄位。

## 二、通膨黏性與勞動市場韌性（軟著陸 vs 硬著陸剖析）
1. 深入分析 CPI 物價指數的邊際變動趨勢，結合失業率評估菲利浦曲線（Phillips Curve）當前表現。
2. 評估實質利率水準（聯邦基金利率減去通膨）對實體經濟與企業資本支出（CapEx）的限制性約束。

## 三、央行政策路徑與全球利差交易（Carry Trade）外溢效應
1. 解構當前 10Y-2Y 利差結構背後所反映的降息/升息預期。
2. 重點剖析美日 10 年期公債利差（目前美債 {latest_10y:.2f}% vs 日債 {latest_jp:.3f}%）對全球流動性與日圓套利交易平倉（Carry Trade Unwind）風險之實質影響。

## 四、宏觀情境機率預測模型
請給出未來 6～12 個月的總經情境機率分佈並逐一分析：
- **基準情境 (Base Case, 機率 %)**：軟著陸或溫和放緩之政策路徑與市場反應。
- **樂觀情境 (Bull Case, 機率 %)**：生產力提升帶動非通膨性成長。
- **悲觀情境 (Bear Case, 機率 %)**：停滯性通膨或深度倒掛引發衰退。

## 五、跨資產配置策略矩陣與投資建議
請提供明確的資產配置權重（建議配置比例 %，總和為 100%），並分別針對以下各類別給出攻守策略：
1. **美股/權益資產**（特別評估科技大型股與價值防禦股）
2. **固定收益/公債**（短天期現金管理 vs 長天期美債資本利得布局）
3. **大宗商品**（黃金避險抗通膨定價 vs 原油景氣需求定價）
4. **外匯策略**（美元指數走勢與新台幣匯率波動防禦）
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
                                            temperature=0.3,
                                            max_output_tokens=4096,  # 擴展至最大上限，確保巨篇深度研報完整生成
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
                            st.success("✅ 全球總體經濟與跨資產配置深度戰略研報已成功生成：")
                            st.markdown(full_report)
                        else:
                            st.error(f"⚠️ 伺服器尖峰繁忙，生成失敗：{last_error}")

                    except Exception as ai_err:
                        st.error(f"調用 Gemini 生成失敗，錯誤訊息：{ai_err}")

    except Exception as e:
        st.error(f"數據讀取失敗，請確認 FRED API Key 是否正確。錯誤訊息: {e}")
else:
    st.info("👈 請在左側輸入您的 FRED API Key 以開啟儀表板。")
