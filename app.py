import calendar
import datetime
from datetime import timedelta, timezone
import hashlib
import io
import locale
import plotly.graph_objects as go
import pandas as pd
import plotly.express as px
from supabase import Client, create_client
import streamlit as st
import calendar
import datetime
import streamlit as st
import streamlit.components.v1 as components

def get_korean_date_picker(label="날짜 선택", key_prefix="sales_date_picker"):
    """브라우저 설정과 관계없이 100% 한글 팝업 달력을 제공하는 위젯"""
    state_val_key = f"{key_prefix}_val"
    if state_val_key not in st.session_state:
        st.session_state[state_val_key] = datetime.date.today()

    curr_date = st.session_state[state_val_key]
    formatted_date_str = curr_date.strftime("%Y년 %m월 %d일")

    # 팝업 버튼 (클릭 시 한글 달력 열림)
    with st.popover(
        f"📅 {label}: {formatted_date_str}", use_container_width=True
    ):
        col_y, col_m = st.columns(2)
        years = list(range(2020, 2031))

        # 연도 및 월 선택
        sel_y = col_y.selectbox(
            "년도",
            years,
            index=years.index(curr_date.year),
            key=f"{key_prefix}_y",
            label_visibility="collapsed",
        )
        sel_m = col_m.selectbox(
            "월",
            list(range(1, 13)),
            index=curr_date.month - 1,
            format_func=lambda x: f"{x}월",
            key=f"{key_prefix}_m",
            label_visibility="collapsed",
        )

        st.write("")

        # 한글 요일 헤더
        weekdays = ["월", "화", "수", "목", "금", "토", "일"]
        hdr_cols = st.columns(7)
        for idx, w in enumerate(weekdays):
            hdr_cols[idx].markdown(
                f"<div style='text-align: center; font-weight: bold; font-size: 13px;'>{w}</div>",
                unsafe_allow_html=True,
            )

        # 달력 일자 그리드 생성
        first_weekday, num_days = calendar.monthrange(sel_y, sel_m)
        day_counter = 1

        for week in range(6):
            if day_counter > num_days:
                break
            grid_cols = st.columns(7)
            for d_idx in range(7):
                if (
                    week == 0 and d_idx < first_weekday
                ) or day_counter > num_days:
                    grid_cols[d_idx].write("")
                else:
                    day_num = day_counter
                    is_selected = (
                        sel_y == curr_date.year
                        and sel_m == curr_date.month
                        and day_num == curr_date.day
                    )
                    btn_type = "primary" if is_selected else "secondary"

                    if grid_cols[d_idx].button(
                        str(day_num),
                        key=f"{key_prefix}_grid_{sel_y}_{sel_m}_{day_num}",
                        type=btn_type,
                        use_container_width=True,
                    ):
                        st.session_state[state_val_key] = datetime.date(
                            sel_y, sel_m, day_num
                        )
                        st.rerun()
                    day_counter += 1

    return st.session_state[state_val_key]

def apply_date_colors(df, date_col):
    """데이터프레임의 날짜 컬럼에서 토요일(파란색), 일요일(빨간색) 글자색을 적용합니다."""

    def get_color(val):
        try:
            dt = pd.to_datetime(val)
            if dt.weekday() == 5:  # 토요일
                return "color: #1E69DE; font-weight: bold;"
            elif dt.weekday() == 6:  # 일요일
                return "color: #E53E3E; font-weight: bold;"
        except Exception:
            pass
        return ""

    # 지정한 날짜 컬럼에 스타일 적용
    return df.style.applymap(get_color, subset=[date_col])


# DB 설정값을 안전하게 불러오는 공통 함수
def get_setting(key, default_value):
    try:
        res = (
            supabase.table("app_settings")
            .select("value")
            .eq("key", key)
            .execute()
        )
        if res.data and res.data[0].get("value"):
            return res.data[0]["value"]
    except Exception:
        pass
    return default_value


def create_excel_download(data_dict):
    """여러 Dataframe이 담긴 Dictionary를 입력받아

    각 키(Key)를 시트명으로 갖는 엑셀 바이너리 스트림을 생성합니다.
    """
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for sheet_name, df in data_dict.items():
            # 빈 데이터프레임이어도 빈 시트로 생성
            if df.empty:
                pd.DataFrame({"안내": ["데이터가 없습니다."]}).to_excel(
                    writer, sheet_name=sheet_name, index=False
                )
            else:
                df.to_excel(writer, sheet_name=sheet_name, index=False)

    file_bytes = output.getvalue()
    mime_type = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    ext = "xlsx"

    return file_bytes, mime_type, ext


# 한국 표준시 (KST) 설정
KST = timezone(timedelta(hours=9))

# ------------------------------------------
# 파이썬 날짜/시간 한국어 로캘 설정
# ------------------------------------------
try:
    locale.setlocale(locale.LC_ALL, "ko_KR.UTF-8")
except Exception:
    try:
        locale.setlocale(locale.LC_ALL, "Korean_Korea.949")
    except Exception:
        pass


# ==========================================
# Supabase 클라이언트 초기화
# ==========================================
@st.cache_resource
def init_supabase() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)


supabase = init_supabase()


# ==========================================
# 0. 유틸리티 (안전 파싱 & 보안 암호화)
# ==========================================
def hash_str(val: str) -> str:
    """문자열을 SHA-256 해시값으로 변환합니다."""
    if not val:
        return ""
    return hashlib.sha256(val.encode("utf-8")).hexdigest()


def verify_hash(input_val: str, stored_val: str) -> bool:
    """해시 검증 (기존 평문 저장 데이터와의 호환성 지원)"""
    if not input_val or not stored_val:
        return False
    if len(stored_val) == 64:  # SHA-256 해시 길이
        return hash_str(input_val) == stored_val
    return input_val == stored_val


def safe_int(val, default=0):
    try:
        if pd.isna(val) or val is None or str(val).strip() == "":
            return default
        return int(float(str(val).replace(",", "")))
    except (ValueError, TypeError):
        return default


def safe_float(val, default=0.0):
    try:
        if pd.isna(val) or val is None or str(val).strip() == "":
            return default
        return float(str(val).replace(",", ""))
    except (ValueError, TypeError):
        return default


# ==========================================
# 1. Supabase 기반 비즈니스 로직 함수
# ==========================================
def get_admin_password():
    res = (
        supabase.table("settings")
        .select("value")
        .eq("key", "admin_password")
        .execute()
    )
    return res.data[0]["value"] if res.data else hash_str("1234")


def set_admin_password(new_pw):
    supabase.table("settings").upsert(
        {"key": "admin_password", "value": hash_str(new_pw)}
    ).execute()


def get_staff_info():
    res = (
        supabase.table("staff").select("name, pin, hourly_rate, role").execute()
    )
    return (
        {
            r["name"]: {
                "pin": r["pin"],
                "hourly_rate": r["hourly_rate"],
                "role": r.get("role", "알바"),
            }
            for r in res.data
        }
        if res.data
        else {}
    )


def get_notice():
    res = (
        supabase.table("notice").select("content, updated_at").eq("id", 1).execute()
    )
    if res.data:
        return res.data[0]["content"], res.data[0].get("updated_at", "")
    return ("공지사항이 없습니다.", "")


def set_notice(content_text):
    now_str = datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    supabase.table("notice").upsert(
        {"id": 1, "content": content_text, "updated_at": now_str}
    ).execute()


def get_latest_handover():
    res = (
        supabase.table("handover")
        .select(
            "sender_name, receiver_name, shift_type, content, created_at, is_read"
        )
        .order("id", desc=True)
        .limit(1)
        .execute()
    )
    if res.data:
        r = res.data[0]
        return (
            r["sender_name"],
            r["receiver_name"],
            r["shift_type"],
            r["content"],
            r["created_at"],
            r.get("is_read", 0),
        )
    return None


def get_pending_shift_count():
    res = (
        supabase.table("shift_requests")
        .select("id", count="exact")
        .eq("status", "대기중")
        .execute()
    )
    return res.count if res.count is not None else 0


def calculate_person_summary(target_name):
    staff_dict = get_staff_info()
    rate = staff_dict.get(target_name, {}).get("hourly_rate", 10030)

    res = (
        supabase.table("attendance")
        .select("*")
        .eq("staff_name", target_name)
        .order("date", desc=False)
        .execute()
    )
    df_att = pd.DataFrame(res.data) if res.data else pd.DataFrame()

    if df_att.empty:
        return {
            "hourly_rate": rate,
            "work_days": 0,
            "total_hours": 0.0,
            "base_pay": 0,
            "holiday_pay": 0,
            "gross_pay": 0,
            "tax_3_3": 0,
            "total_pay": 0,
            "late_count": 0,
            "early_leave_count": 0,
            "df": df_att,
        }

    df_att["work_hours"] = (
        pd.to_numeric(df_att["work_hours"], errors="coerce").fillna(0.0)
    )
    df_att["late_minutes"] = (
        pd.to_numeric(df_att["late_minutes"], errors="coerce").fillna(0)
    )
    df_att["early_leave_minutes"] = (
        pd.to_numeric(df_att["early_leave_minutes"], errors="coerce").fillna(0)
    )

    total_hours = float(df_att["work_hours"].sum())
    base_pay = int(total_hours * rate)

    df_att["dt"] = pd.to_datetime(df_att["date"])
    df_att["year_week"] = df_att["dt"].dt.strftime("%G-%V")

    weekly_hours = df_att.groupby("year_week")["work_hours"].sum()

    total_holiday_pay = 0
    for w_hours in weekly_hours:
        if w_hours >= 15.0:
            applicable_hours = min(w_hours, 40.0)
            holiday_hours = applicable_hours * 0.2
            total_holiday_pay += int(holiday_hours * rate)

    gross_pay = base_pay + total_holiday_pay
    tax_3_3 = int(gross_pay * 0.033)
    net_pay = gross_pay - tax_3_3

    late_count = len(df_att[df_att["late_minutes"] > 0])
    early_leave_count = len(df_att[df_att["early_leave_minutes"] > 0])

    return {
        "hourly_rate": rate,
        "work_days": len(df_att),
        "total_hours": round(total_hours, 1),
        "base_pay": base_pay,
        "holiday_pay": total_holiday_pay,
        "gross_pay": gross_pay,
        "tax_3_3": tax_3_3,
        "total_pay": net_pay,
        "late_count": late_count,
        "early_leave_count": early_leave_count,
        "df": df_att,
    }


def convert_df_to_csv(df):
    return df.to_csv(index=False).encode("utf-8-sig")


def style_date_dataframe(df, date_col="날짜"):
    if df.empty or date_col not in df.columns:
        return df

    df_styled = df.copy()

    def add_weekday_str(val):
        try:
            s_val = str(val).split(" ")[0]
            dt = pd.to_datetime(s_val)
            days = ["월", "화", "수", "목", "금", "토", "일"]
            w = days[dt.weekday()]
            return f"{dt.strftime('%Y-%m-%d')} ({w})"
        except Exception:
            return str(val)

    df_styled[date_col] = df_styled[date_col].apply(add_weekday_str)

    def color_weekdays(val):
        s = str(val)
        if "(토)" in s:
            return "color: #1890ff; font-weight: bold;"
        elif "(일)" in s:
            return "color: #ff4d4f; font-weight: bold;"
        return ""

    styler = df_styled.style
    if hasattr(styler, "map"):
        return styler.map(color_weekdays, subset=[date_col])
    else:
        return styler.applymap(color_weekdays, subset=[date_col])


# ==========================================
# 2. 페이지 기본 설정 및 디자인
# ==========================================
st.set_page_config(
    page_title="컴포즈커피 분당느티마을점 통합 관리 시스템",
    page_icon="☕",
    layout="wide",
)

st.markdown(
    """
    <style>
    .main-title {
        color: #FFC700;
        font-size: 2.2rem;
        font-weight: bold;
        background-color: #111111;
        padding: 16px;
        border-radius: 12px;
        text-align: center;
        margin-bottom: 20px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
    }
    .stButton>button {
        border-radius: 8px;
        font-weight: bold;
    }
    [data-testid="stSidebar"] {
        background-color: #FFC700 !important;
    }
    [data-testid="stSidebar"] * {
        color: #111111 !important;
    }
    [data-testid="stSidebar"] .stRadio label p,
    [data-testid="stSidebar"] div[role="radiogroup"] label {
        color: #111111 !important;
        font-weight: bold !important;
    }
    [data-testid="stSidebar"] .stSelectbox label p {
        color: #111111 !important;
        font-weight: bold !important;
    }
    </style>
""",
    unsafe_allow_html=True,
)

# JavaScript 달력 날짜 번역 및 스타일 처리
js_korean_translation_and_colors = """
<script>
function applyKoreanTranslationAndColors() {
    const parentDoc = window.parent.document;
    if (!parentDoc) return;

    const monthMap = {
        'January': '1월', 'February': '2월', 'March': '3월', 'April': '4월',
        'May': '5월', 'June': '6월', 'July': '7월', 'August': '8월',
        'September': '9월', 'October': '10월', 'November': '11월', 'December': '12월',
        'Jan': '1월', 'Feb': '2월', 'Mar': '3월', 'Apr': '4월',
        'Jun': '6월', 'Jul': '7월', 'Aug': '8월', 'Sep': '9월', 'Oct': '10월', 'Dec': '12월'
    };

    const dayMap = {
        'Su': '일', 'Mo': '월', 'Tu': '화', 'We': '수', 'Th': '목', 'Fr': '금', 'Sa': '토',
        'Sun': '일', 'Mon': '월', 'Tue': '화', 'Wed': '수', 'Thu': '목', 'Fri': '금', 'Sat': '토'
    };

    const containers = parentDoc.querySelectorAll('[role="dialog"], [data-baseweb="popover"], [data-baseweb="calendar"], div[aria-roledescription="calendar"]');

    containers.forEach(container => {
        const walker = parentDoc.createTreeWalker(container, NodeFilter.SHOW_TEXT, null, false);
        let node;
        while (node = walker.nextNode()) {
            let val = node.nodeValue;
            if (!val) continue;

            for (const [eng, kor] of Object.entries(monthMap)) {
                if (val.includes(eng)) {
                    val = val.replace(new RegExp('\\b' + eng + '\\b', 'g'), kor);
                }
            }
            if (node.nodeValue !== val) {
                node.nodeValue = val;
            }
        }

        const dayElements = container.querySelectorAll('button, div, span');
        dayElements.forEach(el => {
            if (el.children.length === 0) {
                const txt = el.innerText ? el.innerText.trim() : '';
                if (dayMap[txt]) {
                    el.innerText = dayMap[txt];
                }

                const currentTxt = el.innerText ? el.innerText.trim() : '';
                if (currentTxt === '토' || currentTxt === 'Sa' || currentTxt === 'Sat') {
                    el.style.color = '#1890ff';
                    el.style.fontWeight = 'bold';
                } else if (currentTxt === '일' || currentTxt === 'Su' || currentTxt === 'Sun') {
                    el.style.color = '#ff4d4f';
                    el.style.fontWeight = 'bold';
                }
            }
        });
    });
}

if (window.parent && window.parent.document) {
    const observer = new MutationObserver(() => {
        applyKoreanTranslationAndColors();
    });
    observer.observe(window.parent.document.body, { childList: true, subtree: true });
    applyKoreanTranslationAndColors();
}
</script>
"""
components.html(js_korean_translation_and_colors, height=0, width=0)

# ==========================================
# 3. 세션 상태 초기화 및 헤더
# ==========================================
if "admin_logged_in" not in st.session_state:
    st.session_state["admin_logged_in"] = False

st.markdown(
    "<div class='main-title'>☕ COMPOSE COFFEE 분당느티마을점 통합 관리 시스템</div>",
    unsafe_allow_html=True,
)

notice_content, notice_date = get_notice()
st.info(f"📢 **매장 공지사항 ({notice_date})**: {notice_content}")

pending_shifts = get_pending_shift_count()

st.sidebar.title("📌 시스템 메뉴")
if pending_shifts > 0:
    st.sidebar.warning(
        f"🚨 대타 교대 승인 요청: **{pending_shifts}건** 대기 중!"
    )

user_mode = st.sidebar.radio(
    "접속 모드를 선택하세요", ["📱 알바생 전용 모드", "🔒 점주 관리자 모드"]
)

# ==========================================
# [모드 1] 📱 알바생 전용 모드
# ==========================================
if user_mode == "📱 알바생 전용 모드":
    staff_dict = get_staff_info()
    staff_names = list(staff_dict.keys()) if staff_dict else []

    # 최근 인수인계 상단 공지
    latest_ho = get_latest_handover()
    if latest_ho:
        s_sender, s_receiver, s_shift, s_content, s_time, s_read = latest_ho
        read_badge = "✅ 확인완료" if s_read == 1 else "🚨 미확인 (체크 필요)"
        st.warning(
            f"🤝 **[최근 근무 인수인계 공지]** `{s_time}` | **인계자:** {s_sender} ➔ "
            f"**인수자:** {s_receiver} ({s_shift}) [{read_badge}]\n\n📌 "
            f"**내용:** {s_content}"
        )
    else:
        st.caption("🤝 등록된 최신 인수인계 내역이 없습니다.")

    tab_st1, tab_st2, tab_st3, tab_st4, tab_st5, tab_st6, tab_st7 = st.tabs([
        "⏰ 출퇴근 찍기",
        "📋 오픈/마감 체크리스트",
        "🤝 알바생 인수인계",
        "📦 재고 실사 점검",
        "🗑️ 유통기한/폐기 보고",
        "🔄 대타 교대 신청",
        "📄 내 근무 기록",
    ])

    # --- 1. 출퇴근 찍기 ---
    with tab_st1:
        st.subheader("⏰ 출퇴근 확인")
        col1, col2 = st.columns(2)

        with col1:
            selected_staff = st.selectbox(
                "직원 이름",
                staff_names if staff_names else ["직원없음"],
                key="att_staff",
            )
            input_pin = st.text_input(
                "PIN 번호 (4자리)", type="password", max_chars=4, key="att_pin"
            )

        today_str = datetime.datetime.now(KST).date().strftime("%Y-%m-%d")
        days_kr = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
        today_weekday = days_kr[datetime.datetime.now(KST).date().weekday()]
        now_time = datetime.datetime.now(KST).strftime("%H:%M")

        att_today = None
        sched_today = None

        try:
            res_att = (
                supabase.table("attendance")
                .select("*")
                .eq("staff_name", selected_staff)
                .eq("date", today_str)
                .execute()
            )
            att_today = res_att.data[0] if res_att and res_att.data else None

            res_sched = (
                supabase.table("schedule")
                .select("start_time, end_time")
                .eq("staff_name", selected_staff)
                .eq("date", today_str)
                .execute()
            )
            sched_today = res_sched.data[0] if res_sched and res_sched.data else None
        except Exception as e:
            st.error(f"⚠️ 출퇴근 데이터 조회 오류: {e}")

        if sched_today:
            st.caption(
                f"📅 오늘 예정 근무시간 ({today_weekday}):"
                f" **{sched_today['start_time']} ~ {sched_today['end_time']}**"
            )
        else:
            st.caption("📅 오늘 등록된 예정 스케줄이 없습니다.")

        st.write("---")
        col_btn1, col_btn2 = st.columns(2)

        with col_btn1:
            if st.button("▶️ 출근하기", use_container_width=True, type="primary"):
                if selected_staff in staff_dict and verify_hash(
                    input_pin, staff_dict[selected_staff]["pin"]
                ):
                    if att_today:
                        st.warning("이미 오늘 출근 찍기가 완료되었습니다.")
                    else:
                        late_min = 0
                        if sched_today:
                            sched_start = datetime.datetime.strptime(
                                f"{today_str} {sched_today['start_time']}", "%Y-%m-%d %H:%M"
                            ).replace(tzinfo=KST)
                            now_dt = datetime.datetime.now(KST)
                            if now_dt > sched_start:
                                late_min = int((now_dt - sched_start).total_seconds() / 60)

                        supabase.table("attendance").insert({
                            "staff_name": selected_staff,
                            "date": today_str,
                            "clock_in": now_time,
                            "late_minutes": late_min,
                        }).execute()

                        if late_min > 0:
                            st.warning(f"✅ 출근 처리되었습니다. (지각 {late_min}분)")
                        else:
                            st.success("✅ 정상 출근 처리되었습니다. 오늘 하루도 화이팅!")
                        st.rerun()
                else:
                    st.error("❌ PIN 번호가 일치하지 않거나 직원이 선택되지 않았습니다.")

        with col_btn2:
            if st.button("⏹️ 퇴근하기", use_container_width=True):
                if selected_staff in staff_dict and verify_hash(
                    input_pin, staff_dict[selected_staff]["pin"]
                ):
                    if not att_today:
                        st.error("출근 기록이 없습니다. 출근을 먼저 찍어주세요.")
                    elif att_today.get("clock_out") is not None:
                        st.warning("이미 퇴근 처리가 완료되었습니다.")
                    else:
                        clock_in_time = att_today["clock_in"]
                        now = datetime.datetime.now(KST)

                        t1 = datetime.datetime.strptime(
                            f"{today_str} {clock_in_time}", "%Y-%m-%d %H:%M"
                        ).replace(tzinfo=KST)
                        t2 = now
                        hours_worked = round((t2 - t1).total_seconds() / 3600.0, 2)

                        early_leave_minutes = 0
                        if sched_today and "end_time" in sched_today:
                            sched_end = datetime.datetime.strptime(
                                f"{today_str} {sched_today['end_time']}", "%Y-%m-%d %H:%M"
                            ).replace(tzinfo=KST)
                            if t2 < sched_end:
                                early_leave_minutes = int((sched_end - t2).total_seconds() / 60)

                        supabase.table("attendance").update({
                            "clock_out": now.strftime("%H:%M"),
                            "work_hours": hours_worked,
                            "early_leave_minutes": early_leave_minutes
                        }).eq("id", att_today["id"]).execute()

                        st.success("퇴근 처리가 정상 완료되었습니다!")
                        st.rerun()
                else:
                    st.error("❌ PIN 번호가 올바르지 않습니다.")

 
# --- 2. 오픈/마감 체크리스트 ---
    with tab_st2:
        st.subheader("📋 업무 체크리스트 수행 및 수정")

        col_st1, col_st2 = st.columns(2)
        chk_date = col_st1.date_input("점검 날짜", datetime.date.today(), key="staff_chk_date")
        chk_type = col_st2.radio("체크리스트 구분", ["☀️ 오픈", "🌙 마감"], horizontal=True, key="staff_chk_type")

        checker_name = st.selectbox(
            "수행자 이름",
            staff_names if staff_names else ["직원없음"],
            key="chk_staff",
        )

        setting_key = "checklist_open_items" if "오픈" in chk_type else "checklist_close_items"
        default_items = (
            ["오픈 매장 청소", "원두/시럽 재고 점검", "머신 예열 및 세팅"]
            if "오픈" in chk_type
            else ["마감 포스 정산", "머신 마감 세척", "쓰레기 분리수거"]
        )

        items = get_setting(setting_key, default_items)

        if items:
            date_str = str(chk_date)
            existing_record = None
            existing_checked = {}
            existing_memo = ""

            try:
                chk_res = (
                    supabase.table("checklist")
                    .select("*")
                    .eq("date", date_str)
                    .eq("shift_type", chk_type)
                    .execute()
                )
                if chk_res and chk_res.data:
                    existing_record = chk_res.data[0]
                    existing_checked = existing_record.get("checked_items") or {}
                    existing_memo = existing_record.get("memo") or ""
            except Exception:
                pass

            if existing_record:
                st.info(f"💡 [{date_str}] **{chk_type}** 이미 제출된 점검 내역이 있습니다. 수정 후 재제출할 수 있습니다.")
            else:
                st.write(f"**[{chk_type} 필수 점검 항목]**")

            with st.form(key=f"staff_chk_form_{chk_type}_{date_str}"):
                checked_items_dict = {}
                for idx, item in enumerate(items):
                    default_val = existing_checked.get(item, False)
                    chk_val = st.checkbox(item, value=default_val, key=f"chk_item_{chk_type}_{date_str}_{idx}")
                    checked_items_dict[item] = chk_val

                memo_input = st.text_input("비고 / 특이사항", value=existing_memo, placeholder="특이사항이 있을 경우 작성해 주세요.")

                submit_label = "💾 체크리스트 수정 완료" if existing_record else "📋 체크리스트 제출"
                if st.form_submit_button(submit_label, type="primary", use_container_width=True):
                    now_str = datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")

                    payload = {
                        "date": date_str,
                        "shift_type": chk_type,
                        "staff_name": checker_name,
                        "checked_items": checked_items_dict,
                        "memo": memo_input,
                        "created_at": now_str
                    }

                    # existing_record가 있을 경우 id를 payload에 포함하여 확실하게 업데이트
                    if existing_record and "id" in existing_record:
                        payload["id"] = existing_record["id"]

                    try:
                        # insert 대신 on_conflict="date"를 명시한 upsert 적용
                        supabase.table("checklist").upsert(payload, on_conflict="date").execute()

                        if existing_record:
                            st.success(f"✅ [{chk_type}] 체크리스트가 성공적으로 수정되었습니다!")
                        else:
                            st.success(f"✅ [{chk_type}] 체크리스트가 성공적으로 제출되었습니다!")

                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ 저장 중 오류가 발생했습니다: {e}")
        else:
            st.info("💡 등록된 체크리스트 항목이 없습니다. 관리자 메뉴에서 항목을 등록해 주세요.")
        

    # --- 3. 알바생 인수인계 ---
    with tab_st3:
        st.subheader("🤝 알바생 근무 인수인계 작성 및 확인")

        col_ho1, col_ho2 = st.columns(2)
        with col_ho1:
            ho_sender = st.selectbox(
                "인계자 (작성자)",
                staff_names if staff_names else ["직원없음"],
                key="ho_sender",
            )
            ho_receiver = st.selectbox(
                "인수자 (다음 근무자)", ["전체 공유"] + staff_names, key="ho_receiver"
            )
        with col_ho2:
            ho_shift_type = st.selectbox(
                "교대 유형",
                ["오픈 → 미들", "미들 → 마감", "마감 → 오픈", "기타"],
                key="ho_shift",
            )
            ho_pin = st.text_input(
                "PIN 번호 (작성자 확인)", type="password", max_chars=4, key="ho_pin"
            )

        ho_content = st.text_area(
            "인수인계 메모 (특이사항, 재고 부족, 금고 잔돈, 주의 요청 등)",
            key="ho_content",
            height=120,
        )

        if st.button("📝 인수인계 사항 등록", type="primary"):
            if ho_sender in staff_dict and verify_hash(
                ho_pin, staff_dict[ho_sender]["pin"]
            ):
                if ho_content.strip():
                    now_str = datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
                    supabase.table("handover").insert({
                        "sender_name": ho_sender,
                        "receiver_name": ho_receiver,
                        "shift_type": ho_shift_type,
                        "content": ho_content,
                        "created_at": now_str,
                        "is_read": 0,
                    }).execute()
                    st.success("✅ 인수인계 사항이 정상적으로 등록되었습니다.")
                    st.rerun()
                else:
                    st.warning("⚠️ 인수인계 내용을 입력해 주세요.")
            else:
                st.error("❌ PIN 번호가 일치하지 않습니다.")

        st.write("---")
        st.subheader("📋 최근 인수인계 내역")

        res_ho = (
            supabase.table("handover")
            .select("id, sender_name, receiver_name, shift_type, content, created_at, is_read")
            .order("id", desc=True)
            .limit(20)
            .execute()
        )
        df_ho = pd.DataFrame(res_ho.data) if res_ho and res_ho.data else pd.DataFrame()

        if not df_ho.empty:
            df_ho.rename(
                columns={
                    "id": "번호",
                    "sender_name": "인계자",
                    "receiver_name": "인수자",
                    "shift_type": "교대유형",
                    "content": "인수인계내용",
                    "created_at": "작성시각",
                    "is_read": "확인상태",
                },
                inplace=True,
            )

            df_ho["확인상태"] = df_ho["확인상태"].apply(
                lambda x: "✅ 확인완료" if x == 1 else "⏳ 미확인"
            )
            st.dataframe(df_ho, use_container_width=True)

            unread_ho = df_ho[df_ho["확인상태"] == "⏳ 미확인"]
            if not unread_ho.empty:
                st.markdown("#### 🔍 미확인 인수인계 처리")
                c_ho_check1, c_ho_check2 = st.columns([2, 1])
                with c_ho_check1:
                    target_ho_id = st.selectbox(
                        "확인 처리할 인수인계 번호",
                        unread_ho["번호"].tolist(),
                        key="target_ho_id",
                    )
                with c_ho_check2:
                    ho_confirm_pin = st.text_input(
                        "인수자 PIN 번호",
                        type="password",
                        max_chars=4,
                        key="ho_confirm_pin",
                    )

                
                if st.button("✅ 읽음 / 확인 완료 처리"):
                    matched_staff = None
                    for name, info in staff_dict.items():
                        if verify_hash(ho_confirm_pin, info["pin"]):
                            matched_staff = name
                            break

                    if matched_staff:
                        # 💡 update(...)를 eq(...)보다 먼저 호출하도록 순서 변경
                        supabase.table("handover").update(
                            {"is_read": 1}
                        ).eq("id", target_ho_id).execute()

                        st.success(
                            f"[{matched_staff}] 님이 인수인계 (#{target_ho_id}) 항목을 확인 완료 처리했습니다."
                        )
                        st.rerun()
                    else:
                        st.error("❌ 올바른 PIN 번호를 입력해 주세요.")
                else:
                    st.info("등록된 인수인계 내역이 없습니다.")



       # --- 4. 재고 실사 점검 ---
    with tab_st4:
        st.subheader("📦 실물 재고 실사 점검")
        st.caption("현재 매장에 있는 실제 재고 수량을 파악하여 전산 재고를 최신 상태로 업데이트합니다.")

        col_inv1, col_inv2 = st.columns(2)
        inv_reporter = col_inv1.selectbox("점검자 이름", staff_names if staff_names else ["직원없음"], key="inv_audit_reporter")
        inv_pin = col_inv2.text_input("PIN 번호", type="password", max_chars=4, key="inv_audit_pin")

        inv_db_map = {}
        try:
            inv_res = supabase.table("inventory").select("item_name, current_qty, unit, unit_price").execute()
            if inv_res and inv_res.data:
                for row in inv_res.data:
                    inv_db_map[row["item_name"]] = {
                        "current_qty": safe_int(row.get("current_qty")),
                        "unit": row.get("unit", "개") or "개",
                        "unit_price": safe_int(row.get("unit_price")),
                    }
        except Exception as e:
            st.error(f"⚠️ 재고 데이터를 불러오는 중 오류 발생: {e}")

        default_inv_items = ["원두 (kg)", "우유 (팩)", "빨대 (박스)", "24oz 컵 (박스)", "바닐라 시럽 (병)"]
        setting_inv_items = get_setting("inventory_items", default_inv_items)

        all_item_names = list(inv_db_map.keys())
        for item_name in setting_inv_items:
            if item_name not in all_item_names:
                all_item_names.append(item_name)

        all_audit_items = []
        for item_name in all_item_names:
            db_info = inv_db_map.get(item_name, {"current_qty": 0, "unit": "개", "unit_price": 0})
            all_audit_items.append({
                "item_name": item_name,
                "current_qty": db_info["current_qty"],
                "unit": db_info["unit"],
                "unit_price": db_info["unit_price"],
            })

        if all_audit_items:
            st.write("#### 📝 품목별 실사 수량 입력")
            st.caption("💡 실제 수량을 입력하면 전산 수량과의 차이가 자동 계산되고 최신 재고로 반영됩니다.")

            with st.form(key="inventory_audit_form"):
                actual_counts = {}
                memo_dict = {}

                col_h1, col_h2, col_h3, col_h4 = st.columns([3, 2, 2, 3])
                col_h1.markdown("**품목명**")
                col_h2.markdown("**현재 전산 재고**")
                col_h3.markdown("**실사 수량 (입력)**")
                col_h4.markdown("**특이사항 / 메모**")
                st.divider()

                for idx, item in enumerate(all_audit_items):
                    c1, c2, c3, c4 = st.columns([3, 2, 2, 3])
                    item_name = item["item_name"]
                    sys_qty = item["current_qty"]
                    unit = item["unit"]

                    c1.write(f"**{item_name}**")
                    c2.write(f"{sys_qty:,} {unit}")

                    actual_qty = c3.number_input(
                        f"{item_name} 실사수량",
                        min_value=0,
                        value=sys_qty,
                        step=1,
                        key=f"audit_qty_{idx}",
                        label_visibility="collapsed"
                    )
                    actual_counts[item_name] = actual_qty

                    memo = c4.text_input(
                        f"{item_name} 메모",
                        placeholder="오차 사유 등",
                        key=f"audit_memo_{idx}",
                        label_visibility="collapsed"
                    )
                    memo_dict[item_name] = memo

                st.write("---")
                audit_submit = st.form_submit_button("💾 재고 실사 결과 제출 및 점주 모드 연동", type="primary", use_container_width=True)

            if audit_submit:
                reporter_pin = staff_dict.get(inv_reporter, {}).get("pin", "")

                if verify_hash(inv_pin, reporter_pin):
                    now_str = datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
                    today_date_str = datetime.datetime.now(KST).date().strftime("%Y-%m-%d")

                    try:
                        audit_logs = []
                        for item in all_audit_items:
                            item_name = item["item_name"]
                            sys_qty = item["current_qty"]
                            act_qty = actual_counts[item_name]
                            diff_qty = act_qty - sys_qty
                            unit = item["unit"]
                            unit_price = item["unit_price"]
                            memo = memo_dict.get(item_name, "")

                            # 1. inventory 최신화
                            supabase.table("inventory").upsert({
                                "item_name": item_name,
                                "current_qty": act_qty,
                                "unit": unit,
                                "unit_price": unit_price,
                                "updated_at": now_str
                            }, on_conflict="item_name").execute()

                            # 2. 실사 이력 저장 (inventory_audit 테이블 표준 필드만 저장)
                            audit_logs.append({
                                "date": today_date_str,
                                "item_name": item_name,
                                "system_qty": sys_qty,
                                "actual_qty": act_qty,
                                "diff_qty": diff_qty,
                                "unit": unit,
                                "checked_by": inv_reporter,
                                "memo": memo,
                                "created_at": now_str
                            })

                        supabase.table("inventory_audit").insert(audit_logs).execute()

                        st.success("✅ 재고 실사 제출 완료! 점주 메뉴 [알바생 실사 점검 이력]에 즉시 연동되었습니다.")
                        st.rerun()

                    except Exception as e:
                        st.error(f"❌ DB 저장 오류 발생: {e}")
                else:
                    st.error("❌ PIN 번호가 틀렸습니다.")
        else:
            st.info("💡 등록된 재고 품목이 없습니다. 점주 메뉴에서 재고 품목을 먼저 등록해 주세요.")
    

   
        # --- 5. 유통기한/폐기 보고 ---
    with tab_st5:
        st.subheader("🗑️ 유통기한 경과 / 파손 원자재 폐기 보고")
        st.caption("버리게 된 원자재를 등록하면 재고 차감 및 폐기 손실 금액이 자동 계산됩니다.")

        col_w1, col_w2 = st.columns(2)
        w_reporter = col_w1.selectbox("보고자", staff_names if staff_names else ["직원없음"], key="w_reporter")
        w_pin = col_w2.text_input("PIN 번호", type="password", max_chars=4, key="w_pin")

        default_waste_reasons = ["유통기한 경과", "제조/조리 실수", "용기/포장 파손", "원두 추출 불량", "기타"]
        waste_reasons = get_setting("waste_reasons", default_waste_reasons)

        default_inv_items = ["원두 (kg)", "우유 (팩)", "빨대 (박스)", "24oz 컵 (박스)", "바닐라 시럽 (병)"]
        setting_inv_items = get_setting("inventory_items", default_inv_items)

        inv_dict = {}
        try:
            inv_list_res = (
                supabase.table("inventory")
                .select("item_name, unit, unit_price, current_qty")  # cost_price -> unit_price 변경
                .execute()
            )
            if inv_list_res and inv_list_res.data:
                for i in inv_list_res.data:
                    inv_dict[i["item_name"]] = {
                        "unit": i.get("unit", "개") or "개",
                        "cost": safe_int(i.get("unit_price")),  # cost_price -> unit_price 변경
                        "current_qty": safe_int(i.get("current_qty")),
                    }
        except Exception:
            pass

        for item_name in setting_inv_items:
            if item_name not in inv_dict:
                inv_dict[item_name] = {
                    "unit": "개",
                    "cost": 0,
                    "current_qty": 0
                }

        if inv_dict:
            col_item, col_qty = st.columns([3, 1])
            w_item = col_item.selectbox("폐기 품목", list(inv_dict.keys()), key="w_item_select")
            w_qty = col_qty.number_input("폐기 수량", min_value=1, value=1, key="w_qty_input")

            item_cost = inv_dict[w_item]["cost"]
            calc_loss = item_cost * w_qty
            st.warning(
                f"💰 **예상 손실 금액: {calc_loss:,} 원** (단가: {item_cost:,}원 / "
                f"{inv_dict[w_item]['unit']})"
            )

            w_reason = st.selectbox("폐기 사유", waste_reasons, key="w_reason_select")

            if st.button("🗑️ 폐기 등록 제출", type="primary", use_container_width=True, key="btn_submit_waste"):
                reporter_pin = staff_dict.get(w_reporter, {}).get("pin", "")

                if verify_hash(w_pin, reporter_pin):
                    now_str = datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
                    today_date_str = datetime.datetime.now(KST).date().strftime("%Y-%m-%d")
                    new_qty = inv_dict[w_item]["current_qty"] - w_qty

                    try:
                        # 재고 차감 시 unit_price 필드로 업데이트
                        supabase.table("inventory").upsert({
                            "item_name": w_item,
                            "current_qty": new_qty,
                            "unit": inv_dict[w_item]["unit"],
                            "unit_price": item_cost
                        }, on_conflict="item_name").execute()

                        supabase.table("waste").insert({
                            "date": today_date_str,
                            "item_name": w_item,
                            "qty": w_qty,
                            "unit": inv_dict[w_item]["unit"],
                            "reason": w_reason,
                            "reported_by": w_reporter,
                            "loss_amount": calc_loss,
                            "created_at": now_str,
                        }).execute()

                        st.success(
                            f"✅ [{w_item}] {w_qty:,}개 폐기 보고 완료! (손실금액: {calc_loss:,}원 자동 반영됨)"
                        )
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ 제출 중 오류가 발생했습니다: {e}")
                else:
                    st.error("❌ PIN 번호가 틀렸습니다.")
        else:
            st.info("💡 등록된 재고 품목이 없습니다. 점주 메뉴에서 재고 품목을 설정해 주세요.")

    # --- 6. 대타 신청 ---
    with tab_st6:
        st.subheader("🔄 알바생 대타 / 근무 교대 신청")

        col_s1, col_s2 = st.columns(2)
        with col_s1:
            applicant = st.selectbox("신청자", staff_names if staff_names else ["직원없음"], key="shift_app")
            substitute = st.selectbox("대타 근무자", staff_names if staff_names else ["직원없음"], key="shift_sub")
            shift_date = st.date_input("근무 교대 날짜", key="shift_req_date")

        with col_s2:
            shift_time = st.text_input("근무 시간대 (예: 09:00~15:00)")
            reason = st.text_area("교대 사유")

        if st.button("🔄 대타 승인 요청 제출", type="primary"):
            try:
                supabase.table("shift_requests").insert({
                    "applicant_name": applicant,
                    "substitute_name": substitute,
                    "shift_date": str(shift_date),
                    "shift_time": shift_time,
                    "reason": reason,
                    "status": "대기중",
                }).execute()
                st.success("점주님께 대타 승인 요청을 보냈습니다.")
            except Exception as e:
                st.error(f"❌ 요청 실패: {e}")

        st.write("---")
        st.subheader("📋 내 대타 신청 처리 현황 (오름차순)")

        try:
            shifts_res = (
                supabase.table("shift_requests")
                .select("applicant_name, substitute_name, shift_date, shift_time, reason, status")
                .order("shift_date", desc=False)
                .order("id", desc=False)
                .execute()
            )
            df_shifts = (
                pd.DataFrame(shifts_res.data)
                if shifts_res and shifts_res.data
                else pd.DataFrame(
                    columns=["applicant_name", "substitute_name", "shift_date", "shift_time", "reason", "status"]
                )
            )
            df_shifts = df_shifts.rename(
                columns={
                    "applicant_name": "신청자",
                    "substitute_name": "대타근무자",
                    "shift_date": "날짜",
                    "shift_time": "시간",
                    "reason": "사유",
                    "status": "상태",
                }
            )
            st.dataframe(style_date_dataframe(df_shifts, "날짜"), use_container_width=True)
        except Exception as e:
            st.error(f"⚠️ 대타 신청 현황 불러오기 오류: {e}")

    # --- 7. 내 근무 기록 및 급여 ---
    with tab_st7:
        st.subheader("📄 내 근무 기록 및 급여 정산 조회")
        my_name = st.selectbox("본인 이름 선택", staff_names if staff_names else ["직원없음"], key="my_name_select")
        my_pin = st.text_input("PIN 번호 확인", type="password", max_chars=4, key="my_pin_check")

        if st.button("🔍 조회하기"):
            user_pin = staff_dict.get(my_name, {}).get("pin", "")
            if verify_hash(my_pin, user_pin):
                res = calculate_person_summary(my_name)

                st.markdown("#### 💰 이번 달 급여 정산 상세 내역")
                c1, c2, c3, c4, c5 = st.columns(5)
                c1.metric("총 근무시간", f"{res['total_hours']} 시간")
                c2.metric("기본급", f"{res['base_pay']:,} 원")
                c3.metric("주휴수당 (자동)", f"{res['holiday_pay']:,} 원")
                c4.metric("3.3% 세금 공제", f"-{res['tax_3_3']:,} 원")
                c5.metric("최종 실수령액", f"{res['total_pay']:,} 원")

                st.caption(
                    "💡 **주휴수당 조건:** 주 15시간 이상 근무 시 자동 계산 | **세금:** "
                    "세전 총급여(기본급+주휴수당)의 3.3% 원천징수 공제"
                )

                if not res["df"].empty:
                    st.write("---")
                    st.write("**상세 출퇴근 내역 (1일 순서 오름차순)**")
                    df_my_display = res["df"][[
                        "date",
                        "clock_in",
                        "clock_out",
                        "work_hours",
                        "late_minutes",
                        "early_leave_minutes",
                    ]].rename(
                        columns={
                            "date": "날짜",
                            "clock_in": "출근시각",
                            "clock_out": "퇴근시각",
                            "work_hours": "근무시간(시간)",
                            "late_minutes": "지각(분)",
                            "early_leave_minutes": "조퇴(분)",
                        }
                    )
                    st.dataframe(
                        style_date_dataframe(df_my_display, "날짜"),
                        use_container_width=True,
                    )
            else:
                st.error("❌ PIN 번호가 틀렸습니다.")

# ==========================================
# [모드 2] 🔒 점주 관리자 모드
# ==========================================
else:
    # 1. KeyError 방지를 위해 .get() 활용
    if not st.session_state.get("admin_logged_in", False):
        st.subheader("🔒 관리자 로그인")
        admin_pw_input = st.text_input("점주 비밀번호를 입력해 주세요", type="password")
        if st.button("🔑 로그인", type="primary"):
            current_admin_pw = get_admin_password()
            if verify_hash(admin_pw_input, current_admin_pw):
                st.session_state["admin_logged_in"] = True
                st.success("로그인 성공!")
                st.rerun()
            else:
                st.error("❌ 비밀번호가 올바르지 않습니다.")
    else:
        col_side1, col_side2 = st.sidebar.columns([2, 1])
        col_side1.success("🔑 점주 관리자 인증됨")
        if col_side2.button("🚪 로그아웃"):
            st.session_state["admin_logged_in"] = False
            st.rerun()

        # 대타 신청 건수 뱃지 생성
        pending_shifts = get_pending_shift_count()
        pending_badge = f" (🚨 {pending_shifts}건)" if pending_shifts > 0 else ""
        shift_menu_label = f"🔄 대타 신청 승인{pending_badge}"

        # 기본 점주 메뉴 목록
        DEFAULT_ADMIN_MENUS = [
            "📝 매출 분석 & 손익계산서(P&L)",
            "🚚 엠즈푸드 발주등록",
            "📈 종합 매출/비용 시각화 분석",
            shift_menu_label,
            "💸 지출 및 비용 관리",
            "🤝 알바생 인수인계 이력 점검",
            "🗑️ 원자재 폐기 이력 & 손실 점검",
            "📋 오픈/마감 체크리스트 점검",
            "⏰ 알바생 캘린더 스케줄 관리",
            "📦 재고 현황 & 원가 관리",
            "💰 전체 인건비 정산",
            "👥 직원 PIN & 시급 관리",
            "🔑 점주 비밀번호 변경",
            "📢 공지사항 수정",
            "💾 데이터 백업 및 복원",
            "⚠️ 데이터 초기화",
            "⚙️ 메뉴 & 항목 설정 관리",
        ]

        # DB에서 점주 커스텀 메뉴 불러오기
        try:
            menu_res = (
                supabase.table("app_settings")
                .select("value")
                .eq("key", "admin_menus")
                .execute()
            )
            if menu_res.data and isinstance(menu_res.data[0]["value"], list):
                raw_options = menu_res.data[0]["value"]
                # 2. DB에서 가져온 메뉴명 중 대타 승인 메뉴에 실시간 뱃지 적용
                admin_menu_options = [
                    shift_menu_label if item.startswith("🔄 대타 신청 승인") else item
                    for item in raw_options
                ]
            else:
                admin_menu_options = DEFAULT_ADMIN_MENUS
        except Exception:
            admin_menu_options = DEFAULT_ADMIN_MENUS

        admin_menu = st.sidebar.selectbox("점주 관리 메뉴", admin_menu_options)


    
          # =========================================================
        # [점주 메뉴 1] 매출 분석 & 손익계산서 (홀 / 배달 플랫폼별 구분)
        # =========================================================
        if admin_menu == "📝 매출 분석 & 손익계산서(P&L)":
            st.subheader("📝 매출 분석 및 관리")

            # DB 설정에서 배달 플랫폼 및 수수료율 불러오기
            del_data = get_setting(
                "delivery_platforms",
                [
                    {"플랫폼명": "배달의민족", "수수료율 (%)": 6.8, "기본라이더비": 3000},
                    {"플랫폼명": "쿠팡이츠", "수수료율 (%)": 9.8, "기본라이더비": 3000},
                    {"플랫폼명": "요기요", "수수료율 (%)": 12.5, "기본라이더비": 3000},
                    {"플랫폼명": "땡겨요", "수수료율 (%)": 2.0, "기본라이더비": 3000},
                    {"플랫폼명": "네이버주문", "수수료율 (%)": 1.65, "기본라이더비": 0},
                    {"플랫폼명": "기타", "수수료율 (%)": 0.0, "기본라이더비": 0},
                ],
            )

            fee_rate_dict = {}
            rider_fee_dict = {}
            for item in del_data:
                if isinstance(item, dict):
                    p_name = item.get("플랫폼명", "기타")
                    p_rate = safe_float(item.get("수수료율 (%)"), 0.0)
                    r_fee = safe_int(item.get("기본라이더비"), 3000)
                else:
                    p_name = str(item)
                    p_rate = 0.0
                    r_fee = 3000
                fee_rate_dict[p_name] = p_rate
                rider_fee_dict[p_name] = r_fee

            platform_list = list(fee_rate_dict.keys())
            if not platform_list:
                platform_list = ["배달의민족", "쿠팡이츠", "요기요", "땡겨요", "기타"]

            # 📅 공통 날짜 선택
            sales_date = get_korean_date_picker("매출 날짜 선택", key_prefix="sales_date_picker")

            # 기존 DB 데이터 조회
            existing_res = (
                supabase.table("daily_sales")
                .select("*")
                .eq("date", str(sales_date))
                .execute()
            )
            existing_sales = existing_res.data[0] if existing_res.data else {}

            # 홀 매출 초기값
            init_cash = safe_int(existing_sales.get("cash_sales"))
            init_card = safe_int(existing_sales.get("card_sales"))
            init_other = safe_int(existing_sales.get("other_sales"))
            init_reward = safe_int(existing_sales.get("reward_sales"))
            init_memo = existing_sales.get("memo") or ""

            # 배달 상세 초기값 불러오기
            init_delivery_details = existing_sales.get("delivery_details")
            if not init_delivery_details:
                if existing_sales.get("delivery_gross"):
                    init_delivery_details = [
                        {
                            "platform": existing_sales.get(
                                "delivery_platform", platform_list[0]
                            ),
                            "fee_rate": safe_float(
                                existing_sales.get("delivery_fee_rate"), 0.0
                            ),
                            "gross": safe_int(existing_sales.get("delivery_gross")),
                            "count": safe_int(existing_sales.get("delivery_count")),
                            "rider_fee_per_order": safe_int(
                                existing_sales.get("rider_fee_per_order"), 3000
                            ),
                        }
                    ]
                else:
                    init_delivery_details = [
                        {
                            "platform": platform_list[0],
                            "fee_rate": fee_rate_dict.get(platform_list[0], 0.0),
                            "gross": 0,
                            "count": 0,
                            "rider_fee_per_order": rider_fee_dict.get(
                                platform_list[0], 3000
                            ),
                        }
                    ]

            # 메인 탭 구성
            tab_input, tab_history = st.tabs(["📝 매출 입력", "📋 매출 내역"])

            # =========================================================
            # [TAB 1] 매출 입력 및 저장
            # =========================================================
            with tab_input:
                with st.expander("➕ 일별 세부 매출 입력 및 관리", expanded=True):
                    subtab_hall, subtab_delivery = st.tabs(
                        ["🏢 홀 매출 입력", "🛵 배달 플랫폼별 매출 입력"]
                    )

                    # [SUBTAB 1] 홀 매출 입력
                    with subtab_hall:
                        st.markdown("##### 🏢 홀 매출 세부 항목")
                        col_m1, col_m2, col_m3, col_m4 = st.columns(4)
                        cash_sales = col_m1.number_input(
                            "💵 현금 매출 (원)",
                            min_value=0,
                            step=1000,
                            value=init_cash,
                            key=f"cash_{sales_date}",
                        )
                        card_sales = col_m2.number_input(
                            "💳 카드 매출 (원)",
                            min_value=0,
                            step=10000,
                            value=init_card,
                            key=f"card_{sales_date}",
                        )
                        other_sales = col_m3.number_input(
                            "📦 기타 매출 (원)",
                            min_value=0,
                            step=1000,
                            value=init_other,
                            key=f"other_{sales_date}",
                        )
                        reward_sales = col_m4.number_input(
                            "🎁 리워드/쿠폰 (원)",
                            min_value=0,
                            step=1000,
                            value=init_reward,
                            key=f"reward_{sales_date}",
                        )

                        hall_sales_calc = cash_sales + card_sales + other_sales + reward_sales
                        st.markdown(f"👉 **홀 매출 합계:** `{hall_sales_calc:,}` 원")

                    # [SUBTAB 2] 배달 플랫폼별 매출 입력
                    with subtab_delivery:
                        st.markdown("##### 🛵 배달 플랫폼별 상세 입력")

                        state_key = f"del_entries_{sales_date}"
                        if state_key not in st.session_state:
                            st.session_state[state_key] = init_delivery_details

                        total_delivery_gross = 0
                        total_delivery_net = 0
                        total_platform_fee = 0
                        total_rider_fee = 0
                        total_delivery_count = 0
                        saved_delivery_details = []

                        for idx, entry in enumerate(st.session_state[state_key]):
                            st.caption(f"📌 **플랫폼 #{idx+1}**")
                            col_d1, col_d2, col_d3, col_d4, col_d5 = st.columns([2, 1.2, 2, 1.5, 2.2])

                            p_key = f"p_{sales_date}_{idx}"
                            r_key = f"r_{sales_date}_{idx}"
                            g_key = f"g_{sales_date}_{idx}"
                            c_key = f"c_{sales_date}_{idx}"
                            rf_key = f"rf_{sales_date}_{idx}"

                            p_sel = col_d1.selectbox(
                                "플랫폼 선택",
                                platform_list,
                                index=(
                                    platform_list.index(entry["platform"])
                                    if entry.get("platform") in platform_list
                                    else 0
                                ),
                                key=p_key,
                            )

                            if p_sel != entry.get("platform"):
                                entry["platform"] = p_sel
                                entry["fee_rate"] = fee_rate_dict.get(p_sel, 0.0)
                                entry["rider_fee_per_order"] = rider_fee_dict.get(p_sel, 3000)
                                st.session_state[r_key] = float(entry["fee_rate"])
                                st.session_state[rf_key] = int(entry["rider_fee_per_order"])
                                st.rerun()

                            default_rate = fee_rate_dict.get(p_sel, 0.0)
                            default_rider_fee = rider_fee_dict.get(p_sel, 3000)

                            f_rate = col_d2.number_input(
                                "중개수수료(%)",
                                min_value=0.0,
                                max_value=100.0,
                                value=float(entry.get("fee_rate", default_rate)),
                                step=0.1,
                                key=r_key,
                            )
                            entry["fee_rate"] = f_rate

                            d_gross = col_d3.number_input(
                                "총 매출액(원)",
                                min_value=0,
                                value=int(entry.get("gross", 0)),
                                step=1000,
                                key=g_key,
                            )
                            entry["gross"] = d_gross

                            d_cnt = col_d4.number_input(
                                "배달 건수(건)",
                                min_value=0,
                                value=int(entry.get("count", 0)),
                                step=1,
                                key=c_key,
                            )
                            entry["count"] = d_cnt

                            r_fee_per_order = col_d5.number_input(
                                "건당 라이더 수수료(원)",
                                min_value=0,
                                value=int(entry.get("rider_fee_per_order", default_rider_fee)),
                                step=100,
                                key=rf_key,
                                help="배달 건당 차감되는 라이더 수수료 금액입니다.",
                            )
                            entry["rider_fee_per_order"] = r_fee_per_order

                            p_fee = int(d_gross * (f_rate / 100.0))
                            r_fee_tot = int(d_cnt * r_fee_per_order)
                            d_net = d_gross - p_fee - r_fee_tot

                            total_delivery_gross += d_gross
                            total_platform_fee += p_fee
                            total_rider_fee += r_fee_tot
                            total_delivery_count += d_cnt
                            total_delivery_net += d_net

                            saved_delivery_details.append(
                                {
                                    "platform": p_sel,
                                    "fee_rate": f_rate,
                                    "gross": d_gross,
                                    "count": d_cnt,
                                    "rider_fee_per_order": r_fee_per_order,
                                    "platform_fee": p_fee,
                                    "rider_fee_tot": r_fee_tot,
                                    "net": d_net,
                                }
                            )
                            st.divider()

                        col_btn1, col_btn2 = st.columns([1, 4])
                        with col_btn1:
                            if st.button("➕ 플랫폼 추가", key=f"add_p_{sales_date}"):
                                st.session_state[state_key].append(
                                    {
                                        "platform": platform_list[0],
                                        "fee_rate": fee_rate_dict.get(platform_list[0], 0.0),
                                        "gross": 0,
                                        "count": 0,
                                        "rider_fee_per_order": rider_fee_dict.get(platform_list[0], 3000),
                                    }
                                )
                                st.rerun()
                        with col_btn2:
                            if (
                                len(st.session_state[state_key]) > 1
                                and st.button("➖ 마지막 플랫폼 삭제", key=f"del_p_{sales_date}")
                            ):
                                st.session_state[state_key].pop()
                                st.rerun()

                        st.info(
                            f"🛵 **배달 정산 요약:** 총 배달 매출 `{total_delivery_gross:,}`원 - "
                            f"수수료 차감액 `{total_platform_fee + total_rider_fee:,}`원 (중개수수료: {total_platform_fee:,}원 / "
                            f"라이더비: {total_rider_fee:,}원 [{total_delivery_count:,}건]) "
                            f"= **배달 순매출 `{total_delivery_net:,}`원**"
                        )

                # ---------------------------------------------------------
                # 💾 매출 저장 (중복 요약 지표 제거)
                # ---------------------------------------------------------
                total_sales_calc = hall_sales_calc + total_delivery_net

                sales_memo = st.text_input(
                    "📝 메모 / 특이사항", value=init_memo, key=f"memo_{sales_date}"
                )

                if st.button("💾 매출 저장", type="primary", use_container_width=True, key=f"save_btn_{sales_date}"):
                    main_platform = (
                        saved_delivery_details[0]["platform"]
                        if saved_delivery_details
                        else "배달"
                    )

                    supabase.table("daily_sales").upsert(
                        {
                            "date": str(sales_date),
                            "cash_sales": cash_sales,
                            "card_sales": card_sales,
                            "other_sales": other_sales,
                            "reward_sales": reward_sales,
                            "hall_sales": hall_sales_calc,
                            "delivery_platform": main_platform,
                            "delivery_gross": total_delivery_gross,
                            "delivery_fee_rate": saved_delivery_details[0]["fee_rate"]
                            if saved_delivery_details
                            else 0,
                            "delivery_sales": total_delivery_net,
                            "delivery_count": total_delivery_count,
                            "rider_fee": total_rider_fee,
                            "delivery_details": saved_delivery_details,
                            "sales_amount": total_sales_calc,
                            "memo": sales_memo,
                        },
                        on_conflict="date",
                    ).execute()

                    st.success(
                        f"✅ [{sales_date}] 매출 기록이 성공적으로 저장되었습니다! (총 매출: {total_sales_calc:,}원)"
                    )
                    st.rerun()

            # =========================================================
            # [TAB 2] 매출 내역 (선택 날짜 월 내역 조회)
            # =========================================================
            with tab_history:
                import calendar

                start_of_month = sales_date.replace(day=1)
                _, last_day = calendar.monthrange(sales_date.year, sales_date.month)
                end_of_month = sales_date.replace(day=last_day)

                st.markdown(
                    f"##### 📋 [{sales_date.strftime('%Y년 %m월')}] 저장된 매출 내역 조회"
                )
                all_sales_res = (
                    supabase.table("daily_sales")
                    .select("*")
                    .gte("date", str(start_of_month))
                    .lte("date", str(end_of_month))
                    .order("date", desc=True)
                    .execute()
                )
                all_sales_data = all_sales_res.data if all_sales_res.data else []

                if all_sales_data:
                    display_list = []
                    for row in all_sales_data:
                        display_list.append(
                            {
                                "날짜": row.get("date"),
                                "총 매출": safe_int(row.get("sales_amount")),
                                "홀 매출 합계": safe_int(row.get("hall_sales")),
                                "현금": safe_int(row.get("cash_sales")),
                                "카드": safe_int(row.get("card_sales")),
                                "기타": safe_int(row.get("other_sales")),
                                "리워드/쿠폰": safe_int(row.get("reward_sales")),
                                "배달 순매출 합계": safe_int(row.get("delivery_sales")),
                                "배달 건수": safe_int(row.get("delivery_count")),
                                "메모": row.get("memo") or "",
                            }
                        )
                    st.dataframe(
                        display_list,
                        column_config={
                            "총 매출": st.column_config.NumberColumn(format="%d 원"),
                            "홀 매출 합계": st.column_config.NumberColumn(format="%d 원"),
                            "현금": st.column_config.NumberColumn(format="%d 원"),
                            "카드": st.column_config.NumberColumn(format="%d 원"),
                            "기타": st.column_config.NumberColumn(format="%d 원"),
                            "리워드/쿠폰": st.column_config.NumberColumn(format="%d 원"),
                            "배달 순매출 합계": st.column_config.NumberColumn(format="%d 원"),
                            "배달 건수": st.column_config.NumberColumn(format="%d 건"),
                        },
                        use_container_width=True,
                        hide_index=True,
                    )
                else:
                    st.info(f"{sales_date.strftime('%Y년 %m월')}에 등록된 매출 내역이 없습니다.")

# =========================================================
        # [점주 메뉴 2] 엠즈푸드 발주 등록 (DB 컬럼명 'day' 기준)
        # =========================================================
        elif admin_menu == "🚚 엠즈푸드 발주등록":
            st.subheader("📦 엠즈푸드 발주 등록 & 내역 관리")

            with st.expander("➕ 새로운 엠즈푸드 발주 내역 입력", expanded=True):
                col_m1, col_m2, col_m3 = st.columns([2, 2, 3])
                with col_m1:
                    order_date = get_korean_date_picker("📅 발주 날짜", key_prefix="mfood_date_picker")
                item_name = col_m2.text_input("🏷️ 품목명 / 내역", placeholder="예: 원두, 우유, 파우더 등", key="mfood_item_input")
                order_amount = col_m3.number_input("💵 발주 금액 (원)", min_value=0, step=1000, key="mfood_amount_input")

                order_memo = st.text_input("📝 비고 / 메모", key="mfood_memo_input")

                if st.button("💾 발주 내역 저장", type="primary", use_container_width=True, key="mfood_save_btn"):
                    if order_amount <= 0:
                        st.warning("⚠️ 발주 금액을 0원 이상 입력해 주세요.")
                    elif not item_name.strip():
                        st.warning("⚠️ 품목명 또는 내역을 입력해 주세요.")
                    else:
                        date_str = str(order_date)
                        supabase.table("mfood_orders").insert({
                            "year_month": date_str[:7],
                            "day": date_str,
                            "item_name": item_name,
                            "amount": int(order_amount),
                            "memo": order_memo
                        }).execute()

                        st.success(f"✅ [{order_date}] {item_name} ({int(order_amount):,}원) 발주 내역이 저장되었습니다!")
                        st.rerun()

            st.write("---")
            st.subheader("📊 엠즈푸드 발주 내역 조회 및 삭제")

            # Supabase DB에서 발주 내역 불러오기
            mfood_res = (
                supabase.table("mfood_orders")
                .select("*")
                .order("day", desc=True)
                .execute()
            )
            mfood_list = mfood_res.data if mfood_res and mfood_res.data else []
            df_mfood = pd.DataFrame(mfood_list) if mfood_list else pd.DataFrame()

            if not df_mfood.empty:
                # 'year_month' 컬럼 누락 방지 및 추출
                if "day" in df_mfood.columns:
                    df_mfood["year_month"] = df_mfood["day"].astype(str).str[:7]

                # 등록된 연월(YYYY-MM) 목록 추출
                available_yms = sorted(df_mfood["year_month"].dropna().unique(), reverse=True)

                col_sel1, col_sel2 = st.columns([2, 3])
                selected_ym = col_sel1.selectbox("📅 조회할 월 선택", available_yms, key="mfood_ym_select")

                # 선택된 월 데이터 필터링
                df_filtered = df_mfood[df_mfood["year_month"] == selected_ym].copy()

                # DB 컬럼 변경 전 고유 ID 컬럼 찾아두기
                raw_id_col = None
                for c in ["id", "ID", "mfood_id", "order_id"]:
                    if c in df_filtered.columns:
                        raw_id_col = c
                        break

                column_mapping = {
                    "id": "ID",
                    "day": "날짜",
                    "item_name": "품목명",
                    "amount": "발주금액(원)",
                    "memo": "메모"
                }
                df_filtered = df_filtered.rename(columns={k: v for k, v in column_mapping.items() if k in df_filtered.columns})

                total_mfood = safe_int(df_filtered["발주금액(원)"].sum()) if "발주금액(원)" in df_filtered.columns else 0
                st.metric(f"📦 {selected_ym} 총 발주 합계", f"{total_mfood:,} 원")

                display_cols = [c for c in ["날짜", "품목명", "발주금액(원)", "메모"] if c in df_filtered.columns]

                st.dataframe(
                    style_date_dataframe(df_filtered[display_cols], "날짜"),
                    column_config={
                        "발주금액(원)": st.column_config.NumberColumn(format="%,d 원"),
                    },
                    use_container_width=True
                )

                # 💡 유연한 삭제 로직
                with st.expander("🗑️ 발주 내역 삭제"):
                    if not df_filtered.empty:
                        # 1. 고유 ID가 존재하는 경우 (ID 기반 삭제)
                        if raw_id_col or "ID" in df_filtered.columns:
                            target_id_col = "ID" if "ID" in df_filtered.columns else raw_id_col
                            delete_options = {
                                row[target_id_col]: f"[{row.get('날짜', '')}] {row.get('품목명', '')} - {safe_int(row.get('발주금액(원)')):,}원"
                                for _, row in df_filtered.iterrows()
                            }

                            selected_id = st.selectbox(
                                "삭제할 발주 항목 선택",
                                options=list(delete_options.keys()),
                                format_func=lambda x: delete_options[x],
                                key=f"mfood_del_select_{selected_ym}"
                            )

                            if st.button("❌ 선택한 발주 내역 삭제", type="secondary", key=f"mfood_del_btn_{selected_ym}"):
                                try:
                                    db_pk = raw_id_col if raw_id_col else "id"
                                    supabase.table("mfood_orders").delete().eq(db_pk, selected_id).execute()
                                    st.success("해당 발주 내역이 성공적으로 삭제되었습니다.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"⚠️ 삭제 실패: {e}")

                        # 2. DB에 ID 컬럼이 없는 경우 (날짜+품목명+금액 조건으로 삭제)
                        else:
                            delete_options = {
                                idx: f"[{row.get('날짜', '')}] {row.get('품목명', '')} - {safe_int(row.get('발주금액(원)')):,}원"
                                for idx, row in df_filtered.iterrows()
                            }

                            selected_idx = st.selectbox(
                                "삭제할 발주 항목 선택",
                                options=list(delete_options.keys()),
                                format_func=lambda x: delete_options[x],
                                key=f"mfood_del_select_idx_{selected_ym}"
                            )
                            target_row = df_filtered.loc[selected_idx]

                            if st.button("❌ 선택한 발주 내역 삭제", type="secondary", key=f"mfood_del_btn_idx_{selected_ym}"):
                                try:
                                    supabase.table("mfood_orders").delete()\
                                        .eq("day", str(target_row.get('날짜')))\
                                        .eq("item_name", str(target_row.get('품목명')))\
                                        .eq("amount", int(target_row.get('발주금액(원)')))\
                                        .execute()
                                    st.success("해당 발주 내역이 성공적으로 삭제되었습니다.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"⚠️ 삭제 실패: {e}")
                    else:
                        st.info("해당 월에는 삭제할 발주 내역이 없습니다.")
            else:
                st.info("💡 등록된 엠즈푸드 발주 내역이 없습니다. 위에서 새로운 발주 내역을 입력해 주세요.")     
       # =========================================================================
        # 3. 종합 매출/비용 시각화 분석
        # =========================================================================
        elif admin_menu == "📈 종합 매출/비용 시각화 분석":
            st.subheader("📈 종합 매출/비용 & 순수익 시각화 분석")

            # ---------------------------------------------------------------------
            # 1. 일별 매출 데이터 조회
            # ---------------------------------------------------------------------
            try:
                sales_res = (
                    supabase.table("daily_sales")
                    .select("date, hall_sales, delivery_gross, delivery_fee_rate, delivery_count, rider_fee")
                    .order("date", desc=False)
                    .execute()
                )
                df_s = pd.DataFrame(sales_res.data) if sales_res and sales_res.data else pd.DataFrame()
            except Exception as e:
                df_s = pd.DataFrame()
                st.error(f"매출 데이터 로드 실패: {e}")

            # ---------------------------------------------------------------------
            # 2. 폐기 손실 데이터 조회
            # ---------------------------------------------------------------------
            try:
                waste_res = supabase.table("waste").select("date, item_name, loss_amount").execute()
                if waste_res and waste_res.data:
                    df_w_raw = pd.DataFrame(waste_res.data)
                    df_w_raw["loss_amount"] = pd.to_numeric(df_w_raw["loss_amount"], errors="coerce").fillna(0)
                    df_waste_chart = (
                        df_w_raw.groupby("item_name", as_index=False)["loss_amount"]
                        .sum()
                        .rename(columns={"loss_amount": "total_loss"})
                    )
                else:
                    df_w_raw = pd.DataFrame()
                    df_waste_chart = pd.DataFrame(columns=["item_name", "total_loss"])
            except Exception:
                df_w_raw = pd.DataFrame()
                df_waste_chart = pd.DataFrame(columns=["item_name", "total_loss"])

            # ---------------------------------------------------------------------
            # 3. 엠즈푸드 발주 데이터 조회
            # ---------------------------------------------------------------------
            try:
                mf_res = supabase.table("mfood_orders").select("year_month, amount").execute()
                if mf_res and mf_res.data:
                    df_mf_raw = pd.DataFrame(mf_res.data)
                    df_mf_raw["amount"] = pd.to_numeric(df_mf_raw["amount"], errors="coerce").fillna(0)
                    df_mf_chart = (
                        df_mf_raw.groupby("year_month", as_index=False)["amount"]
                        .sum()
                        .rename(columns={"amount": "total_mf"})
                        .sort_values("year_month")
                    )
                else:
                    df_mf_raw = pd.DataFrame()
                    df_mf_chart = pd.DataFrame(columns=["year_month", "total_mf"])
            except Exception:
                df_mf_raw = pd.DataFrame()
                df_mf_chart = pd.DataFrame(columns=["year_month", "total_mf"])

            # ---------------------------------------------------------------------
            # 4. 기타 지출(expenses) 데이터 조회 (테이블 존재 시)
            # ---------------------------------------------------------------------
            try:
                exp_res = supabase.table("expenses").select("date, amount").execute()
                if exp_res and exp_res.data:
                    df_exp_raw = pd.DataFrame(exp_res.data)
                    df_exp_raw["amount"] = pd.to_numeric(df_exp_raw["amount"], errors="coerce").fillna(0)
                else:
                    df_exp_raw = pd.DataFrame()
            except Exception:
                df_exp_raw = pd.DataFrame()

            # ---------------------------------------------------------------------
            # 5. 인건비 데이터 계산
            # ---------------------------------------------------------------------
            total_labor_cost = 0
            try:
                staff_dict = get_staff_info()
                for name in staff_dict.keys():
                    res = calculate_person_summary(name)
                    if res and res.get("gross_pay", 0) > 0:
                        total_labor_cost += res["gross_pay"]
            except Exception:
                total_labor_cost = 0

            # ---------------------------------------------------------------------
            # 6. 매출 데이터 전처리
            # ---------------------------------------------------------------------
            if not df_s.empty:
                for col in ["hall_sales", "delivery_gross", "delivery_fee_rate", "delivery_count", "rider_fee"]:
                    if col in df_s.columns:
                        df_s[col] = pd.to_numeric(df_s[col], errors="coerce").fillna(0)

                fee_amt = (df_s["delivery_gross"] * (df_s["delivery_fee_rate"] / 100.0)).astype(int)
                rider_amt = df_s["delivery_count"] * df_s["rider_fee"]
                deliv_net = df_s["delivery_gross"] - fee_amt - rider_amt
                df_s["sales_amount"] = df_s["hall_sales"] + deliv_net
                df_s["date"] = pd.to_datetime(df_s["date"])
                df_s["year_month"] = df_s["date"].dt.strftime("%Y-%m")

            # ---------------------------------------------------------------------
            # 7. 월별 매출/지출/순수익 집계
            # ---------------------------------------------------------------------
            all_yms = set()
            if not df_s.empty:
                all_yms.update(df_s["year_month"].unique())
            if not df_mf_chart.empty:
                all_yms.update(df_mf_chart["year_month"].unique())

            sorted_yms = sorted(list(all_yms))
            monthly_summary_list = []

            # 폐기 및 기타 지출 날짜 변환
            if not df_w_raw.empty and "date" in df_w_raw.columns:
                df_w_raw["date"] = pd.to_datetime(df_w_raw["date"], errors="coerce")
                df_w_raw["year_month"] = df_w_raw["date"].dt.strftime("%Y-%m")

            if not df_exp_raw.empty and "date" in df_exp_raw.columns:
                df_exp_raw["date"] = pd.to_datetime(df_exp_raw["date"], errors="coerce")
                df_exp_raw["year_month"] = df_exp_raw["date"].dt.strftime("%Y-%m")

            for ym in sorted_yms:
                # 1) 총 매출액
                s_amt = df_s[df_s["year_month"] == ym]["sales_amount"].sum() if not df_s.empty else 0
                
                # 2) 지출 항목들
                mf_amt = df_mf_chart[df_mf_chart["year_month"] == ym]["total_mf"].sum() if not df_mf_chart.empty else 0
                w_amt = df_w_raw[df_w_raw["year_month"] == ym]["loss_amount"].sum() if not df_w_raw.empty and "year_month" in df_w_raw.columns else 0
                exp_amt = df_exp_raw[df_exp_raw["year_month"] == ym]["amount"].sum() if not df_exp_raw.empty and "year_month" in df_exp_raw.columns else 0
                l_amt = total_labor_cost / max(1, len(sorted_yms)) if total_labor_cost > 0 else 0

                # 3) 총 지출 비용 합산 & 순수익 계산 (마감 차감)
                total_cost = mf_amt + w_amt + l_amt + exp_amt
                net_profit = s_amt - total_cost
                profit_rate = (net_profit / s_amt * 100) if s_amt > 0 else 0

                monthly_summary_list.append({
                    "year_month": ym,
                    "sales_amount": s_amt,
                    "mfood_cost": mf_amt,
                    "waste_cost": w_amt,
                    "labor_cost": l_amt,
                    "other_cost": exp_amt,
                    "total_cost": total_cost,
                    "net_profit": net_profit,
                    "profit_rate": profit_rate
                })

            df_monthly_summary = pd.DataFrame(monthly_summary_list)

            # ---------------------------------------------------------------------
            # 8. 탭 구성
            # ---------------------------------------------------------------------
            tab_v0, tab_v1, tab_v2, tab_v3, tab_v4 = st.tabs([
                "💵 순수익 분석 & 매출/비용 비교",
                "📊 일별/월별/요일별 매출 추이",
                "🚚 엠즈푸드 발주 지출 추이",
                "🗑️ 품목별 폐기 손실 비중",
                "💰 직원별 인건비 비중",
            ])

            # =====================================================================
            # TAB 0: 💵 순수익 분석 & 매출/비용 비교
            # =====================================================================
            with tab_v0:
                st.markdown("#### 💵 월별 매출 vs 지출 비용 차감 및 순수익")

                if not df_monthly_summary.empty:
                    total_sales_all = df_monthly_summary["sales_amount"].sum()
                    total_cost_all = df_monthly_summary["total_cost"].sum()
                    total_profit_all = df_monthly_summary["net_profit"].sum()
                    avg_profit_rate = (total_profit_all / total_sales_all * 100) if total_sales_all > 0 else 0

                    # 1) 요약 지표 카드
                    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
                    col_m1.metric("총 순매출액 (+)", f"{int(total_sales_all):,} 원")
                    col_m2.metric("총 지출 비용 (-)", f"{int(total_cost_all):,} 원")
                    col_m3.metric("최종 순수익 (=)", f"{int(total_profit_all):,} 원", delta=f"마진율 {avg_profit_rate:.1f}%")
                    col_m4.metric("평균 순수익률", f"{avg_profit_rate:.1f} %")

                    st.write("---")

                    # 2) 직관적 비교 차트 (매출은 양수(+), 지출은 음수(-)로 표현)
                    fig_combo = go.Figure()

                    # 매출 막대 (+)
                    fig_combo.add_trace(go.Bar(
                        x=df_monthly_summary["year_month"],
                        y=df_monthly_summary["sales_amount"],
                        name="총 매출액 (+)",
                        marker_color="#2ecc71"
                    ))

                    # 총 지출 막대 (마이너스 표현)
                    fig_combo.add_trace(go.Bar(
                        x=df_monthly_summary["year_month"],
                        y=-df_monthly_summary["total_cost"],  # 음수로 표현하여 차감 효과 강조
                        name="총 지출 비용 (-)",
                        marker_color="#e74c3c",
                        customdata=df_monthly_summary["total_cost"],
                        hovertemplate="<b>총 지출 비용</b>: -%{customdata:,.0f}원<extra></extra>"
                    ))

                    # 순수익 라인
                    fig_combo.add_trace(go.Scatter(
                        x=df_monthly_summary["year_month"],
                        y=df_monthly_summary["net_profit"],
                        name="최종 순수익 (=)",
                        mode="lines+markers+text",
                        text=[f"{int(v):,}원" for v in df_monthly_summary["net_profit"]],
                        textposition="top center",
                        line=dict(color="#f1c40f", width=3),
                        marker=dict(size=8)
                    ))

                    fig_combo.update_layout(
                        title="📊 매출(+) - 지출(-) = 순수익(=) 월별 비교 차트",
                        barmode="relative",
                        xaxis_title="년-월",
                        yaxis_title="금액 (원)",
                        hovermode="x unified",
                        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                    )
                    st.plotly_chart(fig_combo, use_container_width=True)

                    st.write("---")

                    # 3) 상세 요약 데이터프레임
                    st.markdown("#### 📋 월별 매출 / 차감 지출 항목 / 최종 순수익 내역")
                    df_display_summary = df_monthly_summary.copy()
                    df_display_summary["year_month"] = df_display_summary["year_month"].apply(
                        lambda x: f"{x.split('-')[0]}년 {int(x.split('-')[1]):02d}월" if "-" in str(x) else str(x)
                    )

                    st.dataframe(
                        df_display_summary,
                        column_config={
                            "year_month": "연월",
                            "sales_amount": st.column_config.NumberColumn("① 총 매출액 (+)", format="%d 원"),
                            "mfood_cost": st.column_config.NumberColumn("발주비 (-)", format="%d 원"),
                            "waste_cost": st.column_config.NumberColumn("폐기비 (-)", format="%d 원"),
                            "labor_cost": st.column_config.NumberColumn("인건비 (-)", format="%d 원"),
                            "other_cost": st.column_config.NumberColumn("기타지출 (-)", format="%d 원"),
                            "total_cost": st.column_config.NumberColumn("② 총 지출합계 (-)", format="%d 원"),
                            "net_profit": st.column_config.NumberColumn("③ 최종 순수익 (①-②)", format="%d 원"),
                            "profit_rate": st.column_config.NumberColumn("순수익률", format="%.1f %%"),
                        },
                        use_container_width=True,
                        hide_index=True
                    )
                else:
                    st.info("비교 분석할 집계 데이터가 충분하지 않습니다.")

            # =====================================================================
            # TAB 1: 📊 일별/월별/요일별 매출 추이
            # =====================================================================
            with tab_v1:
                if not df_s.empty and "date" in df_s.columns:
                    fig_line = px.line(
                        df_s,
                        x="date",
                        y="sales_amount",
                        title="📈 일별 매출 추이",
                        labels={"date": "날짜", "sales_amount": "매출액 (원)"},
                        markers=True,
                    )
                    fig_line.update_traces(
                        line_color="#FFC700",
                        hovertemplate="<b>날짜</b>: %{x|%Y년 %m월 %d일}<br><b>매출액</b>: %{y:,.0f}원<extra></extra>",
                    )
                    fig_line.update_xaxes(title_text="날짜", tickformat="%Y-%m-%d")
                    fig_line.update_yaxes(title_text="매출액 (원)")
                    st.plotly_chart(fig_line, use_container_width=True)

                    st.write("---")

                    monthly_sales = df_s.groupby("year_month", as_index=False)["sales_amount"].sum()
                    monthly_sales["연월_한글"] = monthly_sales["year_month"].apply(
                        lambda x: f"{x.split('-')[0]}년 {int(x.split('-')[1]):02d}월" if "-" in str(x) else str(x)
                    )

                    fig_monthly = px.bar(
                        monthly_sales,
                        x="연월_한글",
                        y="sales_amount",
                        title="📅 월별 총 매출 추이",
                        labels={"연월_한글": "년-월", "sales_amount": "총 매출액 (원)"},
                        text_auto=",.0f",
                    )
                    fig_monthly.update_traces(
                        marker_color="#FF9900",
                        hovertemplate="<b>월</b>: %{x}<br><b>총 매출액</b>: %{y:,.0f}원<extra></extra>",
                    )
                    fig_monthly.update_xaxes(title_text="년-월")
                    fig_monthly.update_yaxes(title_text="총 매출액 (원)")
                    st.plotly_chart(fig_monthly, use_container_width=True)

                    st.write("---")

                    df_s["요일"] = df_s["date"].dt.day_name()
                    weekday_map = {
                        "Monday": "월요일", "Tuesday": "화요일", "Wednesday": "수요일",
                        "Thursday": "목요일", "Friday": "금요일", "Saturday": "토요일", "Sunday": "일요일"
                    }
                    df_s["요일"] = df_s["요일"].map(weekday_map)
                    day_order = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
                    avg_sales = (
                        df_s.groupby("요일")["sales_amount"]
                        .mean()
                        .reindex(day_order)
                        .reset_index()
                    )

                    fig_bar = px.bar(
                        avg_sales,
                        x="요일",
                        y="sales_amount",
                        title="🗓️ 요일별 평균 매출액",
                        labels={"sales_amount": "평균 매출액 (원)", "요일": "요일"},
                        color="sales_amount",
                        color_continuous_scale="Viridis",
                    )
                    fig_bar.update_traces(
                        hovertemplate="<b>요일</b>: %{x}<br><b>평균 매출액</b>: %{y:,.0f}원<extra></extra>"
                    )
                    fig_bar.update_xaxes(title_text="요일")
                    fig_bar.update_yaxes(title_text="평균 매출액 (원)")
                    fig_bar.update_layout(coloraxis_colorbar=dict(title="매출 (원)"))
                    st.plotly_chart(fig_bar, use_container_width=True)
                else:
                    st.info("등록된 매출 데이터가 없습니다.")

            # =====================================================================
            # TAB 2: 🚚 엠즈푸드 발주 지출 추이
            # =====================================================================
            with tab_v2:
                if not df_mf_chart.empty and df_mf_chart["total_mf"].sum() > 0:
                    def format_ym(ym_str):
                        try:
                            parts = ym_str.split("-")
                            return f"{parts[0]}년 {int(parts[1]):02d}월"
                        except Exception:
                            return str(ym_str)

                    df_mf_chart["연월_한글"] = df_mf_chart["year_month"].apply(format_ym)

                    fig_mf = px.bar(
                        df_mf_chart,
                        x="연월_한글",
                        y="total_mf",
                        title="🚚 월별 엠즈푸드 발주 지출액 추이",
                        labels={"연월_한글": "년-월", "total_mf": "발주 지출액 (원)"},
                        text_auto=",.0f",
                    )
                    fig_mf.update_traces(
                        marker_color="#1890ff",
                        hovertemplate="<b>월</b>: %{x}<br><b>발주 지출액</b>: %{y:,.0f}원<extra></extra>",
                    )
                    fig_mf.update_xaxes(title_text="년-월")
                    fig_mf.update_yaxes(title_text="발주 지출액 (원)")
                    st.plotly_chart(fig_mf, use_container_width=True)
                else:
                    st.info("등록된 엠즈푸드 발주 지출 데이터가 없거나 0원입니다.")

            # =====================================================================
            # TAB 3: 🗑️ 품목별 폐기 손실 비중
            # =====================================================================
            with tab_v3:
                if not df_waste_chart.empty and df_waste_chart["total_loss"].sum() > 0:
                    fig_pie = px.pie(
                        df_waste_chart,
                        names="item_name",
                        values="total_loss",
                        title="🗑️ 원자재 품목별 폐기 손실 금액 비중",
                        hole=0.4,
                        labels={"item_name": "품목명", "total_loss": "손실 금액 (원)"},
                    )
                    fig_pie.update_traces(
                        hovertemplate="<b>품목명</b>: %{label}<br><b>손실 금액</b>: %{value:,.0f}원 (%{percent})<extra></extra>"
                    )
                    st.plotly_chart(fig_pie, use_container_width=True)
                else:
                    st.info("등록된 폐기 손실 데이터가 없거나 금액이 0원입니다.")

            # =====================================================================
            # TAB 4: 💰 직원별 인건비 비중
            # =====================================================================
            with tab_v4:
                try:
                    staff_dict = get_staff_info()
                    labor_data = []
                    for name in staff_dict.keys():
                        res = calculate_person_summary(name)
                        if res and res.get("gross_pay", 0) > 0:
                            labor_data.append({"직원명": name, "세전총급여": res["gross_pay"]})

                    if labor_data:
                        df_labor_chart = pd.DataFrame(labor_data)
                        fig_donut = px.pie(
                            df_labor_chart,
                            names="직원명",
                            values="세전총급여",
                            title="💰 직원별 총 급여(인건비) 비중",
                            hole=0.4,
                            labels={"직원명": "직원명", "세전총급여": "세전 총급여 (원)"},
                        )
                        fig_donut.update_traces(
                            hovertemplate="<b>직원명</b>: %{label}<br><b>세전 총급여</b>: %{value:,.0f}원 (%{percent})<extra></extra>"
                        )
                        st.plotly_chart(fig_donut, use_container_width=True)
                    else:
                        st.info("정산할 근무 기록이 없습니다.")
                except Exception as e:
                    st.warning(f"인건비 계산 중 오류가 발생했습니다: {e}")
    

        # =========================================================================
        # 4. 지출 및 비용 관리 (독립 메뉴 처리)
        # =========================================================================
        elif "지출" in admin_menu or "비용" in admin_menu:
            st.subheader("💸 매장 지출 및 비용 관리 (점주 전용)")

            tab_exp_add, tab_exp_list = st.tabs(["➕ 지출 입력", "📊 지출 내역 및 조회"])

            with tab_exp_add:
                st.write("#### 📝 신규 지출 등록")
                default_exp_items = ["원부자재(원두/시럽 등)", "임대료/공과금", "인건비", "소모품/비품", "수리/유지보수", "마케팅/홍보", "기타"]
                exp_items = get_setting("expense_categories", default_exp_items)

                with st.form("expense_form", clear_on_submit=True):
                    col_e1, col_e2 = st.columns(2)
                    exp_date = col_e1.date_input("지출 날짜", datetime.date.today())
                    exp_item_selected = col_e2.selectbox("지출 항목", exp_items)

                    col_e3, col_e4 = st.columns(2)
                    exp_amount = col_e3.number_input("지출 금액 (원)", min_value=0, step=1000, value=0)
                    exp_method = col_e4.selectbox("결제 수단", ["카드", "계좌이체", "현금", "기타"])

                    exp_memo = st.text_input("비고 / 메모", placeholder="예: OO유통 입금 완료")

                    if st.form_submit_button("💰 지출 내역 저장", type="primary", use_container_width=True):
                        if exp_amount > 0:
                            now_str = datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
                            try:
                                supabase.table("expenses").insert({
                                    "date": str(exp_date),
                                    "category": exp_item_selected,
                                    "item_name": exp_item_selected,
                                    "amount": exp_amount,
                                    "payment_method": exp_method,
                                    "memo": exp_memo.strip(),
                                    "created_at": now_str
                                }).execute()
                                st.success(f"✅ [{exp_date}] {exp_item_selected} ({exp_amount:,}원) 지출 내역이 저장되었습니다.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ 저장 중 오류 발생: {e}")
                        else:
                            st.warning("⚠️ 0원 이상의 지출 금액을 올바르게 입력해 주세요.")

            with tab_exp_list:
                st.write("#### 📅 지출 내역 조회 및 관리")
                try:
                    res_exp = supabase.table("expenses").select("*").order("date", desc=True).execute()
                    exp_list = res_exp.data if res_exp and res_exp.data else []

                    if exp_list:
                        df_exp = pd.DataFrame(exp_list)
                        df_exp["year_month"] = df_exp["date"].astype(str).str[:7]

                        col_f1, col_f2 = st.columns(2)
                        
                        available_yms = ["전체"] + sorted(df_exp["year_month"].dropna().unique(), reverse=True)
                        selected_ym = col_f1.selectbox("📅 조회 월 선택", available_yms, key="sb_exp_month_filter")

                        available_cats = ["전체"] + sorted(df_exp["category"].dropna().unique())
                        selected_cat = col_f2.selectbox("🏷️ 지출 항목 선택", available_cats, key="sb_exp_cat_filter")

                        # 필터링 로직 (특정 항목 선택 시 전체 기간 조회)
                        df_filtered = df_exp.copy()
                        if selected_cat != "전체":
                            df_filtered = df_filtered[df_filtered["category"] == selected_cat]
                            metric_title = f"📦 '{selected_cat}' 누적 지출 합계 (전체 기간)"
                        elif selected_ym != "전체":
                            df_filtered = df_filtered[df_filtered["year_month"] == selected_ym]
                            metric_title = f"📦 {selected_ym} 전체 지출 합계"
                        else:
                            metric_title = "📦 전체 지출 합계"

                        total_exp = df_filtered["amount"].sum() if not df_filtered.empty else 0
                        st.metric(metric_title, f"{total_exp:,} 원")

                        if not df_filtered.empty:
                            df_disp = df_filtered.copy()
                            df_disp.rename(columns={
                                "date": "날짜",
                                "category": "지출항목",
                                "amount": "금액(원)",
                                "payment_method": "결제수단",
                                "memo": "메모"
                            }, inplace=True)

                            df_disp["금액(원)"] = df_disp["금액(원)"].apply(lambda x: f"{x:,}")
                            cols_to_show = ["날짜", "지출항목", "금액(원)", "결제수단", "메모"]

                            st.dataframe(style_date_dataframe(df_disp[cols_to_show], "날짜"), use_container_width=True)

                            st.write("---")
                            st.write("#### 🗑️ 지출 내역 삭제")
                            del_exp_id = st.selectbox(
                                "삭제할 항목 선택",
                                df_filtered["id"].tolist(),
                                format_func=lambda x: f"[{df_filtered[df_filtered['id']==x]['date'].values[0]}] {df_filtered[df_filtered['id']==x]['category'].values[0]} ({df_filtered[df_filtered['id']==x]['amount'].values[0]:,}원)",
                                key="sb_del_exp_id"
                            )
                            if st.button("❌ 선택한 지출 내역 삭제", type="secondary", key="btn_del_exp"):
                                # 💡 .delete() 위치 수정
                                supabase.table("expenses").delete().eq("id", del_exp_id).execute()
                                st.success("지출 내역이 삭제되었습니다.")
                                st.rerun()
                        else:
                            st.info("💡 해당 조건에 부합하는 지출 내역이 없습니다.")
                    else:
                        st.info("💡 등록된 지출 내역이 없습니다.")
                except Exception as e:
                    st.warning(f"💡 Supabase 'expenses' 테이블 확인이 필요합니다. ({e})")


        # =========================================================================
        # 5. 대타 신청 승인
        # =========================================================================
        elif admin_menu.startswith("🔄 대타 신청 승인"):
            st.subheader("🔄 대타 신청 승인 관리")

            try:
                pending_req_res = (
                    supabase.table("shift_requests")
                    .select("*")
                    .eq("status", "대기중")
                    .order("shift_date", desc=False)
                    .execute()
                )
                pending_requests = pending_req_res.data or []
            except Exception:
                pending_requests = []

            if pending_requests:
                for req in pending_requests:
                    req_id = req.get("id")
                    app = req.get("applicant_name")
                    sub = req.get("substitute_name")
                    date_str = req.get("shift_date")
                    time_str = req.get("shift_time")
                    reason = req.get("reason")

                    st.warning(f"📌 **{app}** ➡️ **{sub}** 교대 요청 | 날짜: {date_str} ({time_str})")
                    st.write(f"사유: {reason}")
                    col_a1, col_a2 = st.columns(2)
                    if col_a1.button(f"✅ 승인 (#{req_id})", key=f"app_{req_id}"):
                        supabase.table("shift_requests").update({"status": "승인됨"}).eq("id", req_id).execute()
                        st.success("승인 처리되었습니다.")
                        st.rerun()
                    if col_a2.button(f"❌ 거절 (#{req_id})", key=f"rej_{req_id}"):
                        supabase.table("shift_requests").update({"status": "거절됨"}).eq("id", req_id).execute()
                        st.error("거절 처리되었습니다.")
                        st.rerun()
            else:
                st.success("대기 중인 대타 교대 신청이 없습니다.")

            st.write("---")
            st.subheader("📋 전체 대타 교대 이력 (오름차순)")
            try:
                res_all_req = (
                    supabase.table("shift_requests")
                    .select("id, applicant_name, substitute_name, shift_date, shift_time, reason, status")
                    .order("shift_date", desc=False)
                    .order("id", desc=False)
                    .execute()
                )
                df_all_req = pd.DataFrame(res_all_req.data) if res_all_req and res_all_req.data else pd.DataFrame()
            except Exception:
                df_all_req = pd.DataFrame()

            if not df_all_req.empty:
                df_all_req = df_all_req.rename(
                    columns={
                        "id": "번호",
                        "applicant_name": "신청자",
                        "substitute_name": "대타근무자",
                        "shift_date": "날짜",
                        "shift_time": "시간",
                        "reason": "사유",
                        "status": "상태",
                    }
                )
                st.dataframe(style_date_dataframe(df_all_req, "날짜"), use_container_width=True)
            else:
                st.info("전체 대타 교대 이력이 없습니다.")

   # =========================================================================
        # 6. 알바생 인수인계 이력 점검
        # =========================================================================
        elif admin_menu == "🤝 알바생 인수인계 이력 점검":
            st.subheader("🤝 알바생 근무 인수인계 이력 조회")

            try:
                res_ho = (
                    supabase.table("handover")
                    .select("id, sender_name, receiver_name, shift_type, content, created_at, is_read")
                    .order("id", desc=True)
                    .execute()
                )
                df_ho_admin = pd.DataFrame(res_ho.data) if res_ho and getattr(res_ho, "data", None) else pd.DataFrame()
            except Exception:
                df_ho_admin = pd.DataFrame()

            if not df_ho_admin.empty:
                # 'created_at'에서 일자(YYYY-MM-DD) 추출
                if "created_at" in df_ho_admin.columns:
                    df_ho_admin["일자"] = df_ho_admin["created_at"].astype(str).str[:10]

                if "is_read" in df_ho_admin.columns:
                    df_ho_admin["상태"] = df_ho_admin["is_read"].apply(
                        lambda x: "✅ 확인완료" if x in [1, True, "true", "True"] else "⏳ 미확인"
                    )
                else:
                    df_ho_admin["상태"] = "⏳ 미확인"

                df_ho_admin = df_ho_admin.rename(
                    columns={
                        "id": "번호",
                        "sender_name": "인계자",
                        "receiver_name": "인수자",
                        "shift_type": "교대유형",
                        "content": "인수인계내용",
                        "created_at": "작성시각",
                    }
                )

                # 💡 날짜 선택만으로 깔끔하게 조회
                col_date, _ = st.columns([2, 2])
                selected_date = col_date.date_input("📅 조회할 날짜 선택", datetime.date.today(), key="ho_date_picker")

                # 선택한 날짜 데이터 필터링
                df_filtered = df_ho_admin[df_ho_admin["일자"] == str(selected_date)].copy()

                # 컬럼 순서 정리
                desired_cols = ["번호", "일자", "인계자", "인수자", "교대유형", "인수인계내용", "작성시각", "상태"]
                existing_cols = [c for c in desired_cols if c in df_filtered.columns]
                df_filtered = df_filtered[existing_cols]

                # CSV 다운로드 버튼
                col_ho_a1, col_ho_a2 = st.columns([3, 1])
                with col_ho_a2:
                    if not df_filtered.empty:
                        csv_data = convert_df_to_csv(df_filtered) if 'convert_df_to_csv' in globals() else df_filtered.to_csv(index=False).encode('utf-8-sig')
                        st.download_button(
                            label="📥 선택 일자 기록 CSV 다운로드",
                            data=csv_data,
                            file_name=f"compose_handover_{selected_date}.csv",
                            mime="text/csv",
                            key="btn_download_handover"
                        )

                # 데이터프레임 출력
                if not df_filtered.empty:
                    st.dataframe(df_filtered, use_container_width=True, hide_index=True)
                else:
                    st.info(f"💡 [{selected_date}] 선택한 일자의 인수인계 기록이 없습니다.")
            else:
                st.info("등록된 인수인계 기록이 없습니다.")

         # =========================================================================
        # 7. 원자재 폐기 이력 & 재고 실사 점검
        # =========================================================================
        elif admin_menu == "🗑️ 원자재 폐기 이력 & 손실 점검":
            st.subheader("🗑️ 원자재 폐기 이력 & 재고 실사 점검")
            st.info("💡 알바생 모드에서 등록된 유통기한/파손 폐기 내역 및 재고 실사 점검 이력을 실시간으로 조회합니다.")

            # ---------------------------------------------------------------------
            # 1. 알바생 폐기 등록 내역 (waste)
            # ---------------------------------------------------------------------
            try:
                waste_res = supabase.table("waste").select("*").execute()
                waste_df = pd.DataFrame(waste_res.data) if waste_res and getattr(waste_res, "data", None) else pd.DataFrame()
            except Exception:
                waste_df = pd.DataFrame()

            # ---------------------------------------------------------------------
            # 2. 알바생 재고 실사 내역 (inventory_audit 우선 조회)
            # ---------------------------------------------------------------------
            inv_log_df = pd.DataFrame()
            audit_tables = ["inventory_audit", "stock_check", "inventory_log", "inventory_logs"]
            
            for log_t in audit_tables:
                try:
                    log_res = supabase.table(log_t).select("*").execute()
                    if log_res and getattr(log_res, "data", None):
                        temp_df = pd.DataFrame(log_res.data)
                        if not temp_df.empty:
                            inv_log_df = temp_df
                            break
                except Exception:
                    continue

            # --- 폐기 데이터 컬럼 호환 및 집계 ---
            total_waste_cost = 0
            total_waste_cnt = 0

            if not waste_df.empty:
                if "loss_amount" in waste_df.columns:
                    waste_df["calc_loss"] = pd.to_numeric(waste_df["loss_amount"], errors="coerce").fillna(0)
                elif "cost" in waste_df.columns:
                    waste_df["calc_loss"] = pd.to_numeric(waste_df["cost"], errors="coerce").fillna(0)
                else:
                    waste_df["calc_loss"] = 0

                if "reported_by" in waste_df.columns:
                    waste_df["calc_worker"] = waste_df["reported_by"]
                elif "worker" in waste_df.columns:
                    waste_df["calc_worker"] = waste_df["worker"]
                else:
                    waste_df["calc_worker"] = "-"

                total_waste_cost = waste_df["calc_loss"].sum()
                total_waste_cnt = len(waste_df)

            # --- 재고 실사 데이터 컬럼 호환 ---
            total_audit_cnt = 0
            if not inv_log_df.empty:
                total_audit_cnt = len(inv_log_df)

                # 점검자 매핑
                if "checked_by" in inv_log_df.columns:
                    inv_log_df["calc_worker"] = inv_log_df["checked_by"]
                elif "worker" in inv_log_df.columns:
                    inv_log_df["calc_worker"] = inv_log_df["worker"]
                else:
                    inv_log_df["calc_worker"] = "-"

                # 일자 매핑
                if "date" in inv_log_df.columns:
                    inv_log_df["calc_date"] = inv_log_df["date"]
                elif "created_at" in inv_log_df.columns:
                    inv_log_df["calc_date"] = inv_log_df["created_at"].astype(str).str.slice(0, 10)
                else:
                    inv_log_df["calc_date"] = "-"

            # --- 상단 서머리 메트릭 ---
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("총 폐기 손실액", f"{int(total_waste_cost):,} 원")
            with col2:
                st.metric("총 폐기 등록 건수", f"{total_waste_cnt:,} 건")
            with col3:
                st.metric("총 실사 점검 건수", f"{total_audit_cnt:,} 건")

            st.write("---")

            # --- 탭 구성 ---
            tab1, tab2 = st.tabs(["📋 폐기 보고 내역", "🔍 재고 실사 점검 내역"])

            with tab1:
                st.markdown("#### 🚨 알바생 폐기 보고 내역")
                if not waste_df.empty:
                    display_cols = ["date", "item_name", "qty", "calc_loss", "reason", "calc_worker"]
                    show_cols = [c for c in display_cols if c in waste_df.columns]
                    display_df = waste_df[show_cols].copy()

                    if "date" in display_df.columns:
                        display_df = display_df.sort_values(by="date", ascending=False)

                    st.dataframe(
                        display_df,
                        column_config={
                            "date": "등록 일자",
                            "item_name": "품목명",
                            "qty": "폐기 수량",
                            "calc_loss": st.column_config.NumberColumn("손실 금액", format="%d 원"),
                            "reason": "폐기 사유",
                            "calc_worker": "작성자/알바생",
                        },
                        use_container_width=True,
                        hide_index=True
                    )
                else:
                    st.info("등록된 폐기 내역이 없습니다.")

           
        
            with tab2:
                st.markdown("#### 📦 알바생 재고 실사 점검 이력")
                if not inv_log_df.empty:
                    # --- 캘린더 기반 콤팩트 필터 ---
                    col_f1, col_f2 = st.columns(2)
                    
                    with col_f1:
                        show_only_diff = st.checkbox("🚨 오차 발생 품목만 보기", value=True)
                        all_dates = st.checkbox("🗓️ 전체 날짜 보기", value=False)

                    with col_f2:
                        selected_date = st.date_input(
                            "📅 실사 일자 선택",
                            value=datetime.datetime.now(KST).date() if 'KST' in globals() else datetime.date.today(),
                            disabled=all_dates,
                            key="inv_audit_date_picker"
                        )

                    # --- 필터링 적용 ---
                    filtered_df = inv_log_df.copy()
                    
                    # 1. 오차 품목 필터링
                    if show_only_diff and "diff_qty" in filtered_df.columns:
                        filtered_df = filtered_df[filtered_df["diff_qty"] != 0]
                        
                    # 2. 캘린더 날짜 필터링 (전체 날짜 보기가 체크 해제된 경우만)
                    if not all_dates:
                        date_str = selected_date.strftime("%Y-%m-%d")
                        filtered_df = filtered_df[filtered_df["calc_date"] == date_str]

                    # 최신순 정렬
                    if "created_at" in filtered_df.columns:
                        filtered_df = filtered_df.sort_values(by="created_at", ascending=False)
                    elif "calc_date" in filtered_df.columns:
                        filtered_df = filtered_df.sort_values(by="calc_date", ascending=False)

                    # --- 결과 표출 ---
                    if not filtered_df.empty:
                        diff_count = len(filtered_df[filtered_df["diff_qty"] != 0]) if "diff_qty" in filtered_df.columns else 0
                        st.caption(f"📊 조회된 내역 **{len(filtered_df)}건** (오차 발생: **{diff_count}건**) ")

                        display_cols_inv = ["calc_date", "item_name", "system_qty", "actual_qty", "diff_qty", "calc_worker", "memo"]
                        show_cols_inv = [c for c in display_cols_inv if c in filtered_df.columns]

                        st.dataframe(
                            filtered_df[show_cols_inv],
                            column_config={
                                "calc_date": "실사 일자",
                                "item_name": "품목명",
                                "system_qty": "전산 수량",
                                "actual_qty": "실물 수량",
                                "diff_qty": st.column_config.NumberColumn("오차 수량", format="%d"),
                                "calc_worker": "점검자",
                                "memo": "메모/비고",
                            },
                            use_container_width=True,
                            hide_index=True
                        )
                    else:
                        st.success("✨ 선택한 조건에 해당하는 실사 기록이 없습니다. (재고 일치 또는 미실행)")
                else:
                    st.info("등록된 재고 실사 기록이 없습니다.")

        # =========================================================================
        # 8. 오픈/마감 체크리스트 관리
        # =========================================================================
        elif "체크리스트" in admin_menu:
            st.subheader("📋 오픈/마감 체크리스트 관리 (점주 전용)")

            tab_history, tab_setting = st.tabs(["📊 알바생 점검 내역 조회", "⚙️ 오픈/마감 항목 관리"])

            with tab_history:
                st.write("#### 📅 알바생 점검 완료 내역")

                selected_shift = st.radio("조회할 근무 파트 선택", ["☀️ 오픈", "🌙 마감"], horizontal=True, key="admin_chk_view_shift")

                setting_key = "checklist_open_items" if "오픈" in selected_shift else "checklist_close_items"
                default_items = (
                    ["오픈 매장 청소", "원두/시럽 재고 점검", "머신 예열 및 세팅"] 
                    if "오픈" in selected_shift 
                    else ["마감 포스 정산", "머신 마감 세척", "쓰레기 분리수거"]
                )
                checklist_items = get_setting(setting_key, default_items) if 'get_setting' in globals() else default_items

                try:
                    chk_res = (
                        supabase.table("checklist")
                        .select("*")
                        .order("date", desc=True)
                        .execute()
                    )
                    chk_list = chk_res.data if chk_res and getattr(chk_res, "data", None) else []

                    filtered_list = [
                        r for r in chk_list 
                        if r.get("shift_type") == selected_shift or selected_shift in str(r.get("shift_type", ""))
                    ]

                    if filtered_list:
                        processed_rows = []
                        for r in filtered_list:
                            row_dict = {
                                "날짜": r.get("date"),
                                "근무 파트": r.get("shift_type", selected_shift),
                                "점검자(알바생)": r.get("staff_name", "-"),
                            }
                            items_status = r.get("checked_items") or {}

                            for item_name in checklist_items:
                                row_dict[item_name] = "✅ 완료" if items_status.get(item_name) else "❌ 미완료"

                            row_dict["비고 / 특이사항"] = r.get("memo", "")
                            processed_rows.append(row_dict)

                        df_chk = pd.DataFrame(processed_rows)

                        styled_df = style_date_dataframe(df_chk, "날짜") if 'style_date_dataframe' in globals() else df_chk

                        st.dataframe(styled_df, use_container_width=True, hide_index=True)
                    else:
                        st.info(f"💡 아직 [{selected_shift}] 파트의 제출된 점검 내역이 없습니다.")
                except Exception:
                    st.warning("💡 Supabase 'checklist' 테이블 확인이 필요합니다.")

            with tab_setting:
                st.write("#### 📌 오픈 / 마감 파트별 점검 항목 설정")
                st.caption("💡 이곳에서 설정한 파트별 항목이 알바생 점검 화면에 실시간으로 구분되어 연동됩니다.")

                target_shift = st.radio("설정할 파트 선택", ["☀️ 오픈", "🌙 마감"], horizontal=True, key="admin_chk_setting_shift")

                setting_key = "checklist_open_items" if "오픈" in target_shift else "checklist_close_items"
                default_items = (
                    ["오픈 매장 청소", "원두/시럽 재고 점검", "머신 예열 및 세팅"] 
                    if "오픈" in target_shift 
                    else ["마감 포스 정산", "머신 마감 세척", "쓰레기 분리수거"]
                )
                checklist_items = get_setting(setting_key, default_items) if 'get_setting' in globals() else default_items

                col_add1, col_add2 = st.columns([3, 1])
                new_item = col_add1.text_input(f"[{target_shift}] 새 점검 항목 이름", placeholder="예: 쓰레기통 비우기 / 정산 완료", key=f"admin_new_chk_{setting_key}")

                if col_add2.button("➕ 항목 추가", type="primary", use_container_width=True, key=f"btn_add_{setting_key}"):
                    new_item_str = new_item.strip()
                    if not new_item_str:
                        st.warning("⚠️ 추가할 항목 이름을 입력해 주세요.")
                    elif new_item_str in checklist_items:
                        st.warning("⚠️ 이미 존재하는 항목입니다.")
                    else:
                        checklist_items.append(new_item_str)
                        supabase.table("app_settings").upsert({
                            "key": setting_key,
                            "value": checklist_items
                        }, on_conflict="key").execute()

                        st.success(f"✅ [{target_shift}] 파트에 '{new_item_str}' 항목이 추가되었습니다!")
                        st.rerun()

                st.write("---")
                if checklist_items:
                    st.write(f"**[{target_shift} 파트 알바생 표시 항목 목록]**")
                    for idx, item in enumerate(checklist_items, 1):
                        st.write(f"**{idx}.** {item}")

                    st.write("---")
                    del_target = st.selectbox(f"[{target_shift}] 삭제할 항목 선택", checklist_items, key=f"admin_del_chk_{setting_key}")
                    if st.button("❌ 선택한 항목 삭제", type="secondary", key=f"btn_del_{setting_key}"):
                        checklist_items.remove(del_target)
                        supabase.table("app_settings").upsert({
                            "key": setting_key,
                            "value": checklist_items
                        }, on_conflict="key").execute()

                        st.success(f"🗑️ [{target_shift}] 파트의 '{del_target}' 항목이 삭제되었습니다.")
                        st.rerun()
                else:
                    st.info(f"💡 [{target_shift}] 파트에 등록된 점검 항목이 없습니다. 위에서 새 항목을 추가해 주세요.")

        # --------------------------------------------------
        # 점주 메뉴: ⏰ 알바생 근무 스케줄 설정 및 관리
        # --------------------------------------------------
        elif admin_menu == "⏰ 알바생 근무 스케줄 설정 및 관리" or "스케줄" in admin_menu:
            st.subheader("🗓️ 알바생 근무 캘린더 & 스케줄 관리")

            # Session State 초기화 (클릭한 날짜 저장용)
            if "selected_sch_date" not in st.session_state:
                st.session_state["selected_sch_date"] = datetime.date.today()

            # 1. 연도 및 월 선택
            col_y, col_m, _ = st.columns([2, 2, 3])
            today = datetime.date.today()
            sel_year = col_y.number_input("연도", min_value=2024, max_value=2030, value=today.year)
            sel_month = col_m.selectbox("월", list(range(1, 13)), index=today.month - 1)

            # 2. 해당 월 스케줄 DB 데이터 불러오기
            first_day_str = f"{sel_year}-{sel_month:02d}-01"
            last_day_num = calendar.monthrange(sel_year, sel_month)[1]
            last_day_str = f"{sel_year}-{sel_month:02d}-{last_day_num:02d}"

            try:
                sch_res = (
                    supabase.table("schedule")
                    .select("*")
                    .gte("date", first_day_str)
                    .lte("date", last_day_str)
                    .execute()
                )
                sch_list = sch_res.data if sch_res and getattr(sch_res, "data", None) else []
            except Exception:
                sch_list = []

            # 날짜별 데이터 딕셔너리 구조화
            schedule_by_date = {}
            for item in sch_list:
                d = item.get("date")
                if d:
                    if d not in schedule_by_date:
                        schedule_by_date[d] = []
                    schedule_by_date[d].append(item)

            # 3. 월간 캘린더 그리드 출력
            st.write("---")
            st.caption("💡 달력의 날짜 버튼을 클릭하면 아래 등록 폼의 날짜가 자동으로 설정됩니다.")
            
            days_kr = ["월", "화", "수", "목", "금", "토", "일"]
            cols = st.columns(7)
            for idx, day_name in enumerate(days_kr):
                cols[idx].markdown(f"**{day_name}**")

            month_calendar = calendar.monthcalendar(sel_year, sel_month)

            for week in month_calendar:
                week_cols = st.columns(7)
                for idx, day in enumerate(week):
                    if day == 0:
                        week_cols[idx].empty()
                    else:
                        curr_date = datetime.date(sel_year, sel_month, day)
                        date_str = f"{sel_year}-{sel_month:02d}-{day:02d}"
                        day_schedules = schedule_by_date.get(date_str, [])

                        # 요일별 주말 표시
                        day_display = f"{day}일"
                        if idx == 5:
                            day_display = f"{day}일(토)"
                        elif idx == 6:
                            day_display = f"{day}일(일)"

                        # 날짜 카드를 컨테이너로 표시
                        with week_cols[idx].container(border=True):
                            # 날짜 클릭 버튼
                            if st.button(day_display, key=f"btn_date_{date_str}", use_container_width=True):
                                st.session_state["selected_sch_date"] = curr_date
                                st.rerun()

                            # 근무자 목록 출력
                            if day_schedules:
                                for s in day_schedules:
                                    st.markdown(f"👤 **{s.get('staff_name', '-')}**\n`{s.get('start_time', '')}~{s.get('end_time', '')}`")
                            else:
                                st.caption("근무 없음")

            # 4. 스케줄 등록 / 수정 / 삭제 폼
            st.write("---")
            tab_sch_add, tab_sch_edit = st.tabs(["➕ 스케줄 등록", "✏️ 스케줄 수정 / 삭제"])

            staff_info = get_staff_info() if 'get_staff_info' in globals() else {}
            staff_list = list(staff_info.keys()) if staff_info else []

            with tab_sch_add:
                st.write(f"#### 📝 스케줄 입력 (선택된 날짜: **{st.session_state['selected_sch_date']}**)")
                with st.form("add_schedule_calendar_form"):
                    col_s1, col_s2 = st.columns(2)
                    s_date = col_s1.date_input("근무 날짜", st.session_state["selected_sch_date"])
                    s_staff = col_s2.selectbox("직원 선택", staff_list) if staff_list else col_s2.text_input("직원명")

                    col_t1, col_t2 = st.columns(2)
                    s_start = col_t1.time_input("시작 시간", datetime.time(9, 0))
                    s_end = col_t2.time_input("종료 시간", datetime.time(15, 0))

                    # 반복 옵션 체크박스
                    is_recurring = st.checkbox("🔄 선택한 달의 같은 요일 매주 반복 등록")

                    if st.form_submit_button("💾 스케줄 저장", type="primary", use_container_width=True):
                        if not s_staff:
                            st.warning("⚠️ 직원명을 입력하거나 선택해 주세요.")
                        elif is_recurring:
                            # 선택한 달의 동일한 요일 전체 날짜 계산
                            target_weekday = s_date.weekday()
                            num_days = calendar.monthrange(s_date.year, s_date.month)[1]
                            
                            records_to_insert = []
                            for d in range(1, num_days + 1):
                                iter_date = datetime.date(s_date.year, s_date.month, d)
                                if iter_date.weekday() == target_weekday and iter_date >= s_date:
                                    records_to_insert.append({
                                        "date": str(iter_date),
                                        "staff_name": s_staff,
                                        "start_time": s_start.strftime("%H:%M"),
                                        "end_time": s_end.strftime("%H:%M")
                                    })

                            try:
                                supabase.table("schedule").upsert(records_to_insert, on_conflict="date, staff_name").execute()
                                st.success(f"✅ [{s_staff}] 님의 매주 반복 스케줄 {len(records_to_insert)}건이 일괄 저장되었습니다.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ 반복 저장 중 오류 발생: {e}")
                        else:
                            # 단일 날짜 저장
                            try:
                                supabase.table("schedule").upsert({
                                    "date": str(s_date),
                                    "staff_name": s_staff,
                                    "start_time": s_start.strftime("%H:%M"),
                                    "end_time": s_end.strftime("%H:%M")
                                }, on_conflict="date, staff_name").execute()
                                st.success(f"✅ {s_date} [{s_staff}] 님의 스케줄이 저장되었습니다.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ 저장 중 오류 발생: {e}")

            with tab_sch_edit:
                if sch_list:
                    # id가 없는 경우 (date + staff_name)을 고유 식별키로 활용
                    sch_options = []
                    for idx, item in enumerate(sch_list):
                        item_id = str(item.get("id")) if "id" in item and item.get("id") else f"{item.get('date')}_{item.get('staff_name')}"
                        sch_options.append((item_id, item))

                    # 1. 수정/삭제할 대상 선택
                    selected_id = st.selectbox(
                        "수정 또는 삭제할 스케줄 선택",
                        options=[opt[0] for opt in sch_options],
                        format_func=lambda x: next(
                            f"[{item.get('date', '')}] {item.get('staff_name', '')} ({item.get('start_time', '')} ~ {item.get('end_time', '')})"
                            for item_id, item in sch_options if item_id == x
                        ),
                        key="select_sch_target"
                    )

                    # 선택한 데이터 가져오기
                    selected_data = next((item for item_id, item in sch_options if item_id == selected_id), None)

                    if selected_data:
                        # 선택된 항목의 날짜 및 시간 데이터 파싱
                        try:
                            def_date = datetime.datetime.strptime(str(selected_data.get("date")), "%Y-%m-%d").date()
                        except Exception:
                            def_date = datetime.date.today()

                        try:
                            def_start = datetime.datetime.strptime(str(selected_data.get("start_time", "09:00")), "%H:%M").time()
                            def_end = datetime.datetime.strptime(str(selected_data.get("end_time", "15:00")), "%H:%M").time()
                        except Exception:
                            def_start = datetime.time(9, 0)
                            def_end = datetime.time(15, 0)

                        # 2. 수정 입력 폼 (selected_id를 key에 결합하여 셀렉트박스 변경 시 입력창도 동기화)
                        with st.form(f"edit_sch_form_{selected_id}"):
                            st.markdown("##### ✏️ 선택한 스케줄 정보 수정")
                            col_e1, col_e2 = st.columns(2)
                            edit_date = col_e1.date_input("근무 날짜", value=def_date, key=f"edit_date_{selected_id}")
                            
                            curr_staff = selected_data.get("staff_name", "")
                            if staff_list:
                                staff_idx = staff_list.index(curr_staff) if curr_staff in staff_list else 0
                                edit_staff = col_e2.selectbox("직원 선택", staff_list, index=staff_idx, key=f"edit_staff_{selected_id}")
                            else:
                                edit_staff = col_e2.text_input("직원명", value=curr_staff, key=f"edit_staff_{selected_id}")

                            col_et1, col_et2 = st.columns(2)
                            edit_start = col_et1.time_input("시작 시간", value=def_start, key=f"edit_start_{selected_id}")
                            edit_end = col_et2.time_input("종료 시간", value=def_end, key=f"edit_end_{selected_id}")

                            col_btn1, col_btn2 = st.columns(2)
                            btn_update = col_btn1.form_submit_button("💾 수정사항 저장", type="primary", use_container_width=True)
                            btn_delete = col_btn2.form_submit_button("❌ 스케줄 삭제", type="secondary", use_container_width=True)

                            # [수정 로직]
                            if btn_update:
                                try:
                                    old_date = str(selected_data.get("date"))
                                    old_staff = selected_data.get("staff_name")
                                    new_date = str(edit_date)
                                    new_staff = edit_staff

                                    # 날짜나 직원이 변경된 경우 이전 기존 레코드 삭제
                                    if (old_date != new_date) or (old_staff != new_staff):
                                        supabase.table("schedule").delete()\
                                            .eq("date", old_date)\
                                            .eq("staff_name", old_staff)\
                                            .execute()

                                    # 새 날짜/시간 정보 저장
                                    update_payload = {
                                        "date": new_date,
                                        "staff_name": new_staff,
                                        "start_time": edit_start.strftime("%H:%M"),
                                        "end_time": edit_end.strftime("%H:%M")
                                    }
                                    supabase.table("schedule").upsert(
                                        update_payload, 
                                        on_conflict="date, staff_name"
                                    ).execute()

                                    st.success("✅ 스케줄이 성공적으로 수정되었습니다.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"❌ 수정 실패: {e}")

                            # [삭제 로직]
                            if btn_delete:
                                try:
                                    target_d = str(selected_data.get("date"))
                                    target_s = selected_data.get("staff_name")

                                    supabase.table("schedule").delete()\
                                        .eq("date", target_d)\
                                        .eq("staff_name", target_s)\
                                        .execute()

                                    st.success("🗑️ 스케줄이 성공적으로 삭제되었습니다.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"❌ 삭제 실패: {e}")
                else:
                    st.info("💡 이번 달 등록된 스케줄이 없습니다.")
               

        # =========================================================================
        # 9. 재고현황 및 원가 관리
        # =========================================================================
        elif admin_menu == "📦 재고 현황 & 원가 관리" or "재고" in admin_menu:
            st.subheader("📦 재고 현황 & 원가 관리")
            st.info(
                "💡 등록된 품목의 현재 재고 수량과 원가 가치를 실시간으로 확인합니다."
                " (신규 품목 등록/수정은 [⚙️ 설정 관리] 메뉴의 재고 탭을 이용해 주세요)"
            )

            # 1. Supabase 재고 데이터 안전 불러오기
            inv_data = []
            try:
                inv_res = supabase.table("inventory").select("*").execute()
                if inv_res and hasattr(inv_res, "data") and inv_res.data:
                    inv_data = inv_res.data
            except Exception as e:
                st.error(f"❌ DB 연동 오류 (inventory 테이블 확인 필요): {e}")

            # Dataframe 변환 및 검증
            if inv_data:
                inv_df = pd.DataFrame(inv_data)

                # 필수 컬럼 존재 여부 체크 및 기본값 채우기
                required_cols = {
                    "category": "기타",
                    "item_name": "미지정 품목",
                    "unit": "개",
                    "unit_price": 0,
                    "current_qty": 0,
                    "safety_qty": 0,
                }
                for col, default_val in required_cols.items():
                    if col not in inv_df.columns:
                        inv_df[col] = default_val

                # 수치형 데이터 타입 정형화 및 평가액 계산
                inv_df["current_qty"] = pd.to_numeric(
                    inv_df["current_qty"], errors="coerce"
                ).fillna(0)
                inv_df["unit_price"] = pd.to_numeric(
                    inv_df["unit_price"], errors="coerce"
                ).fillna(0)
                inv_df["safety_qty"] = pd.to_numeric(
                    inv_df["safety_qty"], errors="coerce"
                ).fillna(0)
                inv_df["total_val"] = inv_df["current_qty"] * inv_df["unit_price"]

                # 2. 상단 KPI 요약
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("총 재고 품목 수", f"{len(inv_df):,} 개")
                with col2:
                    st.metric(
                        "총 재고 자산 가치",
                        f"{int(inv_df['total_val'].sum()):,} 원",
                    )
                with col3:
                    low_stock_cnt = len(
                        inv_df[inv_df["current_qty"] < inv_df["safety_qty"]]
                    )
                    st.metric(
                        "안전재고 부족 품목",
                        f"{low_stock_cnt:,} 개",
                        delta=-low_stock_cnt if low_stock_cnt > 0 else 0,
                        delta_color="inverse",
                    )

                st.write("---")

                # 3. 카테고리 필터링 및 데이터 표 출력
                cat_list = ["전체"] + [
                    str(c) for c in inv_df["category"].unique() if c
                ]
                selected_cat = st.selectbox("카테고리 필터", cat_list)

                filtered_df = inv_df.copy()
                if selected_cat != "전체":
                    filtered_df = filtered_df[
                        filtered_df["category"] == selected_cat
                    ]

                st.markdown("#### 📊 현재 재고 및 자산 현황")

                display_cols = [
                    "category",
                    "item_name",
                    "unit",
                    "unit_price",
                    "current_qty",
                    "safety_qty",
                    "total_val",
                ]
                existing_display_cols = [c for c in display_cols if c in filtered_df.columns]

                st.dataframe(
                    filtered_df[existing_display_cols],
                    column_config={
                        "category": "카테고리",
                        "item_name": "품목명",
                        "unit": "단위",
                        "unit_price": st.column_config.NumberColumn(
                            "단가", format="%d 원"
                        ),
                        "current_qty": st.column_config.NumberColumn(
                            "현재 수량", format="%.1f"
                        ),
                        "safety_qty": st.column_config.NumberColumn(
                            "안전 재고", format="%.1f"
                        ),
                        "total_val": st.column_config.NumberColumn(
                            "재고 평가액", format="%d 원"
                        ),
                    },
                    use_container_width=True,
                    hide_index=True,
                )

                # 안전재고 부족 알림
                low_items = filtered_df[
                    filtered_df["current_qty"] < filtered_df["safety_qty"]
                ]
                if not low_items.empty:
                    st.warning(
                        "🚨 **안전재고 부족 경고**: 다음 품목의 재고가 부족합니다 ->"
                        f" {', '.join(low_items['item_name'].astype(str).tolist())}"
                    )

            else:
                st.warning("📦 현재 DB에 등록된 재고 품목 데이터가 없습니다.")
                st.info(
                    "👉 **[⚙️ 설정 관리] -> [📦 재고 관리 품목 설정]** 메뉴에서"
                    " 품목을 신규 등록해 주시면 이곳에 자동으로 표시됩니다!"
                )

# 10. 전체 인건비 정산 (점주 모드)
        elif admin_menu == "💰 전체 인건비 정산":
            st.subheader("💰 월별 전체 인건비 정산")
            st.caption(
                "실시간 출퇴근 기록(attendance) 기반으로 주휴수당(주 15시간 이상)"
                " 및 3.3% 사업소득세를 반영하여 실수령액을 정산합니다."
            )

            # 1. 정산 월 선택 및 정산 옵션 설정
            col_opt1, col_opt2, col_opt3 = st.columns([2, 1, 1])
            with col_opt1:
                selected_month = st.date_input(
                    "📅 정산 월 선택", datetime.datetime.now(KST)
                ).strftime("%Y-%m")

            with col_opt2:
                include_holiday_pay = st.checkbox(
                    "🎁 주휴수당 포함", value=True, help="주 15시간 이상 근무 시 주휴수당 자동 합산"
                )

            with col_opt3:
                deduct_tax = st.checkbox(
                    "📉 3.3% 세금 공제", value=True, help="총액의 3.3% 사업소득세 원천징수 공제"
                )

            st.write("---")

            # 2. Supabase DB 데이터 동기화
            try:
                # 직원 마스터 (시급 정보)
                staff_res = supabase.table("staff").select("*").execute()
                staff_df = (
                    pd.DataFrame(staff_res.data) if staff_res.data else pd.DataFrame()
                )

                # 출퇴근 기록 (attendance)
                att_res = supabase.table("attendance").select("*").execute()
                att_df = (
                    pd.DataFrame(att_res.data) if att_res.data else pd.DataFrame()
                )
            except Exception as e:
                st.error(f"❌ 데이터베이스 연동 오류: {e}")
                staff_df, att_df = pd.DataFrame(), pd.DataFrame()

            # 3. 해당 월 출퇴근 내역 필터링 및 인건비 계산
            if not att_df.empty and "date" in att_df.columns:
                att_df["month"] = att_df["date"].str.slice(0, 7)
                month_att_df = att_df[att_df["month"] == selected_month].copy()

                if not month_att_df.empty:
                    payroll_list = []

                    # 직원별 그룹화하여 총 근무 시간 및 정산액 산출
                    for staff_name, group in month_att_df.groupby("staff_name"):
                        # 직원 마스터에서 시급 가져오기 (기본값: 10,030원)
                        hourly_wage = 10030
                        if not staff_df.empty and "name" in staff_df.columns:
                            match = staff_df[staff_df["name"] == staff_name]
                            if (
                                not match.empty
                                and "hourly_wage" in match.columns
                            ):
                                hourly_wage = float(
                                    match.iloc[0]["hourly_wage"] or 10030
                                )

                        # 누적 근무시간, 지각, 조퇴 합계 계산
                        total_hours = (
                            group["work_hours"].fillna(0).astype(float).sum()
                            if "work_hours" in group.columns
                            else 0.0
                        )
                        total_late = (
                            group["late_minutes"].fillna(0).astype(int).sum()
                            if "late_minutes" in group.columns
                            else 0
                        )
                        total_early = (
                            group["early_leave_minutes"].fillna(0).astype(int).sum()
                            if "early_leave_minutes" in group.columns
                            else 0
                        )
                        work_days = len(group["date"].unique())

                        # 기본 주급/월급 (총 시간 × 시급)
                        base_salary = total_hours * hourly_wage

                        # 4. 주휴수당 계산 (주 단위 그룹화 계산)
                        holiday_pay = 0.0
                        if include_holiday_pay and "date" in group.columns:
                            group_copy = group.copy()
                            group_copy["dt"] = pd.to_datetime(group_copy["date"])
                            # 주차(ISO Week)별로 총 시간 계산
                            group_copy["week"] = group_copy["dt"].dt.isocalendar().week

                            for week_num, week_group in group_copy.groupby("week"):
                                week_hours = (
                                    week_group["work_hours"]
                                    .fillna(0)
                                    .astype(float)
                                    .sum()
                                )
                                # 주 15시간 이상 근무 시 주휴수당 지급 (최대 40시간 기준)
                                if week_hours >= 15.0:
                                    calculated_hours = min(week_hours, 40.0)
                                    holiday_pay += (
                                        calculated_hours / 40.0
                                    ) * 8.0 * hourly_wage

                        # 총 지급액 (기본급 + 주휴수당)
                        gross_salary = base_salary + holiday_pay

                        # 5. 3.3% 사업소득세 공제 계산
                        tax_amount = gross_salary * 0.033 if deduct_tax else 0.0
                        net_salary = gross_salary - tax_amount

                        payroll_list.append(
                            {
                                "staff_name": staff_name,
                                "hourly_wage": int(hourly_wage),
                                "work_days": work_days,
                                "total_hours": round(total_hours, 2),
                                "base_salary": int(base_salary),
                                "holiday_pay": int(holiday_pay),
                                "gross_salary": int(gross_salary),
                                "tax_amount": int(tax_amount),
                                "net_salary": int(net_salary),
                                "total_late": total_late,
                                "total_early": total_early,
                            }
                        )

                    payroll_df = pd.DataFrame(payroll_list)

                    # 6. 상단 정산 요약 지표 (KPI Cards)
                    col_kpi1, col_kpi2, col_kpi3, col_kpi4 = st.columns(4)
                    with col_kpi1:
                        st.metric(
                            f"💵 {selected_month} 총 지급 실수령액",
                            f"{int(payroll_df['net_salary'].sum()):,} 원",
                            delta=f"총 지급액: {int(payroll_df['gross_salary'].sum()):,}원",
                        )
                    with col_kpi2:
                        st.metric(
                            "🎁 총 주휴수당 지급액",
                            f"{int(payroll_df['holiday_pay'].sum()):,} 원",
                        )
                    with col_kpi3:
                        st.metric(
                            "📉 총 공제 세금 (3.3%)",
                            f"{int(payroll_df['tax_amount'].sum()):,} 원",
                        )
                    with col_kpi4:
                        st.metric(
                            "⏱️ 총 근무시간",
                            f"{payroll_df['total_hours'].sum():.1f} 시간",
                        )

                    st.write("---")

                    # 7. 직원별 인건비 명세 및 원본 상세 탭
                    tab_pay, tab_detail = st.tabs(
                        ["📊 월별 직원별 인건비 명세서", "📋 출퇴근 원본 내역"]
                    )

                    with tab_pay:
                        col_header, col_excel = st.columns([3, 1])
                        with col_header:
                            st.markdown(
                                f"#### 📑 {selected_month} 직원별 급여 지급 상세 명세서"
                            )
                        with col_excel:
                            # Excel 다운로드 바이트 스트림 변환
                            excel_export_df = payroll_df.rename(
                                columns={
                                    "staff_name": "직원명",
                                    "hourly_wage": "시급(원)",
                                    "work_days": "근무일수",
                                    "total_hours": "총근무시간(h)",
                                    "base_salary": "기본급(원)",
                                    "holiday_pay": "주휴수당(원)",
                                    "gross_salary": "총지급액(원)",
                                    "tax_amount": "세금(3.3%)(원)",
                                    "net_salary": "실수령액(원)",
                                    "total_late": "총지각(분)",
                                    "total_early": "총조퇴(분)",
                                }
                            )

                            buffer = io.BytesIO()
                            with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                                excel_export_df.to_excel(
                                    writer,
                                    sheet_name=f"{selected_month}_인건비정산",
                                    index=False,
                                )
                            excel_data = buffer.getvalue()

                            st.download_button(
                                label="📥 Excel 다운로드",
                                data=excel_data,
                                file_name=f"인건비정산명세서_{selected_month}.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                use_container_width=True,
                                type="primary",
                            )

                        st.dataframe(
                            payroll_df,
                            column_config={
                                "staff_name": "직원명",
                                "hourly_wage": st.column_config.NumberColumn(
                                    "시급", format="%d 원"
                                ),
                                "work_days": st.column_config.NumberColumn(
                                    "근무일수", format="%d 일"
                                ),
                                "total_hours": st.column_config.NumberColumn(
                                    "총시간", format="%.2f 시간"
                                ),
                                "base_salary": st.column_config.NumberColumn(
                                    "기본급", format="%d 원"
                                ),
                                "holiday_pay": st.column_config.NumberColumn(
                                    "주휴수당", format="%d 원"
                                ),
                                "gross_salary": st.column_config.NumberColumn(
                                    "총 지급액", format="%d 원"
                                ),
                                "tax_amount": st.column_config.NumberColumn(
                                    "세금(3.3%)", format="%d 원"
                                ),
                                "net_salary": st.column_config.NumberColumn(
                                    "💵 실수령액", format="%d 원"
                                ),
                            },
                            use_container_width=True,
                            hide_index=True,
                        )

                    with tab_detail:
                        st.markdown(f"#### 📋 {selected_month} 출퇴근 기록 상세")
                        show_cols = [
                            c
                            for c in [
                                "date",
                                "staff_name",
                                "clock_in",
                                "clock_out",
                                "work_hours",
                                "late_minutes",
                                "early_leave_minutes",
                            ]
                            if c in month_att_df.columns
                        ]
                        st.dataframe(
                            month_att_df[show_cols].sort_values(
                                by=["date", "clock_in"], ascending=[False, False]
                            ),
                            column_config={
                                "date": "일자",
                                "staff_name": "직원명",
                                "clock_in": "출근 시각",
                                "clock_out": "퇴근 시각",
                                "work_hours": "근무 시간(h)",
                                "late_minutes": "지각(분)",
                                "early_leave_minutes": "조퇴(분)",
                            },
                            use_container_width=True,
                            hide_index=True,
                        )
                else:
                    st.info(
                        f"📅 {selected_month}월에 등록된 출퇴근 정산 내역이 없습니다."
                    )
            else:
                st.info("출퇴근 기록(attendance) 데이터가 존재하지 않습니다.")

        # 11. 직원 PIN & 시급 관리
        elif admin_menu == "👥 직원 PIN & 시급 관리":
            st.subheader("👥 직원 계정 등록 & 시급/PIN 관리")

            res_staff = supabase.table("staff").select("*").execute()
            df_staff = (
                pd.DataFrame(res_staff.data) if res_staff.data else pd.DataFrame()
            )

            if not df_staff.empty:
                st.write("#### 📋 등록된 직원 목록")
                st.dataframe(
                    df_staff[["name", "role", "hourly_rate"]], use_container_width=True
                )

            # --------------------------------------------------
            # 1️⃣ 신규 직원 등록
            # --------------------------------------------------
            with st.expander("➕ 신규 직원 등록", expanded=False):
                with st.form("add_staff_form"):
                    new_name = st.text_input("직원 이름")
                    new_role = st.selectbox("직책", ["알바", "매니저", "팀장"])
                    new_rate = st.number_input("시급 (원)", value=10030, step=100)
                    new_pin = st.text_input(
                        "접속 PIN 번호 (4자리)", type="password", max_chars=4
                    )

                    if st.form_submit_button("➕ 직원 등록 저장", type="primary"):
                        if new_name and new_pin:
                            supabase.table("staff").insert({
                                "name": new_name,
                                "role": new_role,
                                "hourly_rate": new_rate,
                                "pin": hash_str(new_pin),
                            }).execute()
                            st.success(f"✅ {new_name} 직원이 신규 등록되었습니다.")
                            st.rerun()
                        else:
                            st.warning("직원 이름과 PIN 번호를 입력해 주세요.")

            # --------------------------------------------------
            # 2️⃣ 직원 PIN 재설정 & 시급 수정
            # --------------------------------------------------
            st.divider()
            st.subheader("🔑 직원 PIN 재설정 및 정보 수정")

            staff_list = df_staff["name"].tolist() if not df_staff.empty else []

            if staff_list:
                selected_edit_staff = st.selectbox("수정할 직원을 선택하세요", staff_list, key="edit_staff_select")

                # 선택된 직원의 기존 시급 정보 가져오기
                current_rate = int(df_staff[df_staff["name"] == selected_edit_staff]["hourly_rate"].values[0]) if not df_staff.empty else 10030

                with st.form("edit_staff_form"):
                    edit_rate = st.number_input("변경할 시급 (원)", value=current_rate, step=100)
                    edit_pin = st.text_input("새 PIN 번호 (4자리 입력 시에만 변경됨)", type="password", max_chars=4)

                    if st.form_submit_button("💾 정보 수정 저장", type="primary"):
                        try:
                            update_data = {"hourly_rate": edit_rate}
                            # PIN 번호를 입력했을 때만 암호화하여 업데이트
                            if edit_pin:
                                update_data["pin"] = hash_str(edit_pin)

                            supabase.table("staff").update(update_data).eq("name", selected_edit_staff).execute()
                            st.success(f"✅ '{selected_edit_staff}' 직원의 정보가 수정되었습니다.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"수정 중 오류가 발생했습니다: {e}")

            # --------------------------------------------------
            # 3️⃣ 직원 삭제 기능
            # --------------------------------------------------
            st.divider()
            st.subheader("🗑️ 직원 삭제")

            if staff_list:
                selected_delete_staff = st.selectbox("삭제할 직원을 선택하세요", staff_list, key="delete_staff_select")
                confirm_delete = st.checkbox(f"정말로 '{selected_delete_staff}' 직원을 삭제하시겠습니까?")

                if st.button("❌ 직원 정보 삭제", type="primary", disabled=not confirm_delete):
                    try:
                        supabase.table("staff").delete().eq("name", selected_delete_staff).execute()
                        st.success(f"'{selected_delete_staff}' 직원이 성공적으로 삭제되었습니다.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"직원 삭제 중 오류가 발생했습니다: {e}")
            else:
                st.info("현재 등록된 직원이 없습니다.")

        # 12. 점주 비밀번호 변경
        elif admin_menu == "🔑 점주 비밀번호 변경":
            st.subheader("🔑 관리자 비밀번호 변경")

            with st.form("change_admin_pw_form"):
                curr_pw = st.text_input("현재 비밀번호", type="password")
                new_pw = st.text_input("새 비밀번호", type="password")
                confirm_pw = st.text_input("새 비밀번호 확인", type="password")

                if st.form_submit_button("🔑 비밀번호 변경 완료", type="primary"):
                    real_curr_pw = get_admin_password()
                    if not verify_hash(curr_pw, real_curr_pw):
                        st.error("❌ 현재 비밀번호가 일치하지 않습니다.")
                    elif new_pw != confirm_pw:
                        st.error("❌ 새 비밀번호가 서로 일치하지 않습니다.")
                    elif len(new_pw) < 4:
                        st.warning("⚠️ 비밀번호는 최소 4자리 이상이어야 합니다.")
                    else:
                        set_admin_password(new_pw)
                        st.success("✅ 점주 비밀번호가 변경되었습니다.")
                        st.rerun()

        # 13. 공지사항 수정
        elif admin_menu == "📢 공지사항 수정":
            st.subheader("📢 알바생 게시판 공지사항 작성/수정")

            notice_curr, _ = get_notice()
            notice_input = st.text_area(
                "공지사항 내용 입력", value=notice_curr, height=200
            )

            if st.button("📢 공지사항 등록", type="primary", use_container_width=True):
                set_notice(notice_input)
                st.success("공지사항이 성공적으로 게시되었습니다.")
                st.rerun()

        # --------------------------------------------------
        # 14. 점주 메뉴: 데이터 백업 및 복원
        # --------------------------------------------------
        elif "백업" in admin_menu or "복원" in admin_menu or "다운로드" in admin_menu:
            st.subheader("💾 데이터 백업 및 복원")
            st.caption(
                "💡 매장의 데이터를 엑셀로 백업하거나, 기존 백업 파일을 업로드하여 DB를 복원합니다."
            )

            tab_backup, tab_restore = st.tabs(["📥 데이터 백업 (내보내기)", "📤 데이터 복원 (복구하기)"])

            # 안전하게 Supabase 테이블 데이터를 불러오는 헬퍼 함수
            def fetch_table_safe(table_name):
                try:
                    res = supabase.table(table_name).select("*").execute()
                    return pd.DataFrame(res.data or [])
                except Exception:
                    return pd.DataFrame()

            # 시트명 <-> Supabase 테이블명 매핑
            table_mapping = {
                "지출내역": "expenses",
                "근무스케줄": "schedule",
                "출퇴근기록": "attendance",
                "체크리스트기록": "checklist_log",
                "재고현황": "inventory",
                "인수인계노트": "handover",
                "직원목록": "staff",
            }

            # --------------------------------------------------
            # TAB 1: 전체 데이터 백업 (다운로드)
            # --------------------------------------------------
            with tab_backup:
                st.write("#### 📦 전체 DB 데이터 통합 백업")
                st.caption("매장의 모든 테이블 데이터를 하나의 엑셀 파일 내 여러 시트로 다운로드합니다.")

                if st.button(
                    "📥 전체 데이터 백업 파일 생성",
                    type="primary",
                    use_container_width=True,
                    key="btn_full_backup",
                ):
                    try:
                        backup_dict = {
                            sheet_name: fetch_table_safe(tbl_name)
                            for sheet_name, tbl_name in table_mapping.items()
                        }

                        file_bytes, mime_type, ext = create_excel_download(backup_dict)
                        now_str = datetime.date.today().strftime("%Y%m%d")

                        st.download_button(
                            label="💾 백업 파일 PC 저장하기 (.xlsx)",
                            data=file_bytes,
                            file_name=f"컴포즈커피_전체데이터백업_{now_str}.{ext}",
                            mime=mime_type,
                            use_container_width=True,
                            key="dl_btn_full",
                        )
                        st.success("✅ 백업 파일이 생성되었습니다. 위 버튼을 눌러 저장하세요.")
                    except Exception as e:
                        st.error(f"❌ 데이터 백업 중 오류 발생: {e}")

            # --------------------------------------------------
            # TAB 2: 데이터 복원 (복구/업로드)
            # --------------------------------------------------
            with tab_restore:
                st.write("#### 📤 엑셀 백업 파일로 데이터 복원")
                st.warning(
                    "⚠️ **주의**: 기존 데이터베이스의 데이터가 백업 파일의 내용으로 덮어쓰여지거나 추가됩니다."
                )

                uploaded_file = st.file_uploader(
                    "백업 엑셀 파일(.xlsx)을 선택하세요",
                    type=["xlsx"],
                    key="restore_excel_uploader",
                )

                if uploaded_file is not None:
                    if st.button("🚀 선택한 파일로 데이터 복원 실행", type="primary", use_container_width=True):
                        try:
                            # 엑셀 파일의 모든 시트 읽기
                            excel_file = pd.ExcelFile(uploaded_file)
                            sheet_names = excel_file.sheet_names

                            restore_success_count = 0

                            for sheet in sheet_names:
                                if sheet in table_mapping:
                                    tbl_name = table_mapping[sheet]
                                    df_restore = pd.read_excel(excel_file, sheet_name=sheet)

                                    # '안내' 문구용 임시 데이터는 제외
                                    if not df_restore.empty and "안내" not in df_restore.columns:
                                        # NaN 값을 None으로 변환하여 DB 호환성 확보
                                        records = df_restore.where(pd.notnull(df_restore), None).to_dict(orient="records")

                                        if records:
                                            # Supabase 데이터 Upsert(삽입/갱신)
                                            supabase.table(tbl_name).upsert(records).execute()
                                            restore_success_count += 1

                            if restore_success_count > 0:
                                st.success(f"🎉 총 {restore_success_count}개 항목(시트)의 데이터 복원이 완료되었습니다!")
                            else:
                                st.warning("⚠️ 복원 가능한 데이터 시트를 찾지 못했습니다.")
                        except Exception as e:
                            st.error(f"❌ 복원 처리 중 오류가 발생했습니다: {e}")

        # 15. 데이터 초기화
        elif admin_menu == "⚠️ 데이터 초기화":
            st.subheader("⚠️ 시스템 데이터 초기화")
            st.warning(
                "🚨 **주의:** 데이터 초기화 작업은 삭제 후 복구할 수 없습니다. 필요한"
                " 경우 실행 전 [📥 전체 데이터 엑셀/CSV 다운로드] 메뉴에서 백업"
                " 데이터를 저장해 주세요."
            )

            reset_type = st.radio(
                "초기화할 대상을 선택하세요",
                [
                    "📊 매출 및 발주 내역만 초기화 (daily_sales, mfood_orders)",
                    (
                        "⏰ 출퇴근 및 스케줄/대타 내역만 초기화 (attendance, schedule,"
                        " shift_requests)"
                    ),
                    "🤝 인수인계 기록만 초기화 (handover)",
                    "📦 재고 및 폐기/실사 내역만 초기화",
                    "📋 체크리스트 수행 기록만 초기화 (checklist_log)",
                    (
                        "🚨 전체 시스템 완전 초기화 (직원, 재고 실사 이력 등 100% 완전 삭제)"
                    ),
                ],
            )

            st.write("---")
            st.markdown("#### 🔒 초기화 실행 확인")
            confirm_input = st.text_input(
                "실수 방지를 위해 아래에 **'초기화'** 라고 정확히 입력하세요."
            )
            confirm_checkbox = st.checkbox(
                "데이터를 삭제하며, 복구가 불가능함에 동의합니다."
            )

            if st.button("🔥 데이터 초기화 실행", type="primary"):
                if confirm_input.strip() == "초기화" and confirm_checkbox:
                    try:
                        # 모든 하위 실사/기록/마스터 테이블 후보군 전체
                        all_tables = [
                            "inventory_log", "inventory_logs", "inventory_check", "inventory_checks",
                            "stock_check", "stock_checks", "inventory_history", "inventory_audit",
                            "waste", "checklist_log", "shift_requests", "attendance",
                            "handover", "daily_sales", "mfood_orders", "schedule",
                            "inventory", "staff", "checklist"
                        ]

                        if reset_type.startswith("🚨"):
                            for t in all_tables:
                                # 1차: id 컬럼 기준 삭제 시도
                                try:
                                    supabase.table(t).delete().neq("id", -999999).execute()
                                    continue
                                except Exception:
                                    pass

                                # 2차: date 컬럼 기준 삭제 시도
                                try:
                                    supabase.table(t).delete().neq("date", "1900-01-01").execute()
                                    continue
                                except Exception:
                                    pass

                                # 3차: item_name 컬럼 기준 삭제 시도
                                try:
                                    supabase.table(t).delete().neq("item_name", "__DELETE_ALL__").execute()
                                    continue
                                except Exception:
                                    pass

                                # 4차: name 컬럼 기준 삭제 시도
                                try:
                                    supabase.table(t).delete().neq("name", "__DELETE_ALL__").execute()
                                    continue
                                except Exception:
                                    pass

                                # 5차: year_month 컬럼 기준 삭제 시도
                                try:
                                    supabase.table(t).delete().neq("year_month", "1900-01").execute()
                                except Exception:
                                    pass

                        elif reset_type.startswith("📊"):
                            supabase.table("daily_sales").delete().neq("date", "1900-01-01").execute()
                            supabase.table("mfood_orders").delete().neq("year_month", "1900-01").execute()

                        elif reset_type.startswith("⏰"):
                            supabase.table("shift_requests").delete().neq("id", -999999).execute()
                            supabase.table("attendance").delete().neq("id", -999999).execute()
                            supabase.table("schedule").delete().neq("date", "1900-01-01").execute()

                        elif reset_type.startswith("🤝"):
                            supabase.table("handover").delete().neq("id", -999999).execute()

                        elif reset_type.startswith("📦"):
                            for t in ["inventory_log", "inventory_logs", "inventory_check", "inventory_checks", "stock_check", "stock_checks", "inventory_history", "inventory_audit", "waste"]:
                                try:
                                    supabase.table(t).delete().neq("id", -999999).execute()
                                except Exception:
                                    pass
                            supabase.table("inventory").delete().neq("item_name", "__DELETE_ALL__").execute()

                        elif reset_type.startswith("📋"):
                            supabase.table("checklist_log").delete().neq("id", -999999).execute()

                        st.success("✅ 시스템 내 모든 데이터가 완전히 초기화되었습니다.")
                        st.rerun()

                    except Exception as e:
                        st.error(f"❌ 초기화 실패 (DB 권한 또는 오류 확인): {e}")
                else:
                    st.error("❌ '초기화' 문구 입력과 동의 체크박스를 모두 확인해 주세요.")

# ⚙️ 메뉴 & 항목 설정 관리 (전체 세부 항목 커스텀 + 배달 수수료율 포함)
        elif admin_menu == "⚙️ 메뉴 & 항목 설정 관리":
            st.subheader("⚙️ 점주 메뉴 및 세부 항목 커스텀 설정")
            st.caption("사이드바 메뉴, 배달 플랫폼 수수료, 지출 카테고리, 재고, 폐기 사유 등 모든 항목을 직접 관리하세요.")

            tab1, tab2, tab3, tab4, tab5 = st.tabs([
                "📌 사이드바 메뉴",
                "🛵 배달 플랫폼 & 수수료율",
                "💸 지출 카테고리",
                "📦 재고 품목",
                "🗑️ 폐기 사유"
            ])

            # --------------------------------------------------
            # 탭 1: 사이드바 메뉴 순서/이름 수정
            # --------------------------------------------------
            with tab1:
                st.write("#### 📌 점주 사이드바 메뉴 관리")
                current_menus_str = "\n".join(admin_menu_options)
                edited_menus_text = st.text_area("메뉴 항목 (줄바꿈 구분)", value=current_menus_str, height=220, key="menu_tab_area")

                if st.button("💾 메뉴 구성 저장", type="primary", key="save_menu_btn"):
                    new_menu_list = [m.strip() for m in edited_menus_text.split("\n") if m.strip()]
                    if "⚙️ 메뉴 & 항목 설정 관리" not in new_menu_list:
                        new_menu_list.append("⚙️ 메뉴 & 항목 설정 관리")

                    supabase.table("app_settings").upsert({"key": "admin_menus", "value": new_menu_list}).execute()
                    st.success("✅ 사이드바 메뉴 구성이 변경되었습니다!")
                    st.rerun()

            # --------------------------------------------------
            # 탭 2: 배달 플랫폼 & 수수료율 관리 (수정 및 추가/삭제 가능)
            # --------------------------------------------------
            with tab2:
                st.write("#### 🛵 배달 플랫폼 및 수수료율 설정")
                st.caption("표에서 플랫폼명과 수수료율(%)을 입력/수정하세요. 하단의 빈 줄에 클릭하여 새 플랫폼을 추가하거나 삭제할 수도 있습니다.")

                del_res = supabase.table("app_settings").select("value").eq("key", "delivery_platforms").execute()

                # 기존 DB에 저장된 데이터 가져오기 (없을 경우 기본값 적용)
                if del_res.data and isinstance(del_res.data[0]["value"], list):
                    raw_data = del_res.data[0]["value"]
                    # 이전 버전의 단일 문자열 리스트 형태 호환 처리
                    if raw_data and isinstance(raw_data[0], str):
                        init_del_data = [{"플랫폼명": p, "수수료율 (%)": 10.0} for p in raw_data]
                    else:
                        init_del_data = raw_data
                else:
                    init_del_data = [
                        {"플랫폼명": "배달의민족", "수수료율 (%)": 6.8},
                        {"플랫폼명": "쿠팡이츠", "수수료율 (%)": 9.8},
                        {"플랫폼명": "요기요", "수수료율 (%)": 12.5},
                        {"플랫폼명": "땡겨요", "수수료율 (%)": 2.0},
                    ]

                df_del_init = pd.DataFrame(init_del_data)

                # 엑셀처럼 직접 수정 및 추가 가능한 데이터 편집기
                edited_del_df = st.data_editor(
                    df_del_init,
                    num_rows="dynamic",  # 행 추가/삭제 허용
                    use_container_width=True,
                    column_config={
                        "플랫폼명": st.column_config.TextColumn("플랫폼 이름", required=True),
                        "수수료율 (%)": st.column_config.NumberColumn(
                            "수수료율 (%)", min_value=0.0, max_value=100.0, step=0.1, format="%.1f %%"
                        ),
                    },
                    key="del_platform_editor"
                )

                if st.button("💾 배달 플랫폼 & 수수료율 저장", type="primary", key="save_del_btn"):
                    save_data = edited_del_df.to_dict(orient="records")
                    supabase.table("app_settings").upsert({"key": "delivery_platforms", "value": save_data}).execute()
                    st.success("✅ 배달 플랫폼 및 수수료율이 성공적으로 저장되었습니다!")
                    st.rerun()

            # --------------------------------------------------
            # 탭 3: 지출 / 비용 카테고리 관리
            # --------------------------------------------------
            with tab3:
                st.write("#### 💸 지출 및 비용 카테고리 설정")
                st.caption("💡 이곳에서 변경 후 저장하면 [지출 및 비용 관리] 메뉴에 자동으로 반영됩니다.")

                default_exp = ["임대료", "인건비", "원자재/재료비", "공과금(전기/수도/가스)", "통신/포스비", "기타지출"]

                # DB에서 현재 설정값 불러오기
                current_exp = get_setting("expense_categories", default_exp)

                edited_exp_text = st.text_area(
                    "지출 카테고리 목록 (줄바꿈 구분)",
                    value="\n".join(current_exp),
                    height=200,
                    key="exp_tab_area"
                )

                if st.button("💾 카테고리 저장 및 즉시 반영", type="primary", key="save_exp_btn", use_container_width=True):
                    new_exp_list = [e.strip() for e in edited_exp_text.split("\n") if e.strip()]

                    if not new_exp_list:
                        st.warning("⚠️ 최소 1개 이상의 카테고리를 입력해야 합니다.")
                    else:
                        try:
                            supabase.table("app_settings").upsert({
                                "key": "expense_categories",
                                "value": new_exp_list
                            }, on_conflict="key").execute()

                            st.success("✅ 지출 카테고리가 업데이트되었습니다!")
                            st.rerun()  # 화면을 새로고침하여 전체 메뉴에 변경값 자동 반영
                        except Exception as e:
                            st.error(f"❌ 저장 중 오류 발생: {e}")

     
               # --------------------------------------------------
            # 탭 4: 재고 품목 관리 (단가 기준 직접 수정)
            # --------------------------------------------------
            with tab4:
                st.write("#### 📦 재고 관리 품목 설정")
                st.caption("매장에서 사용하는 재고 품목을 관리합니다. 표에서 '단가' 및 정보를 직접 수정 후 저장할 수 있습니다.")

                # 1. 신규 품목 등록
                with st.expander("➕ 신규 재고 품목 등록", expanded=False):
                    with st.form("add_inv_item_form", clear_on_submit=True):
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            new_item_name = st.text_input("품목명 (예: 우유 1L)")
                            new_category = st.selectbox(
                                "카테고리",
                                [
                                    "원두/음료",
                                    "유제품",
                                    "시럽/소스",
                                    "디저트/베이커리",
                                    "용기/부자재",
                                    "기타",
                                ],
                            )
                        with col2:
                            new_unit = st.text_input("단위 (예: 개, 팩, kg, 박스)", value="개")
                            new_unit_price = st.number_input("단가 (원)", min_value=0, step=100)
                        with col3:
                            new_stock_qty = st.number_input("초기 수량", min_value=0.0, step=1.0)
                            new_safety_qty = st.number_input("안전 재고 수량", min_value=0.0, step=1.0)

                        submit_add = st.form_submit_button("💾 품목 저장", type="primary", use_container_width=True)

                        if submit_add:
                            if not new_item_name.strip():
                                st.error("❌ 품목명을 입력해 주세요.")
                            else:
                                try:
                                    # DB에 실제로 존재하는 6개 필드만 전송
                                    data = {
                                        "item_name": new_item_name.strip(),
                                        "category": new_category,
                                        "unit": new_unit.strip(),
                                        "unit_price": int(new_unit_price),
                                        "current_qty": float(new_stock_qty),
                                        "safety_qty": float(new_safety_qty),
                                    }
                                    supabase.table("inventory").insert(data).execute()
                                    st.success(f"✅ '{new_item_name}' 품목이 성공적으로 등록되었습니다.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"❌ 제출 중 오류가 발생했습니다: {e}")

                st.write("---")

                # 2. 등록된 품목 목록
                try:
                    inv_res = supabase.table("inventory").select("*").execute()
                    inv_df = pd.DataFrame(inv_res.data) if inv_res.data else pd.DataFrame()
                except Exception:
                    inv_df = pd.DataFrame()

                if not inv_df.empty:
                    st.write("#### 📋 등록된 재고 품목 목록")
                    st.caption("💡 수정하려는 셀을 클릭하여 단가나 수량을 변경한 뒤 하단의 저장 버튼을 눌러주세요.")

                    # 불필요한 cost_price 컬럼이 데이터프레임에 있다면 강제 제거
                    if "cost_price" in inv_df.columns:
                        inv_df = inv_df.drop(columns=["cost_price"])

                    category_options = ["원두/음료", "유제품", "시럽/소스", "디저트/베이커리", "용기/부자재", "기타"]

                    # 화면에 보여줄 컬럼 설정
                    column_config = {
                        "id": None,  # id 컬럼 화면 숨김
                        "item_name": st.column_config.TextColumn("품목명", required=True),
                        "category": st.column_config.SelectboxColumn("카테고리", options=category_options, required=True),
                        "unit": st.column_config.TextColumn("단위", required=True),
                        "unit_price": st.column_config.NumberColumn("단가 (원)", min_value=0, step=100, format="%d 원"),
                        "current_qty": st.column_config.NumberColumn("현재 수량", min_value=0.0, step=0.1, format="%.1f"),
                        "safety_qty": st.column_config.NumberColumn("안전재고", min_value=0.0, step=0.1, format="%.1f"),
                    }

                    edited_inv_df = st.data_editor(
                        inv_df,
                        column_config=column_config,
                        use_container_width=True,
                        hide_index=True,
                        key="inventory_table_editor"
                    )

                    col_save, col_del_sel, col_del_btn = st.columns([2, 2, 1])

                    with col_save:
                        if st.button("💾 표 수정사항 저장", type="primary", use_container_width=True, key="save_inv_edit_btn"):
                            try:
                                records = edited_inv_df.to_dict(orient="records")
                                for row in records:
                                    # DB의 실제 존재하는 필드만 명시적으로 구성
                                    payload = {
                                        "item_name": str(row.get("item_name", "")).strip(),
                                        "category": row.get("category"),
                                        "unit": str(row.get("unit", "")).strip(),
                                        "unit_price": int(row.get("unit_price", 0)),
                                        "current_qty": float(row.get("current_qty", 0.0)),
                                        "safety_qty": float(row.get("safety_qty", 0.0))
                                    }
                                    
                                    if "id" in row and pd.notna(row["id"]):
                                        payload["id"] = row["id"]
                                        supabase.table("inventory").upsert(payload).execute()
                                    else:
                                        supabase.table("inventory").upsert(payload, on_conflict="item_name").execute()

                                st.success("✅ 재고 단가 및 정보가 수정되었습니다!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ 제출 중 오류가 발생했습니다: {e}")

                    with col_del_sel:
                        del_target = st.selectbox("삭제할 품목 선택", options=inv_df["item_name"].tolist(), key="del_inv_select", label_visibility="collapsed")

                    with col_del_btn:
                        if st.button("🗑️ 품목 삭제", use_container_width=True, key="del_inv_btn"):
                            try:
                                supabase.table("inventory").delete().eq("item_name", del_target).execute()
                                st.success(f"✅ '{del_target}' 삭제 완료")
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ 삭제 실패: {e}")
                else:
                    st.info("등록된 재고 품목이 없습니다. 상단 폼에서 신규 품목을 등록해 주세요.")
            # --------------------------------------------------
            # 탭 5: 원자재 폐기 사유 및 품목 관리
            # --------------------------------------------------
            with tab5:
                st.write("#### 🗑️ 원자재 폐기 사유 목록 설정")
                wst_res = supabase.table("app_settings").select("value").eq("key", "waste_reasons").execute()
                current_wst = wst_res.data[0]["value"] if wst_res.data else ["유통기한 경과", "제조/조리 실수", "용기/포장 파손", "원두 추출 불량", "기타"]

                edited_wst_text = st.text_area("폐기 사유 목록 (줄바꿈 구분)", value="\n".join(current_wst), height=200, key="wst_tab_area")

                if st.button("💾 폐기 사유 저장", type="primary", key="save_wst_btn"):
                    new_wst_list = [w.strip() for w in edited_wst_text.split("\n") if w.strip()]
                    supabase.table("app_settings").upsert({"key": "waste_reasons", "value": new_wst_list}).execute()
                    st.success("✅ 폐기 사유 목록이 업데이트되었습니다!")
                    st.rerun()