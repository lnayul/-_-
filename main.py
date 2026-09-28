import re
from datetime import date
from zoneinfo import ZoneInfo

import requests
import streamlit as st


# -----------------------------
# 기본 설정
# -----------------------------
st.set_page_config(
    page_title="학교 급식 찾아보기",
    page_icon="🍱",
    layout="centered"
)

SCHOOL_API = "https://open.neis.go.kr/hub/schoolInfo"
MEAL_API = "https://open.neis.go.kr/hub/mealServiceDietInfo"

KST = ZoneInfo("Asia/Seoul")
TODAY_KST = datetime_today = date.today()
# 서버의 시간이 한국 시간이 아닐 수 있으므로
# UTC 기준 현재 시각을 한국 시간으로 변환
from datetime import datetime
TODAY_KST = datetime.now(ZoneInfo("Asia/Seoul")).date()


# -----------------------------
# 학교 이름 보정
# -----------------------------
def expand_school_name(name):
    """
    줄임말을 정식 명칭 형태로 한 번 더 검색한다.

    예:
    수도여고 → 수도여자고등학교
    서울고 → 서울고등학교
    """

    name = name.strip()

    if name.endswith("여고"):
        return name[:-2] + "여자고등학교"

    if name.endswith("고"):
        return name[:-1] + "고등학교"

    return None


# -----------------------------
# 학교 검색
# -----------------------------
@st.cache_data(ttl=600)
def search_schools(school_name):
    params = {
        "Type": "json",
        "SCHUL_NM": school_name
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
        return None, "네트워크 오류로 학교 정보를 가져오지 못했습니다."

    except ValueError:
        return None, "학교 정보 API의 응답을 읽을 수 없습니다."

    # 조회 결과가 없는 경우
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
            "office_code": row.get("ATPT_OFCDC_SC_CODE", ""),
            "school_code": row.get("SD_SCHUL_CODE", ""),
            "region": row.get("LCTN_SC_NM", "")
        })

    return schools, None


# -----------------------------
# 급식 조회
# -----------------------------
@st.cache_data(ttl=600)
def get_lunch(office_code, school_code, selected_date):
    ymd = selected_date.strftime("%Y%m%d")

    params = {
        "Type": "json",
        "ATPT_OFCDC_SC_CODE": office_code,
        "SD_SCHUL_CODE": school_code,
        "MMEAL_SC_CODE": "2",
        "MLSV_FROM_YMD": ymd,
        "MLSV_TO_YMD": ymd,
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
        return None, "네트워크 오류로 급식 정보를 가져오지 못했습니다."

    except ValueError:
        return None, "급식 API의 응답을 읽을 수 없습니다."

    # 급식이 없는 경우
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


# -----------------------------
# 화면
# -----------------------------
st.title("🍱 학교 급식 찾아보기")
st.write("학교 이름을 검색하고 날짜를 선택하면 해당 학교의 중식 메뉴를 확인할 수 있습니다.")


# -----------------------------
# 학교 검색 영역
# -----------------------------
st.subheader("1. 학교 선택")

school_input = st.text_input(
    "학교 이름",
    placeholder="예: 수도여고, 서울고, 송탄고등학교"
)

search_button = st.button("🔍 학교 찾기", use_container_width=True)


if search_button:

    if not school_input.strip():
        st.warning("학교 이름을 입력해주세요.")

    else:
        # 먼저 사용자가 입력한 이름 그대로 검색
        schools, error = search_schools(school_input.strip())

        if error:
            st.error(error)

        elif schools:
            st.session_state["schools"] = schools
            st.session_state["searched_name"] = school_input.strip()
            st.session_state["expanded_search"] = False

        else:
            # 못 찾았을 경우 줄임말을 풀어서 한 번 더 검색
            expanded_name = expand_school_name(school_input.strip())

            if expanded_name and expanded_name != school_input.strip():

                schools, error = search_schools(expanded_name)

                if error:
                    st.error(error)

                elif schools:
                    st.session_state["schools"] = schools
                    st.session_state["searched_name"] = expanded_name
                    st.session_state["expanded_search"] = True

                else:
                    st.session_state["schools"] = []
                    st.session_state["searched_name"] = school_input.strip()
                    st.session_state["expanded_search"] = False

            else:
                st.session_state["schools"] = []
                st.session_state["searched_name"] = school_input.strip()
                st.session_state["expanded_search"] = False


# -----------------------------
# 검색 결과 표시
# -----------------------------
if "schools" in st.session_state:

    schools = st.session_state["schools"]

    if schools:

        if st.session_state.get("expanded_search"):
            st.info(
                f"'{school_input}'으로 찾지 못해 "
                f"'{st.session_state['searched_name']}'로 다시 검색했습니다."
            )

        # 지역까지 함께 표시
        school_options = [
            f"{school['name']} · {school['region']}"
            for school in schools
        ]

        selected_index = st.selectbox(
            "학교를 선택하세요",
            range(len(schools)),
            format_func=lambda i: school_options[i]
        )

        selected_school = schools[selected_index]

        st.divider()

        # -----------------------------
        # 날짜 선택
        # -----------------------------
        st.subheader("2. 급식 날짜 선택")

        selected_date = st.date_input(
            "날짜",
            value=TODAY_KST
        )

        lunch_button = st.button(
            "🍚 중식 조회",
            use_container_width=True
        )

        if lunch_button:

            rows, error = get_lunch(
                selected_school["office_code"],
                selected_school["school_code"],
                selected_date
            )

            if error:
                st.error(error)

            elif not rows:
                st.info(
                    f"📅 {selected_date.strftime('%Y년 %m월 %d일')}에는 "
                    f"등록된 중식 급식 정보가 없습니다."
                )

            else:
                # 선택한 날짜와 정확히 일치하는 급식만 표시
                target_date = selected_date.strftime("%Y%m%d")

                matching_rows = [
                    row for row in rows
                    if row.get("MLSV_YMD") == target_date
                ]

                if not matching_rows:
                    st.info(
                        f"📅 {selected_date.strftime('%Y년 %m월 %d일')}에는 "
                        f"등록된 중식 급식 정보가 없습니다."
                    )

                else:
                    row = matching_rows[0]

                    menu = row.get("DDISH_NM", "")
                    calorie = row.get("CAL_INFO", "")

                    # <br/>를 줄바꿈으로 변환
                    menu = re.sub(
                        r"<br\s*/?>",
                        "\n",
                        menu,
                        flags=re.IGNORECASE
                    )

                    # HTML 태그가 남아 있다면 제거
                    menu = re.sub(r"<[^>]+>", "", menu)

                    st.subheader(
                        f"🍽️ {selected_school['name']} 중식"
                    )

                    st.caption(
                        f"{selected_school['region']} · "
                        f"{selected_date.strftime('%Y년 %m월 %d일')}"
                    )

                    st.markdown("### 오늘의 메뉴")

                    # 메뉴와 알레르기 번호를 원문 그대로 표시
                    st.text(menu)

                    if calorie:
                        st.markdown("### 🔥 칼로리")
                        st.info(calorie)

    else:
        searched_name = st.session_state.get(
            "searched_name",
            school_input
        )

        st.warning(
            f"'{searched_name}'에 해당하는 학교를 찾지 못했습니다."
        )

        st.caption(
            "학교 이름의 일부를 입력해 보거나, "
            "학교의 정식 명칭을 입력해 주세요."
        )


# -----------------------------
# 안내
# -----------------------------
st.divider()

st.caption(
    "※ 급식 정보는 나이스 교육정보 개방 포털의 급식식단정보를 이용합니다."
)
