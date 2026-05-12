"""
修复课表数据：以原始 HTML 为准，重新解析课表

核心规则：
1. 表格内同一格子的多门课程，以最下方的数据为准（覆盖上方同课程的周次）
2. 表格下方调课通知中，以右侧"补课时间地点"为准

用法：python fix_schedule.py
"""
import os, re, sqlite3
from datetime import date, datetime
from bs4 import BeautifulSoup

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "schedule.db")
HTML_PATH = os.path.join(BASE_DIR, "学生课表.html")
ARCHIVE_HTML = os.path.join(BASE_DIR, "archive", "20260501_0042_学生课表.html")

PERIODS = [
    (1, "08:20", "09:05"), (2, "09:15", "10:00"), (3, "10:20", "11:05"),
    (4, "11:15", "12:00"), (5, "14:00", "14:45"), (6, "14:55", "15:40"),
    (7, "16:00", "16:45"), (8, "16:55", "17:40"), (9, "18:40", "19:25"),
    (10, "19:35", "20:20"), (11, "20:30", "21:15"),
]
PERIOD_MAP = {p[0]: pi for pi, p in enumerate(PERIODS, 1)}  # period_num -> row_idx (1-based)

COURSE_COLORS = [
    "#4A90D9", "#E8744A", "#50B080", "#B07CC9",
    "#E8A040", "#4AB5C4", "#D9647A", "#80B060",
]

WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"]

# GBK 编码的星期映射
GBK_WEEKDAY_MAP = {
    "周一": 1, "周二": 2, "周三": 3, "周四": 4, "周五": 5, "周六": 6, "周日": 7,
    "星期一": 1, "星期二": 2, "星期三": 3, "星期四": 4, "星期五": 5, "星期六": 6, "星期日": 7,
}


def read_html():
    """读取原始课表 HTML"""
    for path in [HTML_PATH, ARCHIVE_HTML]:
        if os.path.exists(path):
            with open(path, "rb") as f:
                raw = f.read()
            try:
                return raw.decode("gbk")
            except UnicodeDecodeError:
                return raw.decode("gbk", errors="replace")
    print("错误：未找到学生课表.html")
    return None


def parse_period_num(th_text: str) -> int | None:
    """从表头节次文本中解析节次号, 如 '第1节< br >08:20< br >┆< br >09:05' → 1"""
    m = re.search(r"第?(\d+)\s*节", th_text)
    if m:
        return int(m.group(1))
    # 也可能直接以数字开头
    m = re.search(r"^(\d+)", th_text.strip())
    if m:
        return int(m.group(1))
    return None


def expand_weeks(week_text: str) -> set[int]:
    """解析周次文本，返回周号集合，如 '5-11周' → {5,6,7,8,9,10,11}, '5周' → {5}"""
    weeks = set()
    week_text = week_text.strip()
    if not week_text:
        return weeks
    # 处理 "单周" / "双周" / "单" / "双"
    is_odd = any(k in week_text for k in ("单"))
    is_even = any(k in week_text for k in ("双"))
    # 提取所有数字范围
    for m in re.finditer(r"(\d+)\s*[-–—]\s*(\d+)", week_text):
        start, end = int(m.group(1)), int(m.group(2))
        for w in range(start, end + 1):
            weeks.add(w)
    # 提取单个数字
    for m in re.finditer(r"(?<!\d)(\d+)\s*周", week_text):
        w = int(m.group(1))
        # 确保不是范围的一部分
        is_in_range = False
        for m2 in re.finditer(r"(\d+)\s*[-–—]\s*(\d+)", week_text):
            if int(m2.group(1)) <= w <= int(m2.group(2)):
                is_in_range = True
                break
        if not is_in_range:
            weeks.add(w)
    # 如果没找到数字但文本有内容，假设是全部周
    if not weeks and week_text:
        return set()  # 无法解析
    # 应用单双周过滤
    if is_odd and not is_even:
        weeks = {w for w in weeks if w % 2 == 1}
    elif is_even and not is_odd:
        weeks = {w for w in weeks if w % 2 == 0}
    return weeks


def parse_cell_block(block_text: str, day: int, html_row_idx: int) -> dict | None:
    """解析单个课程块文本，返回课程信息"""
    lines = [l.strip() for l in block_text.strip().split("\n") if l.strip()]
    if not lines:
        return None

    first = lines[0]
    name_match = re.match(r"<<(.+?)>>\s*;?\s*(\d*)", first)
    if not name_match:
        return None

    name = name_match.group(1).strip()
    remaining = lines[1:]

    location = ""
    teacher = ""
    week_text = ""

    for line in remaining:
        if line in ("讲课", "实验", "上机", "课内练习", "实践"):
            continue
        # 周次行
        if re.match(r"\d+\s*[-–—,]\s*\d+\s*周", line) or re.match(r"\d+\s*周", line):
            week_text = line
        # 教师行
        elif (re.match(r"^[一-鿿]{2,4}$", line) or "老师" in line or
              re.match(r"^[一-鿿]{2,4}[gG]?$", line)):
            teacher = line
        else:
            location = location or line

    # 过滤无效课程名
    if name in ("", " "):
        return None

    return {
        "name": name,
        "location": location,
        "teacher": teacher.replace("老师", "").replace("g", "").strip(),
        "week_text": week_text,
        "day": day,
    }


def parse_timetable(soup):
    """
    解析主课表表格，应用"最下方为准"规则。

    1. 对每个格子按从下到上处理课程块
    2. 下方课程块的周次优先占据，上方课程块只保留未被占据的周次
    3. 最终产出以 (course_name, day, start_period, week) 为单位的条目
    """
    table = soup.find("table", id="timetable")
    if not table:
        table = soup.find("table", class_="infolist_hr")
    if not table:
        print("错误：未找到课表表格")
        return []

    rows = table.find_all("tr")
    if len(rows) < 2:
        return []

    # Step 1: 解析所有格子，获得 (day, row_idx) → [blocks]
    cell_blocks = {}  # (day, row_idx) -> [(block_text, row_position)]

    for row_idx, row in enumerate(rows):
        if row_idx == 0:
            continue  # 表头
        cells = row.find_all(["td", "th"])
        if len(cells) < 2:
            continue

        for day_idx in range(1, len(cells)):
            cell = cells[day_idx]
            cell_text = cell.get_text("\n", strip=True)
            if not cell_text or cell_text == "\xa0":
                continue

            blocks = re.split(r"\n(?=<<)", cell_text)
            # 从下到上编号，用于排序
            for bi, block_text in enumerate(reversed(blocks)):
                block = block_text.strip()
                if not block:
                    continue
                lines = [l.strip() for l in block.split("\n") if l.strip()]
                if not lines:
                    continue
                key = (day_idx, row_idx)
                if key not in cell_blocks:
                    cell_blocks[key] = []
                cell_blocks[key].append((block, bi))  # bi 从下到上递增

    # Step 2: 对每个 (day, row_idx) 格子，按从下到上解析，bottom wins
    # 结果：week_entries[(day, period, course_name)] = {week: {location, teacher}}
    # 但 row_idx 和 period_num 需要关联
    # 实际上，同一天同一个 period_num（节次）可能有多个 row_idx（如果课程跨行）
    # 更准确：直接用 day 和 period 计算

    # 先建立 row_idx → period_num 的映射
    row_period_map = {}
    for row_idx, row in enumerate(rows):
        if row_idx == 0:
            continue
        th_cells = row.find_all("th")
        if th_cells:
            period_num = parse_period_num(th_cells[0].get_text("\n", strip=True))
            if period_num:
                row_period_map[row_idx] = period_num

    # 按 (day, period_num) 聚合并处理
    # period_blocks[(day, period)] = [(block_text, order_from_bottom)]
    period_blocks = {}
    for (day, row_idx), blocks in cell_blocks.items():
        period = row_period_map.get(row_idx)
        if period is None:
            continue
        key = (day, period)
        if key not in period_blocks:
            period_blocks[key] = []
        period_blocks[key].extend(blocks)

    # 对每个 (day, period)，按从下到上处理
    # bottom_wins[(day, period, course_name)] = {(week, location, teacher)}
    # 但 location/teacher 可能不同，所以需要跟踪每个周的赢家
    all_entries = []  # 最终条目

    for (day, period), pb_blocks in period_blocks.items():
        # 按 order_from_bottom 从小到大排序（先处理最下面的块，bi=0 是最下面）
        pb_blocks.sort(key=lambda x: x[1])

        # claimed: course_name -> { week_number: {location, teacher} }
        claimed = {}

        for block_text, _ in pb_blocks:
            parsed = parse_cell_block(block_text, day, 0)
            if not parsed:
                continue

            name = parsed["name"]
            weeks = expand_weeks(parsed["week_text"])

            # 处理这个课程块在 (day, period) 下的周次
            # 注意：同个课程可能在不同 (day, period) 出现，但这里只处理当前 (day, period)
            if name not in claimed:
                claimed[name] = {}

            for w in weeks:
                if w not in claimed[name]:
                    # 没有被下方的同名课程占据的周次，分配给这个块
                    claimed[name][w] = {
                        "location": parsed["location"],
                        "teacher": parsed["teacher"],
                    }

        # 把结果转成条目
        for name, week_info in claimed.items():
            if not week_info:
                continue
            # 按 location/teacher 聚合连续周次
            # 先把 week_info 按周排序
            sorted_weeks = sorted(week_info.keys())
            if not sorted_weeks:
                continue

            # 按 (location, teacher) 分组连续周
            groups = []
            current_group = {
                "weeks": [],
                "location": week_info[sorted_weeks[0]]["location"],
                "teacher": week_info[sorted_weeks[0]]["teacher"],
            }
            for w in sorted_weeks:
                info = week_info[w]
                if (info["location"] == current_group["location"] and
                        info["teacher"] == current_group["teacher"] and
                        (not current_group["weeks"] or w == current_group["weeks"][-1] + 1)):
                    current_group["weeks"].append(w)
                else:
                    groups.append(current_group)
                    current_group = {
                        "weeks": [w],
                        "location": info["location"],
                        "teacher": info["teacher"],
                    }
            groups.append(current_group)

            for g in groups:
                if not g["weeks"]:
                    continue
                all_entries.append({
                    "name": name,
                    "day": day,
                    "start_period": period,
                    "end_period": period,
                    "location": g["location"],
                    "teacher": g["teacher"],
                    "start_week": min(g["weeks"]),
                    "end_week": max(g["weeks"]),
                    "weeks": g["weeks"],
                })

    # Step 3: 合并连续节次
    # 同一天同一课程同一地点同一教师，且节次连续的合并
    merged = merge_consecutive_periods(all_entries)
    return merged


def merge_consecutive_periods(entries):
    """合并同一个 (day, course, location, teacher) 中连续节次的条目"""
    # 按 (day, name, location, teacher) 分组
    groups = {}
    for e in entries:
        key = (e["day"], e["name"], e["location"], e["teacher"])
        groups.setdefault(key, []).append(e)

    result = []
    for key, group in groups.items():
        day, name, location, teacher = key
        # 按 start_period 排序
        group.sort(key=lambda x: x["start_period"])

        # 合并连续的 periods 和 weeks
        # 对于同一个 (day, course, location, teacher) 下可能多个 period 段
        # 每个 period 段又可能包含多个不连续的周次

        # 策略：按 (period) 分组，然后检查是否可以合并
        # 如果 period1 和 period2 的 weeks 完全相同，且 period2 == period1 + 1，则可合并

        merged_periods = []
        for e in group:
            if not merged_periods:
                merged_periods.append({
                    "name": name,
                    "day": day,
                    "start_period": e["start_period"],
                    "end_period": e["end_period"],
                    "location": location,
                    "teacher": teacher,
                    "weeks": e["weeks"],
                })
            else:
                last = merged_periods[-1]
                # 检查节次是否连续且周次相同
                if (e["start_period"] == last["end_period"] + 1 and
                        set(e["weeks"]) == set(last["weeks"])):
                    last["end_period"] = e["end_period"]
                else:
                    merged_periods.append({
                        "name": name,
                        "day": day,
                        "start_period": e["start_period"],
                        "end_period": e["end_period"],
                        "location": location,
                        "teacher": teacher,
                        "weeks": e["weeks"],
                    })

        for mp in merged_periods:
            if not mp["weeks"]:
                continue
            result.append({
                "name": mp["name"],
                "day_of_week": mp["day"],
                "start_period": mp["start_period"],
                "end_period": mp["end_period"],
                "location": mp["location"],
                "teacher": mp["teacher"],
                "start_week": min(mp["weeks"]),
                "end_week": max(mp["weeks"]),
                "week_type": classify_week_type(mp["weeks"]),
            })

    result.sort(key=lambda c: (c["day_of_week"], c["start_period"]))
    return result


def classify_week_type(weeks):
    """判断周次类型"""
    if not weeks:
        return ""
    odd = [w for w in weeks if w % 2 == 1]
    even = [w for w in weeks if w % 2 == 0]
    if not even:
        return "odd"
    if not odd:
        return "even"
    return ""


def parse_adjustments(soup):
    """
    解析调课通知表格，返回调课信息列表。

    表格结构（清华 URPL 系统）：
      行首有 rowspan 的 = 带完整课程信息的行
      行首无 rowspan 的 = 上一门课程的延续行

    列结构：
      带课程信息行: [调课标记, 课程号, 课程名, 学分, 教师, 班级, 学时,
                     停日期, 停周, 停星期, 停节次, 停地点,
                     补日期, 补周, 补星期, 补节次, 补地点]
      延续行: [停日期, 停周, 停星期, 停节次, 停地点,
               补日期, 补周, 补星期, 补节次, 补地点]
    """
    tables = soup.find_all("table", class_="infolist_hr")
    if len(tables) < 2:
        return []

    adj_table = tables[1]
    rows = adj_table.find_all("tr")
    if len(rows) < 2:
        return []

    adjustments = []
    current_course = None

    for row in rows:
        cells = row.find_all("td")
        if not cells:
            continue

        first_cell = cells[0]
        is_header_row = bool(first_cell.get("rowspan"))

        if is_header_row and len(cells) >= 17:
            # 课程信息行
            name_text = cells[2].get_text(strip=True)
            current_course = name_text

            adj = {
                "course_name": current_course,
                "cancel": {
                    "date": cells[7].get_text(strip=True),
                    "week": parse_int(cells[8].get_text(strip=True)),
                    "day": gbk_weekday(cells[9].get_text(strip=True)),
                    "periods": parse_period_range(cells[10].get_text(strip=True)),
                    "location": cells[11].get_text(strip=True),
                },
                "makeup": {
                    "date": cells[12].get_text(strip=True),
                    "week": parse_int(cells[13].get_text(strip=True)),
                    "day": gbk_weekday(cells[14].get_text(strip=True)),
                    "periods": parse_period_range(cells[15].get_text(strip=True)),
                    "location": cells[16].get_text(strip=True),
                },
            }
            if adj["cancel"]["week"] is not None and adj["makeup"]["week"] is not None:
                adjustments.append(adj)

        elif not is_header_row and current_course and len(cells) >= 10:
            # 延续上一门课程的行
            adj = {
                "course_name": current_course,
                "cancel": {
                    "date": cells[0].get_text(strip=True),
                    "week": parse_int(cells[1].get_text(strip=True)),
                    "day": gbk_weekday(cells[2].get_text(strip=True)),
                    "periods": parse_period_range(cells[3].get_text(strip=True)),
                    "location": cells[4].get_text(strip=True),
                },
                "makeup": {
                    "date": cells[5].get_text(strip=True),
                    "week": parse_int(cells[6].get_text(strip=True)),
                    "day": gbk_weekday(cells[7].get_text(strip=True)),
                    "periods": parse_period_range(cells[8].get_text(strip=True)),
                    "location": cells[9].get_text(strip=True),
                },
            }
            if adj["cancel"]["week"] is not None and adj["makeup"]["week"] is not None:
                adjustments.append(adj)

    return adjustments


def parse_int(text):
    """解析数字"""
    text = text.strip()
    if not text:
        return None
    m = re.search(r"\d+", text)
    if m:
        return int(m.group(0))
    return None


def parse_period_range(text):
    """解析节次范围如 '1--2节', '5-6节' → (5, 6)"""
    text = text.strip()
    m = re.search(r"(\d+)\s*[-–—]+\s*(\d+)", text)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"(\d+)", text)
    if m:
        w = int(m.group(1))
        return w, w
    return None


def gbk_weekday(text):
    """解析 GBK 编码的星期文本"""
    text = text.strip()
    return GBK_WEEKDAY_MAP.get(text)


def apply_adjustments(courses, adjustments):
    """
    应用调课通知：
    1. 删除 停课 对应的课程周次（从现有的 course 中移除匹配周的条目）
    2. 添加 补课 对应的课程周次（可能在新时间新地点）

    注意：停课和补课的时段/地点可能不同（不仅是调教室，还可能是调时间）
    """
    for adj in adjustments:
        name = adj["course_name"]
        cancel = adj["cancel"]
        makeup = adj["makeup"]

        cancel_week = cancel["week"]
        cancel_day = cancel["day"]
        cancel_periods = cancel["periods"]
        cancel_location = cancel["location"]

        makeup_week = makeup["week"]
        makeup_day = makeup["day"]
        makeup_periods = makeup["periods"]
        makeup_location = makeup["location"]

        if cancel_week is None or makeup_week is None:
            continue
        if cancel_day is None or cancel_periods is None:
            continue
        if makeup_day is None or makeup_periods is None:
            continue

        cp_start, cp_end = cancel_periods
        mp_start, mp_end = makeup_periods

        # Step 1: 从现有课程中删除停课周次
        for c in courses:
            if (c["name"] == name and c["day_of_week"] == cancel_day and
                    c["start_period"] == cp_start and c["end_period"] == cp_end and
                    cancel_week in c.get("weeks", set())):
                c["weeks"].discard(cancel_week)

        # Step 2: 添加补课周次
        # 查找是否已有匹配的课程条目
        found = False
        for c in courses:
            if (c["name"] == name and c["day_of_week"] == makeup_day and
                    c["start_period"] == mp_start and c["end_period"] == mp_end and
                    c.get("location", "") == makeup_location):
                c["weeks"].add(makeup_week)
                found = True
                break

        if not found:
            # 查找同时间不同地点的已有课程（可能是原地址被覆盖）
            for c in courses:
                if (c["name"] == name and c["day_of_week"] == makeup_day and
                        c["start_period"] == mp_start and c["end_period"] == mp_end):
                    # 同一时间同一课程，不同地点 → 把补课地点作为这个周的覆盖
                    c["weeks"].add(makeup_week)
                    found = True
                    break

        if not found:
            # 创建新课程
            courses.append({
                "name": name,
                "day_of_week": makeup_day,
                "start_period": mp_start,
                "end_period": mp_end,
                "location": makeup_location,
                "teacher": "",
                "weeks": {makeup_week},
            })

    return courses


def rebuild_courses(courses):
    """从课程列表重建数据库课程表"""
    # 过滤掉空周次
    valid = [c for c in courses if c.get("weeks")]
    if not valid:
        print("警告：没有有效课程可导入")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    sem = cursor.execute("SELECT id FROM semester WHERE is_current = 1").fetchone()
    if not sem:
        sem = cursor.execute("SELECT id FROM semester ORDER BY id DESC LIMIT 1").fetchone()
    if not sem:
        print("错误：没有学期数据")
        conn.close()
        return
    sem_id = sem[0]

    # 删除旧的课程数据
    cursor.execute("DELETE FROM course WHERE semester_id = ? AND source != 'old_before_fix'", (sem_id,))
    cursor.execute("DELETE FROM course WHERE semester_id = ?", (sem_id,))
    old_count = cursor.rowcount
    print(f"已删除 {old_count} 条旧课程数据")

    # 导入新课程
    count = 0
    for c in valid:
        weeks = c["weeks"]
        start_week = min(weeks)
        end_week = max(weeks)
        week_type = classify_week_type(sorted(weeks))
        color = COURSE_COLORS[hash(c["name"]) % len(COURSE_COLORS)]

        cursor.execute("""
            INSERT INTO course (semester_id, name, teacher, location,
                day_of_week, start_period, end_period,
                start_week, end_week, week_type, color, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            sem_id, c["name"], c.get("teacher", ""),
            c.get("location", ""), c["day_of_week"],
            c["start_period"], c["end_period"],
            start_week, end_week, week_type, color, "fix_reimport",
        ))
        count += 1

    conn.commit()
    conn.close()
    print(f"已导入 {count} 门课程（旧数据已保留，标记为 old_before_fix）")


def print_courses(courses):
    """打印课程列表"""
    for c in sorted(courses, key=lambda x: (x["day_of_week"], x["start_period"])):
        weeks_str = ",".join(str(w) for w in sorted(c.get("weeks", set())))
        print(f'  周{c["day_of_week"]} 第{c["start_period"]}-{c["end_period"]}节  '
              f'{c["name"][:12]:12s}  {c.get("location",""):8s}  周次:{weeks_str}')


def main():
    print("=" * 60)
    print("修复课表数据")
    print("=" * 60)

    # 读取 HTML
    html = read_html()
    if not html:
        return

    soup = BeautifulSoup(html, "html.parser")

    # Step 1: 解析主课表（bottom-wins）
    print("\n[Step 1] 解析主课表...")
    courses = parse_timetable(soup)
    print(f"  解析到 {len(courses)} 个课程条目")

    # 先转换成带 weeks set 的格式
    course_list = []
    for c in courses:
        weeks = set(range(c["start_week"], c["end_week"] + 1))
        if c["week_type"] == "odd":
            weeks = {w for w in weeks if w % 2 == 1}
        elif c["week_type"] == "even":
            weeks = {w for w in weeks if w % 2 == 0}
        course_list.append({
            "name": c["name"],
            "day_of_week": c["day_of_week"],
            "start_period": c["start_period"],
            "end_period": c["end_period"],
            "location": c["location"],
            "teacher": c["teacher"],
            "weeks": weeks,
        })

    print("\n[Step 1 结果]")
    print_courses(course_list)

    # Step 2: 解析调课通知
    print("\n[Step 2] 解析调课通知...")
    adjustments = parse_adjustments(soup)
    print(f"  解析到 {len(adjustments)} 条调课通知")
    for adj in adjustments:
        c = adj["cancel"]
        m = adj["makeup"]
        print(f'  {adj["course_name"]}: 停(周{c["week"]} 周{c["day"]} 第{c["periods"][0]}-{c["periods"][1]}节 {c["location"]}) '
              f'→ 补(周{m["week"]} 周{m["day"]} 第{m["periods"][0]}-{m["periods"][1]}节 {m["location"]})')

    # Step 3: 应用调课通知
    print("\n[Step 3] 应用调课通知...")
    course_list = apply_adjustments(course_list, adjustments)

    print("\n[最终结果]")
    print_courses(course_list)
    total_weeks = sum(len(c["weeks"]) for c in course_list)
    print(f"\n课程数: {len(course_list)}, 总周次条目数: {total_weeks}")

    # Step 4: 写入数据库
    print("\n[Step 4] 写入数据库...")
    rebuild_courses(course_list)
    print("完成！")


if __name__ == "__main__":
    main()
