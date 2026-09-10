"""配置二次锁

避免多个并发请求同时写入 .env 文件导致配置文件损坏。
实际写锁已在 config.py 的 update_env 中实现，本模块提供对外接口。
"""
import threading
from contextlib import contextmanager

# 全局配置写入锁
_CONFIG_WRITE_LOCK = threading.Lock()


@contextmanager
def config_write_lock():
    """配置写入上下文管理器"""
    _CONFIG_WRITE_LOCK.acquire()
    try:
        yield
    finally:
        _CONFIG_WRITE_LOCK.release()
