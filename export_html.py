"""从数据库导出课表为独立 HTML 文件"""
import sqlite3, os, json
from datetime import date, datetime, timedelta
from config import PERIODS, WEEKDAYS, COURSE_COLORS

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "schedule.db")
OUTPUT_PATH = os.path.join(BASE_DIR, "我的课表.html")


def calc_current_week(start_date_str: str) -> int:
    try:
        start = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    except ValueError:
        return 1
    start_monday = start - timedelta(days=start.weekday())
    diff = date.today() - start_monday
    return max(1, diff.days // 7 + 1)


def generate():
    if not os.path.exists(DB_PATH):
        print("错误：数据库不存在")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    sem = conn.execute("SELECT * FROM semester WHERE is_current = 1").fetchone()
    if not sem:
        sem = conn.execute("SELECT * FROM semester ORDER BY id DESC LIMIT 1").fetchone()
    if not sem:
        print("错误：没有学期数据")
        conn.close()
        return
    sem = dict(sem)
    rows = conn.execute("SELECT * FROM course WHERE semester_id = ? ORDER BY day_of_week, start_period", (sem["id"],)).fetchall()
    conn.close()
    courses_list = [dict(r) for r in rows]

    current_week = calc_current_week(sem["start_date"])
    if current_week > sem["weeks"]:
        current_week = 1

    # 为每个课程添加颜色
    for c in courses_list:
        if not c.get("color"):
            c["color"] = COURSE_COLORS[hash(c["name"]) % len(COURSE_COLORS)]

    # 构建所有周数据
    all_weeks = {}
    for w in range(1, sem["weeks"] + 1):
        # 过滤本周课程
        week_courses = []
        for c in courses_list:
            if w < c["start_week"] or w > c["end_week"]:
                continue
            if c.get("week_type") == "odd" and w % 2 == 0:
                continue
            if c.get("week_type") == "even" and w % 2 == 1:
                continue
            week_courses.append(c)

        # 按天分组
        by_day = {d: [] for d in range(1, 8)}
        for c in week_courses:
            by_day[c["day_of_week"]].append(c)

        all_weeks[w] = by_day

    data_json = json.dumps(all_weeks, default=str, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>我的课表</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#f5f6f8;color:#333;font-size:14px;display:flex;flex-direction:column;height:100vh}}
.header{{background:#4A90D9;color:#fff;padding:12px 16px;text-align:center;font-size:16px;font-weight:600;flex-shrink:0}}
.week-nav{{background:#fff;height:44px;display:flex;align-items:center;justify-content:space-between;padding:0 16px;border-bottom:1px solid #e8e8e8;flex-shrink:0}}
.week-nav button{{background:none;border:1px solid #e8e8e8;border-radius:6px;height:32px;padding:0 12px;font-size:18px;cursor:pointer;color:#333}}
.week-nav .info{{font-size:15px;font-weight:600}}
.week-nav .today-btn{{background:#4A90D9;color:#fff;border:none;border-radius:4px;padding:4px 10px;font-size:12px;cursor:pointer}}
.wrapper{{flex:1;overflow:auto;-webkit-overflow-scrolling:touch;padding:0}}
table{{width:100%;min-width:750px;border-collapse:collapse;font-size:12px;table-layout:fixed}}
th,td{{border:1px solid #e8e8e8;padding:0;vertical-align:top;text-align:center}}
thead th{{background:#fff;position:sticky;top:0;z-index:2;padding:8px 2px;font-weight:600;font-size:13px;border-bottom:2px solid #ddd}}
th.period-col{{background:#fafafa;width:65px;font-weight:normal;font-size:10px;color:#888;padding:2px;white-space:nowrap}}
th.period-col .num{{font-weight:600;color:#333;font-size:12px}}
td.cell{{height:62px;padding:2px;background:#fff}}
td.empty{{background:#f0f1f3}}
.card{{border-radius:4px;padding:3px 4px;color:#fff;font-size:11px;height:100%}}
.card .name{{font-weight:600;font-size:11px;line-height:1.3;overflow:hidden;text-overflow:ellipsis;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}}
.card .loc{{font-size:10px;opacity:.9;margin-top:1px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
</style>
</head>
<body>
<div class="header" id="header">课程表</div>
<div class="week-nav">
  <button id="prevBtn">‹</button>
  <div class="info"><span id="weekLabel">第 1 周</span> <button class="today-btn" id="todayBtn">今天</button></div>
  <button id="nextBtn">›</button>
</div>
<div class="wrapper" id="wrapper"></div>

<script>
var ALL = {data_json};
var PERIODS = {json.dumps(PERIODS, ensure_ascii=False)};
var TOTAL_WEEKS = {sem["weeks"]};
var SEMESTER_START = "{sem["start_date"]}";
var DAY_NAMES = {json.dumps(WEEKDAYS, ensure_ascii=False)};

function calcCurrentWeek() {{
    var start = new Date(SEMESTER_START);
    var startMonday = new Date(start);
    startMonday.setDate(start.getDate() - start.getDay() + 1);
    var today = new Date();
    today.setHours(0, 0, 0, 0);
    var diff = Math.floor((today - startMonday) / (7 * 86400000));
    var week = Math.max(1, diff + 1);
    if (week > TOTAL_WEEKS) week = 1;
    return week;
}}

var CUR_WEEK = calcCurrentWeek();

function render(week) {{
    if (week < 1) week = 1;
    if (week > TOTAL_WEEKS) week = TOTAL_WEEKS;
    document.getElementById('weekLabel').textContent = '第 ' + week + ' 周 / 共 ' + TOTAL_WEEKS + ' 周';

    var byDay = ALL[String(week)];
    var h = '<table><thead><tr><th class="period-col">节次</th>';
    for (var d = 1; d <= 7; d++) {{
        h += '<th>周' + DAY_NAMES[d-1] + '</th>';
    }}
    h += '</tr></thead><tbody>';

    // 记录每列已被 rowspan 占用的行数
    var skipCol = {{}};
    for (var d = 1; d <= 7; d++) skipCol[d] = 0;

    for (var pi = 0; pi < PERIODS.length; pi++) {{
        var num = PERIODS[pi][0], st = PERIODS[pi][1], et = PERIODS[pi][2];
        h += '<tr><th class="period-col"><div class="num">' + num + '</div><div>' + st + '</div></th>';

        for (var d = 1; d <= 7; d++) {{
            if (skipCol[d] > 0) {{
                skipCol[d]--;
                continue;
            }}

            var courses = byDay[d].filter(function(c) {{ return c.start_period === num; }});
            if (courses.length > 0) {{
                var span = courses[0].end_period - courses[0].start_period + 1;
                if (span > 1) skipCol[d] = span - 1;
                var rs = span > 1 ? ' rowspan="' + span + '"' : '';
                h += '<td class="cell"' + rs + '>';
                for (var k = 0; k < courses.length; k++) {{
                    if (k > 0) h += '<div style="height:2px"></div>';
                    var c = courses[k];
                    h += '<div class="card" style="background:' + c.color + '">' +
                         '<div class="name">' + c.name + '</div>' +
                         '<div class="loc">' + (c.location || c.teacher || '') + '</div></div>';
                }}
                h += '</td>';
            }} else {{
                h += '<td class="cell empty"></td>';
            }}
        }}
        h += '</tr>';
    }}

    h += '</tbody></table>';
    document.getElementById('wrapper').innerHTML = h;
}}

document.getElementById('prevBtn').onclick = function() {{ CUR_WEEK--; render(CUR_WEEK); }};
document.getElementById('nextBtn').onclick = function() {{ CUR_WEEK++; render(CUR_WEEK); }};
document.getElementById('todayBtn').onclick = function() {{ CUR_WEEK = calcCurrentWeek(); render(CUR_WEEK); }};
render(CUR_WEEK);
</script>
</body>
</html>"""

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"已生成：{OUTPUT_PATH}")
    print(f"学期：{sem['name']}，共 {sem['weeks']} 周，{len(courses_list)} 门课程")


if __name__ == "__main__":
    generate()
