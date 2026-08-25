import calendar
import datetime
from datetime import timedelta, timezone
import hashlib
import io
import locale

import pandas as pd
import plotly.express as px

from supabase import Client, create_client
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


  # --- 2. 오픈/마감 체크리스트 ---
  with tab_st2:
    st.subheader("📋 업무 체크리스트 수행")
    chk_type = st.radio("체크리스트 구분", ["오픈", "마감"], horizontal=True)
    checker_name = st.selectbox(
        "수행자 이름",
        staff_names if staff_names else ["직원없음"],
        key="chk_staff",
    )

    res_items = (
        supabase.table("checklist_items")
        .select("item_text")
        .eq("type", chk_type)
        .execute()
    )
    items = [r["item_text"] for r in res_items.data] if res_items.data else []

    if items:
      st.write(f"**[{chk_type} 필수점검 항목]**")
      completed_list = []
      for idx, item in enumerate(items):
        chk = st.checkbox(item, key=f"chk_item_{idx}")
        if chk:
          completed_list.append(item)

      if st.button("📋 체크리스트 제출", type="primary"):
        now_str = datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        logs = []
        for item in items:
          status = "완료" if item in completed_list else "미완료"
          logs.append({
              "type": chk_type,
              "item_text": item,
              "checked_by": checker_name,
              "timestamp": now_str,
              "status": status,
          })
        supabase.table("checklist_log").insert(logs).execute()
        st.success("✅ 체크리스트가 성공적으로 제출되었습니다!")
    else:
      st.info("등록된 체크리스트 항목이 없습니다.")

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
        .select(
            "id, sender_name, receiver_name, shift_type, content, created_at,"
            " is_read"
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
                f"[{matched_staff}] 님이 인수인계 (#{target_ho_id}) 항목을 확인"
                " 완료 처리했습니다."
            )
            st.rerun()
          else:
            st.error("❌ 올바른 PIN 번호를 입력해 주세요.")
    else:
      st.info("등록된 인수인계 내역이 없습니다.")

  # --- 4. 재고 실사 ---
  with tab_st4:
    st.subheader("📦 실시간 재고 실사 및 입력")
    st.caption(
        "매장에 남아있는 실제 재고 수량을 확인 후 수정해 주세요. (자동 기록 저장)"
    )

    inv_checker = st.selectbox("점검자 이름", staff_names, key="inv_checker")

    inv_res = (
        supabase.table("inventory")
        .select("item_name, current_qty, unit, cost_price")
        .execute()
    )
    df_inv = pd.DataFrame(inv_res.data) if inv_res.data else pd.DataFrame()

    if not df_inv.empty:
      df_inv = df_inv.rename(
          columns={
              "item_name": "품목명",
              "current_qty": "현재재고",
              "unit": "단위",
              "cost_price": "단가",
          }
      )
      selected_item = st.selectbox("점검 품목", df_inv["품목명"].tolist())
      current_val = safe_int(
          df_inv[df_inv["품목명"] == selected_item]["현재재고"].values[0]
      )
      unit_val = str(df_inv[df_inv["품목명"] == selected_item]["단위"].values[0])

      real_qty = st.number_input(
          f"실사 수량 ({unit_val})", min_value=0, value=current_val
      )

      if st.button("💾 재고 실사 반영", type="primary"):
        now_str = datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")

        supabase.table("inventory").update({"current_qty": real_qty}).eq(
            "item_name", selected_item
        ).execute()
        supabase.table("inventory_log").insert({
            "item_name": selected_item,
            "old_qty": current_val,
            "new_qty": real_qty,
            "checked_by": inv_checker,
            "timestamp": now_str,
        }).execute()

        st.success(
            f"✅ [{selected_item}] 재고가 {current_val:,} → {real_qty:,}로"
            " 업데이트되었습니다."
        )
        st.rerun()

  # --- 5. 유통기한/폐기 보고 ---
  with tab_st5:
    st.subheader("🗑️ 유통기한 경과 / 파손 원자재 폐기 보고")
    st.caption(
        "버리게 된 원자재를 등록하면 재고 차감 및 폐기 손실 금액이 자동"
        " 계산됩니다."
    )

    w_reporter = st.selectbox("보고자", staff_names, key="w_reporter")
    w_pin = st.text_input("PIN 번호", type="password", max_chars=4, key="w_pin")

    inv_list_res = (
        supabase.table("inventory")
        .select("item_name, unit, cost_price, current_qty")
        .execute()
    )
    inv_list = inv_list_res.data

    if inv_list:
      inv_dict = {
          i["item_name"]: {
              "unit": i.get("unit", "개"),
              "cost": safe_int(i.get("cost_price")),
              "current_qty": safe_int(i.get("current_qty")),
          }
          for i in inv_list
      }

      w_item = st.selectbox("폐기 품목", list(inv_dict.keys()))
      w_qty = st.number_input("폐기 수량", min_value=1, value=1)

      item_cost = inv_dict[w_item]["cost"]
      calc_loss = item_cost * w_qty
      st.warning(
          f"💰 **예상 손실 금액: {calc_loss:,} 원** (단가: {item_cost:,}원 /"
          f" {inv_dict[w_item]['unit']})"
      )

      w_reason = st.selectbox(
          "폐기 사유",
          ["유통기한 경과", "제품 파손/변질", "제조 실수", "기타"],
      )

      if st.button("🗑️ 폐기 등록 제출", type="primary"):
        reporter_pin = staff_dict.get(w_reporter, {}).get("pin", "")
        if verify_hash(w_pin, reporter_pin):
          now_str = datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
          today_date_str = datetime.datetime.now(KST).date().strftime("%Y-%m-%d")
          new_qty = inv_dict[w_item]["current_qty"] - w_qty

          supabase.table("inventory").update({"current_qty": new_qty}).eq(
              "item_name", w_item
          ).execute()
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
              f"✅ [{w_item}] {w_qty:,}개 폐기 보고 완료! (손실금액: {calc_loss:,}원"
              " 자동 반영됨)"
          )
          st.rerun()
        else:
          st.error("❌ PIN 번호가 틀렸습니다.")

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

    admin_menu = st.sidebar.selectbox(
        "점주 관리 메뉴",
        [
            "📝 매출 분석 & 손익계산서(P&L)",
            "🚚 엠즈푸드 발주등록",
            "📈 종합 매출/비용 시각화 분석",
            shift_menu_label,
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
        ],
    )

    # 1. 매출 분석 & 손익계산서 (P&L)
    if admin_menu == "📝 매출 분석 & 손익계산서(P&L)":
      st.subheader("📝 일별 매출 등록 & 손익계산서 (P&L)")

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
          init_platform = (
              existing_sales.get("delivery_platform") or "배달의민족"
          )
          init_delivery_gross = safe_int(
              existing_sales.get("delivery_gross")
          )
          init_fee_rate = safe_float(
              existing_sales.get("delivery_fee_rate"), 9.8
          )
          init_delivery_count = safe_int(
              existing_sales.get("delivery_count")
          )
          init_rider_fee = safe_int(existing_sales.get("rider_fee"))
          init_memo = existing_sales.get("memo") or ""
        else:
          init_cash = init_card = init_other = init_reward = 0
          init_platform = "배달의민족"
          init_delivery_gross, init_fee_rate = 0, 9.8
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
        platform_list = [
            "배달의민족",
            "쿠팡이츠",
            "요기요",
            "땡겨요",
            "네이버주문",
            "기타",
        ]
        DEFAULT_FEE_RATES = {
            "배달의민족": 9.8,
            "쿠팡이츠": 9.8,
            "요기요": 12.5,
            "땡겨요": 2.0,
            "네이버주문": 1.65,
            "기타": 0.0,
        }

        p_key = f"platform_{sales_date}"
        f_key = f"fee_rate_{sales_date}"

        if (
            "current_sales_date_ref" not in st.session_state
            or st.session_state["current_sales_date_ref"] != str(sales_date)
        ):
          st.session_state["current_sales_date_ref"] = str(sales_date)
          st.session_state[p_key] = init_platform
          st.session_state[f_key] = init_fee_rate

        def on_platform_change():
          selected_p = st.session_state[p_key]
          st.session_state[f_key] = DEFAULT_FEE_RATES.get(selected_p, 0.0)

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

    # 2. 엠즈푸드 발주등록
    elif admin_menu == "🚚 엠즈푸드 발주등록":
      st.subheader("🚚 엠즈푸드 월별 발주 내역 등록 (1일~31일 통합 입력)")
      st.caption(
          "한 화면에서 월별 1일부터 31일까지의 발주 항목과 지출 금액을 자유롭게 바로"
          " 입력할 수 있습니다."
      )

      now = datetime.datetime.now(KST)
      c_y, c_m = st.columns(2)
      sel_year = c_y.selectbox(
          "조회/입력 연도",
          range(now.year - 2, now.year + 3),
          index=2,
          key="mf_year",
      )
      sel_month = c_m.selectbox(
          "조회/입력 월", range(1, 13), index=now.month - 1, key="mf_month"
      )

      ym_str = f"{sel_year:04d}-{sel_month:02d}"

      existing_orders_res = (
          supabase.table("mfood_orders")
          .select("day, item_details, amount, memo")
          .eq("year_month", ym_str)
          .order("day", desc=False)
          .execute()
      )
      existing_orders = existing_orders_res.data or []

      existing_map = {
          r["day"]: (r["item_details"], safe_int(r["amount"]), r["memo"])
          for r in existing_orders
      }
      num_days = calendar.monthrange(sel_year, sel_month)[1]

      mfood_data = []
      days_kr = ["월", "화", "수", "목", "금", "토", "일"]

      for d in range(1, 32):
        if d <= num_days:
          dt_temp = datetime.date(sel_year, sel_month, d)
          w_str = days_kr[dt_temp.weekday()]
          day_disp = f"{d}일 ({w_str})"
        else:
          day_disp = f"{d}일 (-)"

        item, amt, memo = existing_map.get(d, ("", 0, ""))
        mfood_data.append({
            "일자": day_disp,
            "day_num": d,
            "발주내용 / 품목": item,
            "지출금액 (원)": amt,
            "비고 / 메모": memo,
        })

      df_mf_input = pd.DataFrame(mfood_data)

      edited_mf_df = st.data_editor(
          df_mf_input,
          use_container_width=True,
          column_config={
              "일자": st.column_config.TextColumn(
                  "일자 (1일~31일)", disabled=True
              ),
              "day_num": None,
              "발주내용 / 품목": st.column_config.TextColumn(
                  "발주내용 / 품목", width="medium"
              ),
              "지출금액 (원)": st.column_config.NumberColumn(
                  "지출금액 (원)", min_value=0, step=1000, format="%,d 원"
              ),
              "비고 / 메모": st.column_config.TextColumn(
                  "비고 / 메모", width="large"
              ),
          },
          key=f"mfood_editor_{ym_str}",
      )

      total_mfood_month = sum(
          [safe_int(x) for x in edited_mf_df["지출금액 (원)"]]
      )
      st.info(
          f"💰 **[{sel_year}년 {sel_month}월] 엠즈푸드 총 발주 지출금액:**"
          f" `{total_mfood_month:,}` 원"
      )

      if st.button(
          f"💾 {sel_year}년 {sel_month}월 엠즈푸드 발주 내역 일괄 저장",
          type="primary",
          use_container_width=True,
      ):
        records_to_upsert = []
        for _, row in edited_mf_df.iterrows():
          d_num = safe_int(row["day_num"])
          item_text = (
              str(row["발주내용 / 품목"])
              if pd.notnull(row["발주내용 / 품목"])
              else ""
          )
          amt_val = safe_int(row["지출금액 (원)"])
          memo_text = (
              str(row["비고 / 메모"]) if pd.notnull(row["비고 / 메모"]) else ""
          )

          records_to_upsert.append({
              "year_month": ym_str,
              "day": d_num,
              "item_details": item_text,
              "amount": amt_val,
              "memo": memo_text,
          })

        supabase.table("mfood_orders").upsert(
            records_to_upsert, on_conflict="year_month, day"
        ).execute()

        st.success(
            f"✅ {sel_year}년 {sel_month}월 엠즈푸드 발주 내역이 성공적으로"
            f" 저장되었습니다! (총 지출: {total_mfood_month:,}원)"
        )
        st.rerun()

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

    # 6. 원자재 폐기 이력 & 손실 점검
    elif admin_menu == "🗑️ 원자재 폐기 이력 & 손실 점검":
      st.subheader("🗑️ 원자재 폐기 등록 이력 & 손실금액 점검")

      res_w = (
          supabase.table("waste")
          .select("*")
          .order("date", desc=True)
          .execute()
      )
      df_waste = pd.DataFrame(res_w.data) if res_w.data else pd.DataFrame()

      if not df_waste.empty:
        total_waste_loss = sum(
            [safe_int(x) for x in df_waste.get("loss_amount", [])]
        )
        st.metric("🗑️ 누적 폐기 손실 총액", f"{total_waste_loss:,} 원")

        df_waste = df_waste.rename(
            columns={
                "id": "번호",
                "date": "폐기일자",
                "item_name": "품목명",
                "qty": "수량",
                "unit": "단위",
                "loss_amount": "손실금액(원)",
                "reason": "폐고사유",
                "reported_by": "등록자",
            }
        )
        st.dataframe(
            style_date_dataframe(df_waste, "폐기일자"),
            use_container_width=True,
        )
      else:
        st.info("등록된 원자재 폐기 이력이 없습니다.")

    # 7. 오픈/마감 체크리스트 점검
    elif admin_menu == "📋 오픈/마감 체크리스트 점검":
      st.subheader("📋 오픈/마감 체크리스트 작성 점검")

      chk_date = st.date_input(
          "📅 점검 날짜 선택", value=datetime.datetime.now(KST).date()
      )
      res_chk = (
          supabase.table("checklist_log")
          .select("*")
          .order("timestamp", desc=True)
          .execute()
      )
      df_chk = pd.DataFrame(res_chk.data) if res_chk.data else pd.DataFrame()

      if not df_chk.empty:
        df_chk = df_chk.rename(
            columns={
                "id": "번호",
                "type": "구분",
                "item_text": "점검항목",
                "checked_by": "수행자",
                "timestamp": "일시",
                "status": "상태",
            }
        )
        st.dataframe(df_chk, use_container_width=True)
      else:
        st.info(f"[{chk_date}] 제출된 체크리스트가 없습니다.")

    # 8. 알바생 캘린더 스케줄 관리
    elif admin_menu == "⏰ 알바생 캘린더 스케줄 관리":
      st.subheader("⏰ 알바생 근무 스케줄 설정 및 관리")

      staff_info = get_staff_info()
      staff_list = list(staff_info.keys())

      with st.form("schedule_form"):
        col_s1, col_s2, col_s3 = st.columns(3)
        sch_date = col_s1.date_input("근무 날짜")
        sch_staff = (
            col_s2.selectbox("직원 선택", staff_list)
            if staff_list
            else col_s2.text_input("직원명")
        )
        sch_shift = col_s3.selectbox(
            "근무 파트", ["오픈", "미들", "마감", "직접입력"]
        )

        col_t1, col_t2 = st.columns(2)
        start_t = col_t1.time_input("시작 시간", datetime.time(9, 0))
        end_t = col_t2.time_input("종료 시간", datetime.time(15, 0))

        submit_sch = st.form_submit_button(
            "➕ 스케줄 저장", type="primary", use_container_width=True
        )
        if submit_sch:
          supabase.table("schedule").upsert(
              {
                  "date": str(sch_date),
                  "staff_name": sch_staff,
                  "start_time": start_t.strftime("%H:%M"),
                  "end_time": end_t.strftime("%H:%M"),
              },
              on_conflict="date, staff_name",
          ).execute()
          st.success(f"✅ {sch_staff} 님의 {sch_date} 스케줄이 저장되었습니다.")
          st.rerun()

      st.write("---")
      res_sch = (
          supabase.table("schedule")
          .select("*")
          .order("date", desc=True)
          .execute()
      )
      df_sch = pd.DataFrame(res_sch.data) if res_sch.data else pd.DataFrame()
      if not df_sch.empty:
        df_sch = df_sch.rename(
            columns={
                "date": "날짜",
                "staff_name": "직원명",
                "start_time": "시작시간",
                "end_time": "종료시간",
            }
        )
        st.dataframe(
            style_date_dataframe(df_sch, "날짜"), use_container_width=True
        )

    # 9. 재고 현황 & 원가 관리
    elif admin_menu == "📦 재고 현황 & 원가 관리":
      st.subheader("📦 원자재 재고 현황 & 단가 관리")

      res_inv = (
          supabase.table("inventory")
          .select("*")
          .order("item_name")
          .execute()
      )
      df_inv = pd.DataFrame(res_inv.data) if res_inv.data else pd.DataFrame()

      if not df_inv.empty:
        edited_inv = st.data_editor(
            df_inv,
            use_container_width=True,
            column_config={
                "item_name": "품목명",
                "category": "분류",
                "current_qty": st.column_config.NumberColumn(
                    "현재 재고", min_value=0
                ),
                "unit": "단위",
                "cost_price": st.column_config.NumberColumn(
                    "단가(원)", format="%,d 원"
                ),
            },
            key="inv_editor",
        )
        if st.button("💾 재고/단가 수정사항 저장", type="primary"):
          records = edited_inv.to_dict(orient="records")
          supabase.table("inventory").upsert(records).execute()
          st.success("재고 정보가 성공적으로 업데이트되었습니다.")
          st.rerun()
      else:
        st.info("등록된 재고 품목이 없습니다.")

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

    # 14. 전체 데이터 엑셀/CSV 다운로드
    elif admin_menu == "📥 전체 데이터 엑셀/CSV 다운로드":
      st.subheader("📥 전체 매장 운영 데이터 백업 & CSV 다운로드")

      tables = [
          "daily_sales",
          "mfood_orders",
          "waste",
          "handover",
          "shift_requests",
          "checklist_log",
          "attendance",
          "schedule",
          "inventory",
      ]
      for tbl in tables:
        res_tbl = supabase.table(tbl).select("*").execute()
        if res_tbl.data:
          df_tmp = pd.DataFrame(res_tbl.data)
          st.download_button(
              label=f"📥 [{tbl}] 테이블 CSV 다운로드",
              data=convert_df_to_csv(df_tmp),
              file_name=f"{tbl}_export.csv",
              mime="text/csv",
          )

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
              "📦 재고 및 폐기 내역만 초기화 (inventory, waste)",
              "📋 체크리스트 수행 기록만 초기화 (checklist_log)",
              (
                  "🚨 전체 시스템 초기화 (모든 데이터 삭제 후 기본 세팅 상태로"
                  " 리셋)"
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
            if reset_type.startswith("📊"):
              supabase.table("daily_sales").delete().not_.is_(
                  "date", "null"
              ).execute()
              supabase.table("mfood_orders").delete().not_.is_(
                  "year_month", "null"
              ).execute()
            elif reset_type.startswith("⏰"):
              supabase.table("attendance").delete().not_.is_(
                  "id", "null"
              ).execute()
              supabase.table("schedule").delete().not_.is_(
                  "date", "null"
              ).execute()
              supabase.table("shift_requests").delete().not_.is_(
                  "id", "null"
              ).execute()
            elif reset_type.startswith("🤝"):
              supabase.table("handover").delete().not_.is_(
                  "id", "null"
              ).execute()
            elif reset_type.startswith("📦"):
              supabase.table("inventory").delete().not_.is_(
                  "item_name", "null"
              ).execute()
              supabase.table("waste").delete().not_.is_("id", "null").execute()
            elif reset_type.startswith("📋"):
              supabase.table("checklist_log").delete().not_.is_(
                  "id", "null"
              ).execute()
            elif reset_type.startswith("🚨"):
              tables = [
                  "daily_sales",
                  "mfood_orders",
                  "attendance",
                  "schedule",
                  "inventory",
                  "waste",
                  "shift_requests",
                  "checklist_log",
                  "handover",
              ]
              for t in tables:
                if t in ["daily_sales", "schedule"]:
                  supabase.table(t).delete().not_.is_("date", "null").execute()
                elif t == "mfood_orders":
                  supabase.table(t).delete().not_.is_(
                      "year_month", "null"
                  ).execute()
                elif t == "inventory":
                  supabase.table(t).delete().not_.is_(
                      "item_name", "null"
                  ).execute()
                else:
                  supabase.table(t).delete().not_.is_("id", "null").execute()
            st.success(
                "✅ 선택한 대상의 데이터가 성공적으로 초기화되었습니다."
            )
            st.rerun()
          except Exception as e:
            st.error(f"❌ 초기화 실패 (DB 권한 또는 오류 확인): {e}")
        else:
          st.error(
              "❌ '초기화' 문구 입력과 동의 체크박스를 모두 확인해 주세요."
          )