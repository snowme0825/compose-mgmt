import calendar
import datetime

from datetime import timedelta, timezone
import hashlib
import io
import locale

import pandas as pd

def apply_date_colors(df, date_col):
    """데이터프레임의 날짜 컬럼에서 토요일(파란색), 일요일(빨간색) 글자색을 적용합니다."""
    def get_color(val):
        try:
            dt = pd.to_datetime(val)
            if dt.weekday() == 5:    # 토요일
                return 'color: #1E69DE; font-weight: bold;'
            elif dt.weekday() == 6:  # 일요일
                return 'color: #E53E3E; font-weight: bold;'
        except:
            pass
        return ''

    # 지정한 날짜 컬럼에 스타일 적용
    return df.style.applymap(get_color, subset=[date_col])
import plotly.express as px

from supabase import Client, create_client
# DB 설정값을 안전하게 불러오는 공통 함수
def get_setting(key, default_value):
    try:
        res = supabase.table("app_settings").select("value").eq("key", key).execute()
        if res.data and res.data[0].get("value"):
            return res.data[0]["value"]
    except Exception:
        pass
    return default_value
import streamlit as st
import io
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

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
  res = supabase.table("staff").select("name, pin, hourly_rate, role").execute()
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
  res = supabase.table("notice").select("content, updated_at").eq("id", 1).execute()
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
  st.sidebar.warning(f"🚨 대타 교대 승인 요청: **{pending_shifts}건** 대기 중!")

user_mode = st.sidebar.radio(
    "접속 모드를 선택하세요", ["📱 알바생 전용 모드", "🔒 점주 관리자 모드"]
)

# ==========================================
# [모드 1] 📱 알바생 전용 모드
# ==========================================
if user_mode == "📱 알바생 전용 모드":
  staff_dict = get_staff_info()
  staff_names = list(staff_dict.keys())

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

    res_att = (
        supabase.table("attendance")
        .select("*")
        .eq("staff_name", selected_staff)
        .eq("date", today_str)
        .execute()
    )
    att_today = res_att.data[0] if res_att.data else None

    res_sched = (
        supabase.table("schedule")
        .select("start_time, end_time")
        .eq("staff_name", selected_staff)
        .eq("date", today_str)
        .execute()
    )
    sched_today = res_sched.data[0] if res_sched.data else None

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
                        
                        # 1. 현재 시간 정의 (KST 적용)
                        now = datetime.datetime.now(KST)

                        # 2. 근무시간 계산
                        t1 = datetime.datetime.strptime(
                            f"{today_str} {clock_in_time}", "%Y-%m-%d %H:%M"
                        ).replace(tzinfo=KST)
                        t2 = now
                        hours_worked = round((t2 - t1).total_seconds() / 3600.0, 2)

                        # 3. 조퇴 시간 계산
                        early_leave_minutes = 0
                        if sched_today and "end_time" in sched_today:
                            sched_end = datetime.datetime.strptime(
                                f"{today_str} {sched_today['end_time']}", "%Y-%m-%d %H:%M"
                            ).replace(tzinfo=KST)
                            if t2 < sched_end:
                                early_leave_minutes = int((sched_end - t2).total_seconds() / 60)

                        # 4. Supabase 데이터베이스 업데이트
                        supabase.table("attendance").update({
                            "clock_out": now.strftime("%H:%M"),
                            "work_hours": hours_worked,
                            "early_leave_minutes": early_leave_minutes
                        }).eq("id", att_today["id"]).execute()

                        st.success("퇴근 처리가 정상 완료되었습니다!")
                        st.rerun()
                else:
                    st.error("PIN 번호가 올바르지 않습니다.")
    # --- [알바생 화면] 2. 오픈/마감 체크리스트 ---
    with tab_st2:
        st.subheader("📋 업무 체크리스트 수행 및 수정")

        # 1. 날짜 및 오픈/마감 파트 선택
        col_st1, col_st2 = st.columns(2)
        chk_date = col_st1.date_input("점검 날짜", datetime.date.today(), key="staff_chk_date")
        chk_type = col_st2.radio("체크리스트 구분", ["☀️ 오픈", "🌙 마감"], horizontal=True, key="staff_chk_type")

        checker_name = st.selectbox(
            "수행자 이름",
            staff_names if staff_names else ["직원없음"],
            key="chk_staff",
        )

        # 2. 점주 메뉴와 연동된 파트별 항목 불러오기
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

            # 3. 해당 날짜+파트에 이미 제출된 기록 조회 (수정 기능 지원)
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

            # 4. 체크리스트 폼 (기존 체크 상태 반영 및 수정 제출)
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

                    try:
                        if existing_record and "id" in existing_record:
                            supabase.table("checklist").update(payload).eq("id", existing_record["id"]).execute()
                            st.success(f"✅ [{chk_type}] 체크리스트가 성공적으로 수정되었습니다!")
                        else:
                            supabase.table("checklist").insert(payload).execute()
                            st.success(f"✅ [{chk_type}] 체크리스트가 성공적으로 제출되었습니다!")

                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ 저장 중 오류가 발생했습니다: {e}")
        else:
            st.info("💡 등록된 체크리스트 항목이 없습니다. 관리자 메뉴에서 항목을 등록해 주세요.")
# --- [알바생 화면] 3. 알바생 인수인계 ---
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
            .select(
                "id, sender_name, receiver_name, shift_type, content, created_at, is_read"
            )
            .order("id", desc=True)
            .limit(20)
            .execute()
        )
        df_ho = pd.DataFrame(res_ho.data) if res_ho.data else pd.DataFrame()

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
                        supabase.table("handover").eq("id", target_ho_id).update(
                            {"is_read": 1}
                        ).execute()
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

        # 1. 점검자 선택 및 PIN 번호 입력
        col_inv1, col_inv2 = st.columns(2)
        inv_reporter = col_inv1.selectbox("점검자 이름", staff_names if staff_names else ["직원없음"], key="inv_audit_reporter")
        inv_pin = col_inv2.text_input("PIN 번호", type="password", max_chars=4, key="inv_audit_pin")

        # 2. 점주 [재고 현황 & 원가 관리] DB 데이터 최우선 조회
        inv_db_map = {}
        try:
            inv_res = supabase.table("inventory").select("item_name, current_qty, unit, cost_price").execute()
            if inv_res and inv_res.data:
                for row in inv_res.data:
                    inv_db_map[row["item_name"]] = {
                        "current_qty": safe_int(row.get("current_qty")),
                        "unit": row.get("unit", "개") or "개",
                        "cost_price": safe_int(row.get("cost_price")),
                    }
        except Exception as e:
            st.error(f"⚠️ 재고 데이터를 불러오는 중 오류 발생: {e}")

        # 3. 점주 [⚙️ 메뉴 & 항목 설정 관리] 설정 데이터 병합
        default_inv_items = ["원두 (kg)", "우유 (팩)", "빨대 (박스)", "24oz 컵 (박스)", "바닐라 시럽 (병)"]
        setting_inv_items = get_setting("inventory_items", default_inv_items)

        all_item_names = list(inv_db_map.keys())
        for item_name in setting_inv_items:
            if item_name not in all_item_names:
                all_item_names.append(item_name)

        all_audit_items = []
        for item_name in all_item_names:
            db_info = inv_db_map.get(item_name, {"current_qty": 0, "unit": "개", "cost_price": 0})
            all_audit_items.append({
                "item_name": item_name,
                "current_qty": db_info["current_qty"],
                "unit": db_info["unit"],
                "cost_price": db_info["cost_price"],
            })

        if all_audit_items:
            st.write("#### 📝 품목별 실사 수량 입력")
            st.caption("💡 실제 수량을 입력하면 전산 수량과의 차이가 자동 계산되고 최신 재고로 반영됩니다.")

            with st.form(key="inventory_audit_form"):
                actual_counts = {}
                memo_dict = {}

                # 테이블 헤더
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
                reporter_pin = staff_dict.get(inv_reporter, {}).get("pin", "") if 'staff_dict' in locals() else ""

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
                            memo = memo_dict.get(item_name, "")

                            # 1) inventory 테이블 최신 수량 업데이트
                            supabase.table("inventory").upsert({
                                "item_name": item_name,
                                "current_qty": act_qty,
                                "unit": unit,
                                "cost_price": item["cost_price"],
                                "updated_at": now_str
                            }, on_conflict="item_name").execute()

                            # 2) inventory_audit 실사 로그 데이터 구성
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

                        # 3) DB에 실사 이력 즉시 저장
                        supabase.table("inventory_audit").insert(audit_logs).execute()

                        st.success("✅ 재고 실사 제출 완료! 점주 메뉴 [알바생 실사 점검 이력]에 즉시 연동되었습니다.")
                        st.rerun()

                    except Exception as e:
                        st.error(f"❌ DB 저장 오류 발생: {e}")
                else:
                    st.error("❌ PIN 번호가 틀렸습니다.")
        else:
            st.info("💡 등록된 재고 품목이 없습니다. 점주 메뉴에서 재고 품목을 먼저 등록해 주세요.")
    
	 #-- 5. 유통기한/폐기 보고 ---
    with tab_st5:
        st.subheader("🗑️ 유통기한 경과 / 파손 원자재 폐기 보고")
        st.caption(
            "버리게 된 원자재를 등록하면 재고 차감 및 폐기 손실 금액이 자동 계산됩니다."
        )

        col_w1, col_w2 = st.columns(2)
        w_reporter = col_w1.selectbox("보고자", staff_names if staff_names else ["직원없음"], key="w_reporter")
        w_pin = col_w2.text_input("PIN 번호", type="password", max_chars=4, key="w_pin")

        # 1. 점주 설정의 [폐기 사유] 연동 (app_settings)
        default_waste_reasons = ["유통기한 경과", "제조/조리 실수", "용기/포장 파손", "원두 추출 불량", "기타"]
        waste_reasons = get_setting("waste_reasons", default_waste_reasons)

        # 2. 점주 설정의 [재고 품목] 연동 (app_settings)
        default_inv_items = ["원두 (kg)", "우유 (팩)", "빨대 (박스)", "24oz 컵 (박스)", "바닐라 시럽 (병)"]
        setting_inv_items = get_setting("inventory_items", default_inv_items)

        # 3. DB inventory 데이터 및 설정 항목 통합
        inv_dict = {}
        try:
            inv_list_res = (
                supabase.table("inventory")
                .select("item_name, unit, cost_price, current_qty")
                .execute()
            )
            if inv_list_res and inv_list_res.data:
                for i in inv_list_res.data:
                    inv_dict[i["item_name"]] = {
                        "unit": i.get("unit", "개") or "개",
                        "cost": safe_int(i.get("cost_price")),
                        "current_qty": safe_int(i.get("current_qty")),
                    }
        except Exception:
            pass

        # DB에 아직 등록되지 않은 점주 설정 품목 기본값 세팅
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

            # 점주 설정 폐기 사유 연동
            w_reason = st.selectbox("폐기 사유", waste_reasons, key="w_reason_select")

            if st.button("🗑️ 폐기 등록 제출", type="primary", use_container_width=True, key="btn_submit_waste"):
                reporter_pin = staff_dict.get(w_reporter, {}).get("pin", "") if 'staff_dict' in locals() else ""
                
                if verify_hash(w_pin, reporter_pin):
                    now_str = datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
                    today_date_str = datetime.datetime.now(KST).date().strftime("%Y-%m-%d")
                    new_qty = inv_dict[w_item]["current_qty"] - w_qty

                    try:
                        # 1) 재고 수량 차감 및 업서트 (inventory)
                        supabase.table("inventory").upsert({
                            "item_name": w_item,
                            "current_qty": new_qty,
                            "unit": inv_dict[w_item]["unit"],
                            "cost_price": item_cost
                        }, on_conflict="item_name").execute()

                        # 2) 폐기 내역 저장 (waste)
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
      applicant = st.selectbox("신청자", staff_names, key="shift_app")
      substitute = st.selectbox("대타 근무자", staff_names, key="shift_sub")
      shift_date = st.date_input("근무 교대 날짜", key="shift_req_date")

    with col_s2:
      shift_time = st.text_input("근무 시간대 (예: 09:00~15:00)")
      reason = st.text_area("교대 사유")

    if st.button("🔄 대타 승인 요청 제출", type="primary"):
      supabase.table("shift_requests").insert({
          "applicant_name": applicant,
          "substitute_name": substitute,
          "shift_date": str(shift_date),
          "shift_time": shift_time,
          "reason": reason,
          "status": "대기중",
      }).execute()
      st.success("점주님께 대타 승인 요청을 보냈습니다.")

    st.write("---")
    st.subheader("📋 내 대타 신청 처리 현황 (오름차순)")

    shifts_res = (
        supabase.table("shift_requests")
        .select(
            "applicant_name, substitute_name, shift_date, shift_time, reason,"
            " status"
        )
        .order("shift_date", desc=False)
        .order("id", desc=False)
        .execute()
    )

    df_shifts = (
        pd.DataFrame(shifts_res.data)
        if shifts_res.data
        else pd.DataFrame(
            columns=[
                "applicant_name",
                "substitute_name",
                "shift_date",
                "shift_time",
                "reason",
                "status",
            ]
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
    st.dataframe(
        style_date_dataframe(df_shifts, "날짜"), use_container_width=True
    )

  # --- 7. 내 근무 기록 및 급여 ---
  with tab_st7:
    st.subheader("📄 내 근무 기록 및 급여 정산 조회")
    my_name = st.selectbox("본인 이름 선택", staff_names, key="my_name_select")
    my_pin = st.text_input(
        "PIN 번호 확인", type="password", max_chars=4, key="my_pin_check"
    )

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
            "💡 **주휴수당 조건:** 주 15시간 이상 근무 시 자동 계산 | **세금:**"
            " 세전 총급여(기본급+주휴수당)의 3.3% 원천징수 공제"
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
  if not st.session_state["admin_logged_in"]:
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

    pending_shifts = get_pending_shift_count()
    pending_badge = f" (🚨 {pending_shifts}건)" if pending_shifts > 0 else ""
    shift_menu_label = f"🔄 대타 신청 승인{pending_badge}"

# 기본 점주 메뉴 목록 (DB에 별도 설정이 없을 때 사용)
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
        "📥 전체 데이터 엑셀/CSV 다운로드",
        "⚠️ 데이터 초기화",
        "⚙️ 메뉴 & 항목 설정 관리",
    ]

    # DB에서 점주님이 커스텀한 메뉴 목록 불러오기
    try:
        menu_res = (
            supabase.table("app_settings")
            .select("value")
            .eq("key", "admin_menus")
            .execute()
        )
        if menu_res.data and isinstance(menu_res.data[0]["value"], list):
            admin_menu_options = menu_res.data[0]["value"]
        else:
            admin_menu_options = DEFAULT_ADMIN_MENUS
    except Exception:
        admin_menu_options = DEFAULT_ADMIN_MENUS

    admin_menu = st.sidebar.selectbox("점주 관리 메뉴", admin_menu_options)

   # 1. 매출 분석 & 손익계산서 (P&L)
    if admin_menu == "📝 매출 분석 & 손익계산서(P&L)":
        st.subheader("📝 일별 매출 등록 & 손익계산서 (P&L)")

        # DB 설정에서 배달 플랫폼 및 수수료율 불러오기
        del_data = get_setting("delivery_platforms", [
            {"플랫폼명": "배달의민족", "수수료율 (%)": 6.8},
            {"플랫폼명": "쿠팡이츠", "수수료율 (%)": 9.8},
            {"플랫폼명": "요기요", "수수료율 (%)": 12.5},
            {"플랫폼명": "땡겨요", "수수료율 (%)": 2.0},
            {"플랫폼명": "네이버주문", "수수료율 (%)": 1.65},
            {"플랫폼명": "기타", "수수료율 (%)": 0.0}
        ])

        # 배달 플랫폼 목록 및 수수료율 매핑 구조 생성
        platform_list = []
        fee_rate_dict = {}
        for item in del_data:
            if isinstance(item, dict):
                p_name = item.get("플랫폼명", "기타")
                p_rate = safe_float(item.get("수수료율 (%)"), 0.0)
            else:
                p_name = str(item)
                p_rate = 0.0
            platform_list.append(p_name)
            fee_rate_dict[p_name] = p_rate

        if not platform_list:
            platform_list = ["배달의민족", "쿠팡이츠", "요기요", "땡겨요", "기타"]

        with st.expander("➕ 일별 세부 매출 입력 (홀/배달 분리)", expanded=True):
            sales_date = st.date_input("📅 매출 날짜 선택", key="sales_date_picker")

            existing_res = (
                supabase.table("daily_sales")
                .select("*")
                .eq("date", str(sales_date))
                .execute()
            )
            existing_sales = existing_res.data[0] if existing_res.data else None

            if existing_sales:
                init_cash = safe_int(existing_sales.get("cash_sales"))
                init_card = safe_int(existing_sales.get("card_sales"))
                init_other = safe_int(existing_sales.get("other_sales"))
                init_reward = safe_int(existing_sales.get("reward_sales"))
                init_platform = existing_sales.get("delivery_platform") or platform_list[0]
                init_delivery_gross = safe_int(existing_sales.get("delivery_gross"))
                init_fee_rate = safe_float(
                    existing_sales.get("delivery_fee_rate"),
                    fee_rate_dict.get(init_platform, 0.0)
                )
                init_delivery_count = safe_int(existing_sales.get("delivery_count"))
                init_rider_fee = safe_int(existing_sales.get("rider_fee"))
                init_memo = existing_sales.get("memo") or ""
            else:
                init_cash = init_card = init_other = init_reward = 0
                init_platform = platform_list[0] if platform_list else "배달의민족"
                init_fee_rate = fee_rate_dict.get(init_platform, 0.0)
                init_delivery_gross = 0
                init_delivery_count, init_rider_fee, init_memo = 0, 0, ""

            st.markdown("#### 🏢 1. 홀 매출 입력")
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
                "🎁 리워드 (원)",
                min_value=0,
                step=1000,
                value=init_reward,
                key=f"reward_{sales_date}",
            )

            hall_sales_calc = cash_sales + card_sales + other_sales + reward_sales
            st.caption(f"👉 **홀 매출 소계:** `{hall_sales_calc:,}` 원")

            st.write("---")

            st.markdown("#### 🛵 2. 배달 매출 입력")

            p_key = f"platform_{sales_date}"
            f_key = f"fee_rate_{sales_date}"

            if (
                "current_sales_date_ref" not in st.session_state
                or st.session_state["current_sales_date_ref"] != str(sales_date)
            ):
                st.session_state["current_sales_date_ref"] = str(sales_date)
                st.session_state[p_key] = init_platform if init_platform in platform_list else platform_list[0]
                st.session_state[f_key] = init_fee_rate

            def on_platform_change():
                selected_p = st.session_state[p_key]
                st.session_state[f_key] = fee_rate_dict.get(selected_p, 0.0)

            col_d1, col_d2, col_d3 = st.columns(3)
            delivery_platform = col_d1.selectbox(
                "🛵 배달 플랫폼 선택",
                platform_list,
                key=p_key,
                on_change=on_platform_change,
            )
            fee_rate = col_d2.number_input(
                "📊 수수료율 (%)",
                min_value=0.0,
                max_value=100.0,
                step=0.1,
                key=f_key,
            )
            delivery_gross = col_d3.number_input(
                "💵 플랫폼 총 매출액 (원)",
                min_value=0,
                step=1000,
                value=init_delivery_gross,
                key=f"gross_{sales_date}",
            )

            col_cnt1, col_cnt2, col_cnt3 = st.columns(3)
            delivery_count = col_cnt1.number_input(
                "📦 배달 건수 (건)",
                min_value=0,
                step=1,
                value=init_delivery_count,
                key=f"cnt_{sales_date}",
            )
            rider_fee = col_cnt2.number_input(
                "🚴 건당 라이더 수수료 (원)",
                min_value=0,
                step=100,
                value=init_rider_fee,
                key=f"rider_{sales_date}",
            )

            fee_amount = int(delivery_gross * (fee_rate / 100.0))
            total_rider_fee_calc = delivery_count * rider_fee
            delivery_sales_calc = (
                delivery_gross - fee_amount - total_rider_fee_calc
            )
            total_deduct = fee_amount + total_rider_fee_calc

            col_cnt3.metric(
                "✨ 수수료 적용 배달 순매출",
                f"{delivery_sales_calc:,} 원",
                delta=(
                    f"차감 합계: -{total_deduct:,}원 (플랫폼: -{fee_amount:,}원 / 라이더:"
                    f" -{total_rider_fee_calc:,}원)"
                ),
            )

            st.write("---")

            total_sales_calc = hall_sales_calc + delivery_sales_calc
            col_m5, col_m6 = st.columns([3, 1])
            sales_memo = col_m5.text_input(
                "📝 메모 / 특이사항", value=init_memo, key=f"memo_{sales_date}"
            )

            st.info(
                f"💡 **[{sales_date}] 총 매출합계:** `{total_sales_calc:,}` 원 | "
                f"**홀 매출:** {hall_sales_calc:,}원 | "
                f"**배달 순매출:** {delivery_sales_calc:,}원 ({delivery_platform})"
            )

            if st.button("💾 매출 저장", type="primary", use_container_width=True):
                supabase.table("daily_sales").upsert(
                    {
                        "date": str(sales_date),
                        "cash_sales": cash_sales,
                        "card_sales": card_sales,
                        "other_sales": other_sales,
                        "reward_sales": reward_sales,
                        "hall_sales": hall_sales_calc,
                        "delivery_platform": delivery_platform,
                        "delivery_gross": delivery_gross,
                        "delivery_fee_rate": fee_rate,
                        "delivery_sales": delivery_sales_calc,
                        "delivery_count": delivery_count,
                        "rider_fee": rider_fee,
                        "sales_amount": total_sales_calc,
                        "memo": sales_memo,
                    },
                    on_conflict="date",
                ).execute()

                st.success(
                    f"✅ [{sales_date}] 매출 기록이 정상 저장되었습니다! (총액:"
                    f" {total_sales_calc:,}원)"
                )
                st.rerun()

        st.write("---")
        st.subheader("📊 손익계산서 요약 (매출 - 인건비 - 엠즈푸드발주 - 폐기손실)")

        sales_list = (
            supabase.table("daily_sales")
            .select("*")
            .order("date", desc=False)
            .execute()
            .data
        )
        df_s = pd.DataFrame(sales_list) if sales_list else pd.DataFrame()

        waste_list = (
            supabase.table("waste").select("loss_amount").execute().data
        )
        waste_loss_sum = (
            sum([safe_int(w.get("loss_amount")) for w in waste_list])
            if waste_list
            else 0
        )

        mfood_list = (
            supabase.table("mfood_orders").select("amount").execute().data
        )
        mfood_loss_sum = (
            sum([safe_int(m.get("amount")) for m in mfood_list])
            if mfood_list
            else 0
        )

        if not df_s.empty:
            df_s = df_s.rename(
                columns={
                    "date": "날짜",
                    "hall_sales": "홀매출(원)",
                    "delivery_platform": "배달플랫폼",
                    "delivery_gross": "배달총액(원)",
                    "delivery_fee_rate": "수수료율(%)",
                    "delivery_sales": "배달순매출(원)",
                    "delivery_count": "배달건수(건)",
                    "rider_fee": "라이더수수료(원)",
                    "sales_amount": "총매출(원)",
                    "memo": "비고",
                }
            )
            df_s["홀매출(원)"] = df_s["홀매출(원)"].fillna(0)
            df_s["배달총액(원)"] = df_s["배달총액(원)"].fillna(0)
            df_s["수수료율(%)"] = df_s["수수료율(%)"].fillna(0.0)
            df_s["배달건수(건)"] = df_s["배달건수(건)"].fillna(0)
            df_s["라이더수수료(원)"] = df_s["라이더수수료(원)"].fillna(0)

            fee_amounts = (
                df_s["배달총액(원)"] * (df_s["수수료율(%)"] / 100.0)
            ).astype(int)
            rider_fees = df_s["배달건수(건)"] * df_s["라이더수수료(원)"]
            df_s["배달순매출(원)"] = df_s["배달총액(원)"] - fee_amounts - rider_fees
            df_s["총매출(원)"] = df_s["홀매출(원)"] + df_s["배달순매출(원)"]

        total_sales = safe_int(df_s["총매출(원)"].sum()) if not df_s.empty else 0
        total_rider_fee = (
            safe_int((df_s["배달건수(건)"] * df_s["라이더수수료(원)"]).sum())
            if not df_s.empty
            else 0
        )

        staff_dict = get_staff_info()
        total_gross_labor = 0
        total_net_labor = 0
        for name in staff_dict.keys():
            summary = calculate_person_summary(name)
            total_gross_labor += summary["gross_pay"]
            total_net_labor += summary["total_pay"]

        net_profit = (
            total_sales - total_gross_labor - mfood_loss_sum - waste_loss_sum
        )
        profit_rate = (
            round(net_profit / total_sales * 100, 1) if total_sales > 0 else 0
        )

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("총 매출액", f"{total_sales:,} 원")
        m2.metric(
            "총 인건비 (세전)",
            f"{total_gross_labor:,} 원",
            help=f"직원 실수령 합계: {total_net_labor:,}원 (3.3% 세금 포함)",
        )
        m3.metric("총 엠즈푸드 발주액", f"{mfood_loss_sum:,} 원")
        m4.metric(
            "라이더 수수료 합계",
            f"{total_rider_fee:,} 원",
            help="배달 순매출에 이미 차감 반영됨",
        )
        m5.metric(
            "추정 영업 이익", f"{net_profit:,} 원", delta=f"매출 대비 {profit_rate}%"
        )

        st.write("### 📅 일자별 상세 매출 기록 (1일 순서 오름차순)")
        col_d1, col_d2 = st.columns([3, 1])
        with col_d2:
            if not df_s.empty:
                today_str = datetime.datetime.now(KST).date()
                st.download_button(
                    label="📥 매출 기록 CSV 다운로드",
                    data=convert_df_to_csv(df_s),
                    file_name=f"compose_sales_{today_str}.csv",
                    mime="text/csv",
                )

        if not df_s.empty:
            st.dataframe(
                style_date_dataframe(df_s, "날짜"),
                column_config={
                    "홀매출(원)": st.column_config.NumberColumn(format="%,d 원"),
                    "배달총액(원)": st.column_config.NumberColumn(format="%,d 원"),
                    "수수료율(%)": st.column_config.NumberColumn(format="%.1f %%"),
                    "배달순매출(원)": st.column_config.NumberColumn(format="%,d 원"),
                    "배달건수(건)": st.column_config.NumberColumn(format="%,d 건"),
                    "라이더수수료(원)": (
                        st.column_config.NumberColumn(format="%,d 원")
                    ),
                    "총매출(원)": st.column_config.NumberColumn(format="%,d 원"),
                },
                use_container_width=True,
            )
    # 2. 엠즈푸드 발주 등록 (DB 컬럼명 'day' 및 주말 색상 스타일 적용)
    elif "엠즈푸드" in admin_menu:
        st.subheader("📦 엠즈푸드 발주 등록 & 내역 관리")

        with st.expander("➕ 새로운 엠즈푸드 발주 내역 입력", expanded=True):
            col_m1, col_m2, col_m3 = st.columns([2, 2, 3])
            order_date = col_m1.date_input("📅 발주 날짜", key="mfood_date_picker")
            item_name = col_m2.text_input("🏷️ 품목명 / 내역", placeholder="예: 원두, 우유, 파우더 등", key="mfood_item_input")
            order_amount = col_m3.number_input("💵 발주 금액 (원)", min_value=0, step=1000, key="mfood_amount_input")

            order_memo = st.text_input("📝 비고 / 메모", key="mfood_memo_input")

            if st.button("💾 발주 내역 저장", type="primary", use_container_width=True):
                if order_amount <= 0:
                    st.warning("⚠️ 발주 금액을 0원 이상 입력해 주세요.")
                elif not item_name.strip():
                    st.warning("⚠️ 품목명 또는 내역을 입력해 주세요.")
                else:
                    # DB 컬럼명 'day'로 지정하여 저장
                    supabase.table("mfood_orders").insert({
                        "day": str(order_date),
                        "item_name": item_name.strip(),
                        "amount": order_amount,
                        "memo": order_memo
                    }).execute()

                    st.success(f"✅ [{order_date}] {item_name} ({order_amount:,}원) 발주 내역이 저장되었습니다!")
                    st.rerun()

        st.write("---")
        st.subheader("📊 엠즈푸드 발주 내역 조회 및 삭제")

        # Supabase DB에서 발주 내역 불러오기 ('day' 컬럼 기준 정렬)
        mfood_res = (
            supabase.table("mfood_orders")
            .select("*")
            .order("day", desc=True)
            .execute()
        )
        mfood_list = mfood_res.data if mfood_res and mfood_res.data else []
        df_mfood = pd.DataFrame(mfood_list) if mfood_list else pd.DataFrame()

        if not df_mfood.empty:
            column_mapping = {
                "id": "ID",
                "day": "날짜",
                "item_name": "품목명",
                "amount": "발주금액(원)",
                "memo": "메모"
            }
            df_mfood = df_mfood.rename(columns={k: v for k, v in column_mapping.items() if k in df_mfood.columns})

            # 총 발주 금액 요약
            total_mfood = safe_int(df_mfood["발주금액(원)"].sum()) if "발주금액(원)" in df_mfood.columns else 0
            
            col_stat1, col_stat2 = st.columns([1, 2])
            col_stat1.metric("📦 총 엠즈푸드 발주 합계", f"{total_mfood:,} 원")

            display_cols = [c for c in ["날짜", "품목명", "발주금액(원)", "메모"] if c in df_mfood.columns]

            # style_date_dataframe을 적용하여 토/일요일 색상 복구
            st.dataframe(
                style_date_dataframe(df_mfood[display_cols], "날짜"),
                column_config={
                    "발주금액(원)": st.column_config.NumberColumn(format="%,d 원"),
                },
                use_container_width=True
            )

            # 삭제 기능
            with st.expander("🗑️ 발주 내역 삭제"):
                if "ID" in df_mfood.columns:
                    delete_options = [
                        f"[{row.get('날짜', '')}] {row.get('품목명', '')} - {safe_int(row.get('발주금액(원)')):,}원 (ID: {row['ID']})"
                        for _, row in df_mfood.iterrows()
                    ]
                    selected_del = st.selectbox("삭제할 발주 항목 선택", delete_options)
                    
                    if st.button("❌ 선택한 발주 내역 삭제", type="secondary"):
                        target_id = int(selected_del.split("ID: ")[1].replace(")", ""))
                        supabase.table("mfood_orders").delete().eq("id", target_id).execute()
                        st.success("해당 발주 내역이 성공적으로 삭제되었습니다.")
                        st.rerun()
        else:
            st.info("💡 등록된 엠즈푸드 발주 내역이 없습니다. 위에서 새로운 발주 내역을 입력해 주세요.")
    
        
    # 3. 종합 매출/비용 시각화 분석
    elif admin_menu == "📈 종합 매출/비용 시각화 분석":
      st.subheader("📈 종합 매출 패턴 & 비용 분석 시각화")

      sales_res = (
          supabase.table("daily_sales")
          .select(
              "date, hall_sales, delivery_gross, delivery_fee_rate,"
              " delivery_count, rider_fee"
          )
          .order("date", desc=False)
          .execute()
      )
      df_s = pd.DataFrame(sales_res.data) if sales_res.data else pd.DataFrame()

      waste_res = (
          supabase.table("waste").select("item_name, loss_amount").execute()
      )
      if waste_res.data:
        df_w_raw = pd.DataFrame(waste_res.data)
        df_waste_chart = (
            df_w_raw.groupby("item_name", as_index=False)["loss_amount"]
            .sum()
            .rename(columns={"loss_amount": "total_loss"})
        )
      else:
        df_waste_chart = pd.DataFrame(columns=["item_name", "total_loss"])

      mf_res = (
          supabase.table("mfood_orders")
          .select("year_month, amount")
          .execute()
      )
      if mf_res.data:
        df_mf_raw = pd.DataFrame(mf_res.data)
        df_mf_chart = (
            df_mf_raw.groupby("year_month", as_index=False)["amount"]
            .sum()
            .rename(columns={"amount": "total_mf"})
            .sort_values("year_month")
        )
      else:
        df_mf_chart = pd.DataFrame(columns=["year_month", "total_mf"])

      if not df_s.empty:
        df_s["hall_sales"] = df_s["hall_sales"].fillna(0)
        df_s["delivery_gross"] = df_s["delivery_gross"].fillna(0)
        df_s["delivery_fee_rate"] = df_s["delivery_fee_rate"].fillna(0.0)
        df_s["delivery_count"] = df_s["delivery_count"].fillna(0)
        df_s["rider_fee"] = df_s["rider_fee"].fillna(0)

        fee_amt = (
            df_s["delivery_gross"] * (df_s["delivery_fee_rate"] / 100.0)
        ).astype(int)
        rider_amt = df_s["delivery_count"] * df_s["rider_fee"]
        deliv_net = df_s["delivery_gross"] - fee_amt - rider_amt
        df_s["sales_amount"] = df_s["hall_sales"] + deliv_net

      tab_v1, tab_v2, tab_v3, tab_v4 = st.tabs([
          "📊 일별/월별/요일별 매출 추이",
          "🚚 엠즈푸드 발주 지출 추이",
          "🗑️ 품목별 폐기 손실 비중",
          "💰 직원별 인건비 비중",
      ])

      with tab_v1:
        if not df_s.empty:
          df_s["date"] = pd.to_datetime(df_s["date"])

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
              hovertemplate=(
                  "<b>날짜</b>: %{x|%Y년 %m월 %d일}<br><b>매출액</b>:"
                  " %{y:,.0f}원<extra></extra>"
              ),
          )
          fig_line.update_xaxes(title_text="날짜", tickformat="%Y-%m-%d")
          fig_line.update_yaxes(title_text="매출액 (원)")
          st.plotly_chart(fig_line, use_container_width=True)

          st.write("---")

          df_s["연월"] = df_s["date"].dt.strftime("%Y년 %m월")
          monthly_sales = df_s.groupby("연월", as_index=False)[
              "sales_amount"
          ].sum()

          fig_monthly = px.bar(
              monthly_sales,
              x="연월",
              y="sales_amount",
              title="📅 월별 총 매출 추이",
              labels={"연월": "년-월", "sales_amount": "총 매출액 (원)"},
              text_auto=",.0f",
          )
          fig_monthly.update_traces(
              marker_color="#FF9900",
              hovertemplate=(
                  "<b>월</b>: %{x}<br><b>총 매출액</b>: %{y:,.0f}원<extra></extra>"
              ),
          )
          fig_monthly.update_xaxes(title_text="년-월")
          fig_monthly.update_yaxes(title_text="총 매출액 (원)")
          st.plotly_chart(fig_monthly, use_container_width=True)

          st.write("---")

          df_s["요일"] = df_s["date"].dt.day_name()
          weekday_map = {
              "Monday": "월요일",
              "Tuesday": "화요일",
              "Wednesday": "수요일",
              "Thursday": "목요일",
              "Friday": "금요일",
              "Saturday": "토요일",
              "Sunday": "일요일",
          }
          df_s["요일"] = df_s["요일"].map(weekday_map)
          day_order = [
              "월요일",
              "화요일",
              "수요일",
              "목요일",
              "금요일",
              "토요일",
              "일요일",
          ]
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
              hovertemplate=(
                  "<b>요일</b>: %{x}<br><b>평균 매출액</b>:"
                  " %{y:,.0f}원<extra></extra>"
              )
          )
          fig_bar.update_xaxes(title_text="요일")
          fig_bar.update_yaxes(title_text="평균 매출액 (원)")
          fig_bar.update_layout(coloraxis_colorbar=dict(title="매출 (원)"))
          st.plotly_chart(fig_bar, use_container_width=True)
        else:
          st.info("등록된 매출 데이터가 없습니다.")

      with tab_v2:
        if not df_mf_chart.empty and df_mf_chart["total_mf"].sum() > 0:

          def format_ym(ym_str):
            try:
              parts = ym_str.split("-")
              return f"{parts[0]}년 {int(parts[1]):02d}월"
            except Exception:
              return ym_str

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
              hovertemplate=(
                  "<b>월</b>: %{x}<br><b>발주 지출액</b>:"
                  " %{y:,.0f}원<extra></extra>"
              ),
          )
          fig_mf.update_xaxes(title_text="년-월")
          fig_mf.update_yaxes(title_text="발주 지출액 (원)")
          st.plotly_chart(fig_mf, use_container_width=True)
        else:
          st.info("등록된 엠즈푸드 발주 지출 데이터가 없거나 0원입니다.")

      with tab_v3:
        if (
            not df_waste_chart.empty
            and df_waste_chart["total_loss"].sum() > 0
        ):
          fig_pie = px.pie(
              df_waste_chart,
              names="item_name",
              values="total_loss",
              title="🗑️ 원자재 품목별 폐기 손실 금액 비중",
              hole=0.4,
              labels={"item_name": "품목명", "total_loss": "손실 금액 (원)"},
          )
          fig_pie.update_traces(
              hovertemplate=(
                  "<b>품목명</b>: %{label}<br><b>손실 금액</b>:"
                  " %{value:,.0f}원 (%{percent})<extra></extra>"
              )
          )
          st.plotly_chart(fig_pie, use_container_width=True)
        else:
          st.info("등록된 폐기 손실 데이터가 없거나 금액이 0원입니다.")

      with tab_v4:
        staff_dict = get_staff_info()
        labor_data = []
        for name in staff_dict.keys():
          res = calculate_person_summary(name)
          if res["gross_pay"] > 0:
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
              hovertemplate=(
                  "<b>직원명</b>: %{label}<br><b>세전 총급여</b>:"
                  " %{value:,.0f}원 (%{percent})<extra></extra>"
              )
          )
          st.plotly_chart(fig_donut, use_container_width=True)
        else:
          st.info("정산할 근무 기록이 없습니다.")

# 지출 및 비용 관리 메뉴
    elif "지출" in admin_menu or "비용" in admin_menu:
        st.subheader("💸 매장 지출 및 비용 관리 (점주 전용)")

        tab_exp_add, tab_exp_list = st.tabs(["➕ 지출 입력", "📊 지출 내역 및 조회"])

        # --------------------------------------------------
        # TAB 1: 신규 지출 등록
        # --------------------------------------------------
        with tab_exp_add:
            st.write("#### 📝 신규 지출 등록")
            
            # DB에서 지출 카테고리 목록을 실시간으로 가져옴
            default_exp_categories = ["원부자재(원두/시럽 등)", "임대료/공과금", "인건비", "소모품/비품", "수리/유지보수", "마케팅/홍보", "기타"]
            exp_categories = get_setting("expense_categories", default_exp_categories)

            with st.form("expense_form", clear_on_submit=True):
                col_e1, col_e2 = st.columns(2)
                exp_date = col_e1.date_input("지출 날짜", datetime.date.today())
                
                # 점주가 설정을 통해 연동한 카테고리 목록 적용
                exp_category = col_e2.selectbox("지출 카테고리", exp_categories)

                col_e3, col_e4 = st.columns(2)
                exp_item = col_e3.text_input("지출 항목명", placeholder="예: 우유 10박스, 전기요금 등")
                exp_amount = col_e4.number_input("지출 금액 (원)", min_value=0, step=1000, value=0)

                col_e5, col_e6 = st.columns(2)
                exp_method = col_e5.selectbox("결제 수단", ["카드", "계좌이체", "현금", "기타"])
                exp_memo = col_e6.text_input("비고 / 메모", placeholder="예: OO유통 입금 완료")

                if st.form_submit_button("💰 지출 내역 저장", type="primary", use_container_width=True):
                    if exp_item.strip() and exp_amount > 0:
                        now_str = datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
                        try:
                            supabase.table("expenses").insert({
                                "date": str(exp_date),
                                "category": exp_category,
                                "item_name": exp_item.strip(),
                                "amount": exp_amount,
                                "payment_method": exp_method,
                                "memo": exp_memo.strip(),
                                "created_at": now_str
                            }).execute()
                            st.success(f"✅ [{exp_date}] {exp_item.strip()} ({exp_amount:,}원) 지출 내역이 저장되었습니다.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ 저장 중 오류 발생: {e}")
                    else:
                        st.warning("⚠️ 지출 항목명과 0원 이상의 금액을 올바르게 입력해 주세요.")

        # TAB 2: 지출 내역 및 통계 (이전과 동일)
        with tab_exp_list:
            st.write("#### 📅 지출 내역 조회 및 관리")
            try:
                res_exp = supabase.table("expenses").select("*").order("date", desc=True).execute()
                exp_list = res_exp.data if res_exp and res_exp.data else []

                if exp_list:
                    df_exp = pd.DataFrame(exp_list)
                    total_exp = df_exp["amount"].sum()
                    st.metric("총 등록 지출 합계", f"{total_exp:,} 원")

                    df_disp = df_exp.copy()
                    df_disp.rename(columns={
                        "date": "날짜",
                        "category": "카테고리",
                        "item_name": "항목명",
                        "amount": "금액(원)",
                        "payment_method": "결제수단",
                        "memo": "메모"
                    }, inplace=True)

                    df_disp["금액(원)"] = df_disp["금액(원)"].apply(lambda x: f"{x:,}")
                    cols_to_show = ["날짜", "카테고리", "항목명", "금액(원)", "결제수단", "메모"]

                    st.dataframe(style_date_dataframe(df_disp[cols_to_show], "날짜"), use_container_width=True)

                    st.write("---")
                    st.write("#### 🗑️ 지출 내역 삭제")
                    del_exp_id = st.selectbox(
                        "삭제할 항목 선택",
                        df_exp["id"].tolist(),
                        format_func=lambda x: f"[{df_exp[df_exp['id']==x]['date'].values[0]}] {df_exp[df_exp['id']==x]['item_name'].values[0]} ({df_exp[df_exp['id']==x]['amount'].values[0]:,}원)"
                    )
                    if st.button("❌ 선택한 지출 내역 삭제", type="secondary"):
                        supabase.table("expenses").eq("id", del_exp_id).delete().execute()
                        st.success("지출 내역이 삭제되었습니다.")
                        st.rerun()
                else:
                    st.info("💡 등록된 지출 내역이 없습니다.")
            except Exception:
                st.warning("💡 Supabase 'expenses' 테이블 생성이 필요합니다.")

    # 4. 대타 신청 승인
    elif admin_menu.startswith("🔄 대타 신청 승인"):
      st.subheader("🔄 대타 신청 승인 관리")

      pending_req_res = (
          supabase.table("shift_requests")
          .select("*")
          .eq("status", "대기중")
          .order("shift_date", desc=False)
          .execute()
      )
      pending_requests = pending_req_res.data or []

      if pending_requests:
        for req in pending_requests:
          req_id = req.get("id")
          app = req.get("applicant_name")
          sub = req.get("substitute_name")
          date_str = req.get("shift_date")
          time_str = req.get("shift_time")
          reason = req.get("reason")

          st.warning(
              f"📌 **{app}** ➡️ **{sub}** 교대 요청 | 날짜: {date_str}"
              f" ({time_str})"
          )
          st.write(f"사유: {reason}")
          col_a1, col_a2 = st.columns(2)
          if col_a1.button(f"✅ 승인 (#{req_id})", key=f"app_{req_id}"):
            supabase.table("shift_requests").update(
                {"status": "승인됨"}
            ).eq("id", req_id).execute()
            st.success("승인 처리되었습니다.")
            st.rerun()
          if col_a2.button(f"❌ 거절 (#{req_id})", key=f"rej_{req_id}"):
            supabase.table("shift_requests").update(
                {"status": "거절됨"}
            ).eq("id", req_id).execute()
            st.error("거절 처리되었습니다.")
            st.rerun()
      else:
        st.success("대기 중인 대타 교대 신청이 없습니다.")

      st.write("---")
      st.subheader("📋 전체 대타 교대 이력 (오름차순)")
      res_all_req = (
          supabase.table("shift_requests")
          .select(
              "id, applicant_name, substitute_name, shift_date, shift_time,"
              " reason, status"
          )
          .order("shift_date", desc=False)
          .order("id", desc=False)
          .execute()
      )
      df_all_req = (
          pd.DataFrame(res_all_req.data) if res_all_req.data else pd.DataFrame()
      )
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
        st.dataframe(
            style_date_dataframe(df_all_req, "날짜"), use_container_width=True
        )
      else:
        st.info("전체 대타 교대 이력이 없습니다.")

    # 5. 알바생 인수인계 이력 점검
    elif admin_menu == "🤝 알바생 인수인계 이력 점검":
      st.subheader("🤝 알바생 근무 인수인계 전체 이력 조회")

      res_ho = (
          supabase.table("handover")
          .select(
              "id, sender_name, receiver_name, shift_type, content,"
              " created_at, is_read"
          )
          .order("id", desc=True)
          .execute()
      )
      df_ho_admin = pd.DataFrame(res_ho.data) if res_ho.data else pd.DataFrame()
      if not df_ho_admin.empty:
        df_ho_admin["상태"] = df_ho_admin["is_read"].apply(
            lambda x: "✅ 확인완료" if x == 1 or x is True else "⏳ 미확인"
        )
        df_ho_admin = df_ho_admin.rename(
            columns={
                "id": "번호",
                "sender_name": "인계자",
                "receiver_name": "인수자",
                "shift_type": "교대유형",
                "content": "인수인계내용",
                "created_at": "작성시각",
            }
        )[
            [
                "번호",
                "인계자",
                "인수자",
                "교대유형",
                "인수인계내용",
                "작성시각",
                "상태",
            ]
        ]

      col_ho_a1, col_ho_a2 = st.columns([3, 1])
      with col_ho_a2:
        if not df_ho_admin.empty:
          today_date = datetime.datetime.now(KST).date()
          st.download_button(
              label="📥 인수인계 기록 CSV 다운로드",
              data=convert_df_to_csv(df_ho_admin),
              file_name=f"compose_handover_{today_date}.csv",
              mime="text/csv",
          )

      if not df_ho_admin.empty:
        st.dataframe(df_ho_admin, use_container_width=True)
      else:
        st.info("등록된 인수인계 기록이 없습니다.")

    # 6.[점주] 원자재 재고 현황 & 단가 관리# --------------------------------------------------
    # 점주 메뉴: 📦 재고 현황 & 원가 관리 (알바생 실사 완벽 연동)
    # --------------------------------------------------
    elif admin_menu == "📦 재고 현황 & 원가 관리":
        st.subheader("📦 재고 현황 및 실사 이력 관리")
        st.caption("현재 전산 재고 수량을 관리하고, 알바생이 점검한 실사 기록 및 오차를 실시간으로 확인합니다.")

        tab_inv1, tab_inv2 = st.tabs(["📋 현재 재고 현황 및 단가 수정", "📜 알바생 실사 점검 이력"])

        # --------------------------------------------------
        # 탭 1: 현재 재고 현황 및 단가 관리
        # --------------------------------------------------
        with tab_inv1:
            st.write("#### 📋 현재 매장 전산 재고 목록")
            try:
                inv_res = supabase.table("inventory").select("*").order("item_name").execute()
                inv_data = inv_res.data if inv_res else []
            except Exception as e:
                st.error(f"❌ 재고 목록 불러오기 실패: {e}")
                inv_data = []

            if inv_data:
                df_inv = pd.DataFrame(inv_data)
                
                disp_inv = df_inv[["item_name", "current_qty", "unit", "cost_price"]].copy()
                disp_inv.columns = ["품목명", "현재 수량", "단위", "단가(원)"]

                edited_inv_df = st.data_editor(
                    disp_inv,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "현재 수량": st.column_config.NumberColumn("현재 수량", min_value=0, step=1),
                        "단가(원)": st.column_config.NumberColumn("단가(원)", min_value=0, step=10, format="%d 원"),
                    },
                    key="inventory_editor"
                )

                if st.button("💾 재고 및 단가 수정사항 저장", type="primary", key="save_inv_master"):
                    try:
                        for _, row in edited_inv_df.iterrows():
                            supabase.table("inventory").upsert({
                                "item_name": row["품목명"],
                                "current_qty": safe_int(row["현재 수량"]),
                                "cost_price": safe_int(row["단가(원)"]),
                                "unit": row["단위"]
                            }, on_conflict="item_name").execute()
                        st.success("✅ 재고 수량 및 단가가 성공적으로 업데이트되었습니다!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ 저장 중 오류 발생: {e}")
            else:
                st.info("💡 등록된 재고가 없습니다. [⚙️ 메뉴 & 항목 설정 관리]에서 재고 품목을 설정해 주세요.")

        # --------------------------------------------------
        # 탭 2: 알바생 실사 점검 이력 (실시간 연동)
        # --------------------------------------------------
        with tab_inv2:
            st.write("#### 📜 알바생 재고 실사 점검 내역")
            
            col_a1, col_a2 = st.columns(2)
            audit_start = col_a1.date_input("조회 시작일", datetime.datetime.now(KST).date() - datetime.timedelta(days=14), key="audit_start_dt")
            audit_end = col_a2.date_input("조회 종료일", datetime.datetime.now(KST).date(), key="audit_end_dt")

            try:
                audit_res = (
                    supabase.table("inventory_audit")
                    .select("*")
                    .gte("date", audit_start.strftime("%Y-%m-%d"))
                    .lte("date", audit_end.strftime("%Y-%m-%d"))
                    .order("created_at", desc=True)
                    .execute()
                )
                audit_data = audit_res.data if audit_res else []
            except Exception as e:
                st.error(f"❌ 실사 이력을 불러오는 중 오류 발생: {e}")
                audit_data = []

            if audit_data:
                df_audit = pd.DataFrame(audit_data)

                df_audit["system_qty"] = df_audit["system_qty"].apply(safe_int)
                df_audit["actual_qty"] = df_audit["actual_qty"].apply(safe_int)
                df_audit["diff_qty"] = df_audit["diff_qty"].apply(safe_int)

                total_audits = len(df_audit)
                diff_count = len(df_audit[df_audit["diff_qty"] != 0])

                m1, m2 = st.columns(2)
                m1.metric("📋 기간 내 총 실사 건수", f"{total_audits:,} 건")
                m2.metric("⚠️ 수량 오차 발생 건수", f"{diff_count:,} 건", delta_color="inverse")

                st.divider()

                disp_audit = df_audit[[
                    "date", "item_name", "system_qty", "actual_qty", "diff_qty", "unit", "checked_by", "memo", "created_at"
                ]].copy()
                disp_audit.columns = [
                    "점검일자", "품목명", "전산재고", "실사수량", "오차수량", "단위", "점검자", "메모/특이사항", "등록일시"
                ]

                st.dataframe(
                    disp_audit,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "오차수량": st.column_config.NumberColumn(
                            "오차수량",
                            help="실사수량 - 전산재고 (음수일 경우 부족)",
                            format="%d"
                        )
                    }
                )
            else:
                st.info(f"ℹ️ {audit_start} ~ {audit_end} 기간 내에 등록된 알바생 실사 이력이 없습니다.")
        
   # 7. [점주] 오픈/마감 체크리스트 관리 (내역 조회 & 항목 관리)
    elif "체크리스트" in admin_menu:
        st.subheader("📋 오픈/마감 체크리스트 관리 (점주 전용)")

        tab_history, tab_setting = st.tabs(["📊 알바생 점검 내역 조회", "⚙️ 오픈/마감 항목 관리"])

        # --------------------------------------------------
        # TAB 1: 알바생 제출 내역 조회 (오픈/마감 분리)
        # --------------------------------------------------
        with tab_history:
            st.write("#### 📅 알바생 점검 완료 내역")

            selected_shift = st.radio("조회할 근무 파트 선택", ["☀️ 오픈", "🌙 마감"], horizontal=True, key="admin_chk_view_shift")

            # 파트별 키 및 기본 항목 설정
            setting_key = "checklist_open_items" if "오픈" in selected_shift else "checklist_close_items"
            default_items = (
                ["오픈 매장 청소", "원두/시럽 재고 점검", "머신 예열 및 세팅"] 
                if "오픈" in selected_shift 
                else ["마감 포스 정산", "머신 마감 세척", "쓰레기 분리수거"]
            )
            checklist_items = get_setting(setting_key, default_items)

            try:
                chk_res = (
                    supabase.table("checklist")
                    .select("*")
                    .order("date", desc=True)
                    .execute()
                )
                chk_list = chk_res.data if chk_res and chk_res.data else []

                # 선택한 근무 파트(☀️ 오픈 / 🌙 마감) 데이터만 필터링
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

                        # 점주가 설정한 항목 기준으로 O/X 표시
                        for item_name in checklist_items:
                            row_dict[item_name] = "✅ 완료" if items_status.get(item_name) else "❌ 미완료"

                        row_dict["비고 / 특이사항"] = r.get("memo", "")
                        processed_rows.append(row_dict)

                    df_chk = pd.DataFrame(processed_rows)

                    # 주말 색상 스타일 적용하여 출력
                    st.dataframe(
                        style_date_dataframe(df_chk, "날짜"),
                        use_container_width=True
                    )
                else:
                    st.info(f"💡 아직 [{selected_shift}] 파트의 제출된 점검 내역이 없습니다.")
            except Exception:
                st.warning("💡 Supabase 'checklist' 테이블 확인이 필요합니다.")

        # --------------------------------------------------
        # TAB 2: 알바생 체크리스트 항목 관리 (오픈/마감 분리)
        # --------------------------------------------------
        with tab_setting:
            st.write("#### 📌 오픈 / 마감 파트별 점검 항목 설정")
            st.caption("💡 이곳에서 설정한 파트별 항목이 알바생 점검 화면에 실시간으로 구분되어 연동됩니다.")

            target_shift = st.radio("설정할 파트 선택", ["☀️ 오픈", "🌙 마감"], horizontal=True, key="admin_chk_setting_shift")

            # 선택 파트에 따른 DB 설정키 매핑
            setting_key = "checklist_open_items" if "오픈" in target_shift else "checklist_close_items"
            default_items = (
                ["오픈 매장 청소", "원두/시럽 재고 점검", "머신 예열 및 세팅"] 
                if "오픈" in target_shift 
                else ["마감 포스 정산", "머신 마감 세척", "쓰레기 분리수거"]
            )
            checklist_items = get_setting(setting_key, default_items)

            # 새 항목 추가
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
                # 항목 삭제
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
            sch_list = sch_res.data if sch_res and sch_res.data else []
        except Exception:
            sch_list = []

        # 날짜별 데이터 딕셔너리 구조화
        schedule_by_date = {}
        for item in sch_list:
            d = item.get("date")
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
                                st.markdown(f"👤 **{s.get('staff_name')}**\n`{s.get('start_time')}~{s.get('end_time')}`")
                        else:
                            st.caption("근무 없음")

        # 4. 스케줄 등록 / 수정 / 삭제 폼
        st.write("---")
        tab_sch_add, tab_sch_edit = st.tabs(["➕ 스케줄 등록", "✏️ 스케줄 수정 / 삭제"])

        staff_info = get_staff_info()
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
                    if is_recurring:
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
                df_sch = pd.DataFrame(sch_list)
                del_target_id = st.selectbox(
                    "삭제할 스케줄 선택",
                    df_sch["id"].tolist(),
                    format_func=lambda x: f"[{df_sch[df_sch['id']==x]['date'].values[0]}] {df_sch[df_sch['id']==x]['staff_name'].values[0]} ({df_sch[df_sch['id']==x]['start_time'].values[0]}~{df_sch[df_sch['id']==x]['end_time'].values[0]})"
                )
                if st.button("❌ 선택한 스케줄 삭제", type="secondary", use_container_width=True):
                    supabase.table("schedule").eq("id", del_target_id).delete().execute()
                    st.success("지정한 스케줄이 성공적으로 삭제되었습니다.")
                    st.rerun()
            else:
                st.info("💡 이번 달 등록된 스케줄이 없습니다.")
    
     # 9. 재고 현황 & 원가 관리
    elif "원자재" in admin_menu or "재고" in admin_menu:
        st.subheader("📦 원자재 재고 현황 & 단가 관리")
        st.caption("💡 원자재 품목, 단가, 기준 재고를 관리하고 알바생이 입력한 실사 수량을 실시간 확인합니다.")

        tab_inv1, tab_inv2, tab_inv3 = st.tabs(["📊 재고 및 단가 현황", "➕ 품목 등록 및 수정", "📜 알바생 실사 이력"])

        with tab_inv1:
            try:
                inv_res = supabase.table("inventory").select("*").order("item_name").execute()
                inv_data = inv_res.data if inv_res and inv_res.data else []
                df_inv = pd.DataFrame(inv_data) if inv_data else pd.DataFrame()

                if not df_inv.empty:
                    df_inv["cost_price"] = df_inv["cost_price"].fillna(0).astype(int)
                    df_inv["current_qty"] = df_inv["current_qty"].fillna(0).astype(int)
                    df_inv["total_asset"] = df_inv["current_qty"] * df_inv["cost_price"]

                    total_inv_value = safe_int(df_inv["total_asset"].sum()) if "safe_int" in globals() else int(df_inv["total_asset"].sum())

                    col_m1, col_m2 = st.columns(2)
                    col_m1.metric("📦 총 원자재 품목 수", f"{len(df_inv)} 개")
                    col_m2.metric("💵 총 재고 자산 추정액", f"{total_inv_value:,} 원")

                    st.write("---")

                    column_mapping = {
                        "item_name": "품목명",
                        "current_qty": "현재 재고",
                        "unit": "단위",
                        "cost_price": "단가(원)",
                        "total_asset": "재고 금액(원)"
                    }
                    df_display = df_inv.rename(columns={k: v for k, v in column_mapping.items() if k in df_inv.columns})
                    display_cols = [c for c in ["품목명", "현재 재고", "단위", "단가(원)", "재고 금액(원)"] if c in df_display.columns]

                    st.dataframe(
                        df_display[display_cols],
                        column_config={
                            "현재 재고": st.column_config.NumberColumn(format="%,d"),
                            "단가(원)": st.column_config.NumberColumn(format="%,d 원"),
                            "재고 금액(원)": st.column_config.NumberColumn(format="%,d 원"),
                        },
                        use_container_width=True
                    )
                else:
                    st.info("💡 등록된 원자재 품목이 없습니다. [➕ 품목 등록 및 수정] 탭에서 품목을 추가해 주세요.")
            except Exception as e:
                st.error(f"❌ 데이터베이스 오류: Supabase 'inventory' 테이블을 확인해 주세요. ({e})")

        with tab_inv2:
            st.write("#### ➕ 신규 원자재 품목 등록")
            col_add1, col_add2, col_add3, col_add4 = st.columns([2, 1, 1, 1])
            new_item_name = col_add1.text_input("품목명", placeholder="예: 원두(1kg)", key="admin_inv_name")
            new_unit = col_add2.text_input("단위", value="개", key="admin_inv_unit")
            new_cost = col_add3.number_input("단가(원)", min_value=0, step=100, key="admin_inv_cost")
            new_qty = col_add4.number_input("초기 수량", min_value=0, step=1, key="admin_inv_qty")

            if st.button("💾 품목 등록", type="primary", use_container_width=True):
                if not new_item_name.strip():
                    st.warning("⚠️ 품목명을 입력해 주세요.")
                else:
                    try:
                        supabase.table("inventory").upsert({
                            "item_name": new_item_name.strip(),
                            "unit": new_unit.strip(),
                            "cost_price": new_cost,
                            "current_qty": new_qty
                        }, on_conflict="item_name").execute()
                        st.success(f"✅ '{new_item_name}' 품목이 등록/수정 되었습니다.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ 저장 중 오류 발생: {e}")

            st.write("---")
            st.write("#### 🗑️ 기존 품목 삭제")
            try:
                inv_res_del = supabase.table("inventory").select("item_name").execute()
                del_items = [r["item_name"] for r in inv_res_del.data] if inv_res_del.data else []

                if del_items:
                    target_del = st.selectbox("삭제할 품목 선택", del_items, key="admin_del_inv_select")
                    if st.button("❌ 품목 삭제", type="secondary"):
                        supabase.table("inventory").delete().eq("item_name", target_del).execute()
                        st.success(f"🗑️ '{target_del}' 품목이 삭제되었습니다.")
                        st.rerun()
            except Exception:
                pass

        with tab_inv3:
            st.write("#### 📜 실시간 재고 실사 변경 로그")
            try:
                log_res = supabase.table("inventory_log").select("*").order("timestamp", desc=True).limit(50).execute()
                log_data = log_res.data if log_res and log_res.data else []
                df_log = pd.DataFrame(log_data) if log_data else pd.DataFrame()

                if not df_log.empty:
                    log_mapping = {
                        "timestamp": "점검 일시",
                        "item_name": "품목명",
                        "old_qty": "기존 수량",
                        "new_qty": "변경 수량",
                        "checked_by": "점검자(알바생)"
                    }
                    df_log_display = df_log.rename(columns={k: v for k, v in log_mapping.items() if k in df_log.columns})
                    log_cols = [c for c in ["점검 일시", "품목명", "기존 수량", "변경 수량", "점검자(알바생)"] if c in df_log_display.columns]

                    st.dataframe(df_log_display[log_cols], use_container_width=True)
                else:
                    st.info("💡 아직 기록된 재고 실사 이력이 없습니다.")
            except Exception:
                st.info("💡 'inventory_log' 테이블이 비어있거나 생성이 필요합니다.")

    # 10. 전체 인건비 정산
    elif admin_menu == "💰 전체 인건비 정산":
      st.subheader("💰 당월 직원별 전체 인건비 정산")

      staff_dict = get_staff_info()
      settlement_data = []

      for name in staff_dict.keys():
        summary = calculate_person_summary(name)
        settlement_data.append({
            "직원명": name,
            "기본 시급": f"{summary.get('hourly_rate', 0):,} 원",
            "총 근무시간": f"{summary.get('total_hours', 0):.1f} 시간",
            "세전 급여": summary.get("gross_pay", 0),
            "공제 세금(3.3%)": summary.get("tax_3_3", 0),
            "실수령액": summary.get("total_pay", 0),
        })

      if settlement_data:
        df_settle = pd.DataFrame(settlement_data)
        tot_gross = sum([x["세전 급여"] for x in settlement_data])
        tot_net = sum([x["실수령액"] for x in settlement_data])

        c1, c2 = st.columns(2)
        c1.metric("총 세전 인건비", f"{tot_gross:,} 원")
        c2.metric("총 실수령액 합계", f"{tot_net:,} 원")

        st.dataframe(
            df_settle,
            column_config={
                "세전 급여": st.column_config.NumberColumn(format="%,d 원"),
                "공제 세금(3.3%)": st.column_config.NumberColumn(
                    format="%,d 원"
                ),
                "실수령액": st.column_config.NumberColumn(format="%,d 원"),
            },
            use_container_width=True,
        )

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

    # 14. 점주 메뉴: 전체 데이터 엑셀/CSV 다운로드
    # --------------------------------------------------
    elif "다운로드" in admin_menu or "엑셀" in admin_menu or "CSV" in admin_menu:
        st.subheader("💾 데이터 백업 및 항목별 다운로드")

        tab_full_backup, tab_single_download = st.tabs(["📦 전체 데이터 백업", "📊 항목별 선택 다운로드"])

        # --------------------------------------------------
        # TAB 1: 전체 데이터 백업 (통합 엑셀 - 여러 시트)
        # --------------------------------------------------
        with tab_full_backup:
            st.write("#### 📦 전체 DB 데이터 통합 백업")
            st.caption("💡 매장의 모든 데이터(지출, 체크리스트, 근무스케줄, 재고 등)를 하나의 엑셀 파일 안의 여러 시트로 통합 다운로드합니다.")

            if st.button("📥 전체 데이터 통합 엑셀 추출", type="primary", use_container_width=True, key="btn_full_backup"):
                try:
                    # 주요 테이블 전체 불러오기
                    backup_dict = {
                        "지출내역": pd.DataFrame(supabase.table("expenses").select("*").execute().data or []),
                        "근무스케줄": pd.DataFrame(supabase.table("schedule").select("*").execute().data or []),
                        "체크리스트기록": pd.DataFrame(supabase.table("checklist_log").select("*").execute().data or []),
                        "재고현황": pd.DataFrame(supabase.table("inventory").select("*").execute().data or []),
                        "인수인계노트": pd.DataFrame(supabase.table("handover").select("*").execute().data or [])
                    }

                    file_bytes, mime_type, ext = create_excel_download(backup_dict)
                    now_str = datetime.date.today().strftime("%Y%m%d")

                    st.download_button(
                        label="💾 전체 백업 파일 PC 저장하기",
                        data=file_bytes,
                        file_name=f"컴포즈커피_전체데이터백업_{now_str}.{ext}",
                        mime=mime_type,
                        use_container_width=True,
                        key="dl_btn_full"
                    )
                    st.success("✅ 전체 백업 파일이 생성되었습니다. 위 버튼을 눌러 다운로드하세요.")
                except Exception as e:
                    st.error(f"❌ 전체 백업 추출 중 오류 발생: {e}")

        # --------------------------------------------------
        # TAB 2: 돈(재무/비용) 관련 항목별 개별 선택 다운로드 (단일 엑셀)
        # --------------------------------------------------
        with tab_single_download:
            st.write("#### 💸 재무 및 비용 항목별 개별 다운로드")
            st.caption("💡 지출, 매출, 인건비 등 돈과 관련된 항목을 선택하여 깔끔하게 엑셀 파일로 추출합니다.")

            # 돈 관련 항목 선택 매핑 (화면 표시 이름: DB 테이블명, 엑셀 시트명)
            table_options = {
                "💸 지출 및 비용 상세 내역": ("expenses", "지출내역"),
                "📈 매출 내역 (일별/월별)": ("sales", "매출내역"),
                "💵 알바생 근무시간 및 인건비 산출 내역": ("schedule", "인건비_근무기록")
            }

            selected_label = st.selectbox("다운로드할 금융 항목 선택", list(table_options.keys()))
            target_table, sheet_title = table_options[selected_label]

            if st.button(f"📥 [{selected_label}] 데이터 추출", type="primary", use_container_width=True, key="btn_single_extract"):
                try:
                    res_data = supabase.table(target_table).select("*").execute().data or []
                    
                    if not res_data:
                        st.warning("⚠️ 선택하신 항목에 등록된 데이터가 없습니다.")
                    else:
                        df_target = pd.DataFrame(res_data)

                        # 개별 엑셀 파일 생성
                        file_bytes, mime_type, ext = create_excel_download({sheet_title: df_target})
                        now_str = datetime.date.today().strftime("%Y%m%d")

                        st.download_button(
                            label=f"💾 {selected_label} 엑셀 파일 저장하기",
                            data=file_bytes,
                            file_name=f"컴포즈커피_{sheet_title}_{now_str}.{ext}",
                            mime=mime_type,
                            use_container_width=True,
                            key="dl_btn_single"
                        )
                        st.success(f"✅ {selected_label} 데이터가 준비되었습니다. 다운로드 버튼을 눌러 저장하세요.")
                except Exception as e:
                    st.error(f"❌ 개별 데이터 추출 중 오류 발생: {e}")
# 15. 데이터 초기화# 15. 데이터 초기화
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
        # 탭 4: 재고 품목 관리
        # --------------------------------------------------
        with tab4:
            st.write("#### 📦 재고 관리 품목 설정")
            inv_res = supabase.table("app_settings").select("value").eq("key", "inventory_items").execute()
            current_inv = inv_res.data[0]["value"] if inv_res.data else ["원두 (kg)", "우유 (팩)", "빨대 (박스)", "24oz 컵 (박스)", "바닐라 시럽 (병)"]

            edited_inv_text = st.text_area("재고 점검 품목 목록 (줄바꿈 구분)", value="\n".join(current_inv), height=200, key="inv_tab_area")

            if st.button("💾 재고 품목 저장", type="primary", key="save_inv_btn"):
                new_inv_list = [i.strip() for i in edited_inv_text.split("\n") if i.strip()]
                supabase.table("app_settings").upsert({"key": "inventory_items", "value": new_inv_list}).execute()
                st.success("✅ 재고 품목 목록이 업데이트되었습니다!")
                st.rerun()

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