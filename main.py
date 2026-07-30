import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


# --------------------------------------------------
# 1. 화면 설정
# --------------------------------------------------
st.set_page_config(
    page_title="영화 흥행 데이터 분석기",
    page_icon="🎬",
    layout="wide"
)

st.title("🎬 영화 흥행 데이터 분석기")
st.write(
    "영화진흥위원회 일별 박스오피스 데이터를 수집하고, "
    "관객 점유율과 상영 효율, 최근 흥행 추이를 분석합니다."
)


# --------------------------------------------------
# 2. API 인증키
# --------------------------------------------------
try:
    KOBIS_KEY = st.secrets["KOBIS_KEY"]
except KeyError:
    st.error("Streamlit Secrets에 KOBIS_KEY가 등록되어 있지 않습니다.")
    st.stop()


# --------------------------------------------------
# 3. 날짜 선택
# --------------------------------------------------
korea_today = datetime.now(ZoneInfo("Asia/Seoul")).date()
latest_date = korea_today - timedelta(days=1)

selected_date = st.date_input(
    "📅 분석할 날짜를 선택하세요",
    value=latest_date,
    max_value=latest_date,
    help="오늘 자료는 아직 집계 전일 수 있어 어제까지만 선택할 수 있습니다."
)

target_dt = selected_date.strftime("%Y%m%d")

st.caption(
    f"분석 기준일: {selected_date.strftime('%Y년 %m월 %d일')}"
)


# --------------------------------------------------
# 4. KOBIS 데이터 가져오기
# --------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def get_daily_boxoffice(api_key, target_date):
    url = (
        "https://www.kobis.or.kr/kobisopenapi/webservice/rest/"
        "boxoffice/searchDailyBoxOfficeList.json"
    )

    response = requests.get(
        url,
        params={
            "key": api_key,
            "targetDt": target_date
        },
        timeout=10
    )

    response.raise_for_status()
    data = response.json()

    if "faultInfo" in data:
        message = data["faultInfo"].get(
            "message",
            "KOBIS API 요청에 실패했습니다."
        )
        raise ValueError(message)

    return (
        data
        .get("boxOfficeResult", {})
        .get("dailyBoxOfficeList", [])
    )


# --------------------------------------------------
# 5. 원자료를 분석 가능한 형태로 변환
# --------------------------------------------------
def process_boxoffice(box_list):
    if not box_list:
        return pd.DataFrame()

    df = pd.DataFrame(box_list)

    numeric_columns = [
        "rank",
        "rankInten",
        "salesAmt",
        "salesAcc",
        "audiCnt",
        "audiAcc",
        "scrnCnt",
        "showCnt"
    ]

    for column in numeric_columns:
        if column not in df.columns:
            df[column] = 0

        df[column] = (
            pd.to_numeric(df[column], errors="coerce")
            .fillna(0)
        )

    df[numeric_columns] = df[numeric_columns].astype(int)

    # 순위순 정렬
    df = df.sort_values("rank").reset_index(drop=True)

    return df


# --------------------------------------------------
# 6. 선택한 날짜 데이터 불러오기
# --------------------------------------------------
with st.spinner("박스오피스 데이터를 불러오는 중입니다..."):
    try:
        box_list = get_daily_boxoffice(
            KOBIS_KEY,
            target_dt
        )

    except requests.exceptions.Timeout:
        st.error("영화진흥위원회 서버의 응답이 늦어지고 있습니다.")
        st.stop()

    except requests.exceptions.RequestException as error:
        st.error(f"데이터 요청 중 오류가 발생했습니다: {error}")
        st.stop()

    except ValueError as error:
        st.error(f"KOBIS API 오류: {error}")
        st.stop()


if not box_list:
    st.warning("그날은 아직 집계 전입니다.")
    st.stop()


df = process_boxoffice(box_list)


# --------------------------------------------------
# 7. 새로운 분석 지표 계산
# --------------------------------------------------

# TOP 10 전체 관객수
total_audience = df["audiCnt"].sum()

# 영화별 관객 점유율
if total_audience > 0:
    df["audienceShare"] = (
        df["audiCnt"] / total_audience * 100
    )
else:
    df["audienceShare"] = 0

# 스크린당 관객수
df["audiencePerScreen"] = (
    df["audiCnt"]
    .div(df["scrnCnt"].replace(0, pd.NA))
    .fillna(0)
)

# 상영 1회당 관객수
df["audiencePerShow"] = (
    df["audiCnt"]
    .div(df["showCnt"].replace(0, pd.NA))
    .fillna(0)
)

# 매출 점유율
total_sales = df["salesAmt"].sum()

if total_sales > 0:
    df["salesShare"] = (
        df["salesAmt"] / total_sales * 100
    )
else:
    df["salesShare"] = 0


# --------------------------------------------------
# 8. 순위 변동 표시
# --------------------------------------------------
def make_rank_change(row):
    if row.get("rankOldAndNew", "") == "NEW":
        return "🆕 신규"

    rank_change = row["rankInten"]

    if rank_change > 0:
        return f"🔺 {rank_change}계단 상승"

    if rank_change < 0:
        return f"🔵 ▼ {abs(rank_change)}계단 하락"

    return "－ 변동 없음"


df["rankChangeText"] = df.apply(
    make_rank_change,
    axis=1
)


# --------------------------------------------------
# 9. 누적 관객 100만 명 영화 표시
# --------------------------------------------------
def make_movie_name(row):
    movie_name = row["movieNm"]

    if row["audiAcc"] > 1_000_000:
        return f"{movie_name} 🏆"

    return movie_name


df["movieNameDisplay"] = df.apply(
    make_movie_name,
    axis=1
)


# --------------------------------------------------
# 10. 핵심 영화 찾기
# --------------------------------------------------

# 선택 날짜 1위
top_movie = df.iloc[0]

# 스크린당 관객 효율 1위
screen_efficiency_movie = (
    df
    .sort_values("audiencePerScreen", ascending=False)
    .iloc[0]
)

# 회차당 관객 효율 1위
show_efficiency_movie = (
    df
    .sort_values("audiencePerShow", ascending=False)
    .iloc[0]
)

# TOP 3 관객 집중도
top3_share = df.head(3)["audienceShare"].sum()


# --------------------------------------------------
# 11. 상단 분석 카드
# --------------------------------------------------
st.subheader("🏆 선택 날짜 핵심 분석")

card1, card2, card3, card4 = st.columns(4)

card1.metric(
    "박스오피스 1위",
    top_movie["movieNm"]
)

card2.metric(
    "1위 영화 관객수",
    f"{top_movie['audiCnt']:,}명"
)

card3.metric(
    "1위 영화 점유율",
    f"{top_movie['audienceShare']:.1f}%"
)

card4.metric(
    "TOP 3 관객 집중도",
    f"{top3_share:.1f}%"
)


# --------------------------------------------------
# 12. 자동 분석 문장 생성
# --------------------------------------------------
st.subheader("📝 데이터로 만든 분석 결과")

st.info(
    f"{selected_date.strftime('%Y년 %m월 %d일')} 박스오피스 1위는 "
    f"「{top_movie['movieNm']}」입니다. "
    f"이날 TOP 10 영화의 전체 관객수는 {total_audience:,}명이며, "
    f"1위 영화는 그중 {top_movie['audienceShare']:.1f}%를 차지했습니다. "
    f"상위 3개 영화의 관객 비중은 총 {top3_share:.1f}%입니다."
)

st.success(
    f"스크린당 관객수가 가장 높은 영화는 "
    f"「{screen_efficiency_movie['movieNm']}」으로, "
    f"스크린 1개당 약 "
    f"{screen_efficiency_movie['audiencePerScreen']:.1f}명을 동원했습니다. "
    f"상영 1회당 관객수가 가장 높은 영화는 "
    f"「{show_efficiency_movie['movieNm']}」으로, "
    f"회차당 약 {show_efficiency_movie['audiencePerShow']:.1f}명입니다."
)


# --------------------------------------------------
# 13. 가공된 데이터 표
# --------------------------------------------------
st.subheader("📋 가공된 박스오피스 데이터")

analysis_table = df[
    [
        "rank",
        "rankChangeText",
        "movieNameDisplay",
        "audiCnt",
        "audienceShare",
        "scrnCnt",
        "audiencePerScreen",
        "showCnt",
        "audiencePerShow",
        "audiAcc"
    ]
].copy()

analysis_table.columns = [
    "순위",
    "순위 변동",
    "영화명",
    "당일 관객수",
    "관객 점유율",
    "스크린수",
    "스크린당 관객수",
    "상영횟수",
    "회차당 관객수",
    "누적관객"
]

display_table = analysis_table.copy()

display_table["당일 관객수"] = (
    display_table["당일 관객수"]
    .map(lambda value: f"{value:,}명")
)

display_table["관객 점유율"] = (
    display_table["관객 점유율"]
    .map(lambda value: f"{value:.1f}%")
)

display_table["스크린수"] = (
    display_table["스크린수"]
    .map(lambda value: f"{value:,}개")
)

display_table["스크린당 관객수"] = (
    display_table["스크린당 관객수"]
    .map(lambda value: f"{value:.1f}명")
)

display_table["상영횟수"] = (
    display_table["상영횟수"]
    .map(lambda value: f"{value:,}회")
)

display_table["회차당 관객수"] = (
    display_table["회차당 관객수"]
    .map(lambda value: f"{value:.1f}명")
)

display_table["누적관객"] = (
    display_table["누적관객"]
    .map(lambda value: f"{value:,}명")
)

st.dataframe(
    display_table,
    hide_index=True,
    use_container_width=True
)


# --------------------------------------------------
# 14. 선택 날짜 영화별 관객수 그래프
# --------------------------------------------------
st.subheader("📊 영화별 당일 관객수 비교")

audience_chart = (
    df[["movieNm", "audiCnt"]]
    .sort_values("audiCnt", ascending=False)
    .set_index("movieNm")
)

st.bar_chart(
    audience_chart,
    y="audiCnt",
    x_label="영화명",
    y_label="관객수"
)


# --------------------------------------------------
# 15. 효율 그래프
# --------------------------------------------------
chart_col1, chart_col2 = st.columns(2)

with chart_col1:
    st.subheader("🎟️ 스크린당 관객수")

    screen_chart = (
        df[["movieNm", "audiencePerScreen"]]
        .sort_values(
            "audiencePerScreen",
            ascending=False
        )
        .set_index("movieNm")
    )

    st.bar_chart(
        screen_chart,
        y="audiencePerScreen",
        x_label="영화명",
        y_label="스크린당 관객수"
    )

with chart_col2:
    st.subheader("👥 상영 1회당 관객수")

    show_chart = (
        df[["movieNm", "audiencePerShow"]]
        .sort_values(
            "audiencePerShow",
            ascending=False
        )
        .set_index("movieNm")
    )

    st.bar_chart(
        show_chart,
        y="audiencePerShow",
        x_label="영화명",
        y_label="회차당 관객수"
    )


# --------------------------------------------------
# 16. 선택 날짜 1위 영화의 최근 7일 추이
# --------------------------------------------------
st.subheader(
    f"📈 「{top_movie['movieNm']}」 최근 7일 흥행 추이"
)

trend_records = []
daily_winner_records = []

with st.spinner("최근 7일 데이터를 분석하는 중입니다..."):
    for days_ago in range(6, -1, -1):
        search_date = selected_date - timedelta(days=days_ago)
        search_dt = search_date.strftime("%Y%m%d")

        try:
            daily_list = get_daily_boxoffice(
                KOBIS_KEY,
                search_dt
            )
        except Exception:
            continue

        if not daily_list:
            continue

        daily_df = process_boxoffice(daily_list)

        if daily_df.empty:
            continue

        # 날짜별 1위 영화
        daily_top = daily_df.iloc[0]

        daily_winner_records.append(
            {
                "날짜": search_date,
                "1위 영화": daily_top["movieNm"],
                "1위 관객수": daily_top["audiCnt"]
            }
        )

        # 선택 날짜의 1위 영화가 그날 TOP 10에 있었는지 확인
        same_movie = daily_df[
            daily_df["movieCd"] == top_movie["movieCd"]
        ]

        if not same_movie.empty:
            movie_row = same_movie.iloc[0]

            trend_records.append(
                {
                    "날짜": search_date,
                    "관객수": movie_row["audiCnt"],
                    "순위": movie_row["rank"]
                }
            )


trend_df = pd.DataFrame(trend_records)

if trend_df.empty:
    st.warning("최근 7일 동안 해당 영화의 자료를 찾지 못했습니다.")

else:
    trend_df = trend_df.sort_values("날짜")

    st.line_chart(
        trend_df.set_index("날짜")[["관객수"]],
        y_label="관객수"
    )

    st.caption(
        "해당 영화가 일별 박스오피스 TOP 10에 포함된 날짜만 "
        "그래프에 표시됩니다."
    )

    if len(trend_df) >= 2:
        first_audience = trend_df.iloc[0]["관객수"]
        last_audience = trend_df.iloc[-1]["관객수"]
        audience_difference = last_audience - first_audience

        if first_audience > 0:
            change_rate = (
                audience_difference / first_audience * 100
            )
        else:
            change_rate = 0

        if audience_difference > 0:
            trend_word = "증가"
        elif audience_difference < 0:
            trend_word = "감소"
        else:
            trend_word = "변동 없음"

        st.write(
            f"그래프에서 확인 가능한 첫날보다 관객수가 "
            f"**{abs(audience_difference):,}명 {trend_word}**했으며, "
            f"변화율은 **{change_rate:+.1f}%**입니다."
        )


# --------------------------------------------------
# 17. 최근 7일 날짜별 1위 영화
# --------------------------------------------------
st.subheader("🥇 최근 7일 날짜별 박스오피스 1위")

winner_df = pd.DataFrame(daily_winner_records)

if not winner_df.empty:
    winner_df = winner_df.sort_values("날짜")

    winner_display = winner_df.copy()
    winner_display["날짜"] = (
        winner_display["날짜"]
        .map(lambda value: value.strftime("%m월 %d일"))
    )
    winner_display["1위 관객수"] = (
        winner_display["1위 관객수"]
        .map(lambda value: f"{value:,}명")
    )

    st.dataframe(
        winner_display,
        hide_index=True,
        use_container_width=True
    )


# --------------------------------------------------
# 18. 가공 결과 내려받기
# --------------------------------------------------
st.subheader("💾 가공 데이터 저장")

download_df = analysis_table.copy()

csv_data = download_df.to_csv(
    index=False
).encode("utf-8-sig")

st.download_button(
    label="가공한 박스오피스 데이터 CSV 내려받기",
    data=csv_data,
    file_name=(
        f"boxoffice_analysis_"
        f"{selected_date.strftime('%Y%m%d')}.csv"
    ),
    mime="text/csv"
)
