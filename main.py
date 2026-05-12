import os
from datetime import date, datetime, timedelta, timezone
from fastapi import FastAPI, HTTPException, Query, File, UploadFile
from fastapi.responses import HTMLResponse, FileResponse

from config import PERIODS, WEEKDAYS, COURSE_COLORS
from database import (
    init_db, create_semester, get_semesters, get_semester,
    get_current_semester, update_semester, delete_semester,
    create_course, get_courses, get_course,
    update_course, delete_course, import_courses,
)
from models import (
    SemesterCreate, SemesterUpdate, CourseCreate, CourseUpdate,
    ImportJsonRequest, ImportHtmlPasteRequest,
    LoginRequest, SettingsOut, SettingsUpdate,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="课程表")


# ---- 启动时初始化 ----
@app.on_event("startup")
def startup():
    init_db()
    _seed_mock_data()


def _seed_mock_data():
    """如果没有学期数据，从保存的课表 HTML 导入，或创建示例学期"""
    if get_semesters():
        return
    sid = create_semester(
        name="2025-2026学年第二学期（2026春）",
        start_date="2026-03-09",
        end_date="2026-07-05",
        weeks=17,
        is_current=True,
    )
    # 尝试从保存的课表 HTML 导入真实数据
    saved_html = os.path.join(BASE_DIR, "学生课表.html")
    if os.path.exists(saved_html):
        try:
            from scraper import parse_schedule_from_html
            with open(saved_html, "rb") as f:
                html = f.read().decode("gbk")
            courses = parse_schedule_from_html(html)
            for c in courses:
                color = COURSE_COLORS[hash(c["name"]) % len(COURSE_COLORS)]
                create_course(
                    semester_id=sid, name=c["name"],
                    teacher=c["teacher"], location=c["location"],
                    day_of_week=c["day_of_week"],
                    start_period=c["start_period"], end_period=c["end_period"],
                    start_week=c["start_week"], end_week=c["end_week"],
                    week_type=c["week_type"], color=color, source="scraper",
                )
            return
        except Exception:
            pass

    # 回退：空学期，用户可通过导入功能添加课程
    pass


# ---- 工具函数 ----

def calc_current_week(start_date_str: str) -> int:
    """根据学期开始日期计算当前是第几周"""
    try:
        start = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    except ValueError:
        return 1
    start_monday = start - timedelta(days=start.weekday())
    today = (datetime.now(timezone.utc) + timedelta(hours=8)).date()
    diff = today - start_monday
    return max(1, diff.days // 7 + 1)


def get_week_range(start_date_str: str, week: int) -> tuple[str, str]:
    """计算某周周一和周日"""
    start = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    start_monday = start - timedelta(days=start.weekday())
    monday = start_monday + timedelta(weeks=week - 1)
    sunday = monday + timedelta(days=6)
    return monday.isoformat(), sunday.isoformat()


def is_course_in_week(course: dict, week: int) -> bool:
    """判断课程在指定周是否有课"""
    if week < course["start_week"] or week > course["end_week"]:
        return False
    if course["week_type"] == "odd" and week % 2 == 0:
        return False
    if course["week_type"] == "even" and week % 2 == 1:
        return False
    return True


def week_type_label(course: dict) -> str:
    if course["week_type"] == "odd":
        return f'{course["start_week"]}-{course["end_week"]}周(单)'
    if course["week_type"] == "even":
        return f'{course["start_week"]}-{course["end_week"]}周(双)'
    if course["start_week"] == course["end_week"]:
        return f'第{course["start_week"]}周'
    return f'{course["start_week"]}-{course["end_week"]}周'


# ---- 前端页面 ----

@app.get("/", response_class=HTMLResponse)
def index():
    path = os.path.join(BASE_DIR, "templates", "index.html")
    if not os.path.exists(path):
        return HTMLResponse("<h1>index.html not found</h1>", status_code=404)
    with open(path, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())


# ---- 学期 API ----

@app.get("/api/semesters")
def api_get_semesters():
    return get_semesters()


@app.get("/api/current-semester")
def api_get_current_semester():
    sem = get_current_semester()
    if not sem:
        raise HTTPException(404, "没有学期数据，请先创建学期")
    return sem


@app.post("/api/semesters")
def api_create_semester(data: SemesterCreate):
    try:
        sid = create_semester(
            name=data.name, start_date=data.start_date,
            end_date=data.end_date, weeks=data.weeks,
            is_current=data.is_current,
        )
        return {"id": sid}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.put("/api/semesters/{sid}")
def api_update_semester(sid: int, data: SemesterUpdate):
    updated = update_semester(sid, **data.model_dump(exclude_none=True))
    if not updated:
        raise HTTPException(404, "学期不存在")
    return {"ok": True}


@app.delete("/api/semesters/{sid}")
def api_delete_semester(sid: int):
    delete_semester(sid)
    return {"ok": True}


# ---- 课程 API ----

@app.get("/api/courses")
def api_get_courses(semester_id: int = Query(...)):
    return get_courses(semester_id)


@app.post("/api/courses")
def api_create_course(data: CourseCreate):
    color_idx = (data.day_of_week * 10 + data.start_period) % len(COURSE_COLORS)
    cid = create_course(
        semester_id=data.semester_id, name=data.name,
        teacher=data.teacher, location=data.location,
        day_of_week=data.day_of_week,
        start_period=data.start_period, end_period=data.end_period,
        start_week=data.start_week, end_week=data.end_week,
        week_type=data.week_type, color=COURSE_COLORS[color_idx],
    )
    return {"id": cid}


@app.put("/api/courses/{cid}")
def api_update_course(cid: int, data: CourseUpdate):
    updated = update_course(cid, **data.model_dump(exclude_none=True))
    if not updated:
        raise HTTPException(404, "课程不存在")
    return {"ok": True}


@app.delete("/api/courses/{cid}")
def api_delete_course(cid: int):
    delete_course(cid)
    return {"ok": True}


# ---- 课表查询 ----

@app.get("/api/schedule")
def api_get_schedule(week: int | None = None, semester_id: int | None = None):
    """获取指定周课表"""
    # 确定学期
    sem = get_semester(semester_id) if semester_id else get_current_semester()
    if not sem:
        raise HTTPException(404, "没有学期数据")

    if week:
        current_week = max(1, min(week, sem["weeks"]))
    else:
        current_week = calc_current_week(sem["start_date"])
        if current_week > sem["weeks"]:
            current_week = 1  # 学期已结束或未开始，默认显示第1周
    week_start, week_end = get_week_range(sem["start_date"], current_week)

    # 查询该学期所有课程
    courses = get_courses(sem["id"])

    # 按时段分组：(day_of_week, start_period, end_period)
    slot_map: dict[tuple[int, int, int], list[dict]] = {}
    for c in courses:
        key = (c["day_of_week"], c["start_period"], c["end_period"])
        if key not in slot_map:
            slot_map[key] = []
        slot_map[key].append(c)

    days = []
    for d in range(1, 8):
        day_slots = []
        for (day, sp, ep), slot_courses in slot_map.items():
            if day != d:
                continue
            # 跳过该时段没有本周课程的情况（纯空时段不显示）
            has_active = any(is_course_in_week(c, current_week) for c in slot_courses)
            if not has_active:
                continue

            slot_courses_out = []
            for c in slot_courses:
                color = c["color"] or COURSE_COLORS[hash(c["name"]) % len(COURSE_COLORS)]
                slot_courses_out.append({
                    "id": c["id"],
                    "name": c["name"],
                    "teacher": c["teacher"],
                    "location": c["location"],
                    "week_type": c["week_type"],
                    "week_info": week_type_label(c),
                    "color": color,
                    "active": is_course_in_week(c, current_week),
                })

            day_slots.append({
                "start_period": sp,
                "end_period": ep,
                "courses": slot_courses_out,
                "total": len(slot_courses_out),
            })

        # 按开始节次排序
        day_slots.sort(key=lambda s: s["start_period"])
        days.append({"day": d, "slots": day_slots})

    return {
        "semester_name": sem["name"],
        "current_week": current_week,
        "total_weeks": sem["weeks"],
        "week_start": week_start,
        "week_end": week_end,
        "periods": PERIODS,
        "weekdays": WEEKDAYS,
        "days": days,
    }


# ---- 登录与导入（Selenium 浏览器自动化）----

@app.post("/api/login")
def api_login(data: LoginRequest):
    """登录第一步：提交账号密码到 CAS"""
    if not data.username or not data.password:
        raise HTTPException(400, "请输入学号和密码")
    from scraper import login_step1
    result = login_step1(data.username, data.password)
    if result["status"] == "ok":
        return {"ok": True, "message": result["message"]}
    if result["status"] == "mfa":
        return {"ok": True, "mfa_required": True, "session_token": result["session_token"]}
    if result["status"] == "captcha":
        return {"ok": False, "captcha_required": True, "message": result["message"]}
    raise HTTPException(401, result["message"])


@app.post("/api/login/mfa")
def api_login_mfa(data: LoginRequest):
    """登录第二步：提交短信验证码完成 MFA"""
    if not data.session_token:
        raise HTTPException(400, "缺少 session_token")
    if not data.sms_code:
        raise HTTPException(400, "请输入短信验证码")
    from scraper import login_step2
    result = login_step2(data.session_token, data.sms_code)
    if result["status"] == "ok":
        return {"ok": True, "message": result["message"]}
    if result["status"] == "retry":
        return {"ok": True, "mfa_retry": True, "message": result["message"]}
    raise HTTPException(401, result["message"])


@app.post("/api/sync")
def api_sync(semester_id: int | None = None):
    """从教务处同步课表"""
    from scraper import imut_get_schedule
    sem = get_semester(semester_id) if semester_id else get_current_semester()
    if not sem:
        raise HTTPException(404, "没有学期数据")
    courses = imut_get_schedule()
    if not courses:
        raise HTTPException(502, "获取课表失败，请重新登录")
    import_courses(sem["id"], courses)
    return {"ok": True, "count": len(courses)}


@app.post("/api/import-html")
def api_import_html(file: UploadFile = File(...)):
    """上传课表 HTML 文件并解析导入"""
    from scraper import parse_schedule_from_html
    sem = get_current_semester()
    if not sem:
        raise HTTPException(404, "没有学期数据")

    content = file.file.read()
    if len(content) < 100:
        raise HTTPException(400, "文件内容为空")

    html = content.decode("gbk", errors="replace")
    courses = parse_schedule_from_html(html)
    if not courses:
        raise HTTPException(422, "未能从文件中解析出课程，请确认上传的是教务系统课表页面")

    import_courses(sem["id"], courses)
    return {"ok": True, "count": len(courses)}


@app.post("/api/import-json")
def api_import_json(data: ImportJsonRequest):
    """接受从教务网页提取的结构化课程 JSON"""
    sem = get_current_semester()
    if not sem:
        raise HTTPException(404, "没有学期数据")
    if not data.courses:
        raise HTTPException(400, "课程列表为空")
    import_courses(sem["id"], data.courses)
    return {"ok": True, "count": len(data.courses)}


@app.post("/api/import-html-paste")
def api_import_html_paste(data: ImportHtmlPasteRequest):
    """接受从教务页面复制粘贴的 HTML 并解析导入"""
    from scraper import parse_schedule_from_html
    sem = get_current_semester()
    if not sem:
        raise HTTPException(404, "没有学期数据")
    if len(data.html) < 100:
        raise HTTPException(400, "内容为空，请确认已复制课表页面内容")

    courses = parse_schedule_from_html(data.html)
    if not courses:
        raise HTTPException(422, "未能从内容中解析出课程，请确认复制的是教务系统课表页面")

    import_courses(sem["id"], courses)
    return {"ok": True, "count": len(courses)}


# ---- 设置 ----

@app.get("/api/settings")
def api_get_settings():
    return SettingsOut()


@app.put("/api/settings")
def api_update_settings(data: SettingsUpdate):
    return {"ok": True}
