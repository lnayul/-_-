import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import streamlit as st
import requests


# =========================================================
# 기본 설정
# =========================================================

st.set_page_config(
    page_title="우리 학교와 주변 학교 간의 메뉴 중복률은 얼마나 될까?",
    page_icon="🍱",
    layout="wide"
)

SCHOOL_API = "https://open.neis.go.kr/hub/schoolInfo"
MEAL_API = "https://open.neis.go.kr/hub/mealServiceDietInfo"

KST = ZoneInfo("Asia/Seoul")
TODAY = datetime.now(KST).date()

# 송탄고등학교 고정 정보
OUR_SCHOOL = {
    "name": "송탄고등학교",
    "region": "경기도",
    "office_code": "J10",
    "school_code": "7530480"
}


# =========================================================
# 학교 정보 API
# =========================================================

@st.cache_data(ttl=600)
def search_schools(keyword):
    """학교 이름의 일부를 이용해 학교를 검색한다."""

    params = {
        "Type": "json",
        "SCHUL_NM": keyword
    }

    try:
        response = requests.get(
            SCHOOL_API,
            params=params,
            timeout=10
        )
        response.raise_for_status()
        data = response.json()

    except requests.RequestException:
        return None, "학교 정보를 불러오는 중 네트워크 오류가 발생했습니다."

    except ValueError:
        return None, "학교 정보 API의 응답을 읽을 수 없습니다."

    # 검색 결과 없음
    try:
        result = data["schoolInfo"][0]["head"][1]["RESULT"]

        if result.get("CODE") == "INFO-200":
            return [], None

    except (KeyError, IndexError, TypeError):
        pass

    try:
        rows = data["schoolInfo"][1]["row"]
    except (KeyError, IndexError, TypeError):
        return [], None

    schools = []

    for row in rows:
        schools.append({
            "name": row.get("SCHUL_NM", ""),
            "region": row.get("LCTN_SC_NM", ""),
            "office_code": row.get("ATPT_OFCDC_SC_CODE", ""),
            "school_code": row.get("SD_SCHUL_CODE", "")
        })

    return schools, None


# =========================================================
# 급식 API
# =========================================================

@st.cache_data(ttl=600)
def get_meals(
    office_code,
    school_code,
    start_date,
    end_date
):
    """선택한 학교의 기간 내 중식 정보를 가져온다."""

    start_ymd = start_date.strftime("%Y%m%d")
    end_ymd = end_date.strftime("%Y%m%d")

    params = {
        "Type": "json",
        "ATPT_OFCDC_SC_CODE": office_code,
        "SD_SCHUL_CODE": school_code,
        "MMEAL_SC_CODE": "2",
        "MLSV_FROM_YMD": start_ymd,
        "MLSV_TO_YMD": end_ymd,
        "pSize": "1000",
        "pIndex": "1"
    }

    try:
        response = requests.get(
            MEAL_API,
            params=params,
            timeout=10
        )
        response.raise_for_status()
        data = response.json()

    except requests.RequestException:
        return None, "급식 정보를 불러오는 중 네트워크 오류가 발생했습니다."

    except ValueError:
        return None, "급식 API의 응답을 읽을 수 없습니다."

    # 데이터가 없는 경우
    try:
        result = data["mealServiceDietInfo"][0]["head"][1]["RESULT"]

        if result.get("CODE") == "INFO-200":
            return [], None

    except (KeyError, IndexError, TypeError):
        pass

    try:
        rows = data["mealServiceDietInfo"][1]["row"]
    except (KeyError, IndexError, TypeError):
        return [], None

    return rows, None


# =========================================================
# 메뉴 전처리
# =========================================================

def clean_menu_name(menu):
    """
    메뉴 이름에서 알레르기 번호를 제거한다.

    예:
    김치찌개(5.6.9) → 김치찌개
    계란찜(1) → 계란찜
    """

    if not menu:
        return ""

    # 알레르기 번호가 들어 있는 괄호 제거
    menu = re.sub(
        r"\(\s*\d+(?:\s*[.,]\s*\d+)*\s*\)",
        "",
        menu
    )

    # 공백 정리
    menu = re.sub(r"\s+", " ", menu).strip()

    return menu


def split_menu(menu_text):
    """<br/>로 연결된 급식 메뉴를 각각 분리한다."""

    if not menu_text:
        return []

    text = re.sub(
        r"<br\s*/?>",
        "\n",
        menu_text,
        flags=re.IGNORECASE
    )

    # 혹시 남아 있는 HTML 태그 제거
    text = re.sub(r"<[^>]+>", "", text)

    menus = []

    for item in text.split("\n"):
        item = item.strip()

        if item:
            menus.append(item)

    return menus


def normalized_menu_set(menu_text):
    """
    중복률 계산용 메뉴 집합을 만든다.

    알레르기 번호를 제거하고 같은 메뉴는 한 번만 계산한다.
    """

    menus = split_menu(menu_text)

    result = set()

    for menu in menus:
        cleaned = clean_menu_name(menu)

        if cleaned:
            result.add(cleaned)

    return result


# =========================================================
# 중복률 계산
# =========================================================

def calculate_overlap(our_menus, other_menus):
    """
    두 학교의 메뉴 중복률을 계산한다.

    중복률 =
    공통 메뉴 수 / 두 학교의 전체 메뉴 종류 수 × 100

    여기서 전체 메뉴 종류 수는 두 학교 메뉴의 합집합이다.
    """

    our_set = normalized_menu_set(our_menus)
    other_set = normalized_menu_set(other_menus)

    common = our_set & other_set
    union = our_set | other_set

    if len(union) == 0:
        return 0.0, 0, 0, our_set, other_set

    rate = len(common) / len(union) * 100

    return (
        rate,
        len(common),
        len(union),
        our_set,
        other_set
    )


# =========================================================
# 급식 데이터를 날짜별로 정리
# =========================================================

def meal_dict(rows):
    """API의 row 목록을 날짜별 딕셔너리로 변환한다."""

    result = {}

    for row in rows:
        ymd = row.get("MLSV_YMD")

        if ymd:
            result[ymd] = {
                "menu": row.get("DDISH_NM", ""),
                "calorie": row.get("CAL_INFO", ""),
                "origin": row.get("ORPLC_INFO", "")
            }

    return result


# =========================================================
# 제목
# =========================================================

st.title("🍱 우리 학교와 주변 학교 간의 메뉴 중복률은 얼마나 될까?")

st.info(
    "탐구 질문: 우리 학교와 주변 학교 간의 메뉴 중복률은 얼마나 될까?"
)

st.markdown(
    """
송탄고등학교의 중식 메뉴와 주변 학교의 중식 메뉴를 비교하여
**같은 날짜에 제공된 메뉴가 얼마나 겹치는지** 데이터로 확인합니다.
"""
)


# =========================================================
# 학교 선택
# =========================================================

st.subheader("🏫 비교할 학교 선택")

st.markdown(
    f"**우리 학교:** {OUR_SCHOOL['name']} ({OUR_SCHOOL['region']})"
)

school_keyword = st.text_input(
    "주변 학교 이름 검색",
    placeholder="예: ○○고등학교"
)

if "school_results" not in st.session_state:
    st.session_state.school_results = []

if st.button("🔍 주변 학교 찾기"):

    if not school_keyword.strip():
        st.warning("검색할 학교 이름을 입력해주세요.")

    else:
        results, error = search_schools(school_keyword.strip())

        if error:
            st.error(error)

        elif not results:
            st.warning(
                f"'{school_keyword}'에 해당하는 학교를 찾지 못했습니다."
            )

        else:
            # 송탄고등학교는 주변 학교 선택 목록에서 제외
            results = [
                school for school in results
                if school["school_code"] != OUR_SCHOOL["school_code"]
            ]

            st.session_state.school_results = results


if st.session_state.school_results:

    options = [
        f"{school['name']} · {school['region']}"
        for school in st.session_state.school_results
    ]

    selected_indices = st.multiselect(
        "비교할 주변 학교를 선택하세요. 여러 학교를 선택할 수 있습니다.",
        range(len(st.session_state.school_results)),
        format_func=lambda i: options[i]
    )

    selected_schools = [
        st.session_state.school_results[i]
        for i in selected_indices
    ]

else:
    selected_schools = []


# =========================================================
# 날짜 선택
# =========================================================

st.subheader("📅 비교 기간")

default_start = TODAY - timedelta(days=4)
default_end = TODAY

date_col1, date_col2 = st.columns(2)

with date_col1:
    start_date = st.date_input(
        "시작일",
        value=default_start
    )

with date_col2:
    end_date = st.date_input(
        "끝 날짜",
        value=default_end
    )


if start_date > end_date:
    st.error("시작일은 끝 날짜보다 빠르거나 같아야 합니다.")
    st.stop()

# 너무 긴 기간을 방지
if (end_date - start_date).days > 14:
    st.warning(
        "조회 기간은 최대 15일까지만 선택할 수 있습니다. "
        "나이스 API의 안정적인 조회를 위해 기간을 짧게 설정했습니다."
    )
    st.stop()


# =========================================================
# 조회 버튼
# =========================================================

st.divider()

if st.button(
    "🍚 급식 데이터 조회",
    type="primary",
    use_container_width=True
):

    if not selected_schools:
        st.warning("비교할 주변 학교를 먼저 선택해주세요.")

    else:

        with st.spinner("급식 데이터를 불러오는 중입니다..."):

            our_rows, our_error = get_meals(
                OUR_SCHOOL["office_code"],
                OUR_SCHOOL["school_code"],
                start_date,
                end_date
            )

            if our_error:
                st.error(our_error)
                st.stop()

            if our_rows is None:
                st.warning("송탄고등학교의 급식 정보를 가져오지 못했습니다.")
                st.stop()

            our_meals = meal_dict(our_rows)

            # 주변 학교 급식 가져오기
            all_school_data = {
                OUR_SCHOOL["name"]: {
                    "school": OUR_SCHOOL,
                    "meals": our_meals
                }
            }

            failed_schools = []

            for school in selected_schools:

                rows, error = get_meals(
                    school["office_code"],
                    school["school_code"],
                    start_date,
                    end_date
                )

                if error:
                    failed_schools.append(school["name"])
                    continue

                if rows is None:
                    failed_schools.append(school["name"])
                    continue

                all_school_data[school["name"]] = {
                    "school": school,
                    "meals": meal_dict(rows)
                }


        # =================================================
        # 결과 데이터 생성
        # =================================================

        comparison_rows = []
        detail_rows = []

        for school in selected_schools:

            school_name = school["name"]

            if school_name not in all_school_data:
                continue

            other_meals = all_school_data[school_name]["meals"]

            # 송탄고와 이 학교 모두 급식이 있는 날짜만 비교
            common_dates = sorted(
                set(our_meals.keys()) &
                set(other_meals.keys())
            )

            for ymd in common_dates:

                our_menu = our_meals[ymd]["menu"]
                other_menu = other_meals[ymd]["menu"]

                rate, common_count, union_count, our_set, other_set = (
                    calculate_overlap(
                        our_menu,
                        other_menu
                    )
                )

                comparison_rows.append({
                    "날짜": ymd,
                    "학교": school_name,
                    "중복률": rate,
                    "공통 메뉴 수": common_count,
                    "전체 메뉴 종류 수": union_count
                })

                detail_rows.append({
                    "날짜": ymd,
                    "학교": school_name,
                    "송탄고 메뉴": our_menu,
                    "주변 학교 메뉴": other_menu,
                    "송탄고 칼로리": our_meals[ymd]["calorie"],
                    "주변 학교 칼로리": other_meals[ymd]["calorie"],
                    "공통 메뉴": sorted(our_set & other_set)
                })


        # =================================================
        # 세션에 결과 저장
        # =================================================

        st.session_state.comparison_rows = comparison_rows
        st.session_state.detail_rows = detail_rows
        st.session_state.selected_schools = selected_schools
        st.session_state.failed_schools = failed_schools
        st.session_state.all_school_data = all_school_data


# =========================================================
# 결과 표시
# =========================================================

if "comparison_rows" in st.session_state:

    comparison_rows = st.session_state.comparison_rows
    detail_rows = st.session_state.detail_rows
    selected_schools = st.session_state.selected_schools

    if st.session_state.failed_schools:
        st.warning(
            "다음 학교의 급식 정보를 불러오지 못했습니다: "
            + ", ".join(st.session_state.failed_schools)
        )

    if not comparison_rows:

        st.info(
            "선택한 기간에는 송탄고등학교와 주변 학교가 "
            "모두 급식을 제공한 날짜가 없습니다."
        )

        st.markdown(
            "**급식이 없는 날은 오류가 아니라 비교 대상에서 제외됩니다.**"
        )

    else:

        df = pd.DataFrame(comparison_rows)

        # =============================================
        # 요약 카드
        # =============================================

        st.divider()
        st.subheader("📊 비교 결과 요약")

        comparison_dates = df["날짜"].nunique()
        school_count = len(selected_schools)

        # 기간 내 모든 메뉴 종류
        all_menu_set = set()

        for detail in detail_rows:
            all_menu_set.update(
                normalized_menu_set(detail["송탄고 메뉴"])
            )
            all_menu_set.update(
                normalized_menu_set(detail["주변 학교 메뉴"])
            )

        total_menu_count = len(all_menu_set)

        average_rate = df["중복률"].mean()

        card1, card2, card3, card4 = st.columns(4)

        with card1:
            st.metric(
                "비교한 날짜 수",
                f"{comparison_dates}일"
            )

        with card2:
            st.metric(
                "비교한 주변 학교",
                f"{school_count}곳"
            )

        with card3:
            st.metric(
                "전체 메뉴 종류",
                f"{total_menu_count}개"
            )

        with card4:
            st.metric(
                "평균 메뉴 중복률",
                f"{average_rate:.1f}%"
            )


        # =============================================
        # 그래프 1
        # =============================================

        st.divider()
        st.subheader("📈 학교별 평균 메뉴 중복률")

        school_average = (
            df.groupby("학교", as_index=False)["중복률"]
            .mean()
            .sort_values("중복률", ascending=False)
        )

        fig1 = px.bar(
            school_average,
            x="학교",
            y="중복률",
            text="중복률",
            labels={
                "학교": "주변 학교",
                "중복률": "평균 메뉴 중복률 (%)"
            }
        )

        fig1.update_traces(
            texttemplate="%{text:.1f}%",
            textposition="outside"
        )

        fig1.update_layout(
            yaxis_range=[
                0,
                max(100, school_average["중복률"].max() + 10)
            ]
        )

        st.plotly_chart(
            fig1,
            use_container_width=True
        )


        # =============================================
        # 그래프 2
        # =============================================

        st.subheader("📅 날짜별 메뉴 중복률 변화")

        df["날짜표시"] = pd.to_datetime(
            df["날짜"],
            format="%Y%m%d"
        )

        fig2 = px.line(
            df,
            x="날짜표시",
            y="중복률",
            color="학교",
            markers=True,
            labels={
                "날짜표시": "날짜",
                "중복률": "메뉴 중복률 (%)",
                "학교": "주변 학교"
            }
        )

        fig2.update_yaxes(range=[0, 100])

        st.plotly_chart(
            fig2,
            use_container_width=True
        )


        # =============================================
        # 그래프 3
        # =============================================

        st.subheader("🔎 학교별 공통 메뉴와 전체 메뉴 비교")

        graph3 = (
            df.groupby("학교", as_index=False)[
                ["공통 메뉴 수", "전체 메뉴 종류 수"]
            ]
            .mean()
        )

        graph3_long = graph3.melt(
            id_vars="학교",
            value_vars=[
                "공통 메뉴 수",
                "전체 메뉴 종류 수"
            ],
            var_name="구분",
            value_name="메뉴 수"
        )

        fig3 = px.bar(
            graph3_long,
            x="학교",
            y="메뉴 수",
            color="구분",
            barmode="group",
            labels={
                "학교": "주변 학교",
                "메뉴 수": "평균 메뉴 수",
                "구분": "메뉴 구분"
            }
        )

        st.plotly_chart(
            fig3,
            use_container_width=True
        )


        # =============================================
        # 메뉴 비교 카드
        # =============================================

        st.divider()
        st.subheader("🍽️ 날짜별 메뉴 비교")

        for detail in detail_rows:

            raw_date = detail["날짜"]

            formatted_date = datetime.strptime(
                raw_date,
                "%Y%m%d"
            ).strftime("%Y년 %m월 %d일")

            st.markdown(f"### 📅 {formatted_date}")

            left, right = st.columns(2)

            # 송탄고
            with left:

                st.markdown(
                    f"#### 🏫 {OUR_SCHOOL['name']}"
                )

                calorie = detail["송탄고 칼로리"]

                if calorie:
                    st.caption(f"🔥 {calorie}")

                our_menus = split_menu(
                    detail["송탄고 메뉴"]
                )

                for menu in our_menus:

                    clean = clean_menu_name(menu)

                    if clean in detail["공통 메뉴"]:
                        st.success(
                            f"✓ {menu}"
                        )
                    else:
                        st.info(menu)

            # 주변 학교
            with right:

                st.markdown(
                    f"#### 🏫 {detail['학교']}"
                )

                calorie = detail["주변 학교 칼로리"]

                if calorie:
                    st.caption(f"🔥 {calorie}")

                other_menus = split_menu(
                    detail["주변 학교 메뉴"]
                )

                for menu in other_menus:

                    clean = clean_menu_name(menu)

                    if clean in detail["공통 메뉴"]:
                        st.success(
                            f"✓ {menu}"
                        )
                    else:
                        st.info(menu)

            if detail["공통 메뉴"]:
                st.caption(
                    "✓ 표시된 메뉴는 두 학교에 공통으로 제공된 메뉴입니다."
                )
            else:
                st.caption(
                    "공통으로 제공된 메뉴가 없습니다."
                )

            st.divider()


        # =============================================
        # 결과 해석 작성
        # =============================================

        st.subheader("📝 알 수 있는 점")

        st.text_area(
            "탐구 결과를 직접 작성해 보세요.",
            placeholder=(
                "예: 송탄고등학교와 주변 학교의 급식을 비교한 결과 "
                "학교마다 공통으로 제공되는 메뉴가 있었지만, "
                "날짜에 따라 중복률에는 차이가 나타났다. "
                "이를 통해 학교 급식 메뉴가 완전히 동일하지는 않지만 "
                "일부 메뉴가 반복적으로 함께 제공된다는 점을 확인할 수 있었다."
            ),
            height=180,
            key="result_interpretation"
        )


        # =============================================
        # 계산 방법 안내
        # =============================================

        with st.expander("📌 메뉴 중복률은 어떻게 계산했나요?"):

            st.markdown(
                """
**메뉴 중복률 = 공통 메뉴 수 ÷ 두 학교의 전체 메뉴 종류 수 × 100**

예를 들어,

- 송탄고 메뉴: 김치찌개, 계란찜, 멸치볶음, 깍두기
- 주변 학교 메뉴: 김치찌개, 계란찜, 미역국, 배추김치

라면,

- 공통 메뉴 = 2개
- 전체 메뉴 종류 = 6개
- 중복률 = 2 ÷ 6 × 100 = **33.3%**

메뉴 뒤의 알레르기 번호는 비교할 때 제외합니다.

예를 들어 `김치찌개(5.6.9)`와 `김치찌개(5.6)`은
둘 다 **김치찌개**로 처리합니다.
"""
            )
