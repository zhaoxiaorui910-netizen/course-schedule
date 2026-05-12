from pydantic import BaseModel
from typing import Optional


class SemesterCreate(BaseModel):
    name: str
    start_date: str  # YYYY-MM-DD
    end_date: str    # YYYY-MM-DD
    weeks: int = 20
    is_current: bool = False


class SemesterUpdate(BaseModel):
    name: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    weeks: Optional[int] = None
    is_current: Optional[bool] = None


class SemesterOut(BaseModel):
    id: int
    name: str
    start_date: str
    end_date: str
    weeks: int
    is_current: bool


class CourseCreate(BaseModel):
    semester_id: int
    name: str
    teacher: str = ""
    location: str = ""
    day_of_week: int       # 1=周一 … 7=周日
    start_period: int      # 开始节次 1-11
    end_period: int        # 结束节次
    start_week: int = 1
    end_week: int = 20
    week_type: str = ""    # ''=每周, 'odd'=单周, 'even'=双周


class CourseUpdate(BaseModel):
    name: Optional[str] = None
    teacher: Optional[str] = None
    location: Optional[str] = None
    day_of_week: Optional[int] = None
    start_period: Optional[int] = None
    end_period: Optional[int] = None
    start_week: Optional[int] = None
    end_week: Optional[int] = None
    week_type: Optional[str] = None


class CourseOut(BaseModel):
    id: int
    semester_id: int
    name: str
    teacher: str
    location: str
    day_of_week: int
    start_period: int
    end_period: int
    start_week: int
    end_week: int
    week_type: str
    color: str
    source: str


class SlotCourse(BaseModel):
    """时段内单门课程"""
    id: int
    name: str
    teacher: str
    location: str
    week_type: str
    week_info: str
    color: str
    active: bool            # 本周是否有课


class ScheduleSlot(BaseModel):
    """同一时段的一组课程"""
    start_period: int
    end_period: int
    courses: list[SlotCourse]
    total: int              # 该时段课程总数


class ScheduleDay(BaseModel):
    """某一天的时段列表"""
    day: int                # 1-7
    slots: list[ScheduleSlot]


class ScheduleOut(BaseModel):
    semester_name: str
    current_week: int
    total_weeks: int
    week_start: str         # 周一的日期
    week_end: str           # 周日的日期
    periods: list
    weekdays: list
    days: list[ScheduleDay]


class LoginRequest(BaseModel):
    username: str = ""
    password: str = ""
    sms_code: Optional[str] = None
    session_token: Optional[str] = None


class ImportJsonRequest(BaseModel):
    courses: list[dict]


class ImportHtmlPasteRequest(BaseModel):
    html: str


class SettingsOut(BaseModel):
    campus: str = "通用"


class SettingsUpdate(BaseModel):
    campus: Optional[str] = None
