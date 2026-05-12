# 变更记录

## 2026-05-08 16:05 — [database.py]
- 问题：测试导入功能时覆盖了正式数据库，用户课表数据被清空
- 原因：`import_courses()` 会先清再写，测试时直接操作了正式 `schedule.db`
- 修正：`database.py` 的 `DB_PATH` 增加环境变量判断——`COURSE_SCHEDULE_TEST=1` 时读写 `test.db`，否则读写 `schedule.db`
- 下次怎么做：涉及数据库 CRUD 的改动，先用 `COURSE_SCHEDULE_TEST=1` 启动测试版测试，确认无误后再切回正式版

## 2026-05-08 15:40 — [database.py / main.py / templates/index.html]
- 问题：新增「从网页源代码粘贴导入」功能时，测试导入数据覆盖了用户已有的全部课表数据
- 原因：`import_courses()` 会先清除 source='scraper' 的所有课程再写入。测试时直接调用了该函数，导致用户真实课程被删除
- 修正：从 `archive/20260501_0042_学生课表.html` 重新导入原始课表数据（31 门课程）
- 下次怎么做：
  1. 改源代码前，先按 CLAUDE.md 规则备份到 archive/
  2. 涉及 `import_courses()` 的测试，用测试数据库或临时 semester，不要操作当前学期
  3. 测试完后检查数据库状态，确认数据完整

## 2026-05-08 14:34 — [templates/index.html]
- macOS Glassmorphism UI 改造（渐变背景、噪点纹理、毛玻璃效果）
- 移动端适配：去除 min-width 约束，表格自适应手机宽度
- 按天视图功能实现但隐藏（预留）
- 底部操作栏新增"添加课程"按钮
- 备份：`archive/20260508_1434_index.html`
- 决策记录：移动端不做独立日视图，直接缩窄原表格

## 2026-05-08 19:30 — [templates/index.html]
- 问题：角标气泡偏大（18px 高），比"周一"文字大一圈
- 原因：`.slot-badge` 固定 height: 18px，移动端表头文字仅 11px
- 修正：桌面端 14px 高 8px 字，移动端 12px 高 7px 字
- 备份：`archive/20260508_1930_index.html`

## 2026-05-08 20:00 — [templates/index.html] 白灰配色 + 玻璃质感 + CSS Grid 布局改造
### 配色
- 主色从 `#5B7FFF`（蓝）→ `#636366`（深灰）→ `#e8e8e8`（白灰）
- 今天/导入课表按钮改为黑底白字
- 课程色块 `mutedColor()` 向灰色靠拢 25% 降饱和度

### 角标 & 卡片玻璃质感
- 角标缩小到 14px + 135° 白色渐变 + 6px blur 模拟玻璃反光
- 课程卡片 `::before` 叠加底部白色泛光层
- 卡片圆角 6px → 10px，backdrop-filter 2px → 4px
- 课程文字加 `text-shadow` 提升可读性

### 模态框 & 手势
- 开合均使用 CSS transition 平滑过渡（关闭不再瞬间消失）
- 新增左右滑动手势切换周数（>50px 触发）

### CSS Grid 布局重建（冻结首行首列）
- 从 `<table>` 改为 CSS Grid 布局
- 节次列固定左侧（sticky left）、日期表头固定顶部（sticky top）
- 课程网格整体滑动，边栏不动
- rowspan 用 `grid-row: span N` 替代

### 备份
- `archive/20260508_1935_index.html`（Grid 改造前）
- `archive/20260508_2000_index.html`（当前最新）

## 2026-05-12 — [export_standalone.py / templates/index.html / main.py]
- 问题：独立 HTML 课表文件（课表.html）初始显示导出时的固定周次，不随实际时间更新；"今天"按钮和移动端日高亮可能因设备时区偏差显示错误日期
- 原因：`init()` 使用导出时写入的 `EMBEDDED_CURRENT_WEEK` 硬编码值；`new Date()` 基于设备本地时区而非北京时间
- 修正：
  - `export_standalone.py`：生成 JS 中新增 `getBeijingDate()`（使用 `timeZone: 'Asia/Shanghai'`）和 `calcBeijingCurrentWeek()`，`init()`/`goToToday()`/`getTodayDayOfWeek()` 改为基于北京时间的动态计算
  - `templates/index.html`：`getTodayDayOfWeek()` 同样改为北京时间
  - `main.py`：`calc_current_week()` 的 `date.today()` 替换为 UTC+8 偏移
- 备份：`archive/20260512_export_standalone.py`、`archive/20260512_index.html`、`archive/20260512_main.py`、`archive/20260512_课表.html`
