"""导出课表为手机版 HTML（纯静态，无需 JavaScript）"""
import sqlite3, os
from datetime import date, datetime, timedelta
from config import PERIODS, WEEKDAYS, COURSE_COLORS

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "schedule.db")
OUTPUT_PATH = os.path.join(BASE_DIR, "课表-手机版.html")


def calc_current_week(start_date_str: str) -> int:
    try:
        start = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    except ValueError:
        return 1
    start_monday = start - timedelta(days=start.weekday())
    diff = date.today() - start_monday
    return max(1, diff.days // 7 + 1)


def build_week_table(week_courses, week_num):
    """生成一周课表的 HTML 表格"""
    by_day = {d: [] for d in range(1, 8)}
    for c in week_courses:
        by_day[c["day_of_week"]].append(c)

    rows = []
    skip_col = {d: 0 for d in range(1, 8)}

    for pi in range(len(PERIODS)):
        num, st, et = PERIODS[pi]
        cells = []
        for d in range(1, 8):
            if skip_col[d] > 0:
                skip_col[d] -= 1
                continue
            day_courses = [c for c in by_day[d] if c["start_period"] == num]
            if day_courses:
                c = day_courses[0]
                span = c["end_period"] - c["start_period"] + 1
                if span > 1:
                    skip_col[d] = span - 1
                rowspan = f' rowspan="{span}"' if span > 1 else ""
                color = c["color"] or COURSE_COLORS[hash(c["name"]) % len(COURSE_COLORS)]
                cards = []
                for c2 in day_courses:
                    color2 = c2["color"] or COURSE_COLORS[hash(c2["name"]) % len(COURSE_COLORS)]
                    cards.append(
                        f'<div class="card" style="background:{color2}">'
                        f'<div class="name">{c2["name"]}</div>'
                        f'<div class="loc">{c2.get("location") or c2.get("teacher") or ""}</div>'
                        f"</div>"
                    )
                cells.append(
                    f'<td class="cell"{rowspan}>{"".join(cards)}</td>'
                )
            else:
                cells.append('<td class="cell empty"></td>')

        rows.append(
            f'<tr>'
            f'<th class="period-col"><div class="num">{num}</div><div>{st}</div></th>'
            f'{"".join(cells)}'
            f"</tr>"
        )

    return f'<table><thead><tr><th class="period-col">节次</th><th>周一</th><th>周二</th><th>周三</th><th>周四</th><th>周五</th><th>周六</th><th>周日</th></tr></thead><tbody>{"".join(rows)}</tbody></table>'


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

    # 给课程分配颜色
    for c in courses_list:
        if not c.get("color"):
            c["color"] = COURSE_COLORS[hash(c["name"]) % len(COURSE_COLORS)]

    # 构建所有周的课表 HTML
    weeks_html = []
    week_labels = []
    for w in range(1, sem["weeks"] + 1):
        week_courses = []
        for c in courses_list:
            if w < c["start_week"] or w > c["end_week"]:
                continue
            if c.get("week_type") == "odd" and w % 2 == 0:
                continue
            if c.get("week_type") == "even" and w % 2 == 1:
                continue
            week_courses.append(c)
        weeks_html.append(build_week_table(week_courses, w))
        checked = ' checked' if w == current_week else ''
        week_labels.append(
            f'<label for="w{w}" class="tab-label" data-week="{w}">第{w}周</label>'
        )

    # 构建 CSS 选择器：每两周的 radio 控制对应 .week-page 的显示
    css_rules = []
    for w in range(1, sem["weeks"] + 1):
        css_rules.append(f"#w{w}:checked ~ .weeks-container .week-page[data-week=\"{w}\"] {{ display: block; }}")
        css_rules.append(f"#w{w}:checked ~ .tab-bar .tab-label[data-week=\"{w}\"] {{ background: #4A90D9; color: #fff; }}")

    total_weeks = sem["weeks"]
    radio_buttons = "\n".join(
        f'<input type="radio" name="week" id="w{w}"{" checked" if w == current_week else ""}>'
        for w in range(1, total_weeks + 1)
    )
    week_pages = "\n".join(
        f'<div class="week-page" data-week="{w}">{weeks_html[w-1]}</div>'
        for w in range(1, total_weeks + 1)
    )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=3.0,user-scalable=yes">
<title>课表 - {sem['name']}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#f5f6f8;color:#333;font-size:13px;display:flex;flex-direction:column;min-height:100vh;overflow-x:hidden}}

/* 隐藏 radio */
input[name="week"]{{position:absolute;opacity:0;pointer-events:none}}

.header{{background:#4A90D9;color:#fff;padding:10px 12px;text-align:center;font-size:15px;font-weight:600;flex-shrink:0}}
.header .sub{{font-size:11px;font-weight:400;opacity:.8;margin-top:2px}}

/* 周导航标签栏 - 横滑 */
.tab-bar{{background:#fff;padding:6px 0;border-bottom:1px solid #e8e8e8;flex-shrink:0;overflow-x:auto;-webkit-overflow-scrolling:touch;white-space:nowrap}}
.tab-bar .tab-label{{display:inline-block;padding:6px 12px;margin:0 3px;border-radius:16px;font-size:12px;cursor:pointer;background:#f0f0f0;color:#666;transition:all .2s;white-space:nowrap;user-select:none;-webkit-tap-highlight-color:transparent}}
.tab-bar .tab-label:active{{opacity:.7}}

/* 课表容器 */
.weeks-container{{flex:1;overflow:auto;-webkit-overflow-scrolling:touch;padding:4px}}
.week-page{{display:none;padding:4px 0}}

/* 表格 */
table{{width:100%;min-width:680px;border-collapse:collapse;font-size:11px}}
th,td{{border:1px solid #ddd;padding:0;vertical-align:top;text-align:center}}
thead th{{background:#f8f9fa;position:sticky;top:0;z-index:2;padding:6px 2px;font-weight:600;font-size:11px;border-bottom:2px solid #ccc}}
th.period-col{{background:#fafafa;width:55px;font-weight:normal;font-size:9px;color:#888;padding:2px}}
th.period-col .num{{font-weight:600;color:#333;font-size:11px}}
td.cell{{height:50px;padding:2px;background:#fff}}
td.empty{{background:#f0f1f3}}
.card{{border-radius:3px;padding:2px 3px;color:#fff;font-size:10px;margin-bottom:1px}}
.card .name{{font-weight:600;font-size:10px;line-height:1.3;overflow:hidden;text-overflow:ellipsis;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}}
.card .loc{{font-size:9px;opacity:.9;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}

/* 空状态 */
.empty-state{{text-align:center;padding:40px 20px;color:#999;font-size:14px}}

{chr(10).join(css_rules)}
</style>
</head>
<body>
<div class="header">
  课程表
  <div class="sub">{sem['name']} · 共{total_weeks}周</div>
</div>

{radio_buttons}

<div class="tab-bar">
  {chr(10).join(week_labels)}
</div>

<div class="weeks-container">
  {week_pages}
</div>

<div style="text-align:center;padding:16px;font-size:11px;color:#aaa;flex-shrink:0">
  内蒙古工业大学 · {sem['name']}
</div>
</body>
</html>"""

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"已生成手机版课表：{OUTPUT_PATH}")
    print(f"学期：{sem['name']}，共 {sem['weeks']} 周，{len(courses_list)} 门课程")
    print(f"当前周：第 {current_week} 周")


if __name__ == "__main__":
    generate()
