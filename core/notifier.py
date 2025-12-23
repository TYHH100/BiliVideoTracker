import smtplib
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr

from core import debug_log, logger


def send_notification(settings, subject, html_content):
    """发送邮件通知"""
    logger.info(f"[Mail] 开始发送邮件通知: {subject}")

    if settings.get("smtp_enable") != "1":
        logger.info(f"[NOTIFIER] SMTP未启用，跳过发送")
        debug_log(f"[NOTIFIER] SMTP未启用，跳过邮件发送: {subject}")
        return False

    sender_name = settings.get("sender_name", "BiliVideoTracker")
    smtp_server = settings.get("smtp_server")
    smtp_port = int(settings.get("smtp_port", 465))
    account = settings.get("email_account")
    auth_code = settings.get("email_auth_code")
    receivers_str = settings.get("receiver_emails", "")

    debug_log(
        f"[NOTIFIER] SMTP配置: 服务器={smtp_server}, 端口={smtp_port}, 发件人={account}"
    )
    debug_log(f"[NOTIFIER] 邮件主题: {subject}")
    debug_log(f"[NOTIFIER] 邮件内容长度: {len(html_content)} 字符")
    debug_log(f"[NOTIFIER] 邮件内容预览: {html_content[:200]}...")

    if not account or not auth_code or not receivers_str:
        debug_log(f"[NOTIFIER] 配置不完整，缺少必要参数")
        logger.info("[Mail] 配置不完整，跳过发送")
        return False

    receivers = [r.strip() for r in receivers_str.split(",") if r.strip()]
    debug_log(f"[NOTIFIER] 收件人列表: {receivers}")
    debug_log(f"[NOTIFIER] 收件人数量: {len(receivers)} 个")

    debug_log(f"[NOTIFIER] 构建邮件消息")
    message = MIMEText(html_content, "html", "utf-8")
    # 修复发件人格式：同时包含名称和邮箱地址
    message["From"] = formataddr((sender_name, account))
    # 修复收件人格式：直接使用邮箱列表，不使用Header编码
    message["To"] = ",".join(receivers)
    message["Subject"] = Header(subject, "utf-8")
    debug_log(f"[NOTIFIER] 邮件消息构建完成")
    debug_log(f"[NOTIFIER] 发件人: {message['From']}")
    debug_log(f"[NOTIFIER] 收件人: {message['To']}")

    try:
        debug_log(f"[NOTIFIER] 连接SMTP服务器: {smtp_server}:{smtp_port}")
        if settings.get("use_tls") == "1":
            debug_log(f"[NOTIFIER] 使用SMTP_SSL连接")
            smtp = smtplib.SMTP_SSL(smtp_server, smtp_port)
            debug_log(f"[NOTIFIER] SMTP_SSL连接成功")
        else:
            debug_log(f"[NOTIFIER] 使用普通SMTP连接")
            smtp = smtplib.SMTP(smtp_server, smtp_port)
            debug_log(f"[NOTIFIER] 普通SMTP连接成功")
            # 非SSL模式下有些服务器需要 starttls
            # smtp.starttls()

        debug_log(f"[NOTIFIER] 登录SMTP服务器")
        smtp.login(account, auth_code)
        debug_log(f"[NOTIFIER] 登录成功，发送邮件")

        # 记录发送前的详细信息
        debug_log(f"[NOTIFIER] 邮件大小: {len(message.as_string())} 字节")
        debug_log(f"[NOTIFIER] 开始发送邮件...")

        smtp.sendmail(account, receivers, message.as_string())
        debug_log(f"[NOTIFIER] 邮件发送成功")

        smtp.quit()
        debug_log(f"[NOTIFIER] SMTP连接已关闭")
        logger.info(f"[Mail] 发送成功: {subject}")
        debug_log(f"[NOTIFIER] 邮件发送完成: {subject}")
        return True
    except Exception as e:
        debug_log(f"[NOTIFIER] 邮件发送失败: {e}")
        debug_log(f"[NOTIFIER] 错误类型: {type(e).__name__}")
        logger.info(f"[Mail] 发送失败: {e}")
        return False
