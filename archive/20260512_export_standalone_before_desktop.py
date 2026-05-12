"""
导出独立运行的课表 HTML 文件

把当前数据库中的课表数据，结合精致的毛玻璃 UI，
生成一份完全自包含的 HTML 文件，不需要任何服务端。

用法: python export_standalone.py
"""
import json, os, sqlite3
from datetime import date, datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "schedule.db")
TEMPLATE_PATH = os.path.join(BASE_DIR, "templates", "index.html")
OUTPUT_PATH = os.path.join(BASE_DIR, "课表.html")

PERIODS = [
    (1, "08:20", "09:05"), (2, "09:15", "10:00"), (3, "10:20", "11:05"),
    (4, "11:15", "12:00"), (5, "14:00", "14:45"), (6, "14:55", "15:40"),
    (7, "16:00", "16:45"), (8, "16:55", "17:40"), (9, "18:40", "19:25"),
    (10, "19:35", "20:20"), (11, "20:30", "21:15"),
]
WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"]
COURSE_COLORS = ["#4A90D9","#E8744A","#50B080","#B07CC9","#E8A040","#4AB5C4","#D9647A","#80B060"]


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def calc_current_week(start_date_str: str) -> int:
    start = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    start_monday = start - timedelta(days=start.weekday())
    diff = date.today() - start_monday
    return max(1, diff.days // 7 + 1)


def is_course_in_week(course, week):
    if week < course["start_week"] or week > course["end_week"]:
        return False
    if course["week_type"] == "odd" and week % 2 == 0:
        return False
    if course["week_type"] == "even" and week % 2 == 1:
        return False
    return True


def week_type_label(course):
    if course["week_type"] == "odd":
        return f'{course["start_week"]}-{course["end_week"]}周(单)'
    if course["week_type"] == "even":
        return f'{course["start_week"]}-{course["end_week"]}周(双)'
    if course["start_week"] == course["end_week"]:
        return f'第{course["start_week"]}周'
    return f'{course["start_week"]}-{course["end_week"]}周'


def get_schedule_for_week(semester, courses, week):
    """为指定周生成 schedule 数据（与 /api/schedule 返回格式一致）"""
    current_week = max(1, min(week, semester["weeks"]))

    start_date = datetime.strptime(semester["start_date"], "%Y-%m-%d").date()
    start_monday = start_date - timedelta(days=start_date.weekday())
    monday = start_monday + timedelta(weeks=current_week - 1)
    sunday = monday + timedelta(days=6)

    # 按时段分组
    slot_map = {}
    for c in courses:
        key = (c["day_of_week"], c["start_period"], c["end_period"])
        slot_map.setdefault(key, []).append(c)

    days = []
    for d in range(1, 8):
        day_slots = []
        for (day, sp, ep), slot_courses in slot_map.items():
            if day != d:
                continue
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

        day_slots.sort(key=lambda s: s["start_period"])
        days.append({"day": d, "slots": day_slots})

    return {
        "semester_name": semester["name"],
        "current_week": current_week,
        "total_weeks": semester["weeks"],
        "week_start": monday.isoformat(),
        "week_end": sunday.isoformat(),
        "periods": PERIODS,
        "weekdays": WEEKDAYS,
        "days": days,
    }


def generate():
    conn = get_conn()

    # 读取学期和课程
    sem = conn.execute("SELECT * FROM semester WHERE is_current = 1").fetchone()
    if not sem:
        sem = conn.execute("SELECT * FROM semester ORDER BY id DESC LIMIT 1").fetchone()
    if not sem:
        print("错误：没有学期数据")
        conn.close()
        return
    sem = dict(sem)

    courses = [dict(r) for r in conn.execute(
        "SELECT * FROM course WHERE semester_id = ? ORDER BY day_of_week, start_period",
        (sem["id"],)
    ).fetchall()]
    conn.close()

    # 补全颜色
    for c in courses:
        if not c.get("color"):
            c["color"] = COURSE_COLORS[hash(c["name"]) % len(COURSE_COLORS)]

    print(f"学期：{sem['name']}, 共 {sem['weeks']} 周, {len(courses)} 门课程")

    # 预生成所有周的数据
    all_weeks = {}
    for w in range(1, sem["weeks"] + 1):
        all_weeks[str(w)] = get_schedule_for_week(sem, courses, w)

    # 当前周
    current_week = calc_current_week(sem["start_date"])
    if current_week > sem["weeks"]:
        current_week = 1

    data_json = json.dumps(all_weeks, ensure_ascii=False, default=str)
    current_week_json = json.dumps(current_week)
    periods_json = json.dumps(PERIODS, ensure_ascii=False)
    weekdays_json = json.dumps(WEEKDAYS, ensure_ascii=False)
    semester_name_json = json.dumps(sem["name"], ensure_ascii=False)

    # 读取模板
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        template = f.read()

    # 找到 <script> 开始和 init() 调用的位置，进行替换
    # 策略：在模板中找到 init() 调用位置，替换整个 JS 逻辑
    # 更简单的方式：在 </body> 前注入 embedded data 和新的 init 逻辑

    # 找到 init() 调用的位置
    init_call_pos = template.find("init();")
    if init_call_pos == -1:
        print("错误：模板中未找到 init() 调用")
        return

    # 构建独立的 JS，替换原有的 JS
    standalone_js = f"""
<script>
// ===== 嵌入的课表数据 =====
var EMBEDDED_ALL_WEEKS = {data_json};
var EMBEDDED_CURRENT_WEEK = {current_week_json};
var EMBEDDED_PERIODS = {periods_json};
var EMBEDDED_WEEKDAYS = {weekdays_json};
var EMBEDDED_SEMESTER_NAME = {semester_name_json};

// ===== 状态 =====
const state = {{
    currentWeek: EMBEDDED_CURRENT_WEEK,
    totalWeeks: Object.keys(EMBEDDED_ALL_WEEKS).length,
    schedule: null,
    selectedDay: 0,
}};

// ===== 北京时间（UTC+8）工具函数 =====
function getBeijingDate() {{
    var s = new Date().toLocaleDateString('en-CA', {{ timeZone: 'Asia/Shanghai' }});
    return new Date(s + 'T00:00:00.000Z');
}}

function calcBeijingCurrentWeek() {{
    var today = getBeijingDate();
    var startMonday = new Date(Object.values(EMBEDDED_ALL_WEEKS)[0].week_start + 'T00:00:00.000Z');
    var diff = Math.floor((today - startMonday) / (7 * 86400000));
    return Math.max(1, Math.min(diff + 1, state.totalWeeks));
}}

// ===== Toast =====
function toast(msg, duration) {{
    const el = document.getElementById('toast');
    el.textContent = msg;
    el.className = 'toast show';
    setTimeout(() => el.className = 'toast', duration || 2000);
}}

// ===== 模态框 =====
function showModal(id) {{ document.getElementById(id).classList.add('active'); }}
function closeModal(id) {{ document.getElementById(id).classList.remove('active'); }}
document.querySelectorAll('.modal-overlay').forEach(el => {{
    el.addEventListener('click', e => {{
        if (e.target === el) el.classList.remove('active');
    }});
}});

// ===== 左右滑动切换周 =====
(function() {{
    let startX = 0, startY = 0;
    const MIN_SWIPE = 50;
    document.addEventListener('touchstart', e => {{
        startX = e.touches[0].clientX;
        startY = e.touches[0].clientY;
    }}, {{ passive: true }});
    document.addEventListener('touchend', e => {{
        const endX = e.changedTouches[0].clientX;
        const endY = e.changedTouches[0].clientY;
        const dx = endX - startX;
        const dy = endY - startY;
        if (Math.abs(dx) > Math.abs(dy) && Math.abs(dx) > MIN_SWIPE) {{
            if (e.target.closest('.modal-overlay, .modal, .modal-close')) return;
            changeWeek(dx > 0 ? -1 : 1, true);
        }}
    }}, {{ passive: true }});
}})();

// ===== 初始化（动态计算当前周，基于北京时间） =====
function init() {{
    loadSchedule(calcBeijingCurrentWeek());
}}

function loadSchedule(week) {{
    var data = EMBEDDED_ALL_WEEKS[String(week)];
    if (!data) return;
    state.currentWeek = data.current_week;
    state.totalWeeks = data.total_weeks;
    state.schedule = data;
    state.selectedDay = 0;
    render();
}}

// ===== 周导航 =====
function changeWeek(delta, animate) {{
    var newWeek = state.currentWeek + delta;
    if (newWeek < 1 || newWeek > state.totalWeeks) return;

    if (!animate) {{
        state.currentWeek = newWeek;
        loadSchedule(newWeek);
        return;
    }}

    var el = document.getElementById('courseTrack');
    var dir = delta > 0 ? '-100%' : '100%';
    el.style.transition = 'transform .25s cubic-bezier(0.25, 0.1, 0.25, 1)';
    el.style.transform = 'translate3d(' + dir + ', 0, 0)';

    setTimeout(function() {{
        state.currentWeek = newWeek;
        loadSchedule(newWeek);
        el.style.transition = 'none';
        el.style.transform = 'translate3d(' + (delta > 0 ? '100%' : '-100%') + ', 0, 0)';
        el.offsetHeight;
        el.style.transition = 'transform .25s cubic-bezier(0.25, 0.1, 0.25, 1)';
        el.style.transform = 'translate3d(0, 0, 0)';
        setTimeout(function() {{
            el.style.transition = '';
            el.style.transform = '';
        }}, 260);
    }}, 260);
}}

function goToToday() {{
    state.currentWeek = calcBeijingCurrentWeek();
    loadSchedule(state.currentWeek);
}}

// ===== 辅助 =====
function mutedColor(hex, alpha) {{
    var r = parseInt(hex.slice(1,3), 16);
    var g = parseInt(hex.slice(3,5), 16);
    var b = parseInt(hex.slice(5,7), 16);
    var mr = Math.round(r + (192 - r) * 0.25);
    var mg = Math.round(g + (192 - g) * 0.25);
    var mb = Math.round(b + (192 - b) * 0.25);
    return 'rgba(' + mr + ',' + mg + ',' + mb + ',' + alpha + ')';
}}

function getTodayDayOfWeek() {{
    var d = getBeijingDate().getUTCDay();
    return d === 0 ? 7 : d;
}}

// ===== 渲染 =====
function render() {{
    if (!state.schedule) return;
    document.getElementById('headerTitle').textContent = state.schedule.semester_name;
    document.getElementById('weekLabel').textContent = '第 ' + state.currentWeek + ' 周 / 共 ' + state.totalWeeks + ' 周';
    document.getElementById('todayBtn').style.display = 'inline-block';
    tableRender();
    mobileRender();
}}

// ===== 桌面端表格渲染 =====
function tableRender() {{
    if (!state.schedule) return;
    var periods = state.schedule.periods;
    var weekdays = state.schedule.weekdays;
    var days = state.schedule.days;

    var slotByDay = {{}};
    for (var i = 0; i < days.length; i++) {{
        slotByDay[days[i].day] = days[i].slots;
    }}

    var occupied = {{}};
    function mark(d, fromP, toP) {{
        for (var p = fromP; p <= toP; p++) {{
            occupied[d + '-' + p] = true;
        }}
    }}

    // 节次列
    var pHtml = '';
    for (var pi = 0; pi < periods.length; pi++) {{
        pHtml += '<div class=\"period-item\"><div class=\"period-num\">' + periods[pi][0] + '</div>'
              + '<div class=\"period-time\">' + periods[pi][1] + '-' + periods[pi][2] + '</div></div>';
    }}
    document.getElementById('periodColBody').innerHTML = pHtml;

    // 日期表头
    var hHtml = '';
    var todayDOW = getTodayDayOfWeek();
    var isCurrentWeek = calcBeijingCurrentWeek() === state.currentWeek;
    for (var d = 0; d < weekdays.length; d++) {{
        var dateStr = '';
        if (state.schedule.week_start) {{
            var start = new Date(state.schedule.week_start);
            var dayDate = new Date(start);
            dayDate.setDate(start.getDate() + d);
            dateStr = (dayDate.getMonth() + 1) + '/' + dayDate.getDate();
        }}
        var cls = d >= 5 ? ' weekend' : '';
        if (isCurrentWeek && d + 1 === todayDOW) cls += ' today';
        hHtml += '<div class=\"day-header' + cls + '\">周' + weekdays[d]
               + '<span class=\"day-date\">' + dateStr + '</span></div>';
    }}
    document.getElementById('scheduleHeader').innerHTML = hHtml;

    // 课程网格
    var cells = [];
    for (var pi = 0; pi < periods.length; pi++) {{
        var num = periods[pi][0];
        for (var d = 1; d <= 7; d++) {{
            var key = d + '-' + num;
            if (occupied[key]) continue;

            var isWeekend = d >= 6;
            var slots = slotByDay[d] || [];
            var slot = null;
            for (var si = 0; si < slots.length; si++) {{
                if (slots[si].start_period === num) {{
                    var hasActive = false;
                    for (var ci = 0; ci < slots[si].courses.length; ci++) {{
                        if (slots[si].courses[ci].active) {{ hasActive = true; break; }}
                    }}
                    if (hasActive) {{ slot = slots[si]; break; }}
                }}
            }}

            if (slot) {{
                var activeCourse = null;
                for (var ci = 0; ci < slot.courses.length; ci++) {{
                    if (slot.courses[ci].active) {{ activeCourse = slot.courses[ci]; break; }}
                }}
                if (!activeCourse) {{
                    cells.push({{ col: d, row: pi + 1, span: 1, empty: true, cls: isWeekend ? ' weekend' : '' }});
                    continue;
                }}
                var span = slot.end_period - slot.start_period + 1;
                if (span > 1) mark(d, slot.start_period, slot.end_period);
                var badgeCount = slot.total - 1;
                var badgeHtml = badgeCount > 0
                    ? '<span class=\"slot-badge\">+' + badgeCount + '</span>' : '';

                cells.push({{
                    col: d, row: pi + 1, span: span,
                    cls: isWeekend ? ' weekend' : '',
                    html: '<div class=\"course-card\" style=\"background:' + mutedColor(activeCourse.color,0.65)
                        + ';\" onclick=\"showSlotDetail(' + d + ',' + slot.start_period + ',' + slot.end_period + ')\">'
                        + '<div class=\"course-name\">' + activeCourse.name + '</div>'
                        + '<div class=\"course-location\">' + (activeCourse.location || activeCourse.teacher || '') + '</div>'
                        + badgeHtml + '</div>'
                }});
            }} else {{
                cells.push({{ col: d, row: pi + 1, span: 1, empty: true, cls: isWeekend ? ' weekend' : '' }});
            }}
        }}
    }}

    var gHtml = '';
    for (var ci = 0; ci < cells.length; ci++) {{
        var cell = cells[ci];
        var pos = 'grid-column:' + cell.col + ';grid-row:' + cell.row + (cell.span > 1 ? '/span ' + cell.span : '');
        if (cell.empty) {{
            gHtml += '<div class=\"course-cell empty' + cell.cls + '\" style=\"' + pos + '\"></div>';
        }} else {{
            gHtml += '<div class=\"course-cell' + cell.cls + '\" style=\"' + pos + '\">' + cell.html + '</div>';
        }}
    }}
    document.getElementById('courseTrack').innerHTML = gHtml;
}}

// ===== 移动端渲染 =====
function mobileRender() {{
    if (!state.schedule) return;
    var days = state.schedule.days;
    var weekdays = state.schedule.weekdays;
    var week_start = state.schedule.week_start;

    if (!state.selectedDay) {{
        state.selectedDay = getTodayDayOfWeek();
    }}

    var start = week_start ? new Date(week_start) : null;
    var tabsHtml = '';
    for (var d = 1; d <= 7; d++) {{
        var dateStr = '';
        if (start) {{
            var dayDate = new Date(start);
            dayDate.setDate(start.getDate() + d - 1);
            dateStr = (dayDate.getMonth() + 1) + '/' + dayDate.getDate();
        }}
        var isToday = d === getTodayDayOfWeek();
        var isActive = d === state.selectedDay;
        var cls = 'day-tab';
        if (isActive) cls += ' active';
        if (isToday) cls += ' today';
        tabsHtml += '<div class=\"' + cls + '\" onclick=\"switchToDay(' + d + ')\">'
                  + '<span class=\"dow\">周' + weekdays[d-1] + '</span>'
                  + '<span class=\"date-num\">' + dateStr + '</span></div>';
    }}
    document.getElementById('dayTabs').innerHTML = tabsHtml;

    var dayData = null;
    for (var i = 0; i < days.length; i++) {{
        if (days[i].day === state.selectedDay) {{ dayData = days[i]; break; }}
    }}

    var tlContainer = document.getElementById('mobileTimeline');
    var ROW_H = 50;
    var totalH = state.schedule.periods.length * ROW_H;

    var labelsHtml = '';
    for (var pi = 0; pi < state.schedule.periods.length; pi++) {{
        labelsHtml += '<div class=\"tl-label\"><span class=\"num\">' + state.schedule.periods[pi][0]
                    + '</span><span class=\"time\">' + state.schedule.periods[pi][1] + '</span></div>';
    }}

    var coursesHtml = '';
    if (dayData) {{
        for (var si = 0; si < dayData.slots.length; si++) {{
            var slot = dayData.slots[si];
            var activeCourses = [];
            for (var ci = 0; ci < slot.courses.length; ci++) {{
                if (slot.courses[ci].active) activeCourses.push(slot.courses[ci]);
            }}
            if (!activeCourses.length) continue;

            var course = activeCourses[0];
            var span = slot.end_period - slot.start_period + 1;
            var top = (slot.start_period - 1) * ROW_H;
            var height = span * ROW_H - 4;
            var badgeCount = slot.total - 1;
            var badgeHtml = badgeCount > 0 ? '<div class=\"tl-badge\">+' + badgeCount + '门</div>' : '';

            coursesHtml += '<div class=\"tl-course\" style=\"top:' + top + 'px;height:' + height
                        + 'px;background:' + mutedColor(course.color,0.65)
                        + '\" onclick=\"showSlotDetail(' + state.selectedDay + ',' + slot.start_period + ',' + slot.end_period + ')\">'
                        + '<div class=\"name\">' + course.name + '</div>'
                        + '<div class=\"loc\">' + (course.location || course.teacher || '') + '</div>'
                        + badgeHtml + '</div>';
        }}
    }}

    if (!coursesHtml) coursesHtml = '<div class=\"tl-empty\">当天没有课程</div>';

    tlContainer.innerHTML = '<div class=\"tl-wrapper\" style=\"min-height:' + totalH + 'px\">'
                          + '<div class=\"tl-labels\">' + labelsHtml + '</div>'
                          + '<div class=\"tl-courses\" style=\"min-height:' + totalH + 'px\">' + coursesHtml
                          + '</div></div>';
}}

function switchToDay(day) {{
    state.selectedDay = day;
    mobileRender();
}}

function changeSelectedDay(delta) {{
    var newDay = state.selectedDay + delta;
    if (newDay < 1) newDay = 7;
    if (newDay > 7) newDay = 1;
    state.selectedDay = newDay;
    mobileRender();
}}

// 移动端触摸滑动
(function() {{
    var touchStartX = 0, touchStartY = 0;
    var mv = document.getElementById('mobileView');
    if (mv) {{
        mv.addEventListener('touchstart', function(e) {{
            touchStartX = e.touches[0].clientX;
            touchStartY = e.touches[0].clientY;
        }}, {{ passive: true }});
        mv.addEventListener('touchend', function(e) {{
            var dx = e.changedTouches[0].clientX - touchStartX;
            var dy = e.changedTouches[0].clientY - touchStartY;
            if (Math.abs(dx) > Math.abs(dy) && Math.abs(dx) > 40) {{
                if (dx < 0) changeSelectedDay(1);
                else changeSelectedDay(-1);
            }}
        }}, {{ passive: true }});
    }}
}})();

// 窗口 resize
(function() {{
    var resizeTimer;
    window.addEventListener('resize', function() {{
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(render, 200);
    }});
}})();

// ===== 时段详情 =====
function showSlotDetail(day, startPeriod, endPeriod) {{
    var dayData = null;
    for (var i = 0; i < state.schedule.days.length; i++) {{
        if (state.schedule.days[i].day === day) {{ dayData = state.schedule.days[i]; break; }}
    }}
    if (!dayData) return;
    var slot = null;
    for (var si = 0; si < dayData.slots.length; si++) {{
        if (dayData.slots[si].start_period === startPeriod && dayData.slots[si].end_period === endPeriod) {{
            slot = dayData.slots[si]; break;
        }}
    }}
    if (!slot) return;

    var dayNames = state.schedule.weekdays || ['一','二','三','四','五','六','日'];
    var weekday = dayNames[day - 1];

    var html = '';
    for (var ci = 0; ci < slot.courses.length; ci++) {{
        var course = slot.courses[ci];
        var inactive = !course.active;
        var cardStyle = inactive ? 'background:rgba(0,0,0,0.15)' : 'background:' + mutedColor(course.color,0.65);
        var statusText = inactive ? '本周无课（' + course.week_info + '）' : '本周有课';

        html += '<div class=\"slot-detail-card' + (inactive ? ' inactive' : '') + '\" style=\"' + cardStyle + '\">'
              + '<div class=\"slot-detail-name\">' + course.name + '</div>'
              + '<div class=\"slot-detail-info\">教师：' + (course.teacher || '未设置') + '</div>'
              + '<div class=\"slot-detail-info\">地点：' + (course.location || '未设置') + '</div>'
              + '<div class=\"slot-detail-info\">时间：周' + weekday + ' 第' + startPeriod + '-' + endPeriod + '节</div>'
              + '<div class=\"slot-detail-info\">周次：' + course.week_info + '</div>'
              + '<div class=\"slot-detail-status\">' + statusText + '</div></div>';
    }}

    document.getElementById('slotDetailBody').innerHTML = html;
    showModal('slotDetailModal');
}}

// ===== 设置 =====
function showSettings() {{
    var pTable = document.getElementById('periodTable');
    var html = '<table style=\"width:100%;border-collapse:collapse;margin-top:8px;\">'
             + '<tr><th style=\"text-align:left;padding:6px;\">节次</th><th style=\"text-align:left;padding:6px;\">时间</th></tr>';
    for (var pi = 0; pi < EMBEDDED_PERIODS.length; pi++) {{
        html += '<tr><td style=\"padding:4px 6px;border-bottom:1px solid #eee;\">第' + EMBEDDED_PERIODS[pi][0]
              + '节</td><td style=\"padding:4px 6px;border-bottom:1px solid #eee;\">' + EMBEDDED_PERIODS[pi][1]
              + ' - ' + EMBEDDED_PERIODS[pi][2] + '</td></tr>';
    }}
    html += '</table>';
    pTable.innerHTML = html;
    showModal('settingsModal');
}}

// ===== 启动 =====
init();
</script>"""

    # 找到 script 边界
    head_end = template.find("</head>")
    body_start = template.find("<body", head_end)
    body_end = template.find("</body>", body_start)

    body_content = template[body_start:body_end]
    first_script = body_content.find("<script>")
    last_script_end = body_content.rfind("</script>")

    if first_script == -1 or last_script_end == -1:
        print("错误：模板中没有找到 script 标签")
        return

    new_body = body_content[:first_script] + "\n" + standalone_js + "\n" + body_content[last_script_end + len("</script>"):]
    html = template[:body_start] + new_body + template[body_end:]

    # 写入文件
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"已生成：{OUTPUT_PATH}")
    print(f"学期：{sem['name']}，共 {sem['weeks']} 周，{len(courses)} 门课程")
    print(f"文件大小：{os.path.getsize(OUTPUT_PATH) / 1024:.1f} KB")


if __name__ == "__main__":
    generate()
