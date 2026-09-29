# -*- coding: utf-8 -*-
"""每日收益 · 跨平台自动汇总（v3.4：养基宝风格布局 + 卡片式盈亏日历）

每天每平台手动抄 2 个数：「当日总市值」和「总收益（累计）」。
- 录入两种方式可混用（每平台择一）：① 市值 + 总收益（市值可留 0 = 今天不记）
  ② 当日收益——自动推算：总收益 = 上一条总收益 + 当日收益，
  市值 = 上一条市值 + 当日收益（上一条没记市值则推不出，存 NULL；
  该平台无更早记录时，当日收益即首期盈亏）
- 每日收益 = 当次总收益 − 该平台上一条总收益；**每平台首条记录**把它的总收益整体当作首期盈亏
  （日历 日/月/年、明细表、月度统计都会体现这笔建仓以来的收益；遇申赎当天会失真，属预期）
- 收益率走势 = 自建仓累计收益率：分母固定 = 第一天倒推的初始本金（第一天市值 − 第一天总收益）
  （第一天就有真实收益率，不再从 0 起；叠加指数也用同一起点算累计涨跌，跑赢/跑输才可比；
   时间范围「本周/本月/本年/全部」只控制显示哪一段）
- 日历 / 当日收益率 = 当期口径：当日（当月/当年）赚的钱 ÷ 期初市值
- 同日同平台重复保存 = 覆盖；取消勾选并保存 = 移除该平台当日记录
- 某平台某天未录入：总市值 / 总收益沿用其最近一次值（曲线不出现假跌）
- 市值漏填（0 或空）的日子收益率显示「—」，不影响金额类数值
- 收益率走势（本周/本月/本年/全部 × 总/分平台/叠加）可叠加 A 股主要指数对比
  （东方财富公开接口，失败自动切腾讯源，离线/失败自动跳过）；
  对比条主数值 = 区间赚的钱 ÷ 初始本金（分母四档统一，v3.8.5）
- 盈亏日历：仿养基宝卡片网格——
  日=按周一~周五排布的日格（当日实心高亮）、月=12 月卡、年=年卡，
  底部显示累计收益与同期指数涨跌
- 布局：养基宝风格——蓝色渐变总览卡 + 居中窄栏白色卡片分区
- 背景：同目录下放置 hutao.png/jpg/... 自动作为单张固定背景（无图则跳过）
- 配色：蓝白主题（项目 .streamlit/config.toml 强制浅色主题）；盈亏数据保留红盈绿亏
- v1 旧库（daily_pnl 字段）自动升级：原数据迁入新表并保留备份 records_v1_backup
"""
import base64
import io
import os
import sqlite3
from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

px.defaults.template = "plotly_white"  # 统一白底网格，配合蓝白主题

# ---------------- 配置 ----------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE_DIR, "portfolio.db")

PLATFORMS = ["同花顺", "养基宝"]  # 新增平台只需在此列表加名字

RED = "#E5484D"       # 盈利（国内习惯：红涨）
GREEN = "#30A46C"     # 亏损（绿跌）
BLUE = "#2E7CF6"      # 主色（市值曲线 / 主题蓝，养基宝风格）
BLUE_DEEP = "#1E5EDB" # 深蓝（总收益曲线）
BLUE_LIGHT = "#8FB8FF"  # 浅蓝（平台对比第二色）
AMBER = "#F59E0B"     # 指数对比线
TREND_COLORS = [BLUE, BLUE_DEEP, BLUE_LIGHT, AMBER]
POS_BG, NEG_BG = "#FCE9E9", "#E4F5EA"   # 卡片浅色底：红盈 / 绿亏

# A 股主要指数（东方财富 secid；对比走势用）
INDEXES = {
    "上证指数": "1.000001",
    "沪深300": "1.000300",
    "创业板指": "0.399006",
    "科创50": "1.000688",
    "中证500": "1.000905",
}

BG_FILES = ("hutao.png", "hutao.jpg", "hutao.jpeg", "hutao.webp",
            "hutao.gif", "hutao.bmp")
BG_MAX_PX = 1600     # 背景图最长边压缩尺寸（全屏单张）

# Streamlit 新旧版本兼容：width="stretch" 需 1.46+，旧版用 use_container_width
_ST = tuple(int(x) for x in st.__version__.split(".")[:2])
STRETCH = {"width": "stretch"} if _ST >= (1, 46) else {"use_container_width": True}


# ---------------- 固定背景 ----------------
def find_bg():
    for name in BG_FILES:
        p = os.path.join(BASE_DIR, name)
        if os.path.exists(p):
            return p
    return None


@st.cache_data(show_spinner=False)
def load_bg_css(path: str, mtime: float) -> str | None:
    """读取背景图（压缩后 base64 内嵌，避免每次请求传原图）。"""
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "webp": "image/webp", "gif": "image/gif", "bmp": "image/bmp"}[ext]
    data = None
    try:  # 压缩大图，减小页面体积（保留足够分辨率供全屏 cover 显示）
        from PIL import Image
        img = Image.open(path).convert("RGB")
        img.thumbnail((BG_MAX_PX, BG_MAX_PX))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=86)
        data, mime = buf.getvalue(), "image/jpeg"
    except Exception:
        data = open(path, "rb").read()
    b64 = base64.b64encode(data).decode()
    return f"""
    <style>
    .stApp {{
      background-image: url("data:{mime};base64,{b64}") !important;
      background-repeat: no-repeat !important;
      background-size: cover !important;
      background-position: center !important;
      background-attachment: fixed !important;  /* 固定跟随屏幕，不随内容滚动 */
      color: #1F2937 !important;  /* 正文统一深灰，杜绝白底白字 */
    }}
    [data-testid="stHeader"] {{ background: transparent; }}
    footer, #MainMenu {{ visibility: hidden; }}
    /* 居中窄栏（仿养基宝）：纯色浅灰蓝底 + 钝化圆角 */
    .block-container {{
      max-width: 920px !important;
      margin: 0 auto !important;
      padding: 1.4rem 2.2rem 4rem !important;
      background: #EDF2F9;
      border-radius: 22px;
      box-shadow: 0 4px 22px rgba(30, 94, 219, 0.09);
    }}
    /* 白色圆角卡片（四角钝化） */
    [data-testid="stVerticalBlockBorderWrapper"] {{
      background: #FFFFFF;
      border: 1px solid rgba(46, 124, 246, 0.10) !important;
      border-radius: 18px !important;
      box-shadow: 0 2px 12px rgba(30, 94, 219, 0.06);
      padding: 18px 22px !important;
    }}
    h1, h2, h3, [data-testid="stMetricLabel"], [data-testid="stMetricValue"] {{
      color: #1F2937;
    }}
    /* ---- 盈亏日历卡片网格 ---- */
    .pcal-row {{ display: grid; gap: 7px; margin-bottom: 7px; }}
    .pcal-cols-5 {{ grid-template-columns: repeat(5, 1fr); }}
    .pcal-cols-4 {{ grid-template-columns: repeat(4, 1fr); }}
    .pcal-cols-3 {{ grid-template-columns: repeat(3, 1fr); }}
    .pcal-hd {{ text-align: center; color: #9CA3AF; font-size: 13px; padding: 2px 0; }}
    .pcal-cell {{
      border-radius: 13px; text-align: center; padding: 7px 2px 9px;
      min-height: 54px; background: #FFFFFF; border: 1px solid #EEF2F7;
    }}
    .pcal-cell .d {{ font-size: 12px; color: #9CA3AF; line-height: 1.3; }}
    .pcal-cell .v {{ font-size: 15px; font-weight: 600; margin-top: 1px; color: #6B7280; }}
    .pcal-cell .big {{ font-size: 18px; }}
    .pcal-pos {{ background: {POS_BG}; border-color: {POS_BG}; }}
    .pcal-pos .v {{ color: {RED}; }}
    .pcal-neg {{ background: {NEG_BG}; border-color: {NEG_BG}; }}
    .pcal-neg .v {{ color: {GREEN}; }}
    .pcal-today-pos {{ background: {RED}; border-color: {RED}; }}
    .pcal-today-pos .d, .pcal-today-pos .v {{ color: #FFFFFF; }}
    .pcal-today-neg {{ background: {GREEN}; border-color: {GREEN}; }}
    .pcal-today-neg .d, .pcal-today-neg .v {{ color: #FFFFFF; }}
    .pcal-today-flat {{ background: {BLUE}; border-color: {BLUE}; }}
    .pcal-today-flat .d, .pcal-today-flat .v {{ color: #FFFFFF; }}
    .pcal-mute {{ background: #F8FAFC; }}
    .pcal-mute .d, .pcal-mute .v {{ color: #CBD5E1; }}
    /* 底部累计行 */
    .pcal-foot {{
      display: flex; justify-content: space-between; padding: 6px 4px 0;
      font-size: 14px; color: #4B5563; flex-wrap: wrap; gap: 6px;
    }}
    </style>
    """


def inject_background() -> None:
    path = find_bg()
    if path:
        css = load_bg_css(path, os.path.getmtime(path))
        if css:
            st.markdown(css, unsafe_allow_html=True)


def section(title: str) -> None:
    """养基宝风格分区标题：蓝色竖条 + 加粗。"""
    st.markdown(
        f'<div style="border-left:4px solid {BLUE};padding-left:9px;'
        f'font-weight:700;font-size:18px;margin:14px 0 2px 2px;color:#1F2937">'
        f'{title}</div>',
        unsafe_allow_html=True,
    )


def _sign_color(v) -> str:
    if v is None or pd.isna(v):
        return "#6B7280"
    return RED if v > 0 else (GREEN if v < 0 else "#6B7280")


def _fmt_signed(v, kind: str) -> str:
    if v is None or pd.isna(v):
        return "—"
    return f"{v:+,.2f}{'%' if kind == '收益率' else ''}"


# ---------------- 指数对比数据 ----------------
_HTTP_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept": "*/*",
}


def _http_json(url: str, referer: str, timeout: int = 8):
    import json
    import urllib.request
    req = urllib.request.Request(
        url, headers={**_HTTP_HEADERS, "Referer": referer})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _index_east(secid: str, beg: str) -> pd.DataFrame:
    """东方财富日 K（date, close）。失败抛异常，由上层换源。"""
    url = ("https://push2his.eastmoney.com/api/qt/stock/kline/get"
           f"?secid={secid}&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f53"
           f"&klt=101&fqt=1&beg={beg}&end=20500101")
    data = _http_json(url, "https://quote.eastmoney.com/")
    kl = (data.get("data") or {}).get("klines") or []
    if not kl:
        raise ValueError("eastmoney: empty klines")
    df = pd.DataFrame([x.split(",")[:2] for x in kl], columns=["date", "close"])
    df["date"] = pd.to_datetime(df["date"])
    df["close"] = df["close"].astype(float)
    return df


def _index_tencent(secid: str, beg: str) -> pd.DataFrame:
    """腾讯行情日 K（date, close）。东财被限流时的备用源。"""
    code = ("sh" if secid.startswith("1.") else "sz") + secid.split(".", 1)[1]
    b = f"{beg[:4]}-{beg[4:6]}-{beg[6:]}"
    end = pd.Timestamp.today().strftime("%Y-%m-%d")
    url = ("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
           f"?param={code},day,{b},{end},640,qfq")
    data = _http_json(url, "https://gu.qq.com/")
    node = (data.get("data") or {}).get(code) or {}
    k = node.get("qfqday") or node.get("day") or []
    if not k:
        raise ValueError("tencent: empty klines")
    df = pd.DataFrame([(r[0], r[2]) for r in k], columns=["date", "close"])
    df["date"] = pd.to_datetime(df["date"])
    df["close"] = df["close"].astype(float)
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_index_cached(secid: str, beg: str) -> pd.DataFrame:
    """多源尝试：东财 → 腾讯。全部失败抛异常（异常不会被缓存，下次自动重试）。"""
    errs = []
    for fn in (_index_east, _index_tencent):
        try:
            df = fn(secid, beg)
            if df is not None and not df.empty:
                return df
            errs.append(f"{fn.__name__}: empty")
        except Exception as e:
            errs.append(f"{fn.__name__}: {type(e).__name__}")
    raise RuntimeError("; ".join(errs))


def fetch_index(secid: str, beg: str) -> pd.DataFrame | None:
    """取指数收盘价（date, close）。全部数据源失败返回 None（不缓存失败结果）。"""
    try:
        return _fetch_index_cached(secid, beg)
    except Exception:
        return None


def index_relative(idf: pd.DataFrame, start, range_idx) -> pd.Series:
    """指数区间累计涨跌幅（%），基期 = 区间起点前最后收盘（与收益率口径一致）。"""
    idf = idf.sort_values("date")
    pre = idf[idf["date"] < start]
    base = float(pre["close"].iloc[-1]) if not pre.empty else float(idf["close"].iloc[0])
    s = idf.set_index("date")["close"] / base * 100 - 100
    full = s.index.union(pd.DatetimeIndex(range_idx))
    return s.reindex(full).ffill().reindex(pd.DatetimeIndex(range_idx))


def index_period_change(idf: pd.DataFrame | None, start, end) -> float | None:
    """指数在 [start, end] 的累计涨跌幅（%）。数据缺失返回 None。"""
    if idf is None or idf.empty:
        return None
    idf = idf.sort_values("date")
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    pre = idf[idf["date"] < start]
    sub = idf[(idf["date"] >= start) & (idf["date"] <= end)]
    if sub.empty:
        return None
    base = float(pre["close"].iloc[-1]) if not pre.empty else float(sub["close"].iloc[0])
    if base <= 0:
        return None
    return float(sub["close"].iloc[-1]) / base * 100 - 100


# ---------------- 数据层 ----------------
def init_db() -> None:
    con = sqlite3.connect(DB)
    cols = [r[1] for r in con.execute("PRAGMA table_info(records)")]
    migrated = False
    if "daily_pnl" in cols and "market_value" not in cols:
        # v1 → v2/v3：旧表改名备份，迁移已有总收益（市值留空，待补录）
        con.execute("ALTER TABLE records RENAME TO records_v1_backup")
        cols, migrated = [], True
    if not cols:
        con.execute(
            """CREATE TABLE IF NOT EXISTS records(
                date         TEXT,   -- 'YYYY-MM-DD'
                platform     TEXT,   -- 平台名
                market_value REAL,  -- 当日总市值
                total_pnl    REAL,  -- 总收益（累计）
                PRIMARY KEY(date, platform)
            )"""
        )
    if migrated:
        con.execute(
            "INSERT OR REPLACE INTO records(date, platform, total_pnl) "
            "SELECT date, platform, total_pnl FROM records_v1_backup"
        )
    con.commit()
    con.close()


def upsert(d: date, platform: str, market_value: float, total: float) -> None:
    """同日同平台重复保存 = 覆盖。

    市值留 0（或 None）= 今天不记市值，存 NULL：该平台当日不显示收益率，
    金额类数值不受影响。
    """
    con = sqlite3.connect(DB)
    mv = (float(market_value)
          if market_value is not None and float(market_value) > 0 else None)
    con.execute(
        "INSERT OR REPLACE INTO records VALUES(?,?,?,?)",
        (d.isoformat(), platform, mv, float(total)),
    )
    con.commit()
    con.close()


def delete(d: date, platform: str) -> None:
    """移除某天某平台的记录（取消勾选后保存时调用）。"""
    con = sqlite3.connect(DB)
    con.execute(
        "DELETE FROM records WHERE date = ? AND platform = ?",
        (d.isoformat(), platform),
    )
    con.commit()
    con.close()


def prev_record(d: date, platform: str):
    """该平台在 d 之前最近一条记录 (market_value, total_pnl)；没有则 None。"""
    con = sqlite3.connect(DB)
    row = con.execute(
        "SELECT market_value, total_pnl FROM records "
        "WHERE platform = ? AND date < ? ORDER BY date DESC LIMIT 1",
        (platform, d.isoformat()),
    ).fetchone()
    con.close()
    return row


def resolve_daily_entry(d: date, platform: str, daily: float):
    """「当日收益」模式换算（保存时折算成统一的 市值+总收益 存储）：

    - 总收益 = 上一条总收益 + 当日收益
    - 市值   = 上一条市值 + 当日收益（上一条没记市值则推不出，存 NULL）
    - 该平台没有任何更早记录时：当日收益即首期盈亏（总收益），市值 NULL
    """
    prev = prev_record(d, platform)
    if prev is None:
        return None, float(daily)
    p_mv, p_tp = prev
    new_mv = (float(p_mv) + float(daily)) if p_mv is not None else None
    return new_mv, float(p_tp) + float(daily)


def load_df() -> pd.DataFrame:
    con = sqlite3.connect(DB)
    df = pd.read_sql("SELECT * FROM records", con)
    con.close()
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date", kind="stable")


# ---------------- 计算层（纯函数，不依赖 Streamlit） ----------------
def prep_daily(df: pd.DataFrame) -> pd.DataFrame:
    """按平台计算：当日收益、前期市值、当日收益率（%）。

    - **每平台首条记录**：把它的「总收益」整体当作首期盈亏（建仓以来的收益）
    - 之后各日：当日收益 = 当次总收益 − 上一条总收益
    - 前期市值 = 上一条记录的市值；首条用「当日市值 − 当日收益」（= 初始本金）
    - 当日市值缺失（0/空）的日子收益率记 NaN（显示「—」）
    """
    d = df.sort_values(["platform", "date"], kind="stable").copy()
    chg = d.groupby("platform")["total_pnl"].diff()
    d["当日收益"] = chg.fillna(d["total_pnl"])   # 首条记录：总收益 = 首期盈亏
    prev = d.groupby("platform")["market_value"].shift()
    d["前期市值"] = prev.fillna(d["market_value"] - d["当日收益"])
    d["当日收益率"] = (d["当日收益"] / d["前期市值"] * 100).where(
        (d["前期市值"] > 0) & (d["market_value"] > 0)
    )
    return d


def initial_capital(d: pd.DataFrame) -> dict:
    """各平台的初始本金：取该平台最早一条有市值的记录，用「市值 − 总收益」倒推。

    第一天（建仓）就已经带着历史收益，所以本金 = 市值 − 总收益，
    据此算出的收益率从第一天起就是真实累计收益率（而非 0）。
    市值缺失（0/空）的记录跳过，继续找下一条。
    返回 {平台: 初始本金}；无可用市值数据的平台不出现在结果里。
    """
    bases = {}
    for p, g in d.groupby("platform"):
        ok = g[g["market_value"] > 0].sort_values("date", kind="stable")
        if ok.empty:
            continue
        row = ok.iloc[0]
        base = float(row["market_value"]) - float(row["total_pnl"])
        if base > 0:                     # 市值 ≤ 总收益（本金算不出来）则跳过
            bases[p] = base
    return bases


def cumulative_return_curves(d: pd.DataFrame, start, scopes, bases: dict):
    """自建仓累计收益率曲线（%）：分母固定 = 第一天倒推的初始本金。

    每天数值 = 当天累计总收益 ÷ 初始本金 × 100%（含建仓以来的历史收益）。
    start 只决定显示哪一段，曲线不自区间起点归零。
    d: prep_daily 结果；start: pd.Timestamp；scopes: [(名称, [平台...]), ...]
    返回 long 表：日期, 名称, 收益率, 当日金额。
    """
    empty = pd.DataFrame(columns=["日期", "名称", "收益率", "当日金额"])
    start = pd.Timestamp(start)
    pv_pnl = d.pivot(index="date", columns="platform", values="total_pnl").ffill()
    range_idx = pv_pnl.index[pv_pnl.index >= start]
    if len(range_idx) == 0:
        return empty

    frames = []
    for name, plats in scopes:
        usable = [p for p in plats if p in bases]
        if not usable:
            continue
        den = sum(bases[p] for p in usable)
        if den <= 0:
            continue
        contrib = pd.DataFrame(index=range_idx)
        for p in usable:
            contrib[p] = pv_pnl[p].reindex(range_idx)
        if len(usable) == 1:
            num = contrib[usable[0]]                        # 单平台：无数据日留空
        else:
            num = contrib.sum(axis=1, skipna=True, min_count=1)
        dsub = d[d["platform"].isin(usable) & (d["date"] >= start)]
        amt = (dsub.groupby("date")["当日收益"].sum()
               .reindex(range_idx).fillna(0.0))
        frames.append(pd.DataFrame({
            "日期": range_idx, "名称": name,
            "收益率": (num / den * 100).values,
            "当日金额": amt.values,
        }))
    if not frames:
        return empty
    return pd.concat(frames, ignore_index=True)


def month_daily(dd: pd.DataFrame, year: int, month: int) -> pd.DataFrame:
    """日历日视图数据：按日聚合 金额 / 分母 / 收益率（值可能为 NaN）。"""
    dd2 = dd[(dd["date"].dt.year == year) & (dd["date"].dt.month == month)]
    if dd2.empty:
        return pd.DataFrame(columns=["date", "金额", "分母", "mv_ok", "收益率"])
    g = dd2.groupby("date").agg(
        金额=("当日收益", "sum"),
        分母=("前期市值", "sum"),
        mv_ok=("market_value", lambda s: bool((s > 0).any())),
    ).reset_index()
    g["收益率"] = (g["金额"] / g["分母"] * 100).where((g["分母"] > 0) & g["mv_ok"])
    return g


def monthly_summary(dd: pd.DataFrame) -> pd.DataFrame:
    """按月汇总（index=月末日期）：月金额（当月差值合计）、月收益率（%/上月末市值）。

    首月与首日口径一致：没有上月可减，把当月总收益整体当作当月盈亏，
    分母用「第一天倒推的初始本金」。
    """
    pv_pnl = (dd.pivot(index="date", columns="platform", values="total_pnl")
              .ffill().resample("ME").last())
    mv = dd.pivot(index="date", columns="platform", values="market_value")
    mv = mv.mask(mv <= 0).ffill().resample("ME").last()
    amt = pv_pnl.diff().sum(axis=1, skipna=True, min_count=1)
    prev_mv = mv.shift().sum(axis=1, skipna=True, min_count=1)
    base_total = sum(initial_capital(dd).values())
    if len(amt) and pd.isna(amt.iloc[0]):
        amt.iloc[0] = pv_pnl.iloc[0].sum(skipna=True)    # 首月 = 建仓以来的总收益
    if len(prev_mv) and pd.isna(prev_mv.iloc[0]) and base_total > 0:
        prev_mv.iloc[0] = base_total                     # 首月分母 = 初始本金
    rate = (amt / prev_mv * 100).where(prev_mv > 0)
    out = pd.DataFrame({"月金额": amt, "月收益率": rate})
    first, last = dd["date"].min().to_period("M"), dd["date"].max().to_period("M")
    periods = out.index.to_period("M")
    return out[(periods >= first) & (periods <= last)]


def yearly_summary(dd: pd.DataFrame) -> pd.DataFrame:
    """年视图表：年份, 年收益金额, 年收益率（分母=上年末市值；首年用初始本金）。"""
    m = monthly_summary(dd)
    if m.empty:
        return pd.DataFrame(columns=["年份", "年收益金额", "年收益率"])
    mv = dd.pivot(index="date", columns="platform", values="market_value")
    mv = mv.mask(mv <= 0).ffill().resample("YE").last()
    prev = mv.shift().sum(axis=1, skipna=True, min_count=1)
    base_total = sum(initial_capital(dd).values())
    if len(prev) and pd.isna(prev.iloc[0]) and base_total > 0:
        prev.iloc[0] = base_total                        # 首年分母 = 初始本金
    prev.index = prev.index.year
    yr = m["月金额"].groupby(m.index.year).sum().rename_axis("年份")
    out = pd.DataFrame({"年收益金额": yr})
    out["年收益率"] = (yr / prev * 100).where(prev > 0)
    return out.reset_index()


# ---------------- 盈亏日历（HTML 卡片网格，仿养基宝） ----------------
def _cell(value, top, cls, title=""):
    t = f' title="{title}"' if title else ""
    big = " big" if len(str(value)) <= 9 and value != "—" else ""
    return (f'<div class="pcal-cell {cls}"{t}>'
            f'<div class="d">{top}</div>'
            f'<div class="v{big}">{value}</div></div>')


def _foot_html(left_label, left_v, idx_name, idx_v):
    c1 = _sign_color(left_v)
    c2 = _sign_color(idx_v)
    lv = "—" if left_v is None or pd.isna(left_v) else f"{left_v:+,.2f}"
    iv = "—" if idx_v is None or pd.isna(idx_v) else f"{idx_v:+.2f}%"
    return (f'<div class="pcal-foot"><span>{left_label}：'
            f'<b style="color:{c1}">{lv}</b></span>'
            f'<span>{idx_name}：<b style="color:{c2}">{iv}</b></span></div>')


def calendar_day_html(g: pd.DataFrame, year: int, month: int,
                      value_mode: str, today: date) -> str | None:
    """日视图：周一~周五排布的日格网格（仿养基宝）。"""
    import calendar as pycal
    fw = pycal.weekday(year, month, 1)   # 1 号是周几（0=周一）
    ndays = pycal.monthrange(year, month)[1]
    nweeks = (fw + ndays + 6) // 7
    lookup = {ts.day: (float(r.金额), float(r.收益率))
              for ts, r in zip(g["date"], g.itertuples())}
    rows = ['<div class="pcal-row pcal-cols-5">'
            + "".join(f'<div class="pcal-hd">{h}</div>'
                      for h in ["一", "二", "三", "四", "五"])
            + "</div>"]
    for w in range(nweeks):
        cells = []
        for wd in range(5):
            day = w * 7 + wd - fw + 1
            if day < 1 or day > ndays:
                cells.append('<div class="pcal-cell pcal-mute"></div>')
                continue
            d = date(year, month, day)
            amt, rate = lookup.get(day, (None, None))
            v = rate if value_mode == "收益率" else amt
            top = "今" if d == today else str(day)
            title = (f"{d:%Y-%m-%d}　金额 {amt:+,.2f}"
                     if amt is not None else f"{d:%Y-%m-%d}　未录入")
            if rate is not None and not pd.isna(rate):
                title += f"　收益率 {rate:+.2f}%"
            elif amt is not None:
                title += "　收益率 —（市值缺失）"
            if d == today:
                cls = ("pcal-today-flat" if amt is None
                       else "pcal-today-pos" if amt > 0
                       else "pcal-today-neg" if amt < 0 else "pcal-today-flat")
            elif amt is None or pd.isna(amt):
                cls = "pcal-mute" if d > today else ""
            elif amt > 0:
                cls = "pcal-pos"
            elif amt < 0:
                cls = "pcal-neg"
            else:
                cls = ""
            disp = "" if amt is None else _fmt_signed(v, value_mode)
            cells.append(_cell(disp, top, cls, title))
        rows.append('<div class="pcal-row pcal-cols-5">' + "".join(cells) + "</div>")
    return "".join(rows)


def calendar_month_html(ms: pd.DataFrame, year: int, value_mode: str,
                        today: date) -> str:
    """月视图：12 个月卡网格。"""
    col = "月收益率" if value_mode == "收益率" else "月金额"
    look = {(ts.year, ts.month): v for ts, v in zip(ms.index, ms[col])}
    look_amt = {(ts.year, ts.month): v for ts, v in zip(ms.index, ms["月金额"])}
    look_rate = {(ts.year, ts.month): v for ts, v in zip(ms.index, ms["月收益率"])}
    rows = []
    for mo in range(1, 13):
        v = look.get((year, mo))
        amt, rate = look_amt.get((year, mo)), look_rate.get((year, mo))
        top = f"{mo}月"
        title = f"{year}年{mo:02d}月"
        title += f"　金额 {amt:+,.2f}" if amt is not None and not pd.isna(amt) else "　未录入"
        if rate is not None and not pd.isna(rate):
            title += f"　收益率 {rate:+.2f}%"
        if (today.year, today.month) == (year, mo):
            # 本月：有盈亏按红/绿实心高亮，没录数据才是蓝色
            cls = ("pcal-today-flat" if amt is None or pd.isna(amt)
                   else "pcal-today-pos" if amt > 0
                   else "pcal-today-neg" if amt < 0 else "pcal-today-flat")
        elif v is None or pd.isna(v):
            cls = "pcal-mute" if mo > today.month or year > today.year else ""
        elif v > 0:
            cls = "pcal-pos"
        elif v < 0:
            cls = "pcal-neg"
        else:
            cls = ""
        rows.append(_cell(_fmt_signed(v, value_mode), top, cls, title))
        if mo % 4 == 0:
            rows.append("</div><div class='pcal-row pcal-cols-4'>" if mo < 12 else "")
    body = ('<div class="pcal-row pcal-cols-4">' + "".join(rows) + "</div>")
    # 修正上面按 4 个一行的分段拼接（若 12 个恰好整除则无需分段）
    return body


def calendar_year_html(ys: pd.DataFrame, value_mode: str, today: date) -> str:
    """年视图：年卡网格。"""
    rows = []
    for r in ys.itertuples():
        v = r.年收益率 if value_mode == "收益率" else r.年收益金额
        title = f"{r.年份}年　金额 {r.年收益金额:+,.2f}"
        if r.年收益率 is not None and not pd.isna(r.年收益率):
            title += f"　收益率 {r.年收益率:+.2f}%"
        if r.年份 == today.year:
            # 本年：有盈亏按红/绿实心高亮，没录数据才是蓝色
            a = r.年收益金额
            cls = ("pcal-today-flat" if a is None or pd.isna(a)
                   else "pcal-today-pos" if a > 0
                   else "pcal-today-neg" if a < 0 else "pcal-today-flat")
        elif v is None or pd.isna(v):
            cls = "pcal-mute"
        elif v > 0:
            cls = "pcal-pos"
        elif v < 0:
            cls = "pcal-neg"
        else:
            cls = ""
        rows.append(_cell(_fmt_signed(v, value_mode), str(r.年份), cls, title))
    return '<div class="pcal-row pcal-cols-3">' + "".join(rows) + "</div>"


init_db()

# ---------------- 页面 ----------------
st.set_page_config(page_title="每日收益 · 跨平台汇总", layout="wide")
inject_background()


# ---------------- 录入弹窗 ----------------
def apply_entries(d_in: date, entries: dict) -> list:
    """保存弹窗提交（UI 只收集，保存统一走这里，便于测试）。

    entries = {平台: (on, 模式, 值...)}：
      (True, "daily", 当日收益) / (True, "full", 市值, 总收益) / (False, ...)
    返回已保存的平台列表；未勾选的平台其当日记录被移除。
    """
    saved = []
    for p, e in entries.items():
        if not e[0]:
            delete(d_in, p)          # 勾掉并保存 = 移除该平台当日记录
        elif e[1] == "daily":
            mv, tp = resolve_daily_entry(d_in, p, e[2])
            upsert(d_in, p, mv, tp)
            saved.append(p)
        else:
            upsert(d_in, p, e[2], e[3])
            saved.append(p)
    return saved


@st.dialog("录入数据", width="large")
def entry_dialog():
    d_in = st.date_input("日期", value=date.today())
    st.caption("两种方式可混用：**① 当日收益**——只抄 1 个数，市值/总收益按上一条记录自动推算"
               "　**② 市值 + 总收益**（市值可留 0 = 今天不记；申赎/出入金当天建议用这个）")
    entries = {}
    cols = st.columns(len(PLATFORMS))
    for col, p in zip(cols, PLATFORMS):
        with col:
            on = st.checkbox(f"今日录入 {p}", value=True, key=f"{p}_on")
            mode = st.radio(
                f"{p} · 方式", ["当日收益", "市值 + 总收益"],
                key=f"{p}_mode", horizontal=True,
                disabled=not on, label_visibility="collapsed",
            )
            daily_in = st.number_input(
                f"{p} · 当日收益（当天赚/亏，非累计）", step=0.01, format="%.2f",
                key=f"{p}_daily", disabled=(not on or mode != "当日收益"),
            )
            mv_in = st.number_input(
                f"{p} · 当日市值", step=0.01, format="%.2f",
                key=f"{p}_mv", disabled=(not on or mode != "市值 + 总收益"),
                help="留 0 = 今天不记市值（该平台当日不显示收益率，金额不受影响）",
            )
            tp_in = st.number_input(
                f"{p} · 总收益（累计）", step=0.01, format="%.2f",
                key=f"{p}_tp", disabled=(not on or mode != "市值 + 总收益"),
            )
            if mode == "当日收益":
                entries[p] = (on, "daily", daily_in)
            else:
                entries[p] = (on, "full", mv_in, tp_in)

    if st.button("保存", type="primary", use_container_width=True,
                 disabled=not any(e[0] for e in entries.values())):
        saved = apply_entries(d_in, entries)
        st.success(f"{d_in} 已保存：{'、'.join(saved)}（同日重复保存=覆盖）")
        st.caption("点右上角 ✕ 关闭弹窗返回主页，指标与图表会自动刷新。")


df = load_df()
if df.empty:
    st.info("还没有数据：点下方「录入数据」按钮开始——填「市值 + 总收益」，"
            "或只填「当日收益」（自动推算），都行。")
    if st.button("✏️ 录入数据", type="primary"):
        entry_dialog()
    st.stop()

d = prep_daily(df)
PLATFORMS_with_data = [p for p in PLATFORMS if p in set(d["platform"])]

# 初始本金（第一天倒推：市值 − 总收益），收益率走势与累计收益率统一以此做分母
INIT_BASE = initial_capital(d)


def _fmt(v, nd=2):
    return "—" if v is None or pd.isna(v) else f"{v:,.{nd}f}"


# ---------------- 盈亏总览（养基宝风格蓝色渐变卡） ----------------
last_date = d["date"].max()
last_rows = d[d["date"] == last_date]

pv_pnl = d.pivot(index="date", columns="platform", values="total_pnl").ffill()
mv = d.pivot(index="date", columns="platform", values="market_value")
pv_mv = mv.mask(mv <= 0).ffill()
cum_by_date = pv_pnl.sum(axis=1)
mv_by_date = pv_mv.sum(axis=1)
total_mv = float(mv_by_date.iloc[-1])
total_cum = float(cum_by_date.iloc[-1])
daily_sum = float(last_rows["当日收益"].sum())
denom = float(last_rows["前期市值"].sum())
day_rate = (daily_sum / denom * 100) if denom > 0 else None
base_total = sum(INIT_BASE.values())
cum_rate = (total_cum / base_total * 100) if base_total > 0 else None

rate_txt = "—" if day_rate is None or pd.isna(day_rate) else f"{day_rate:+.2f}%"
cum_rate_txt = "—" if cum_rate is None or pd.isna(cum_rate) else f"{cum_rate:+.2f}%"
st.markdown(
    f"""
    <div style="background:linear-gradient(135deg,#4E92F8 0%,{BLUE} 60%,#2563EB 100%);
                border-radius:20px;padding:20px 26px;color:#FFFFFF;
                box-shadow:0 4px 16px rgba(37,99,235,0.25);">
      <div style="display:flex;justify-content:space-between;opacity:.85;font-size:13px">
        <span>每日收益 · 跨平台自动汇总</span>
        <span>截至 {last_date:%Y-%m-%d}</span>
      </div>
      <div style="display:flex;align-items:flex-end;gap:40px;margin-top:10px;flex-wrap:wrap">
        <div>
          <div style="font-size:13px;opacity:.88">当日总收益</div>
          <div style="font-size:40px;font-weight:700;line-height:1.15">{_fmt(daily_sum)}</div>
          <div style="font-size:14px;opacity:.92">当日收益率&nbsp;&nbsp;{rate_txt}
            <span style="opacity:.55">&nbsp;｜&nbsp;</span>
            累计收益率&nbsp;&nbsp;{cum_rate_txt}
          </div>
        </div>
        <div style="margin-left:auto;display:flex;gap:40px;text-align:right;padding-bottom:4px">
          <div>
            <div style="font-size:13px;opacity:.88">总市值</div>
            <div style="font-size:22px;font-weight:600">{_fmt(total_mv)}</div>
          </div>
          <div>
            <div style="font-size:13px;opacity:.88">总收益</div>
            <div style="font-size:22px;font-weight:600">{_fmt(total_cum)}</div>
          </div>
        </div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown('<div style="height:16px"></div>', unsafe_allow_html=True)  # 按钮下移一点
b1, b2 = st.columns([1, 3])
with b1:
    if st.button("✏️ 录入数据", type="primary"):
        entry_dialog()
with b2:
    st.caption("同日重复保存=覆盖；取消勾选并保存=移除该平台当日记录（数值留在弹窗里可恢复）")

# ---------------- 收益走势 ----------------
section("收益走势")
with st.container(border=True):
    today = date.today()
    range_map = {
        "本周": pd.Timestamp(today - timedelta(days=today.weekday())),
        "本月": pd.Timestamp(today.replace(day=1)),
        "本年": pd.Timestamp(today.replace(month=1, day=1)),
        "全部": d["date"].min(),
    }
    r1, r2, r3 = st.columns(3)
    sel_range = r1.radio("时间范围", list(range_map.keys()), horizontal=True)
    sel_scope_a = r2.radio(
        "范围", ["总收益"] + PLATFORMS_with_data + ["全部叠加"], horizontal=True)
    idx_name = r3.selectbox("对比指数", ["无"] + list(INDEXES.keys()))

    if sel_scope_a == "全部叠加":
        scopes = [("总收益", PLATFORMS_with_data)] + [(p, [p]) for p in PLATFORMS_with_data]
    elif sel_scope_a == "总收益":
        scopes = [("总收益", PLATFORMS_with_data)]
    else:
        scopes = [(sel_scope_a, [sel_scope_a])]

    start = range_map[sel_range]
    curves = cumulative_return_curves(d, start, scopes, INIT_BASE)

    idx_label = None
    parts = []
    if not curves.empty:
        parts.append(curves)
    if idx_name != "无":
        first_day = d["date"].min()      # 建仓日：指数与收益同一起点，跑赢/跑输才可比
        beg = (first_day - timedelta(days=25)).strftime("%Y%m%d")
        idf = fetch_index(INDEXES[idx_name], beg)
        if idf is None or idf.empty:
            st.caption(f"{idx_name}数据获取失败（可能网络不通），已跳过叠加。")
        elif not curves.empty:
            idx_label = idx_name
            idx_range = pd.DatetimeIndex(sorted(curves["日期"].unique()))
            s = index_relative(idf, first_day, idx_range)
            parts.append(pd.DataFrame({
                "日期": s.index, "名称": idx_label,
                "收益率": s.values, "当日金额": float("nan"),
            }).dropna(subset=["收益率"]))

    if not parts:
        st.info("该区间暂无数据，或缺少市值无法计算收益率。")
    else:
        plot_df = pd.concat(parts, ignore_index=True)
        fig_trend = px.line(
            plot_df, x="日期", y="收益率", color="名称", markers=True,
            color_discrete_sequence=TREND_COLORS,
            custom_data=["当日金额"],
        )
        for tr in fig_trend.data:
            if tr.name == idx_label:  # 指数线：固定琥珀色，与蓝色系收益线明显区分
                tr.line.color = AMBER
                tr.hovertemplate = ("%{fullData.name}　%{y:.2f}%<extra></extra>")
            else:
                tr.hovertemplate = ("%{fullData.name}　%{y:.2f}%"
                                    "<br>当日金额 %{customdata[0]:,.2f}<extra></extra>")
        for tr in fig_trend.data:   # 数据点：白色描边圆点，单点也清晰可见
            tr.marker = dict(size=6, line=dict(width=1.5, color="#FFFFFF"))
        fig_trend.update_yaxes(ticksuffix="%", tickformat=",")
        # X 轴只标实际数据点：范围=首末数据日期，按点数自动稀疏刻度（多则隔几天一标）
        x0, x1 = plot_df["日期"].min(), plot_df["日期"].max()
        span_ms = max((x1 - x0).total_seconds() * 1000, 86400000)
        fig_trend.update_xaxes(
            tickformat="%m-%d",
            range=[x0 - pd.Timedelta(hours=12), x1 + pd.Timedelta(hours=12)],
            dtick=max(span_ms / 6, 86400000),
        )
        # 悬停交互：竖直比对虚线 + 该日各线数值汇总（仿支付宝盈亏分析）
        fig_trend.update_layout(
            height=330, margin=dict(t=10, b=0),
            legend=dict(orientation="h", y=1.12),
            hovermode="x unified",
            hoverlabel=dict(bgcolor="rgba(255,255,255,0.96)",
                            bordercolor=BLUE, font=dict(color="#1F2937")),
        )
        st.plotly_chart(fig_trend, **STRETCH)

        # 跑赢/跑输对比条（白色半透明底）——分子按所选时间范围取区间收益，
        # 分母固定 = 初始本金；数值随 本周/本月/本年/全部 切换而变化
        #（曲线本身仍是自建仓累计，分母同为初始本金，口径一致）
        primary = "总收益" if sel_scope_a in ("总收益", "全部叠加") else sel_scope_a
        sub = (curves[curves["名称"] == primary]["收益率"].dropna()
               if not curves.empty else pd.Series(dtype=float))
        if not sub.empty:
            # 我的区间收益率 = 区间赚的钱 ÷ 初始本金（四档统一口径）：
            # 分子 = 最新总收益 − 范围起点前最后一条记录的总收益
            #（范围起点早于/等于首条记录时，首条的总收益整体计入本区间，
            #  与日历「首期盈亏」口径一致）；
            # 分母固定 = 初始本金，不再用期初市值（v3.8.5，用户要求统一「后值」口径）
            pv_bar = d.pivot(index="date", columns="platform",
                             values="total_pnl").ffill()
            plats_bar = [p for p in (PLATFORMS_with_data if primary == "总收益"
                                     else [primary]) if p in pv_bar.columns]
            pnl = pv_bar[plats_bar].sum(axis=1)
            start_ts = pd.Timestamp(start)
            pre = pnl[pnl.index < start_ts]
            pnl_base = float(pre.iloc[-1]) if not pre.empty else 0.0
            mv_base = float(sum(INIT_BASE.get(p, 0.0) for p in plats_bar))
            my_ret = (((float(pnl.iloc[-1]) - pnl_base) / mv_base * 100)
                      if mv_base > 0 else float("nan"))
            range_txt = {"本周": "本周", "本月": "本月", "本年": "本年",
                         "全部": "建仓以来"}[sel_range]
            my_txt = (f"{my_ret:+.2f}%" if pd.notna(my_ret) else "—")
            line = f"<b>{primary}·{range_txt}收益率：{my_txt}</b>"
            # 非「全部」区间：顺带保留自建仓累计收益率，两种口径都能看到
            if sel_range != "全部":
                cum_last = float(sub.iloc[-1])
                line += (f"<span style='opacity:.55'>　（建仓以来累计 "
                         f"{cum_last:+.2f}%）</span>")
            if idx_label:
                idx_rows = plot_df[plot_df["名称"] == idx_label]["收益率"].dropna()
                if not idx_rows.empty:
                    idx_ret = index_period_change(
                        idf, start, curves["日期"].max())
                    if idx_ret is None:
                        idx_ret = 0.0
                    diff = my_ret - idx_ret
                    win = diff >= 0
                    line += (f"<span style='opacity:.55'>　｜　</span>{idx_label}同期："
                             f"<b style='color:{_sign_color(idx_ret)}'>{idx_ret:+.2f}%</b>"
                             f"<span style='opacity:.55'>　｜　</span>"
                             f"<span style='color:{RED if win else GREEN};"
                             f"font-weight:600'>{'跑赢' if win else '跑输'} "
                             f"{idx_label} {abs(diff):.2f} 个百分点</span>")
            st.markdown(
                f'<div style="background:rgba(255,255,255,0.65);'
                f'border:1px solid rgba(46,124,246,0.08);border-radius:10px;'
                f'padding:9px 16px;font-size:15px;color:#1F2937">{line}</div>',
                unsafe_allow_html=True,
            )

    if INIT_BASE:  # 口径透明：把倒推出来的初始本金亮出来
        bp = "　｜　".join(f"{p} {INIT_BASE[p]:,.2f}"
                          for p in PLATFORMS_with_data if p in INIT_BASE)
        st.caption(f"初始本金（= 第一天市值 − 第一天总收益）：{bp}"
                   f"　｜　合计 {sum(INIT_BASE.values()):,.2f}")

# ---------------- 盈亏日历 ----------------
section("盈亏日历")
with st.container(border=True):
    ca, cb, cc = st.columns(3)
    gran = ca.radio("粒度", ["日", "月", "年"], horizontal=True)
    vmode = cb.radio("显示", ["收益率", "金额"], horizontal=True)
    cscope = cc.radio("范围", ["总收益"] + PLATFORMS_with_data, horizontal=True)
    dd = d if cscope == "总收益" else d[d["platform"] == cscope]
    today = date.today()

    if gran == "日":
        months = sorted(d["date"].dt.strftime("%Y-%m").unique(), reverse=True)
        sel_month = st.selectbox("月份", months)
        yy, mm = (int(x) for x in sel_month.split("-"))
        g = month_daily(dd, yy, mm)
        if g.empty:
            st.info("该月暂无数据。")
        else:
            st.markdown(calendar_day_html(g, yy, mm, vmode, today),
                        unsafe_allow_html=True)
            m_amt = float(g["金额"].sum())
            idf = fetch_index(INDEXES["上证指数"],
                              (pd.Timestamp(yy, mm, 1) - timedelta(days=25))
                              .strftime("%Y%m%d"))
            m_end = (pd.Timestamp(yy, mm, 1) + pd.offsets.MonthEnd(0))
            idx_v = index_period_change(idf, pd.Timestamp(yy, mm, 1),
                                        min(m_end, pd.Timestamp(today)))
            st.markdown(_foot_html(f"{mm}月累计收益", m_amt, "上证指数", idx_v),
                        unsafe_allow_html=True)
    elif gran == "月":
        years = sorted(d["date"].dt.year.unique(), reverse=True)
        sel_year = st.selectbox("年份", years)
        ms = monthly_summary(dd)
        msy = ms[ms.index.year == sel_year]
        if msy.empty:
            st.info("该年暂无数据。")
        else:
            st.markdown(calendar_month_html(msy, sel_year, vmode, today),
                        unsafe_allow_html=True)
            y_amt = float(msy["月金额"].sum())
            idf = fetch_index(INDEXES["上证指数"],
                              f"{sel_year}0101")
            y_end = min(pd.Timestamp(sel_year, 12, 31), pd.Timestamp(today))
            idx_v = index_period_change(idf, pd.Timestamp(sel_year, 1, 1), y_end)
            st.markdown(_foot_html(f"{sel_year}年累计收益", y_amt, "上证指数", idx_v),
                        unsafe_allow_html=True)
    else:
        ys = yearly_summary(dd)
        if ys.empty:
            st.info("暂无数据。")
        else:
            st.markdown(calendar_year_html(ys, vmode, today), unsafe_allow_html=True)
            a_amt = float(ys["年收益金额"].sum())
            idf = fetch_index(INDEXES["上证指数"],
                              (dd["date"].min() - timedelta(days=25)).strftime("%Y%m%d"))
            idx_v = index_period_change(idf, dd["date"].min(),
                                        min(dd["date"].max(), pd.Timestamp(today)))
            st.markdown(_foot_html("全部累计收益", a_amt, "上证指数", idx_v),
                        unsafe_allow_html=True)

# ---------------- 明细 / 月度 ----------------
section("数据")
with st.expander("查看明细数据"):
    detail = d.drop(columns=["前期市值"])
    detail["_o"] = detail["platform"].map({p: i for i, p in enumerate(PLATFORMS)})
    detail = detail.sort_values(
        ["date", "_o"], ascending=[False, True], kind="stable"
    ).drop(columns="_o")
    st.dataframe(
        detail,
        hide_index=True,
        column_config={
            "date": st.column_config.DateColumn("日期", format="YYYY-MM-DD"),
            "platform": st.column_config.TextColumn("平台"),
            "market_value": st.column_config.NumberColumn("当日市值", format="%.2f"),
            "total_pnl": st.column_config.NumberColumn("总收益", format="%.2f"),
            "当日收益": st.column_config.NumberColumn("当日收益(推算)", format="%.2f"),
            "当日收益率": st.column_config.NumberColumn("当日收益率(%)", format="%.2f"),
        },
        **STRETCH,
    )

with st.expander("月度统计"):
    m2 = d.copy()
    m2["月份"] = m2["date"].dt.strftime("%Y-%m")
    monthly = (
        m2.groupby("月份")["当日收益"].sum().reset_index()
        .sort_values("月份", ascending=False)
    )
    monthly.columns = ["月份", "当月总收益"]
    monthly["当月总收益"] = monthly["当月总收益"].map("{:,.2f}".format)
    st.dataframe(monthly, hide_index=True, **STRETCH)

st.caption(
    "每日收益=总收益逐次差值；每平台首条记录把总收益整体计为首期盈亏（首日/首月/首年都体现） ｜ "
    "遇申赎当日会失真属预期 ｜ "
    "走势图=自建仓累计收益率，分母固定=第一天倒推的初始本金（第一天市值−第一天总收益） ｜ "
    "叠加指数同起点（建仓日）累计，跑赢/跑输按同一基期对比 ｜ "
    "日历与当日收益率=当期口径（当期赚的钱÷期初市值），市值漏填的日子显示「—」 ｜ "
    "漏录平台时市值/总收益沿用其最近一次值 ｜ "
    "指数数据来自东方财富公开接口，仅供参考"
)
