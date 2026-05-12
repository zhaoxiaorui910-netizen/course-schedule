"""
内蒙古工业大学 URPL 教务系统课表爬虫

登录流程 (Selenium 浏览器自动化)：
1. Selenium 启动 Chrome → 导航到 CAS 登录页
2. 填充 username/password → 模拟点击登录按钮
3. CAS 可能要求 MFA（手机验证码）
4. 如果不需要 MFA：等待重定向到 jw.imut.edu.cn → 完成
5. 如果需要 MFA：保持浏览器开启 → 返回 session_token → 前端请用户输入验证码 → 填入验证码继续

课表页面 HTML 格式（清华 URPL 系统）：
  <table id="timetable">
    <th>周一</th>...<th>周日</th>
    <tr>
      <th>第1节<br>08:20<br>┆<br>09:05</th>
      <td id="1-1">&lt;&lt;课程名&gt;&gt;;学分<br/>地点<br/>教师<br/>周数<br/>类型</td>
    </tr>

URL 结构：
  http://jw.imut.edu.cn/academic/manager/coursearrange/showTimetable.do
    ?id=学生ID&yearid=学年ID&termid=学期ID&timetableType=STUDENT&sectionType=BASE
"""

import os
import re
import time
import uuid
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

# ---- 配置 ----
CAS_BASE = "https://authserver.imut.edu.cn/cas"
CAS_LOGIN_URL = f"{CAS_BASE}/login?service=http%3A%2F%2Fjw.imut.edu.cn%2Facademic%2F"
JW_BASE_URL = "http://jw.imut.edu.cn"
SCHEDULE_URL = ""  # 登录成功后设置

_client: httpx.Client | None = None


# Module-level sentinel — this runs when scraper.py is imported
_sentinel_file = os.path.join(os.path.dirname(__file__), "debug_login", "MODULE_LOADED.txt")
os.makedirs(os.path.dirname(_sentinel_file), exist_ok=True)
with open(_sentinel_file, "w") as _f:
    _f.write("module loaded\n")


def _debug_write(msg: str):
    """写入调试日志（不依赖 Selenium）"""
    import os
    debug_dir = os.path.join(os.path.dirname(__file__), "debug_login")
    os.makedirs(debug_dir, exist_ok=True)
    with open(os.path.join(debug_dir, "debug_log.txt"), "a", encoding="utf-8") as f:
        import datetime
        f.write(f"[{datetime.datetime.now().isoformat()}] {msg}\n")


def _debug_save_screenshot(driver):
    """登录失败时保存截图和页面源码用于调试"""
    import os, uuid
    debug_dir = os.path.join(os.path.dirname(__file__), "debug_login")
    os.makedirs(debug_dir, exist_ok=True)
    tag = uuid.uuid4().hex[:8]
    try:
        driver.save_screenshot(os.path.join(debug_dir, f"login_{tag}.png"))
    except Exception:
        pass
    try:
        with open(os.path.join(debug_dir, f"login_{tag}.html"), "w", encoding="utf-8") as f:
            f.write(driver.page_source)
    except Exception:
        pass


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(
            follow_redirects=True,
            timeout=30.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/120.0.0.0 Safari/537.36",
            },
        )
    return _client


def close():
    global _client
    if _client:
        _client.close()
        _client = None


def _extract_cas_error(driver) -> str:
    """从 CAS 页面提取错误信息"""
    from selenium.webdriver.common.by import By
    # 精确的错误选择器
    for sel in [".error", ".alert-error", ".msg-error",
                "#error", ".alert-danger", ".alert",
                ".login-error", "#loginError1", "#loginError2"]:
        try:
            el = driver.find_element(By.CSS_SELECTOR, sel)
            t = el.text.strip()
            if t:
                return t
        except Exception:
            continue
    return ""


def _detect_captcha(driver) -> bool:
    """检测 CAS 页面是否出现图片验证码"""
    from selenium.webdriver.common.by import By
    try:
        captcha_dialog = driver.find_element(By.CSS_SELECTOR, ".captcha-dialog-wrapper")
        if captcha_dialog.is_displayed():
            return True
    except Exception:
        pass
    try:
        captcha_img = driver.find_element(By.CSS_SELECTOR, "#captcha")
        if captcha_img.is_displayed():
            return True
    except Exception:
        pass
    return False


# ---- MFA 登录会话管理 ----
_login_sessions: dict[str, dict] = {}
_SESSION_TTL = 120  # 会话有效期 2 分钟


def _cleanup_sessions():
    """清理超时的登录会话"""
    now = time.time()
    expired = [k for k, v in _login_sessions.items() if now - v["created_at"] > _SESSION_TTL]
    for k in expired:
        try:
            _login_sessions[k]["driver"].quit()
        except Exception:
            pass
        del _login_sessions[k]


def get_mfa_session(session_token: str) -> dict | None:
    """获取 MFA 登录会话"""
    _cleanup_sessions()
    return _login_sessions.get(session_token)


def release_mfa_session(session_token: str):
    """释放 MFA 登录会话"""
    session = _login_sessions.pop(session_token, None)
    if session:
        try:
            session["driver"].quit()
        except Exception:
            pass


def _detect_mfa(driver) -> bool:
    """
    检测 CAS 页面是否出现了 MFA 验证（手机验证码）
    """
    from selenium.webdriver.common.by import By
    try:
        indicators = [
            (By.CSS_SELECTOR, "#smsCodeLogin"),
            (By.CSS_SELECTOR, "#fm2"),
            (By.CSS_SELECTOR, 'input[name="smsCode"]'),
            (By.CSS_SELECTOR, 'input[autocomplete="sms-code"]'),
            (By.CSS_SELECTOR, ".dialog-wrap[style*='display: block']"),
            (By.CSS_SELECTOR, ".dialog-wrap[style*='display: block']"),
            (By.XPATH, "//*[contains(text(), '手机动态密码') or contains(text(), '验证码')]"),
            (By.XPATH, "//*[contains(text(), '多因子认证') or contains(text(), '安全验证')]"),
        ]
        for by, selector in indicators:
            els = driver.find_elements(by, selector)
            for el in els:
                if el.is_displayed():
                    return True
    except Exception:
        pass
    return False


def _create_driver(headless=True):
    """创建并返回 Selenium WebDriver"""
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from webdriver_manager.chrome import ChromeDriverManager

    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920x1080")
    options.add_experimental_option("detach", True)  # 非 headless 时保持浏览器打开

    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        driver.set_page_load_timeout(60)
        return driver
    except Exception as e:
        raise RuntimeError(f"浏览器启动失败: {e}")


def _fill_and_submit_cas(driver, username: str, password: str):
    """在 CAS 登录页填充用户名密码并提交

    绕过 Vue 前端，直接用 JSEncrypt 加密密码后提交隐藏表单 #fm1，
    避免 Vue 事件绑定/异步公钥加载的时序问题。
    """
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.by import By

    driver.get(CAS_LOGIN_URL)

    # 等待 Vue 表单渲染完成
    WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "form.el-form.login-form"))
    )

    # 等待 JSEncrypt 异步加载 RSA 公钥
    WebDriverWait(driver, 20).until(
        lambda d: d.execute_script(
            "return typeof encrypt !== 'undefined' "
            "&& typeof encrypt.getPublicKey === 'function' "
            "&& encrypt.getPublicKey() !== false;"
        )
    )

    # 先调 MFA detect AJAX 拿到 mfaState，再提交表单
    # CAS 要求用户设置了手机验证码时必须先通过 /cas/mfa/detect 获取 mfaState
    result = driver.execute_script("""
        try {
            var fm = document.getElementById('fm1');
            if (!fm) return JSON.stringify({ok: false, error: '#fm1 not found'});

            var username = arguments[0];
            var password = arguments[1];

            // 设置用户名到隐藏表单
            document.getElementById('username').value = username;

            // 加密密码（和 /cas/mfa/detect 需要用同样的加密）
            var encrypted = encrypt.encrypt(password);
            if (!encrypted || encrypted === false) {
                return JSON.stringify({ok: false, error: 'encrypt failed'});
            }
            var encodedPassword = '__RSA__' + encrypted;

            // 设置密码到隐藏表单
            document.getElementById('password').value = encodedPassword;

            // 获取 fpVisitorId
            var fpVisitorId = document.querySelector('[name="fpVisitorId"]').value || '';

            // 发起同步 AJAX 调用 /cas/mfa/detect
            var xhr = new XMLHttpRequest();
            xhr.open('POST', '/cas/mfa/detect', false);  // false = synchronous
            xhr.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded');
            xhr.send('username=' + encodeURIComponent(username)
                + '&password=' + encodeURIComponent(encodedPassword)
                + '&fpVisitorId=' + encodeURIComponent(fpVisitorId));

            if (xhr.status !== 200) {
                return JSON.stringify({ok: false, error: 'mfa detect HTTP ' + xhr.status});
            }

            var resp = JSON.parse(xhr.responseText);
            var rawResp = JSON.stringify(resp);
            if (resp.code !== 0) {
                return JSON.stringify({ok: false, error: 'mfa detect failed', code: resp.code, raw: rawResp});
            }

            var mfaState = resp.data.state;
            var needMfa = resp.data.need !== undefined ? resp.data.need : resp.data.needMfa;

            // 设置 mfaState 到表单
            fm.querySelector('[name="mfaState"]').value = mfaState;

            // 如果用户配置了 MFA，走短信验证流程
            // 不在这里提交表单，让 Python 侧根据返回结果决定走 MFA 还是直接提交
            return JSON.stringify({ok: true, needMfa: needMfa, mfaState: mfaState, raw: rawResp, username: username, encodedPassword: encodedPassword});
        } catch(e) { return JSON.stringify({ok: false, error: e.message}); }
    """, username, password)

    import json
    try:
        info = json.loads(result)
        _debug_write(f"_fill_and_submit_cas: {json.dumps(info)}")
    except Exception:
        _debug_write(f"_fill_and_submit_cas: raw={result}")
    return result


def _is_at_jw(url: str) -> bool:
    """判断是否真正到达了 jw.imut.edu.cn（不是 CAS 服务参数中的引用）"""
    return url.startswith("http://jw.imut.edu.cn") or url.startswith("https://jw.imut.edu.cn")


def _handle_affair_login(driver, username: str, password: str) -> tuple[str, str]:
    """
    处理 URPL 的二次登录（affairLogin.jsp）。
    用 ddddocr 识别图片验证码（从 canvas 截取而非 HTTP fetch），自动提交，最多重试 3 次。
    返回 (status, message)，status 为 "ok" / "error"
    """
    _debug_write("_handle_affair_login: start")
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    import os, uuid, base64, time
    debug_dir = os.path.join(os.path.dirname(__file__), "debug_login")
    os.makedirs(debug_dir, exist_ok=True)

    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.NAME, "j_username"))
        )
    except Exception:
        _debug_write("_handle_affair_login: not on affair page")
        return "ok", "已登录"

    for attempt in range(3):
        _debug_write(f"_handle_affair_login: attempt {attempt + 1}")

        # 每次重试重新初始化 OCR，避免 ddddocr 状态残留
        import ddddocr
        ocr = ddddocr.DdddOcr()

        # 每次重试都要重新填用户名密码（提交失败后页面刷新，字段被清空）
        try:
            driver.execute_script("""
                document.querySelector('input[name="j_username"]').value = arguments[0];
                document.querySelector('input[name="j_password"]').value = arguments[1];
            """, username, password)
        except Exception as e:
            _debug_write(f"_handle_affair_login: fill username/password via JS failed: {e}")
            continue

        # 截取验证码图片 — 用 canvas 读取页面上已显示的图片，不触发新 HTTP 请求
        tag = uuid.uuid4().hex[:8]
        try:
            img_b64 = driver.execute_script("""
                var img = document.getElementById('jcaptcha');
                if (!img) return '';
                var c = document.createElement('canvas');
                c.width = img.naturalWidth || img.width || 80;
                c.height = img.naturalHeight || img.height || 50;
                var ctx = c.getContext('2d');
                ctx.drawImage(img, 0, 0);
                return c.toDataURL('image/png');
            """)
            if not img_b64 or ',' not in img_b64:
                _debug_write("_handle_affair_login: canvas captcha empty, refreshing")
                driver.execute_script("document.getElementById('jcaptcha').click();")
                time.sleep(1)
                continue
            b64_data = img_b64.split(',', 1)[1]
            _debug_write(f"_handle_affair_login: captcha b64 len={len(b64_data)}")
            img_data = base64.b64decode(b64_data)
            with open(os.path.join(debug_dir, f"captcha_{tag}.png"), "wb") as f:
                f.write(img_data)
        except Exception as e:
            _debug_write(f"_handle_affair_login: captcha capture failed: {e}")
            continue

        # OCR 识别
        try:
            code = ocr.classification(img_data)
            _debug_write(f"_handle_affair_login: ocr='{code}'")
        except Exception as e:
            _debug_write(f"_handle_affair_login: ocr failed: {e}")
            continue

        if not code or len(code.strip()) < 1:
            driver.execute_script("document.getElementById('jcaptcha').click();")
            time.sleep(1)
            continue
        code = code.strip()

        # 填验证码
        try:
            driver.execute_script("""
                document.querySelector('input[name="j_captcha"]').value = arguments[0];
            """, code)
        except Exception as e:
            _debug_write(f"_handle_affair_login: fill captcha via JS failed: {e}")
            continue

        # 诊断：模拟 check() 构造的 URL，验证字段值是否正确
        diag_url = driver.execute_script("""
            var u = $(":text[name='j_username']").val();
            var c = $(":text[name='j_captcha']").val();
            var pd = document.form1.j_password.value;
            var newpd = trans();
            return JSON.stringify({
                username_from_jq: u,
                username_from_dom: document.form1.j_username.value,
                password_len: pd ? pd.length : 0,
                trans_len: newpd ? newpd.length : 0,
                trans_prefix: (newpd || '').substring(0,16),
                captcha: c
            });
        """)
        _debug_write(f"_handle_affair_login: diag before submit={diag_url}")

        # 模拟正常用户操作：点击登录按钮，走 submitForm → validCaptcha → AJAX → check
        _debug_write("_handle_affair_login: clicking submit button")
        try:
            btn = driver.find_element(By.CSS_SELECTOR, 'input[name="button1"]')
            btn.click()
        except Exception as e:
            _debug_write(f"_handle_affair_login: button click failed, fallback to check(): {e}")
            driver.execute_script("check();")

        # 等待导航稳定
        time.sleep(3)
        try:
            url_after = driver.current_url
        except Exception:
            url_after = ""
        _debug_write(f"_handle_affair_login: after submit URL={url_after}")

        # 空 URL = 浏览器异常状态，不是成功
        if url_after and "affairLogin" not in url_after:
            _debug_write("_handle_affair_login: redirect OK")
            return "ok", "已提交"
        else:
            _debug_write("_handle_affair_login: login rejected, still on affair page")
            # 检查服务器返回的错误信息
            try:
                error_text = driver.execute_script("""
                    var el = document.getElementById('message');
                    return el ? el.textContent.trim() : '';
                """)
                if error_text:
                    _debug_write(f"_handle_affair_login: page error='{error_text}'")
            except Exception:
                pass
            try:
                driver.execute_script("document.getElementById('jcaptcha').click();")
            except Exception:
                pass
            time.sleep(1)
            continue

    return "error", "验证码识别失败，请通过 HTML 文件导入课表"


def _complete_login(driver, username="", password="") -> tuple[str, str]:
    """
    登录成功后的公共流程：检查登录状态、注入 cookies、获取课表 URL
    返回 (status, message)，status 为 "ok" / "error" / "mfa" / "captcha"
    """
    global SCHEDULE_URL
    from selenium.common.exceptions import TimeoutException
    from selenium.webdriver.support.ui import WebDriverWait

    _debug_write("_complete_login: start")
    try:
        WebDriverWait(driver, 25).until(
            lambda d: _is_at_jw(d.current_url)
        )
        _debug_write("_complete_login: at jw, sleeping")
    except TimeoutException:
        current_url = driver.current_url
        _debug_write(f"_complete_login: timeout URL={current_url}")
        if "login" in current_url.lower():
            error_text = _extract_cas_error(driver)
            driver.quit()
            return "error", error_text or "学号或密码错误"
        driver.quit()
        return "error", "登录超时，请重试"

    time.sleep(2)

    # 重新验证 URL — jw 可能在 ticket 验证后将页面重定向回 CAS
    if not _is_at_jw(driver.current_url):
        _debug_write(f"_complete_login: redirected away from jw, now at {driver.current_url}")
        if driver.current_url.startswith(CAS_BASE) and _detect_mfa(driver):
            _debug_write("_complete_login: MFA detected")
            return "mfa", "需要短信验证"
        _debug_write("_complete_login: no MFA, returning error")
        error_text = _extract_cas_error(driver)
        driver.quit()
        return "error", error_text or "登录已过期，请重试"

    _debug_write(f"_complete_login: still at jw, URL={driver.current_url}")

    # 如果是 affair 登录页，处理二次登录
    if "affairLogin" in driver.current_url:
        _debug_write("_complete_login: affair login page detected")
        status, msg = _handle_affair_login(driver, username, password)
        if status != "ok":
            return status, msg
        # 等待 affair 登录完成
        try:
            WebDriverWait(driver, 15).until(
                lambda d: "affairLogin" not in d.current_url
            )
            _debug_write(f"_complete_login: after affair login, URL={driver.current_url}")
        except Exception:
            _debug_write(f"_complete_login: affair login timeout, URL={driver.current_url}")
            error_text = _extract_cas_error(driver)
            driver.quit()
            return "error", error_text or "教务系统登录失败，请重试"
    else:
        # 直接到了门户，不需要二次登录
        _debug_write("_complete_login: at portal, no affair login needed")

    page_text = driver.page_source
    _debug_save_screenshot(driver)

    if not _is_at_jw(driver.current_url):
        _debug_write("_complete_login: lost jw after page_source")
        driver.quit()
        return "error", "登录已过期，请重试"

    if re.search(r"登录|login|error", page_text[:2000], re.I):
        error_text = _extract_cas_error(driver)
        if error_text:
            driver.quit()
            return "error", error_text

    _inject_cookies_to_httpx(driver)
    _resolve_schedule_url(page_text)
    driver.quit()
    return "ok", "登录成功"


# ---- 公开 API ----


def login_step1(username: str, password: str) -> dict:
    """
    登录第一步：提交用户名密码到 CAS。

    返回:
      {"status": "ok", "message": "登录成功"}            — 无需 MFA，直接登录成功
      {"status": "mfa", "session_token": "xxx"}         — 需要 MFA，等待短信验证码
      {"status": "error", "message": "原因"}             — 登录失败
    """
    _cleanup_sessions()

    _debug_write("login_step1: start")

    try:
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.common.by import By
        driver = _create_driver(headless=False)  # 调试模式：可见浏览器
    except RuntimeError as e:
        return {"status": "error", "message": str(e)}

    try:
        submit_result = _fill_and_submit_cas(driver, username, password)
        # 解析 _fill_and_submit_cas 的返回结果
        import json as _json
        try:
            submit_info = _json.loads(submit_result)
        except Exception:
            submit_info = {"ok": False, "error": submit_result}
        _debug_write(f"login_step1: submit_info={submit_info}")

        if not submit_info.get("ok"):
            driver.quit()
            return {"status": "error", "message": submit_info.get("error", "提交失败")}

        # ---- 检查 MFA 弹窗是否可用 ----
        # 无论 needMfa 是 true/false，只要 mfaState 存在，就尝试触发 MFA 弹窗
        has_mfa_state = bool(submit_info.get("mfaState"))
        mfa_dialog_shown = False

        if has_mfa_state:
            _debug_write("login_step1: mfaState present, attempting MFA dialog")
            try:
                driver.execute_script("$('#showGuardDialog').click();")
                time.sleep(1.5)
                # 检查弹窗是否真的出现了
                mfa_dialog_shown = driver.execute_script("""
                    return document.querySelector('#showGuardDialog')
                        || document.querySelector('#smsCodeLogin')
                        || document.querySelector('#fm2');
                """) is not None
                _debug_write(f"login_step1: MFA dialog shown={mfa_dialog_shown}")
            except Exception as e:
                _debug_write(f"login_step1: MFA dialog trigger failed: {e}")

        if mfa_dialog_shown:
            # MFA 弹窗已出现 → 走短信验证流程
            _debug_write("login_step1: entering MFA flow")
            session_token = uuid.uuid4().hex
            _login_sessions[session_token] = {
                "driver": driver,
                "created_at": time.time(),
                "username": submit_info.get("username", ""),
                "password": password,
                "encoded_password": submit_info.get("encodedPassword", ""),
            }
            return {"status": "mfa", "session_token": session_token}

        # ---- 没有 MFA，直接提交表单 ----
        _debug_write("login_step1: no MFA, submitting CAS form")
        try:
            # 用 Selenium 点击提交按钮（比 fm.submit() 更接近真实操作）
            submit_btn = driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]')
            submit_btn.click()
        except Exception:
            # 兜底：直接用 JS 提交
            driver.execute_script("document.getElementById('fm1').submit();")

        # 等待重定向到 jw.imut.edu.cn
        mfa_detected = False
        try:
            WebDriverWait(driver, 30).until(lambda d:
                _is_at_jw(d.current_url)
                or _detect_mfa(d)
            )
            mfa_detected = _detect_mfa(driver)
            _debug_write(f"login_step1: wait succeed, at_jw={_is_at_jw(driver.current_url)}, mfa={mfa_detected}, URL={driver.current_url}")
        except Exception:
            _debug_write(f"login_step1: wait timeout, URL={driver.current_url}")
            pass

        if _is_at_jw(driver.current_url) and not mfa_detected:
            _debug_write("login_step1: -> _complete_login")
            status, msg = _complete_login(driver, username, password)
            if status == "ok":
                return {"status": "ok", "message": msg}
            elif status == "mfa":
                session_token = uuid.uuid4().hex
                _login_sessions[session_token] = {
                    "driver": driver,
                    "created_at": time.time(),
                    "username": username,
                    "password": password,
                    "encoded_password": submit_info.get("encodedPassword", ""),
                }
                return {"status": "mfa", "session_token": session_token}
            return {"status": "error", "message": msg}

        # 仍然在 CAS 页面，检查是否是 MFA
        if driver.current_url.startswith(CAS_BASE):
            _debug_write("login_step1: still at CAS, checking MFA")
            time.sleep(2)
            if _detect_mfa(driver):
                _debug_write("login_step1: MFA detected after submit")
                session_token = uuid.uuid4().hex
                _login_sessions[session_token] = {
                    "driver": driver,
                    "created_at": time.time(),
                    "username": username,
                    "password": password,
                    "encoded_password": submit_info.get("encodedPassword", ""),
                }
                return {"status": "mfa", "session_token": session_token}

            _debug_write("login_step1: no MFA, checking error/captcha")
            _debug_save_screenshot(driver)
            error_text = _extract_cas_error(driver)
            _debug_write(f"login_step1: error_text='{error_text}'")
            if error_text:
                driver.quit()
                return {"status": "error", "message": error_text}
            if _detect_captcha(driver):
                _debug_write("login_step1: captcha detected")
                driver.quit()
                return {"status": "error", "message": "需要图片验证码，请在校园网环境下重试或使用 HTML 文件导入"}
            driver.quit()
            return {"status": "error", "message": "学号或密码错误"}

        # 其他 URL
        _debug_write(f"login_step1: unexpected URL={driver.current_url}")
        driver.quit()
        return {"status": "error", "message": "登录超时，请重试"}

    except Exception as e:
        _debug_write(f"login_step1: exception={e}")
        try:
            driver.quit()
        except Exception:
            pass
        return {"status": "error", "message": f"登录失败: {e}"}


def login_step2(session_token: str, sms_code: str) -> dict:
    """
    登录第二步：提交短信验证码完成 MFA。

    自动区分 CAS MFA（手机动态密码）和 affair 二次登录（短信验证码）。
    返回:
      {"status": "ok", "message": "登录成功"}
      {"status": "error", "message": "原因"}
    """
    session = get_mfa_session(session_token)
    if not session:
        return {"status": "error", "message": "会话已过期，请重新登录"}

    driver = session["driver"]
    screenshot_dir = os.path.join(os.path.dirname(__file__), "debug_login")

    try:
        from selenium.webdriver.common.by import By
        current_url = driver.current_url

        # ---- 判断是 affair 二次登录还是 CAS MFA ----
        if "affairLogin" in current_url:
            _debug_write("login_step2: affair login SMS mode")
            # affair 页面：找 j_captcha 输入框填入短信验证码并提交
            code_input = None
            for sel in [
                'input[name="j_captcha"]',
                'input[id="j_captcha"]',
                'input[placeholder*="验证码"]',
                'input[name="captcha"]',
            ]:
                try:
                    el = driver.find_element(By.CSS_SELECTOR, sel)
                    if el.is_displayed():
                        code_input = el
                        break
                except Exception:
                    continue

            if not code_input:
                all_inputs = driver.find_elements(By.CSS_SELECTOR, "input:not([type='hidden']):not([name='j_username']):not([name='j_password'])")
                for inp in all_inputs:
                    if inp.is_displayed():
                        code_input = inp
                        break

            if not code_input:
                _debug_save_screenshot(driver)
                release_mfa_session(session_token)
                return {"status": "error", "message": "未找到验证码输入框"}

            code_input.clear()
            code_input.send_keys(sms_code)
            time.sleep(0.5)

            # 提交 affair 表单
            submit_btn = None
            for sel in [
                'input[type="submit"]',
                'button[type="submit"]',
                'input[value*="登录"]',
                'button:contains("登录")',
            ]:
                try:
                    btns = driver.find_elements(By.CSS_SELECTOR, sel)
                    for b in btns:
                        if b.is_displayed():
                            submit_btn = b
                            break
                    if submit_btn:
                        break
                except Exception:
                    continue

            if submit_btn:
                submit_btn.click()
            else:
                # 兜底：通过 trans() 函数直接构造 URL 提交
                _debug_write("login_step2: submitting affair form via JS")
                driver.execute_script("""
                    try {
                        var newpd = trans();
                        var link = '/academic/j_acegi_security_check?j_username='
                            + encodeURIComponent(document.form1.j_username.value)
                            + '&j_password=' + encodeURIComponent(newpd)
                            + '&j_captcha=' + encodeURIComponent(document.form1.j_captcha.value)
                            + '&randomTag=' + encodeURIComponent(document.form1.randomTag.value);
                        location.href = link;
                    } catch(e) { return e.message; }
                """)

            time.sleep(3)
            _debug_save_screenshot(driver)

            # 完成登录（cookie 注入、课表 URL 解析）
            _saved_username = session.get("username", "")
            _saved_password = session.get("password", "")
            status, msg = _complete_login(driver, _saved_username, _saved_password)
            release_mfa_session(session_token)
            if status == "ok":
                return {"status": "ok", "message": msg}
            return {"status": "error", "message": msg}

        # ---- CAS MFA 模式 — 全部用 JS 操作 Vue 弹窗 ----
        _debug_write("login_step2: CAS MFA mode")

        # ---- 诊断：dump 当前页面状态 ----
        import datetime as _dt
        _ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        # 保存一份 HTML 快照（带时间戳，不覆盖）
        _diag_html_path = os.path.join(screenshot_dir, f"login_step2_{_ts}.html")
        try:
            with open(_diag_html_path, "w", encoding="utf-8") as _f:
                _f.write(driver.page_source)
            _debug_write(f"login_step2: saved HTML to login_step2_{_ts}.html")
        except Exception as _e:
            _debug_write(f"login_step2: save HTML failed: {_e}")

        # dump 所有 dialog-wrapper 类元素的可见性
        _diag = driver.execute_script("""
            var result = [];
            var all = document.querySelectorAll(
                '.el-dialog__wrapper, .dialog-wrap, .card.mfa, ' +
                '.captcha-dialog-wrapper, .notice-dialog-wrap'
            );
            for (var i = 0; i < all.length; i++) {
                var el = all[i];
                result.push({
                    idx: i,
                    tag: el.tagName,
                    className: el.className,
                    style: el.getAttribute('style'),
                    cs_display: window.getComputedStyle(el).display,
                    childCount: el.querySelectorAll('*').length,
                    inputCount: el.querySelectorAll('input:not([type="hidden"])').length
                });
            }
            return JSON.stringify(result);
        """)
        _debug_write(f"login_step2: dialog dump={_diag}")

        # dump 所有非隐藏 input
        _diag2 = driver.execute_script("""
            var inputs = document.querySelectorAll('input:not([type="hidden"])');
            var result = [];
            for (var i = 0; i < inputs.length; i++) {
                var inp = inputs[i];
                var rect = inp.getBoundingClientRect();
                result.push({
                    idx: i,
                    type: inp.type,
                    placeholder: inp.placeholder || '',
                    className: inp.className,
                    name: inp.name || '',
                    id: inp.id || '',
                    rect_top: rect.top,
                    rect_left: rect.left,
                    rect_w: rect.width,
                    rect_h: rect.height,
                    cs_display: window.getComputedStyle(inp).display,
                    offsetParent: inp.offsetParent ? true : false
                });
            }
            return JSON.stringify(result);
        """)
        _debug_write(f"login_step2: input dump={_diag2}")

        # ---- 诊断结束 ----

        # 重新注入学号和加密密码到 #fm1（防止 Vue 组件初始化时被清空）
        _saved_username = session.get("username", "")
        _saved_password = session.get("encoded_password", "")
        driver.execute_script("""
            var u = document.querySelector('#fm1 #username');
            var p = document.querySelector('#fm1 #password');
            if (u) u.value = arguments[0];
            if (p) p.value = arguments[1];
        """, _saved_username, _saved_password)
        _debug_write("login_step2: re-injected credentials into #fm1")

        # ---- MFA 验证 ----
        # 用 fetch() 直接调用 attest API 验证验证码（已在 login_step1 中发过短信）
        # 验证成功后重新加密密码（防止公钥过期）再提交表单
        _debug_write(f"login_step2: validating code via attest API")
        mfa_result = driver.execute_async_script("""
            var callback = arguments[arguments.length - 1];
            var smsCode = arguments[0];
            var rawPassword = arguments[1];

            var vm = document.querySelector('#vue_main').__vue__;
            if (!vm) { callback(JSON.stringify({ok: false, error: 'Vue not found'})); return; }

            // 把验证码写入 Vue 实例
            vm.securePhoneCode = smsCode;

            var url = vm.attestServerUrl + '/api/guard/securephone/valid';
            var postdata = JSON.stringify({gid: vm.gid, code: smsCode});

            fetch(url, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: postdata,
                credentials: 'include'
            })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data && data.code === 0 && data.data && data.data.status === 2) {
                    // MFA 验证通过 → 重新加密密码 + 提交表单
                    try {
                        // 重新加密密码（使用当前公钥）
                        var newEncrypted = '__RSA__' + encrypt.encrypt(rawPassword);
                        document.querySelector('#fm1 #password').value = newEncrypted;

                        // 提交表单
                        var fm = document.getElementById('fm1');
                        if (fm) {
                            // 添加 _eventId_success 参数
                            var evtInput = fm.querySelector('input[name="_eventId_success"]');
                            if (!evtInput) {
                                evtInput = document.createElement('input');
                                evtInput.type = 'hidden';
                                evtInput.name = '_eventId_success';
                                evtInput.value = 'Submit';
                                fm.appendChild(evtInput);
                            }
                            fm.submit();
                        }
                        callback(JSON.stringify({ok: true}));
                    } catch(e) {
                        callback(JSON.stringify({ok: false, error: 'submit failed: ' + e.message}));
                    }
                } else {
                    callback(JSON.stringify({ok: false, data: data}));
                }
            })
            .catch(function(err) {
                callback(JSON.stringify({ok: false, error: err.message}));
            });
        """, sms_code, session.get("password", ""))

        _debug_write(f"login_step2: MFA result={mfa_result}")

        import json as _json
        try:
            mfa_info = _json.loads(mfa_result)
        except Exception:
            mfa_info = {"ok": false, "error": mfa_result}

        if mfa_info.get("ok"):
            # MFA 验证成功，表单已提交，等待 CAS 重定向到 jw
            _debug_write("login_step2: MFA OK, form submitted, waiting for redirect")
            time.sleep(3)
            _debug_save_screenshot(driver)
            _saved_username = session.get("username", "")
            _saved_password = session.get("password", "")
            status, msg = _complete_login(driver, _saved_username, _saved_password)
            release_mfa_session(session_token)
            if status == "ok":
                return {"status": "ok", "message": msg}
            return {"status": "error", "message": msg}

        # ---- MFA 验证失败，尝试重新初始化 + 重发短信 ----
        _debug_write("login_step2: MFA failed, re-init + resend")
        try:
            reinit_result = driver.execute_script("""
                var state = document.querySelector('#fm1 [name="mfaState"]');
                if (!state) return JSON.stringify({error: 'mfaState not found'});
                state = state.value;

                var xhr = new XMLHttpRequest();
                xhr.open('GET', '/cas/mfa/initByType/securephone?state=' + state, false);
                xhr.send();
                var r = JSON.parse(xhr.responseText);
                if (r.code !== 0) return JSON.stringify({error: 'initByType failed', resp: xhr.responseText});

                var vm = document.querySelector('#vue_main').__vue__;
                if (vm) {
                    vm.gid = r.data.gid;
                    vm.attestServerUrl = r.data.attestServerUrl;
                    vm.securePhone = r.data.securePhone || null;
                    vm.clearSecurePhone();
                }

                var url = r.data.attestServerUrl + '/api/guard/securephone/send';
                var xhr2 = new XMLHttpRequest();
                xhr2.open('POST', url, false);
                xhr2.setRequestHeader('Content-Type', 'application/json');
                xhr2.send(JSON.stringify({gid: r.data.gid}));
                var r2 = JSON.parse(xhr2.responseText);

                return JSON.stringify({ok: true, newGid: r.data.gid, newServer: r.data.attestServerUrl, sendResult: r2});
            """)
            _debug_write(f"login_step2: reinit result={reinit_result}")

            _debug_save_screenshot(driver)
            return {"status": "retry", "message": "验证码已重新发送，请在浏览器中输入新验证码后重试"}
        except Exception as reinit_e:
            _debug_write(f"login_step2: reinit failed: {reinit_e}")
            _debug_save_screenshot(driver)
            return {"status": "error", "message": f"MFA 验证失败: {str(reinit_e)}"}

    except Exception as e:
        try:
            _debug_save_screenshot(driver)
        except Exception:
            pass
        release_mfa_session(session_token)
        return {"status": "error", "message": f"MFA 验证失败: {e}"}


def _inject_cookies_to_httpx(driver):
    """将 Selenium 浏览器中的 cookies 注入 httpx client"""
    client = _get_client()
    selenium_cookies = driver.get_cookies()
    for c in selenium_cookies:
        client.cookies.set(
            c["name"], c["value"],
            domain=c.get("domain", ""),
            path=c.get("path", "/"),
        )


def _resolve_schedule_url(html: str):
    """从登录后的页面中找出课表 URL"""
    global SCHEDULE_URL
    if SCHEDULE_URL:
        return

    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "showTimetable" in href:
            full = href if href.startswith("http") else urljoin(JW_BASE_URL, href)
            SCHEDULE_URL = full
            return

    for frame in soup.find_all(["frame", "iframe"], src=True):
        src = frame["src"]
        if "showTimetable" in src:
            full = src if src.startswith("http") else urljoin(JW_BASE_URL, src)
            SCHEDULE_URL = full
            return


def imut_get_schedule() -> list[dict] | None:
    """
    从教务处获取并解析课表。
    返回课程列表或 None。
    """
    if not SCHEDULE_URL:
        demo_path = os.path.join(os.path.dirname(__file__), "学生课表.html")
        if os.path.exists(demo_path):
            try:
                with open(demo_path, "rb") as f:
                    html = f.read().decode("gbk")
                courses = _parse_schedule(html)
                print(f"[scraper] 从保存文件加载了 {len(courses)} 门课程")
                return courses
            except Exception as e:
                print(f"[scraper] 加载保存文件失败: {e}")
        return None

    client = _get_client()
    try:
        resp = client.get(SCHEDULE_URL)
        resp.raise_for_status()
        resp.encoding = "gbk"
        return _parse_schedule(resp.text)
    except Exception as e:
        print(f"获取课表失败: {e}")
        return None


def parse_schedule_from_html(html: str) -> list[dict]:
    """解析教务系统课表 HTML（直接从文件调用）"""
    return _parse_schedule(html)


def _parse_schedule(html: str) -> list[dict]:
    """解析 URPL 课表 HTML"""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id="timetable")
    if not table:
        table = soup.find("table", class_="infolist_hr")
    if not table:
        return []

    rows = table.find_all("tr")
    if len(rows) < 2:
        return []

    raw_courses = []  # (day, period, name, teacher, location, week_text)

    for row_idx, row in enumerate(rows):
        if row_idx == 0:
            continue  # 跳过表头
        cells = row.find_all(["td", "th"])
        if len(cells) < 2:
            continue

        for day_idx in range(1, len(cells)):
            cell = cells[day_idx]
            cell_text = cell.get_text("\n", strip=True)
            if not cell_text or cell_text == "\xa0":
                continue

            blocks = re.split(r"\n(?=<<)", cell_text)

            for block in blocks:
                block = block.strip()
                if not block:
                    continue

                lines = [l.strip() for l in block.split("\n") if l.strip()]
                if not lines:
                    continue

                parsed = _parse_course_block(lines, day_idx, row_idx)
                if parsed:
                    raw_courses.append(parsed)

    return _merge_consecutive(raw_courses)


def _parse_course_block(lines: list[str], day: int, period: int) -> dict | None:
    """解析单个课程块文本"""
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
        if re.match(r"\d+\s*[-–—,]\s*\d+\s*周", line) or re.match(r"\d+\s*周", line):
            week_text = line
        elif (re.match(r"^[一-鿿]{2,4}$", line)
              and not any(k in line for k in ("教学楼", "实验馆", "体育馆", "操场", "宿", "餐"))
              ) or "老师" in line or re.match(r"^[一-鿿]{2,4}[gG]?$", line):
            teacher = line
        else:
            location = location or line

    return {
        "day": day,
        "period": period,
        "name": name,
        "teacher": teacher,
        "location": location,
        "week_text": week_text,
    }


def _merge_consecutive(raw: list[dict]) -> list[dict]:
    """合并同一天同一门课的连续节次"""
    if not raw:
        return []

    groups = {}
    for c in raw:
        key = (c["day"], c["name"], c["teacher"], c["location"])
        groups.setdefault(key, []).append(c)

    result = []
    for (day, name, teacher, location), entries in groups.items():
        periods = sorted(set(e["period"] for e in entries))

        ranges = []
        start = periods[0]
        end = periods[0]
        for p in periods[1:]:
            if p == end + 1:
                end = p
            else:
                ranges.append((start, end))
                start = p
                end = p
        ranges.append((start, end))

        for sp, ep in ranges:
            min_w, max_w = 999, 0
            wt_set = set()
            for c in entries:
                if sp <= c["period"] <= ep and c.get("week_text", ""):
                    sw, ew, wtype = _parse_weeks(c["week_text"])
                    min_w = min(min_w, sw)
                    max_w = max(max_w, ew)
                    if wtype:
                        wt_set.add(wtype)

            start_w = max(1, min_w) if min_w != 999 else 1
            end_w = max_w if max_w != 0 else 20
            week_type = ""
            if len(wt_set) == 1:
                week_type = wt_set.pop()
            elif len(wt_set) > 1:
                week_type = ""

            result.append({
                "name": name,
                "teacher": teacher.replace("老师", "").replace("g", "").strip(),
                "location": location,
                "day_of_week": day,
                "start_period": sp,
                "end_period": ep,
                "start_week": start_w,
                "end_week": end_w,
                "week_type": week_type,
            })

    result.sort(key=lambda c: (c["day_of_week"], c["start_period"]))
    return result


def _parse_weeks(week_text: str) -> tuple[int, int, str]:
    """解析周数字符串"""
    if not week_text:
        return 1, 18, ""

    week_text = week_text.strip()
    week_type = ""

    if "单" in week_text:
        week_type = "odd"
    elif "双" in week_text:
        week_type = "even"

    m = re.search(r"(\d+)\s*[-–—]\s*(\d+)", week_text)
    if m:
        return int(m.group(1)), int(m.group(2)), week_type

    m = re.search(r"(\d+)\s*周", week_text)
    if m:
        w = int(m.group(1))
        return w, w, week_type

    return 1, 18, ""
