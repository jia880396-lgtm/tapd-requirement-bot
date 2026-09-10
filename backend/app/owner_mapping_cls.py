"""分类机器人 - 处理人映射
基于功能分类表，根据分类结果查找对应模块负责人

重要说明：
- display_name: 中文显示名，用于前端展示
- username: TAPD 登录账号，用于写回 TAPD 的 owner 字段
"""
import logging

logger = logging.getLogger(__name__)

# 负责人映射表
OWNER_MAPPING = {
    "登录": {"display_name": "王思域", "username": "王思域03"},
    "商品": {"display_name": "杨润", "username": "杨润"},
    "仓储": {"display_name": "杨晶晶", "username": "杨晶晶01"},
    "采购": {"display_name": "梁峻嵩", "username": "梁峻嵩"},
    "报表": {"display_name": "张莹莹", "username": "张莹莹"},
    "铺货": {"display_name": "尹春龙", "username": "尹春龙"},
    "供分销": {"display_name": "陈梦琦", "username": "陈梦琦"},
    "跨境": {"display_name": "王佳良", "username": "王佳良"},

    "订单": {
        "_default": {"display_name": "徐玥玥", "username": "徐玥玥01"},
        "订单自动策略": {"display_name": "徐玥玥", "username": "徐玥玥01"},
        "订单手动操作": {"display_name": "董伊彤", "username": "董仪彤"},
        "订单打印": {"display_name": "董伊彤", "username": "董仪彤"},
        "订单信息": {"display_name": "徐玥玥", "username": "徐玥玥01"},
    },
    "售后": {
        "_default": {"display_name": "王思域", "username": "王思域03"},
        "售后单自动策略": {"display_name": "王思域", "username": "王思域03"},
        "售后单手动操作": {"display_name": "王思域", "username": "王思域03"},
        "售后单信息": {"display_name": "王思域", "username": "王思域03"},
        "快递拦截": {"display_name": "王思域", "username": "王思域03"},
        "智能退货入库": {"display_name": "王思域", "username": "王思域03"},
        "快速登记": {"display_name": "王思域", "username": "王思域03"},
        "无头件管理": {"display_name": "王思域", "username": "王思域03"},
    },
    "账款": {
        "_default": {"display_name": "徐玥玥", "username": "徐玥玥01"},
        "交易对象": {"display_name": "徐玥玥", "username": "徐玥玥01"},
        "应收应付": {"display_name": "徐玥玥", "username": "徐玥玥01"},
        "收款付款": {"display_name": "徐玥玥", "username": "徐玥玥01"},
        "结算账户": {"display_name": "徐玥玥", "username": "徐玥玥01"},
        "资金流水": {"display_name": "徐玥玥", "username": "徐玥玥01"},
        "费用账单": {"display_name": "徐玥玥", "username": "徐玥玥01"},
        "发票管理": {"display_name": "徐玥玥", "username": "徐玥玥01"},
    },
    "分享": {
        "_default": {"display_name": "布合丽且古丽托热", "username": "布合丽且古丽托热"},
        "提供方管理": {"display_name": "布合丽且古丽托热", "username": "布合丽且古丽托热"},
        "使用方管理": {"display_name": "布合丽且古丽托热", "username": "布合丽且古丽托热"},
        "面单使用详情": {"display_name": "布合丽且古丽托热", "username": "布合丽且古丽托热"},
    },
    "配置": {
        "_default": {"display_name": "杨润", "username": "杨润"},
        "绑定店铺": {"display_name": "布合丽且古丽托热", "username": "布合丽且古丽托热"},
        "快递管理": {"display_name": "布合丽且古丽托热", "username": "布合丽且古丽托热"},
        "仓库信息维护": {"display_name": "杨晶晶", "username": "杨晶晶01"},
        "非物流单模板": {"display_name": "布合丽且古丽托热", "username": "布合丽且古丽托热"},
        "快递单模板": {"display_name": "布合丽且古丽托热", "username": "布合丽且古丽托热"},
        "货区货位": {"display_name": "杨晶晶", "username": "杨晶晶01"},
        "货位分组": {"display_name": "杨晶晶", "username": "杨晶晶01"},
        "权限设置": {"display_name": "王思域", "username": "王思域03"},
        "视频管理": {"display_name": "布合丽且古丽托热", "username": "布合丽且古丽托热"},
        "基本配置": {"display_name": "杨润", "username": "杨润"},
    },
    "档口": {
        "_default": {"display_name": "杨润", "username": "杨润"},
        "拿货标签管理": {"display_name": "杨润", "username": "杨润"},
        "备货单": {"display_name": "杨润", "username": "杨润"},
        "分拣墙管理": {"display_name": "杨润", "username": "杨润"},
        "到货登记": {"display_name": "杨润", "username": "杨润"},
        "退货登记": {"display_name": "杨润", "username": "杨润"},
        "退货签重匹配": {"display_name": "杨润", "username": "杨润"},
        "盲扫分拣发货": {"display_name": "杨润", "username": "杨润"},
        "逐单扫描发货": {"display_name": "杨润", "username": "杨润"},
        "爆款标签发货": {"display_name": "杨润", "username": "杨润"},
        "标签对账": {"display_name": "杨润", "username": "杨润"},
        "到缺货报表": {"display_name": "杨润", "username": "杨润"},
        "档口最早缺货": {"display_name": "杨润", "username": "杨润"},
    },
    "对接": {
        "_default": {"display_name": "布合丽且古丽托热", "username": "布合丽且古丽托热"},
        "新平台对接": {"display_name": "布合丽且古丽托热", "username": "布合丽且古丽托热"},
        "物流对接": {"display_name": "布合丽且古丽托热", "username": "布合丽且古丽托热"},
        "单据下载": {"display_name": "布合丽且古丽托热", "username": "布合丽且古丽托热"},
        "库存同步": {"display_name": "杨晶晶", "username": "杨晶晶01"},
        "奇门对接": {"display_name": "张莹莹", "username": "张莹莹"},
        "API对接": {"display_name": "张莹莹", "username": "张莹莹"},
    },
}


def resolve_owner(category_l1: str, category_l2: str) -> dict | None:
    """根据分类结果查找对应的处理人"""
    mapping = OWNER_MAPPING.get(category_l1)
    if mapping is None:
        logger.info(f"No owner mapping for L1: {category_l1}")
        return None
    if "display_name" in mapping:
        username = mapping.get("username", mapping["display_name"])
        return {"display_name": username, "username": username}
    if category_l2 and category_l2 in mapping:
        info = mapping[category_l2]
        username = info.get("username", info["display_name"])
        return {"display_name": username, "username": username}
    default = mapping.get("_default")
    if default:
        username = default.get("username", default["display_name"])
        logger.info(f"No L2 match for {category_l1}>{category_l2}, using default: {username}")
        return {"display_name": username, "username": username}
    return None


def get_all_owner_names() -> list:
    """获取所有模块负责人列表（去重排序）"""
    seen = set()
    result = []
    for l1_key, mapping in OWNER_MAPPING.items():
        if "display_name" in mapping:
            username = mapping.get("username", mapping["display_name"])
            if username not in seen:
                seen.add(username)
                result.append({"display_name": username, "username": username})
        else:
            for l2_key, owner_info in mapping.items():
                if isinstance(owner_info, dict) and "display_name" in owner_info:
                    username = owner_info.get("username", owner_info["display_name"])
                    if username not in seen:
                        seen.add(username)
                        result.append({"display_name": username, "username": username})
    return sorted(result, key=lambda x: x["display_name"])


def get_all_l1_categories() -> list:
    """获取所有有效的一级分类名称列表"""
    return list(OWNER_MAPPING.keys())


def get_tapd_account_by_display_name(display_name: str) -> str:
    """根据中文显示名查找对应的 TAPD 账号

    TAPD API 的 owner 参数需要传账号名（如 "徐玥玥01"），
    而非显示名（如 "徐玥玥"）。此函数从 OWNER_MAPPING 中反查。

    若未找到映射，返回原值（兜底）。
    """
    if not display_name:
        return display_name
    for l1_key, mapping in OWNER_MAPPING.items():
        if "display_name" in mapping:
            if mapping["display_name"] == display_name:
                return mapping.get("username", display_name)
        else:
            for l2_key, owner_info in mapping.items():
                if isinstance(owner_info, dict) and "display_name" in owner_info:
                    if owner_info["display_name"] == display_name:
                        return owner_info.get("username", display_name)
    # 也检查 OWNER_NAME_TO_TAPD（tapd_client 中的补充映射）
    from app.tapd_client import OWNER_NAME_TO_TAPD
    if display_name in OWNER_NAME_TO_TAPD:
        return OWNER_NAME_TO_TAPD[display_name]
    return display_name
