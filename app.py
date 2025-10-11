# filename: app.py
import requests
import logging
import random
import json
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request, render_template_string
import hashlib
from xml.etree import ElementTree as ET
import concurrent.futures
from functools import partial
import time
import functools

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

# 定义统一返回对象
class ResultVO:
    def __init__(self, code=200, message="success", data=None):
        self.code = code
        self.message = message
        self.data = data if data is not None else []

    def to_dict(self):
        return {
            "code": self.code,
            "message": self.message,
            "data": self.data
        }


class OrderFetcher:
    def __init__(self, login_data=None, headers=None):
        self.session = requests.Session()
        self.login_url = 'https://e.jwsaas.com/admin/account/check'
        self.list_url = 'https://e.jwsaas.com/admin/supplier/order/list/ajaxData'
        self.detail_url = 'https://e.jwsaas.com/admin/supplier/order/detail/'

        self.login_data = login_data or {
            'code': '372118',
            'userName': 'ljb001',
            'password': '6B04A8E1C319F905C054AA310BE39E78'
        }

        self.headers = headers or {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36 Edg/138.0.0.0"
        }

        # 添加缓存字典
        self._cache = {}
        self._cache_timeout = 300  # 5分钟缓存

    def _get_cache_key(self, *args):
        """生成缓存键"""
        return hash(str(args))

    def _get_from_cache(self, key):
        """从缓存获取数据"""
        if key in self._cache:
            data, timestamp = self._cache[key]
            if time.time() - timestamp < self._cache_timeout:
                return data
            else:
                del self._cache[key]
        return None

    def _set_cache(self, key, data):
        """设置缓存数据"""
        self._cache[key] = (data, time.time())

    def login(self):
        """登录并维持会话"""
        response = self.session.post(self.login_url, data=self.login_data, headers=self.headers, allow_redirects=False)
        if response.status_code in [301, 302]:
            redirect_url = response.headers.get('Location')
            full_url = 'https://e.jwsaas.com' + redirect_url if redirect_url.startswith('/') else redirect_url
            self.session.get(full_url)
        return response.status_code == 200


    def fetch_orders(self, target_date=None):
        """获取菜单并过滤"""
        if target_date is None:
            # 默认查询当天
            target_date = datetime.today()
        else:
            target_date = datetime.strptime(target_date, '%Y-%m-%d')

        # 构建日期范围条件对象
        data1 = target_date.strftime('%Y-%m-%d')
        data2 = target_date.strftime('%Y-%m-%d')

        condition = {
            "name": "setDate",
            "type": "range",
            "key": "setDate",
            "data1": data1,
            "data1Type": "",
            "data2": data2,
            "data2Type": ""
        }

        # 模拟页面行为：先对条件对象进行JSON.stringify，再放入数组
        condition_str = json.dumps(condition, ensure_ascii=False)
        # 获取过滤条件（模拟getFilterCondition）
        filter_conditions = [condition_str]
        filter_param = json.dumps(filter_conditions, ensure_ascii=False)

        data = {
            'searchFields': 'no,description',
            'storeId': '',
            'filter': filter_param,
            '_search': 'false',
            'rows': '99',
            'page': '1',
            'sidx': '',
            'sord': 'asc',
            'keyword': '',
            'warehouseId': ''
        }

        params = {
            't': str(random.random()),
            'refStatus1': ' ',
            'refStatus2': '',
            'status': ' '
        }

        response = self.session.post(self.list_url, params=params, data=data)
        if response.status_code == 200:
            try:
                json_data = response.json()
                rows = json_data.get('rows', [])
                target_date_str = target_date.strftime('%Y-%m-%d')

                # 过滤出当天19点之后的数据
                filter_time_str = f"{target_date_str} 19:00:00"
                filtered_rows = [
                    row for row in rows
                    if row.get('createDate', '') > filter_time_str and
                       row.get('setDate', '').startswith(target_date_str)
                ]

                return filtered_rows
            except requests.exceptions.JSONDecodeError:
                logging.error("菜单列表响应不是有效的 JSON")
        else:
            logging.error("菜单列表请求失败，状态码: %d", response.status_code)
        return []


    def fetch_order_items(self, order_id):
        """获取菜单明细数据"""
        detaillist_url = f'https://e.jwsaas.com/admin/supplier/order/detaillist/ajaxData?t={random.random()}'
        response = self.session.post(detaillist_url, data={
            'id': order_id,
            '_search': 'false',
            'rows': '-1',
            'page': '1',
            'sidx': '',
            'sord': 'asc'
        })

        if response.status_code == 200:
            try:
                return response.json().get('rows', [])
            except json.JSONDecodeError:
                logging.error("菜单详情响应不是有效的 JSON，菜单ID: %s", order_id)
        else:
            logging.error("获取菜单详情失败，状态码: %d，菜单ID: %s", response.status_code, order_id)
        return []

    @functools.lru_cache(maxsize=128)
    def fetch_order_items_cached(self, order_id):
        """带缓存的订单明细获取方法"""
        return self.fetch_order_items(order_id)

    # 修改 get_order_details 方法中的总数量计算
    def get_order_details(self, order_id):
        """获取菜单详情"""
        # 检查缓存
        cache_key = f"order_detail_{order_id}"
        cached_result = self._get_from_cache(cache_key)
        if cached_result:
            return cached_result

        detail_url = f"{self.detail_url}{order_id}?t={random.random()}"
        response = self.session.get(detail_url)

        if response.status_code != 200:
            logging.error("获取菜单页面失败，状态码: %d，菜单ID: %s", response.status_code, order_id)
            return None

        soup = BeautifulSoup(response.text, 'html.parser')
        select_element = soup.find('select', {'id': 'warehouseId'})

        selected_text = '未知仓库'
        selected_value = ''
        if select_element:
            options = select_element.find_all('option')
            for option in options:
                if 'selected' in option.attrs:
                    selected_value = option.get('value', '')
                    selected_text = option.get_text(strip=True)
                    parts = selected_text.split('-', 1)
                    shop_name = parts[0]
                    warehouse = parts[1] if len(parts) > 1 else ''
                    break

        # 门店映射
        shop_mapping = {
            "0001": "广源一品",
            "0002": "广源二店",
            "0003": "麻婆豆腐"
        }

        # 精确匹配前缀（只取4位）
        prefix = shop_name[:4] if len(shop_name) >= 4 else shop_name
        shop_name = shop_mapping.get(prefix, "未知门店")

        no = soup.find("input", id="no")
        no_value = no.get("value") if no and no.has_attr("value") else "未知单据编号"

        # 使用缓存版本获取订单明细
        items = self.fetch_order_items_cached(order_id)

        # 计算商品种类数量（个数）
        item_count = len(items)

        result_parts = []
        for item in items:
            description = item.get('description', '')
            product_name = item.get('productName', '未知产品')
            quantity = item.get('quantity', 0)
            unit_name = item.get('unitName', '')
            result_parts.append(f"{product_name}:{quantity}{unit_name}{f'({description})' if description else ''}")

        full_result = ",".join(result_parts)

        result = {
            "菜单编号": no_value,
            "仓库编号": selected_value,
            "门店": shop_name,
            "仓库": warehouse,
            "菜单内容": full_result,
            "总数量": item_count  # 商品种类个数
        }

        # 设置缓存
        self._set_cache(cache_key, result)

        return result

    def process_order_detail(self, row):
        """处理单个订单详情的辅助方法"""
        order_id = row.get('id')
        if not order_id:
            return None
        order_detail = self.get_order_details(order_id)
        if order_detail:
            order_detail["制单时间"] = row.get('setDate', '未知')
            return order_detail
        return None

    # 修改 OrderFetcher 类中的 get_filtered_orders 方法
    def get_filtered_orders(self, target_date=None):
        """对外接口：获取并返回格式化菜单信息，封装为 ResultVO，并按门店、仓库分组"""
        if not self.login():
            logging.error("登录失败")
            return ResultVO(code=401, message="登录失败").to_dict()

        orders = self.fetch_orders(target_date)

        # 使用线程池并行处理订单详情获取
        order_details = []
        if orders:
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                # 创建偏函数以便传递额外参数
                process_order_partial = partial(self.process_order_detail)
                order_details = list(executor.map(process_order_partial, orders))

            # 过滤掉处理失败的订单
            order_details = [detail for detail in order_details if detail is not None]

        grouped_orders = {}  # 按门店 -> 仓库 分组

        for order_detail in order_details:
            shop_name = order_detail.get("门店")
            creator = order_detail.get("仓库")
            # 修改这里：添加总数量字段和制单时间
            order_info = {
                "菜单编号": order_detail["菜单编号"],
                "菜单内容": order_detail["菜单内容"],
                "总数量": order_detail["总数量"],  # 添加总数量字段
                "制单时间": order_detail["制单时间"]  # 添加制单时间
            }

            if shop_name not in grouped_orders:
                grouped_orders[shop_name] = {}

            if creator not in grouped_orders[shop_name]:
                grouped_orders[shop_name][creator] = []

            grouped_orders[shop_name][creator].append(order_info)

        # 转换为最终格式
        result_data = []
        for shop, creators in grouped_orders.items():
            shop_entry = {
                "门店": shop,
                "仓库列表": [
                    {
                        "仓库": creator,
                        "菜单列表": orders_list,
                        "菜单数量": len(orders_list)  # 添加菜单数量
                    }
                    for creator, orders_list in creators.items()
                ],
                "菜单总数": sum(len(orders_list) for orders_list in creators.values()),  # 添加门店总菜单数，
                "total_quantity": sum(sum(order.get("总数量", 0) for order in orders_list) for orders_list in creators.values())  # 添加门店总商品数量
            }
            result_data.append(shop_entry)

        if not result_data:
            return ResultVO(code=200, message="无符合条件的菜单", data=[]).to_dict()

        return ResultVO(code=200, message="成功获取菜单并按门店和仓库分组", data=result_data).to_dict()



# Flask应用
app = Flask(__name__)

# 微信公众号配置（请根据实际情况修改）
WEIXIN_TOKEN = "111111"  # 替换为你的微信公众号Token
WEIXIN_APPID = "wxc0c051408ae52cf2"  # 替换为你的微信公众号appid
WEIXIN_SECRET = "f0f46eeaae3a02ac3372e18e3aa3f84a"  # 替换为你的微信公众号secret

# 菜单URL配置
MENU_URL = "http://q66b28d3.natappfree.cc/orders_page"

def verify_weixin_signature(signature, timestamp, nonce):
    """
    验证微信签名
    """
    if not all([signature, timestamp, nonce]):
        return False

    # 将token、timestamp、nonce三个参数进行字典序排序
    params = [WEIXIN_TOKEN, timestamp, nonce]
    params.sort()

    # 将三个参数字符串拼接成一个字符串进行sha1加密
    sha1 = hashlib.sha1()
    sha1.update("".join(params).encode('utf-8'))
    hashcode = sha1.hexdigest()

    # 开发者获得加密后的字符串可与signature对比，标识该请求来源于微信
    return hashcode == signature

def get_access_token():
    """
    获取微信access_token
    """
    url = f"https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={WEIXIN_APPID}&secret={WEIXIN_SECRET}"
    response = requests.get(url)
    data = response.json()
    return data.get('access_token')

def create_menu():
    """
    创建自定义菜单
    """
    access_token = get_access_token()
    if not access_token:
        logging.error("获取access_token失败")
        return False

    url = f"https://api.weixin.qq.com/cgi-bin/menu/create?access_token={access_token}"

    menu_data = {
        "button": [
            {
                "type": "view",
                "name": "菜单查询",
                "url": MENU_URL
            }
        ]
    }

    # 使用ensure_ascii=False确保中文正确编码，并指定UTF-8编码
    json_data = json.dumps(menu_data, ensure_ascii=False)
    response = requests.post(url, data=json_data.encode('utf-8'),
                           headers={'Content-Type': 'application/json; charset=utf-8'})
    result = response.json()

    if result.get('errcode') == 0:
        logging.info("菜单创建成功")
        return True
    else:
        logging.error(f"菜单创建失败: {result}")
        return False


# 简约风格的HTML模板（适合移动端，无统计信息，紧凑版）
SIMPLE_HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>菜单查询</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, 'Open Sans', 'Helvetica Neue', sans-serif;
            background-color: #f5f5f5;
            color: #333;
            line-height: 1.6;
            padding: 0;
        }

        .header {
            background: #1976d2;
            color: white;
            padding: 15px 20px;
            position: sticky;
            top: 0;
            z-index: 100;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 10px;
        }

        .header h1 {
            font-size: 1.4rem;
            font-weight: 500;
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .date-selector {
            display: flex;
            align-items: center;
            gap: 10px;
            background: rgba(255,255,255,0.2);
            padding: 5px 10px;
            border-radius: 20px;
        }

        .date-selector label {
            font-size: 0.9rem;
            white-space: nowrap;
        }

        .date-selector input {
            border: none;
            padding: 5px;
            border-radius: 4px;
            font-size: 0.9rem;
        }

        .refresh-btn {
            background: rgba(255,255,255,0.2);
            border: none;
            color: white;
            padding: 8px 15px;
            border-radius: 20px;
            font-size: 0.9rem;
            cursor: pointer;
            white-space: nowrap;
        }

        .refresh-btn:active {
            background: rgba(255,255,255,0.3);
        }

        .shop-list {
            padding: 10px;
        }

        .shop-item {
            background: white;
            margin-bottom: 12px;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }

        .shop-header {
            background: #2196f3;
            color: white;
            padding: 15px 15px;
            font-weight: 500;
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 1.1rem;
        }

        .warehouse-list {
            padding: 15px;
        }

        .warehouse-item {
            border-left: 4px solid #4caf50;
            padding: 12px 0 12px 15px;
            margin-bottom: 20px;
        }

        .warehouse-name {
            font-weight: 500;
            color: #2e7d32;
            margin-bottom: 12px;
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 1rem;
        }

        .order-list {
            padding-left: 0;
        }

        .order-item {
            background: #fafafa;
            border-radius: 6px;
            padding: 12px;
            margin-bottom: 10px;
            border: 1px solid #eee;
        }

        .order-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 8px;
            padding-bottom: 6px;
            border-bottom: 1px dashed #ddd;
        }

        .order-quantity {
            font-weight: 500;
            color: #e91e63;
            font-size: 0.9rem;
            background: #fce4ec;
            padding: 2px 8px;
            border-radius: 10px;
        }
        
        .order-number {
            font-weight: 600;
            color: #1976d2;
            font-size: 1rem;
        }

        .order-content {
            font-size: 0.95rem;
            color: #444;
            line-height: 1.5;
            word-break: break-word;
        }

        .content-line {
            display: flex;
            margin-bottom: 2px;
            padding: 1px 0;
        }

        .content-label {
            font-weight: 500;
            min-width: 55px;
            color: #666;
            font-size: 0.9rem;
        }

        .content-value {
            flex: 1;
            color: #333;
            font-size: 0.9rem;
        }

        .no-data {
            text-align: center;
            padding: 40px 20px;
            color: #999;
        }

        .no-data-icon {
            font-size: 3rem;
            margin-bottom: 15px;
            opacity: 0.3;
        }

        .timestamp {
            text-align: center;
            padding: 15px 15px;
            color: #888;
            font-size: 0.85rem;
            background: white;
            border-top: 1px solid #eee;
        }

        .loading {
            display: inline-block;
            width: 16px;
            height: 16px;
            border: 2px solid rgba(255,255,255,.3);
            border-radius: 50%;
            border-top-color: #fff;
            animation: spin 1s ease-in-out infinite;
            margin-right: 5px;
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        @media (min-width: 768px) {
            .header h1 {
                font-size: 1.6rem;
            }

            .shop-item {
                max-width: 700px;
                margin: 0 auto 15px;
            }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>📦 菜单查询</h1>
        <form id="dateForm" style="display: flex; gap: 10px;">
            <div class="date-selector">
                <label for="date">选择日期:</label>
                <input type="date" id="date" name="date" value="{{ selected_date }}">
            </div>
            <button class="refresh-btn" type="submit">
                <span id="refresh-text">🔍 查询</span>
            </button>
        </form>
    </div>

    <div class="shop-list">
        {% if data.code == 200 and data.data %}
            {% for shop in data.data %}
                <div class="shop-item">
                    <div class="shop-header">
                        <span>🏪</span>
                        <span>{{ shop.门店 }} ({{ shop.菜单总数 }}个菜单, 总计: {{ shop.total_quantity }})</span>
                    </div>
                    <div class="warehouse-list">
                        {% for warehouse in shop.仓库列表 %}
                            <div class="warehouse-item">
                                <div class="warehouse-name">
                                    <span>🏢</span>
                                    <span>{{ warehouse.仓库 }} ({{ warehouse.菜单数量 }})</span>
                                </div>
                                <div class="order-list">
                                    {% if warehouse.菜单列表 %}
                                        {% for order in warehouse.菜单列表 %}
                                            <div class="order-item">
                                                <div class="order-header">
                                                    <div>
                                                        <div class="order-number">📋 {{ order.菜单编号 }}</div>
                                                        {% if order.制单时间 %}
                                                        <div style="font-size: 0.8rem; color: #666;">制单时间: {{ order.制单时间 }}</div>
                                                        {% endif %}
                                                    </div>
                                                    {% if order.总数量 %}
                                                    <div class="order-quantity">总计: {{ order.总数量 }}</div>
                                                    {% endif %}
                                                </div>  
                                                <div class="order-content">
                                                    {% set content_lines = order.菜单内容.split('\n') %}
                                                    {% for line in content_lines %}
                                                        {% if ':' in line %}
                                                            {% set parts = line.split(':', 1) %}
                                                            <div class="content-line">
                                                                <span class="content-label">{{ parts[0] }}:</span>
                                                                <span class="content-value">{{ parts[1] }}</span>
                                                            </div>
                                                        {% else %}
                                                            <div class="content-line">
                                                                <span class="content-value">{{ line }}</span>
                                                            </div>
                                                        {% endif %}
                                                    {% endfor %}
                                                </div>
                                            </div>
                                        {% endfor %}
                                    {% else %}
                                        <div class="no-data" style="padding: 20px 0; color: #999; background: #fafafa; border-radius: 6px;">
                                            <div>📭 暂无菜单</div>
                                        </div>
                                    {% endif %}
                                </div>
                            </div>
                        {% endfor %}
                    </div>
                </div>
            {% endfor %}
        {% elif data.code == 200 %}
            <div class="no-data">
                <div class="no-data-icon">📭</div>
                <div>暂无菜单数据</div>
            </div>
        {% else %}
            <div class="no-data">
                <div class="no-data-icon">❌</div>
                <div>数据加载失败</div>
                <div style="font-size: 0.9rem; margin-top: 10px;">{{ data.message }}</div>
            </div>
        {% endif %}
    </div>

    <div class="timestamp">
        更新时间: {{ current_time }}
    </div>

    <script>
        // 设置默认日期为今天
        document.addEventListener('DOMContentLoaded', function() {
            const dateInput = document.getElementById('date');
            if (dateInput && !dateInput.value) {
                dateInput.valueAsDate = new Date();
            }
            
            // 如果URL中有日期参数，则使用该日期
            const urlParams = new URLSearchParams(window.location.search);
            const dateParam = urlParams.get('date');
            if (dateParam && dateInput) {
                dateInput.value = dateParam;
            }
        });
    </script>
</body>
</html>
"""

def format_orders_for_display(orders_data):
    """格式化菜单数据用于显示"""
    if not orders_data or orders_data.get("code") != 200:
        return orders_data

    formatted_data = orders_data.copy()
    if formatted_data.get("data"):
        for shop in formatted_data["data"]:
            for warehouse in shop.get("仓库列表", []):
                for order in warehouse.get("菜单列表", []):
                    # 对菜单内容进行简单的格式化，使其更易读
                    content = order.get("菜单内容", "")
                    if content:
                        # 将逗号分隔的内容用换行符分隔，提高可读性
                        formatted_content = content.replace(",", "\n")
                        order["菜单内容"] = formatted_content
    return formatted_data

def calculate_statistics(orders_data):
    """计算统计数据"""
    if not orders_data or orders_data.get("code") != 200 or not orders_data.get("data"):
        return {"shop_count": 0, "warehouse_count": 0, "order_count": 0}

    shop_count = len(orders_data["data"])
    warehouse_count = 0
    order_count = 0

    for shop in orders_data["data"]:
        warehouse_count += len(shop.get("仓库列表", []))
        for warehouse in shop.get("仓库列表", []):
            order_count += len(warehouse.get("菜单列表", []))

    return {
        "shop_count": shop_count,
        "warehouse_count": warehouse_count,
        "order_count": order_count
    }

@app.route('/get_menu', methods=['GET'])
def get_wechat_menu():
    """
    获取当前微信自定义菜单的接口
    """
    access_token = get_access_token()
    if not access_token:
        return jsonify({"code": 500, "message": "获取access_token失败"})

    url = f"https://api.weixin.qq.com/cgi-bin/menu/get?access_token={access_token}"
    response = requests.get(url)
    result = response.json()

    return jsonify(result)

@app.route('/wechat', methods=['GET', 'POST'])
def wechat():
    """
    微信公众号接口
    """
    signature = request.args.get('signature')
    timestamp = request.args.get('timestamp')
    nonce = request.args.get('nonce')
    echostr = request.args.get('echostr')

    # 验证URL时的GET请求处理
    if request.method == 'GET':
        if verify_weixin_signature(signature, timestamp, nonce):
            return echostr
        else:
            return "验证失败", 403

    # 用户发送消息时的POST请求处理
    elif request.method == 'POST':
        # 验证签名
        if not verify_weixin_signature(signature, timestamp, nonce):
            return "签名验证失败", 403

        # 解析XML数据
        xml_data = request.data
        root = ET.fromstring(xml_data)

        # 提取必要的字段
        from_user = root.find('FromUserName').text
        to_user = root.find('ToUserName').text
        msg_type = root.find('MsgType').text
        create_time = int(datetime.now().timestamp())

        # 处理不同类型的事件
        if msg_type == 'event':
            event = root.find('Event').text
            event_key = root.find('EventKey')

            # 处理菜单点击事件
            if event == 'CLICK' and event_key is not None and event_key.text == 'QUERY_ORDERS':
                # 获取菜单数据
                fetcher = OrderFetcher()
                result = fetcher.get_filtered_orders()

                # 构造返回结果
                if result["code"] == 200 and result["data"]:
                    response_text = "今日菜单信息：\n\n"
                    for shop_data in result["data"]:
                        response_text += f"门店: {shop_data['门店']} ({shop_data['菜单总数']}个菜单)\n"
                        for warehouse_data in shop_data['仓库列表']:
                            response_text += f"  仓库: {warehouse_data['仓库']} ({warehouse_data['菜单数量']}个菜单)\n"
                            for order in warehouse_data['菜单列表']:
                                response_text += f"    {order['菜单编号']}: {order['菜单内容']}\n"
                        response_text += "\n"
                elif result["code"] == 200:
                    response_text = "暂无符合条件的菜单"
                else:
                    response_text = f"获取菜单失败: {result['message']}"

                # 构造XML响应
                response_xml = f"""<xml>
<ToUserName><![CDATA[{from_user}]]></ToUserName>
<FromUserName><![CDATA[{to_user}]]></FromUserName>
<CreateTime>{create_time}</CreateTime>
<MsgType><![CDATA[text]]></MsgType>
<Content><![CDATA[{response_text}]]></Content>
</xml>"""
                return response_xml, {'Content-Type': 'application/xml'}

        # 处理普通文本消息
        elif msg_type == 'text':
            content = root.find('Content').text.lower()  # 转换为小写便于匹配

            # 检查是否包含"菜单"关键词
            if '菜单' in content:
                response_text = f"点击以下链接查看菜单信息：\n{MENU_URL}"

                # 构造XML响应（包含链接）
                response_xml = f"""<xml>
<ToUserName><![CDATA[{from_user}]]></ToUserName>
<FromUserName><![CDATA[{to_user}]]></FromUserName>
<CreateTime>{create_time}</CreateTime>
<MsgType><![CDATA[text]]></MsgType>
<Content><![CDATA[{response_text}]]></Content>
</xml>"""
                return response_xml, {'Content-Type': 'application/xml'}

            # 获取菜单数据
            fetcher = OrderFetcher()
            result = fetcher.get_filtered_orders()

            # 构造返回结果
            if result["code"] == 200 and result["data"]:
                response_text = "今日菜单信息：\n\n"
                for shop_data in result["data"]:
                    response_text += f"门店: {shop_data['门店']} ({shop_data['菜单总数']}个菜单)\n"
                    for warehouse_data in shop_data['仓库列表']:
                        response_text += f"  仓库: {warehouse_data['仓库']} ({warehouse_data['菜单数量']}个菜单)\n"
                        for order in warehouse_data['菜单列表']:
                            response_text += f"    {order['菜单编号']}: {order['菜单内容']}\n"
                    response_text += "\n"
            elif result["code"] == 200:
                response_text = "暂无符合条件的菜单"
            else:
                response_text = f"获取菜单失败: {result['message']}"

            # 构造XML响应
            response_xml = f"""<xml>
<ToUserName><![CDATA[{from_user}]]></ToUserName>
<FromUserName><![CDATA[{to_user}]]></FromUserName>
<CreateTime>{create_time}</CreateTime>
<MsgType><![CDATA[text]]></MsgType>
<Content><![CDATA[{response_text}]]></Content>
</xml>"""
            return response_xml, {'Content-Type': 'application/xml'}

        # 默认回复
        default_response = f"""<xml>
<ToUserName><![CDATA[{from_user}]]></ToUserName>
<FromUserName><![CDATA[{to_user}]]></FromUserName>
<CreateTime>{create_time}</CreateTime>
<MsgType><![CDATA[text]]></MsgType>
<Content><![CDATA[您好，欢迎使用菜单查询服务！发送"菜单"获取菜单查询链接，或点击菜单中的"菜单查询"获取最新菜单信息。]]></Content>
</xml>"""
        return default_response, {'Content-Type': 'application/xml'}

@app.route('/orders', methods=['GET'])
def get_orders():
    """
    直接获取菜单数据的API接口
    """
    target_date = request.args.get('date')
    fetcher = OrderFetcher()
    result = fetcher.get_filtered_orders(target_date)
    return jsonify(result)

@app.route('/orders_page', methods=['GET'])
def get_orders_page():
    """
    获取菜单数据并以网页形式展示
    """
    target_date = request.args.get('date')
    fetcher = OrderFetcher()
    result = fetcher.get_filtered_orders(target_date)
    formatted_result = format_orders_for_display(result)

    return render_template_string(
        SIMPLE_HTML_TEMPLATE,
        data=formatted_result,
        current_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        selected_date=target_date or datetime.now().strftime("%Y-%m-%d")
    )

@app.route('/create_menu', methods=['GET'])
def create_wechat_menu():
    """
    创建微信自定义菜单的接口
    """
    success = create_menu()
    if success:
        return jsonify({"code": 200, "message": "菜单创建成功"})
    else:
        return jsonify({"code": 500, "message": "菜单创建失败"})

@app.route('/', methods=['GET'])
def index():
    """
    主页 - 重定向到菜单页面
    """
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>菜单查询系统</title>
        <meta http-equiv="refresh" content="0; url=/orders_page">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {
                font-family: Arial, sans-serif;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
                background: #f5f5f5;
            }
            .loading {
                text-align: center;
                color: #666;
            }
            .spinner {
                border: 3px solid #f3f3f3;
                border-top: 3px solid #1976d2;
                border-radius: 50%;
                width: 30px;
                height: 30px;
                animation: spin 1s linear infinite;
                margin: 0 auto 15px;
            }
            @keyframes spin {
                0% { transform: rotate(0deg); }
                100% { transform: rotate(360deg); }
            }
        </style>
    </head>
    <body>
        <div class="loading">
            <div class="spinner"></div>
            <p>正在加载菜单数据...</p>
        </div>
    </body>
    </html>
    """), 200

if __name__ == "__main__":
    # 在80端口运行（需要管理员权限）
    app.run(host='0.0.0.0', port=80, debug=False)
