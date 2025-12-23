import requests
import re
import time
from urllib.parse import urlparse, parse_qs
from . import logger, APIError, ValidationError
from core import debug_log


class BiliAPI:
    def __init__(self):
        self.base_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Origin": "https://space.bilibili.com",
        }

    def _get(self, url, mid_for_referer, max_retries=3):
        """发送GET请求，动态设置Referer，带指数退避重试机制"""
        headers = self.base_headers.copy()
        headers["Referer"] = f"https://space.bilibili.com/{mid_for_referer}"

        debug_log(
            "BiliAPI",
            "_get",
            f"准备发送请求: URL={url}, Referer={headers['Referer']}, max_retries={max_retries}",
        )

        for retry in range(max_retries):
            try:
                debug_log(
                    "BiliAPI", "_get", f"发送第 {retry+1}/{max_retries} 次请求: {url}"
                )
                resp = requests.get(url, headers=headers, timeout=10)
                debug_log(
                    "BiliAPI",
                    "_get",
                    f"收到响应: status_code={resp.status_code}, URL={url}",
                )

                if resp.status_code == 200:
                    debug_log("BiliAPI", "_get", f"请求成功: {url}")
                    return resp.json()
                else:
                    logger.error(
                        f"API请求失败: 状态码 {resp.status_code} for URL {url}, retry {retry+1}/{max_retries}"
                    )
                    debug_log(
                        "BiliAPI",
                        "_get",
                        f"请求失败: status_code={resp.status_code}, retry={retry+1}/{max_retries}, URL={url}",
                    )
            except requests.RequestException as e:
                logger.error(
                    f"API请求异常: {e} for URL {url}, retry {retry+1}/{max_retries}"
                )
                debug_log(
                    "BiliAPI",
                    "_get",
                    f"请求异常: {e}, retry={retry+1}/{max_retries}, URL={url}",
                )

            # 指数退避策略
            if retry < max_retries - 1:
                sleep_time = 2**retry
                debug_log("BiliAPI", "_get", f"退避 {sleep_time} 秒后重试，URL={url}")
                time.sleep(sleep_time)

        logger.error(f"API请求彻底失败，已重试 {max_retries} 次: {url}")
        debug_log("BiliAPI", "_get", f"请求彻底失败，已重试 {max_retries} 次: {url}")
        raise APIError(f"API请求失败，已重试 {max_retries} 次", url=url)

    def get_info(self, monitor_type, remote_id, mid):
        """统一入口：根据类型获取信息"""
        debug_log(
            "BiliAPI",
            "get_info",
            f"获取监控信息: type={monitor_type}, remote_id={remote_id}, mid={mid}",
        )

        if monitor_type not in ["series", "season"]:
            debug_log("BiliAPI", "get_info", f"无效的监控类型: {monitor_type}")
            raise ValidationError(f"无效的监控类型: {monitor_type}")

        try:
            if monitor_type == "series":
                debug_log(
                    "BiliAPI",
                    "get_info",
                    f"调用 _get_series 获取系列信息: series_id={remote_id}",
                )
                return self._get_series(remote_id, mid)
            elif monitor_type == "season":
                debug_log(
                    "BiliAPI",
                    "get_info",
                    f"调用 _get_season 获取合集信息: season_id={remote_id}",
                )
                return self._get_season(remote_id, mid)
        except Exception as e:
            logger.error(
                f"获取监控信息失败: {e}, type={monitor_type}, remote_id={remote_id}, mid={mid}"
            )
            debug_log(
                "BiliAPI",
                "get_info",
                f"获取监控信息失败: {e}, type={monitor_type}, remote_id={remote_id}, mid={mid}",
            )
            raise APIError(f"获取监控信息失败: {e}") from e

        return None

    def _get_series(self, series_id, mid):
        # 系列 API
        url = f"https://api.bilibili.com/x/series/series?series_id={series_id}"
        debug_log(
            "BiliAPI", "_get_series", f"获取系列信息: series_id={series_id}, URL={url}"
        )

        data = self._get(url, mid)

        if data and data["code"] == 0 and "data" in data and "meta" in data["data"]:
            debug_log(
                "BiliAPI",
                "_get_series",
                f"成功获取系列信息: series_id={series_id}, data={data}",
            )
            meta = data["data"]["meta"]
            # 删除标题前面的"合集·"前缀（兼容有空格和无空格两种情况）
            name = meta.get("name", "").replace("合集· ", "").replace("合集·", "")
            result = {
                "name": name,
                "desc": meta.get("description", ""),
                "total": meta.get("total", 0),
                "cover": meta.get("cover", ""),
                "last_update": meta.get("last_update_ts", 0),
            }
            debug_log("BiliAPI", "_get_series", f"处理后系列信息: {result}")
            return result

        debug_log(
            "BiliAPI",
            "_get_series",
            f"未获取到有效系列信息: series_id={series_id}, data={data}",
        )
        return None

    def _get_season(self, season_id, mid):
        # 合集 API
        url = f"https://api.bilibili.com/x/polymer/web-space/seasons_archives_list?mid={mid}&season_id={season_id}&sort_reverse=false&page_size=1&page_num=1"
        debug_log(
            "BiliAPI",
            "_get_season",
            f"获取合集信息: season_id={season_id}, mid={mid}, URL={url}",
        )

        data = self._get(url, mid)

        if data and data["code"] == 0 and "data" in data:
            debug_log(
                "BiliAPI",
                "_get_season",
                f"成功获取合集信息: season_id={season_id}, data={data}",
            )
            if "meta" in data["data"]:
                meta = data["data"]["meta"]
                # 删除标题前面的"合集·"前缀（兼容有空格和无空格两种情况）
                name = meta.get("name", "").replace("合集· ", "").replace("合集·", "")
                # 获取最后更新时间
                last_update = 0
                if "archives" in data["data"] and data["data"]["archives"]:
                    try:
                        last_update = max(
                            v.get("pubdate", 0) for v in data["data"]["archives"]
                        )
                        debug_log(
                            "BiliAPI",
                            "_get_season",
                            f"获取到最后更新时间: {last_update}",
                        )
                    except (TypeError, ValueError) as e:
                        debug_log(
                            "BiliAPI", "_get_season", f"获取最后更新时间失败: {e}"
                        )
                        last_update = 0

                result = {
                    "name": name,
                    "desc": meta.get("description", ""),
                    "total": meta.get("total", 0),
                    "cover": meta.get("cover", ""),
                    "last_update": last_update,
                }
                debug_log("BiliAPI", "_get_season", f"处理后合集信息: {result}")
                return result

        debug_log(
            "BiliAPI",
            "_get_season",
            f"未获取到有效合集信息: season_id={season_id}, data={data}",
        )
        return None

    def get_latest_videos(self, monitor_type, remote_id, mid, count=5):
        """
        获取合集中最新的视频列表
        monitor_type: 'series' 或 'season'
        remote_id: 系列ID或合集ID
        mid: 用户ID
        count: 获取的视频数量
        """
        debug_log(
            "BiliAPI",
            "get_latest_videos",
            f"获取最新视频: type={monitor_type}, remote_id={remote_id}, mid={mid}, count={count}",
        )

        if monitor_type == "season":
            # 合集 API - 获取最新视频
            url = f"https://api.bilibili.com/x/polymer/web-space/seasons_archives_list?mid={mid}&season_id={remote_id}&sort_reverse=true&page_size={count}&page_num=1"
            debug_log("BiliAPI", "get_latest_videos", f"获取合集最新视频: URL={url}")

            data = self._get(url, mid)

            if (
                data
                and data["code"] == 0
                and "data" in data
                and "archives" in data["data"]
            ):
                debug_log(
                    "BiliAPI",
                    "get_latest_videos",
                    f"成功获取合集最新视频: type={monitor_type}, data={data}",
                )
                archives = data["data"]["archives"]
                videos = []
                for i, archive in enumerate(archives):
                    debug_log(
                        "BiliAPI",
                        "get_latest_videos",
                        f"处理视频 {i+1}/{len(archives)}: archive={archive}",
                    )
                    # 确保所有必要字段都存在
                    if not archive:
                        debug_log("BiliAPI", "get_latest_videos", f"跳过空视频对象")
                        continue
                    video_id = archive.get("aid", "")
                    if not video_id:
                        debug_log(
                            "BiliAPI", "get_latest_videos", f"跳过无video_id的视频"
                        )
                        continue
                    video = {
                        "video_id": str(video_id),
                        "title": archive.get("title", "未命名视频"),
                        "publish_time": archive.get("pubdate", 0),
                        "cover": archive.get(
                            "pic", ""
                        ),  # API返回的是pic字段，不是cover
                    }
                    videos.append(video)
                    debug_log("BiliAPI", "get_latest_videos", f"添加视频: {video}")
                debug_log(
                    "BiliAPI",
                    "get_latest_videos",
                    f"共获取到 {len(videos)} 个合集最新视频",
                )
                return videos
        elif monitor_type == "series":
            # 系列 API - 获取最新视频
            url = f"https://api.bilibili.com/x/polymer/web-space/home/seasons_series?mid={mid}&series_id={remote_id}&sort_reverse=true&page_size={count}&page_num=1"
            debug_log("BiliAPI", "get_latest_videos", f"获取系列最新视频: URL={url}")

            data = self._get(url, mid)

            if (
                data
                and data["code"] == 0
                and "data" in data
                and "archives" in data["data"]
            ):
                debug_log(
                    "BiliAPI",
                    "get_latest_videos",
                    f"成功获取系列最新视频: type={monitor_type}, data={data}",
                )
                archives = data["data"]["archives"]
                videos = []
                for i, archive in enumerate(archives):
                    debug_log(
                        "BiliAPI",
                        "get_latest_videos",
                        f"处理视频 {i+1}/{len(archives)}: archive={archive}",
                    )
                    # 确保所有必要字段都存在
                    if not archive:
                        debug_log("BiliAPI", "get_latest_videos", f"跳过空视频对象")
                        continue
                    video_id = archive.get("aid", "")
                    if not video_id:
                        debug_log(
                            "BiliAPI", "get_latest_videos", f"跳过无video_id的视频"
                        )
                        continue
                    video = {
                        "video_id": str(video_id),
                        "title": archive.get("title", "未命名视频"),
                        "publish_time": archive.get("pubdate", 0),
                        "cover": archive.get(
                            "pic", ""
                        ),  # API返回的是pic字段，不是cover
                    }
                    videos.append(video)
                    debug_log("BiliAPI", "get_latest_videos", f"添加视频: {video}")
                debug_log(
                    "BiliAPI",
                    "get_latest_videos",
                    f"共获取到 {len(videos)} 个系列最新视频",
                )
                return videos

        debug_log(
            "BiliAPI",
            "get_latest_videos",
            f"未获取到最新视频: type={monitor_type}, remote_id={remote_id}",
        )
        return []

    def parse_url(self, url):
        """解析URL
        返回: (mid, remote_id, type)
        """
        debug_log("BiliAPI", "parse_url", f"解析URL: {url}")

        if not url:
            debug_log("BiliAPI", "parse_url", "URL为空")
            raise ValidationError("URL不能为空")

        try:
            parsed = urlparse(url)
            debug_log(
                "BiliAPI",
                "parse_url",
                f"解析后的URL: scheme={parsed.scheme}, netloc={parsed.netloc}, path={parsed.path}, query={parsed.query}",
            )

            # 路径类似 /12345/lists/67890
            path_parts = parsed.path.strip("/").split("/")
            debug_log("BiliAPI", "parse_url", f"路径部分: {path_parts}")

            # 尝试提取 mid (用户ID)
            mid = None
            if len(path_parts) >= 3 and path_parts[1] == "lists":
                mid = path_parts[0]  # space.bilibili.com/UID/...
                debug_log("BiliAPI", "parse_url", f"从路径提取mid: {mid}")
            elif "space.bilibili.com" in url:
                # 正则提取 space.bilibili.com/(\d+)
                m = re.search(r"space\.bilibili\.com/(\d+)", url)
                if m:
                    mid = m.group(1)
                    debug_log("BiliAPI", "parse_url", f"从URL正则提取mid: {mid}")

            # 提取 remote_id
            remote_id = None
            if len(path_parts) >= 3 and path_parts[1] == "lists":
                remote_id = path_parts[2]  # lists/ID
                debug_log("BiliAPI", "parse_url", f"从路径提取remote_id: {remote_id}")

            # 提取 type
            qs = parse_qs(parsed.query)
            debug_log("BiliAPI", "parse_url", f"查询参数: {qs}")
            m_type = qs.get("type", [""])[0]  # series 或 season
            debug_log("BiliAPI", "parse_url", f"提取type: {m_type}")

            if mid and remote_id and m_type in ["series", "season"]:
                debug_log(
                    "BiliAPI",
                    "parse_url",
                    f"解析成功: mid={mid}, remote_id={remote_id}, type={m_type}",
                )
                return mid, remote_id, m_type
            else:
                debug_log(
                    "BiliAPI",
                    "parse_url",
                    f"解析失败: mid={mid}, remote_id={remote_id}, type={m_type}",
                )
                raise ValidationError(f"无法从URL中提取有效信息: {url}")

        except ValidationError:
            raise
        except Exception as e:
            logger.error(f"URL解析失败: {e}, URL: {url}")
            debug_log("BiliAPI", "parse_url", f"解析异常: {e}")
            raise ValidationError(f"URL解析失败: {e}") from e
