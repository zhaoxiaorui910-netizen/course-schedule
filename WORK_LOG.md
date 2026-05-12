# 工作日志

## 2026-05-08 — 课表 UI macOS Glassmorphism 改造 + 移动端适配

### 改动的文件
- `templates/index.html` — 全部 UI 改造，仅此一个文件

### 完成内容

**macOS Glassmorphism UI：**
- 渐变背景 + 全页白色噪点纹理（SVG feTurbulence）
- 顶栏/周导航/底部操作栏/弹窗 → 半透明白 + backdrop-filter blur（15-30px）
- 课程卡片圆角 6px、内发光、柔和阴影
- 主色改为 `#5B7FFF`，文字颜色改为 `#1d1d1f`
- 表单/上传区域/Toast 统一毛玻璃风格

**移动端适配：**
- 去除 `min-width: 800px`，表格自适应手机宽度
- 节次列缩窄到 28px（仅显示数字）
- 其余所有字号/行高/信息完整度保持桌面原样，内容窄了自然换行

**按天视图（预留未激活）：**
- `mobileRender`、`switchToDay`、`changeSelectedDay`、触摸滑动切换已实现
- CSS hidden，将来改一行代码即可启用

**其他：**
- 底部操作栏新增"添加课程"按钮
- 修改前备份到 `archive/20260508_1434_index.html`

### 重要决策
1. 移动端不做独立日视图/时间轴，直接缩窄原表格适配
2. 按天视图代码保留但隐藏，以备将来
3. 桌面移动端共用同一份代码，无同步问题

### 遗留
- CAS affair 登录问题未定位
- 按天视图启用时需改 CSS media query + render 函数

## 2026-05-08 (第二段) — 手机端开启 + 视觉微调

### 改动的文件
- `templates/index.html` — 仅此一个文件

### 完成内容

**手机端适配（启用）：**
- 激活手机端布局：≤599px 时隐藏桌面表格 `.desktop-layout`，显示 `.mobile-layout`（日视图/时间轴）
- `render()` 增加 `window.innerWidth` 判断，自动调用 `tableRender()` 或 `mobileRender()`
- ❌ 用户纠正：上次改的是直接缩窄周表格，不是日视图 → 已还原为直接缩窄表格方案

**视觉微调：**
- 背景底色变浅：`#f0f2f8→#e2e6ef` → `#f5f6fa→#ebedf3`
- 表格网状线淡化：单元格 border 透明度从 0.05 → 0.025，表头底边 0.06 → 0.03
- 课程色块改为 70% 透明度（新增 `hexToRgba()` 辅助函数）
- 角标改为气泡质感：半透明白底 + backdrop-filter blur + 细亮边 + 小阴影 → 再调淡边框和阴影 → 椭圆形状 16×18px
- 课程卡片文字居中（`justify-content: center; text-align: center`），避免角标遮挡内容
- 手机端节次列宽度 28px → 42px
- 手机端时间文字字号 6px → 10px，允许换行

### 备份
- `archive/20260508_？_index.html`（当前版本备份）

### 遗留
- CAS affair 登录问题未定位

## 2026-05-08 (第三段) — 白灰配色 + 角标玻璃质感 + 课程卡片毛玻璃

### 完成内容

**配色调整：**
- 主色 `--primary`: `#5B7FFF` → `#636366`（深灰）→ `#e8e8e8`（白灰）
- 今天/导入课表等按钮：黑底白字（`#1d1d1f` / `#fff`）
- 表头今天列文字改为普通深色，不再用主色
- 表单聚焦、上传区悬浮、spinner 改为中灰色

**角标（slot-badge）增强：**
- 缩小到 14px 高（≈"周一"文字大小）
- 135° 白色渐变模拟玻璃反光 + 6px blur + 亮边 + inset 高光

**课程卡片玻璃反光：**
- `::before` 伪元素叠加底部上泛的白色渐变反光层
- backdrop-filter blur 2px → 4px
- 边框更细更亮，inset 高光加强
- 卡片圆角 6px → 10px

**配色饱和度调整：**
- `hexToRgba` → `mutedColor`：向灰色靠拢 25% 降饱和度
- 透明度 0.7 → 0.65

**背景网格淡化：**
- 表格边框透明度 0.025 → 0.008

**模态框动画：**
- 改为 CSS transition（opacity + transform），开合均有平滑过渡
- 关闭时不再瞬间消失

**左右滑动手势：**
- 检测 touchstart/touchend 水平滑动切换周数
- 右滑上一周、左滑下一周，>50px 触发

**表格布局改为 CSS Grid（冻结首行首列）：**
- 从 HTML `<table>` 改为 CSS Grid 布局
- `.period-col` 固定左侧节次列（sticky left）
- `.schedule-header` 固定顶部日期表头（sticky top）
- `.slide-track` 课程网格整体滑动（左右切换周时仅该区域动画）
- rowspan 用 `grid-row: span N` 替代
- 空单元格占位保持网格完整

**文字可读性：**
- 课程卡片文字加 `text-shadow: 0 1px 3px rgba(0,0,0,0.25)`

### 备份
- `archive/20260508_1935_index.html`（改 CSS Grid 前备份）
- `archive/20260508_2000_index.html`（最新版）

### 遗留
- CAS affair 登录问题未定位
- 按天视图启用时需改 CSS media query + render 函数
