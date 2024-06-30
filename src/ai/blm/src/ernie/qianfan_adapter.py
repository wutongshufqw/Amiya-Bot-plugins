import asyncio
import json
import time
import re

from datetime import datetime
from typing import List, Optional, Union

from core import AmiyaBotPluginInstance
from core.util.threadPool import run_in_thread_pool

from amiyabot.log import LoggerManager
from amiyabot.network.httpRequests import http_requests

from ..common.blm_types import BLMAdapter, BLMFunctionCall
from ..common.database import AmiyaBotBLMLibraryMetaStorageModel, AmiyaBotBLMLibraryTokenConsumeModel

from ..common.extract_json import extract_json

logger = LoggerManager('BLM-QIANFAN')


class QianFanAdapter(BLMAdapter):
    def __init__(self, plugin):
        super().__init__()
        self.plugin: AmiyaBotPluginInstance = plugin
        self.thread_cache = {}

    def debug_log(self, msg):
        show_log = self.plugin.get_config("show_log")
        if show_log == True:
            logger.info(f'{msg}')

    def get_config(self, key):
        model_config = self.plugin.get_config("QianFan")
        if model_config and model_config["enable"] and key in model_config:
            return model_config[key]
        return None

    def get_model_quota_left(self, model_name: str) -> int:
        return 0

    def model_list(self) -> List[dict]:
        # 千帆没有常规Model
        return []

    async def chat_flow(
        self,
        prompt: Union[str, List[str]],
        model: Optional[Union[str, dict]] = None,
        context_id: Optional[str] = None,
        channel_id: Optional[str] = None,
        functions: Optional[List[BLMFunctionCall]] = None,
        json_mode: Optional[bool] = False,
    ) -> Optional[str]:
        # 千帆没有Chat Flow
        ...

    def assistant_list(self) -> List[dict]:

        # 获取千帆模型列表
        apps = self.get_config("apps")
        if apps is None:
            self.debug_log("fail to get app list. No conf.")
            return []

        app_list = []

        for app in apps:
            app_id = app["app_id"]
            name = app["app_name"]
            vision = app["vision_supported"]
            app_list.append({"id": app_id, "name": name, "model": "QianFanApp", "vision": vision})

        return app_list

    async def assistant_thread_touch(self, thread_id: str, assistant_id: str):
        # 我可以选择从服务器取，但是目前我就是设置一个5天超时
        timeout = 5 * 24 * 60 * 60

        if thread_id in self.thread_cache:
            if time.time() - self.thread_cache[thread_id] < timeout:
                return thread_id
            else:
                self.thread_cache.pop(thread_id, None)

        return None

    async def assistant_thread_create(self, assistant_id: str):

        url = "https://qianfan.baidubce.com/v2/app/conversation"

        app_key = self.get_config("api_key")

        if app_key is None or assistant_id is None:
            self.debug_log("fail to create thread, no app_key or assistant_id")
            return None

        headers = {"Content-Type": "application/json", "Authorization": "Bearer " + app_key}

        data = {"app_id": assistant_id}

        response_str = ""

        self.debug_log(f"Create thread data = {data} headers = {headers}")

        try:
            response_str = await http_requests.post(url, headers=headers, payload=data)

            response_json = json.loads(response_str)
            conv_id = response_json["conversation_id"]

            self.thread_cache[conv_id] = time.time()

            return conv_id
        except Exception as e:
            self.debug_log(f"fail to create thread, error: {e} \n response: {response_str}")
            return None

    async def assistant_run(
        self,
        thread_id: str,
        assistant_id: str,
        messages: Union[dict, List[dict]],
        channel_id: Optional[str] = None,
    ) -> Optional[str]:

        url = f"https://qianfan.baidubce.com/v2/app/conversation/runs"

        app_key = self.get_config("api_key")

        headers = {"Content-Type": "application/json", "Authorization": "Bearer " + app_key}

        if isinstance(messages, dict):
            messages = [messages]

        query = ""

        for i in range(len(messages)):
            if isinstance(messages[i], dict):
                if "type" not in messages[i]:
                    raise ValueError("无效的messages")
                if messages[i]["type"] == "text":
                    query = query + messages[i]["text"]
                elif messages[i]["type"] == "image_url":
                    ...
                else:
                    raise ValueError("无效的messages")
            else:
                raise ValueError("无效的messages")

        data = {"app_id": assistant_id, "query": query, "conversation_id": thread_id, "stream": False}

        self.debug_log(f"Data: {data} headers: {headers}")

        response_str = ""

        if assistant_id is None or query is None or thread_id is None or app_key is None:
            self.debug_log("fail to run assistant, no assistant_id, query, thread_id or app_key")
            return None

        try:
            response_str = await http_requests.post(url, headers=headers, payload=data)

            response_json = json.loads(response_str)

            if "answer" in response_json:
                self.thread_cache[thread_id] = time.time()

                answer = response_json["answer"]

                # 稍微处理一下
                answer = re.sub(r'\^\[\d+\]\^', '', answer)

                return answer

        except Exception as e:
            self.debug_log(f"fail to run assistant, error: {e} \n response: {response_str}")
            return None