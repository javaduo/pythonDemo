import requests
import logging
import random
import json
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

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

    def login(self):
        """登录并维持会话"""
        response = self.session.post(self.login_url, data=self.login_data, headers=self.headers, allow_redirects=False)
        if response.status_code in [301, 302]:
            redirect_url = response.headers.get('Location')
            full_url = 'https://e.jwsaas.com' + redirect_url if redirect_url.startswith('/') else redirect_url
            self.session.get(full_url)
        return response.status_code == 200

    def fetch_orders(self):
        """获取订单并过滤"""
        today = datetime.today()
        monday = today - timedelta(days=today.weekday())
        sunday = monday + timedelta(days=6)
        data1 = monday.strftime('%Y-%m-%d')
        data2 = sunday.strftime('%Y-%m-%d')

        data = {
            'searchFields': 'no,description',
            'storeId': '',
            'filter': json.dumps([{
                "name": "setDate",
                "type": "range",
                "key": "setDate",
                "data1": data1,
                "data1Type": "",
                "data2": data2,
                "data2Type": ""
            }]),
            '_search': 'false',
            'rows': '20',
            'page': '1',
            'sidx': '',
            'sord': 'asc',
            'keyword': ''
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
                today_date = datetime.today().date()
                filter_time = datetime.strptime(f"{today_date} 19:00:00", "%Y-%m-%d %H:%M:%S")

                return [
                    row for row in rows
                    if datetime.strptime(row['createDate'], "%Y-%m-%d %H:%M:%S") > filter_time
                ]
            except requests.exceptions.JSONDecodeError:
                logging.error("订单列表响应不是有效的 JSON")
        else:
            logging.error("订单列表请求失败，状态码: %d", response.status_code)
        return []

    def fetch_order_items(self, order_id):
        """获取订单明细数据"""
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
                logging.error("订单详情响应不是有效的 JSON，订单ID: %s", order_id)
        else:
            logging.error("获取订单详情失败，状态码: %d，订单ID: %s", response.status_code, order_id)
        return []

    def get_order_details(self, order_id):
        """获取订单详情"""
        detail_url = f"{self.detail_url}{order_id}?t={random.random()}"
        response = self.session.get(detail_url)

        if response.status_code != 200:
            logging.error("获取订单页面失败，状态码: %d，订单ID: %s", response.status_code, order_id)
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

        # 精确匹配前缀（只取前4位）
        prefix = shop_name[:4] if len(shop_name) >= 4 else shop_name
        shop_name = shop_mapping.get(prefix, "未知门店")

        no = soup.find("input", id="no")
        no_value = no.get("value") if no and no.has_attr("value") else "未知单据编号"

        items = self.fetch_order_items(order_id)
        result_parts = []
        for item in items:
            description = item.get('description', '')
            product_name = item.get('productName', '未知产品')
            quantity = item.get('quantity', 0)
            unit_name = item.get('unitName', '')
            result_parts.append(f"{product_name}:{quantity}{unit_name}{f'({description})' if description else ''}")

        full_result = ",".join(result_parts)

        return {
            "订单编号": no_value,
            "仓库编号": selected_value,
            "门店": shop_name,
            "仓库": warehouse,
            "订单内容": full_result
        }

    def get_filtered_orders(self):
        """对外接口：获取并返回格式化订单信息，封装为 ResultVO，并按门店、仓库分组"""
        if not self.login():
            logging.error("登录失败")
            return ResultVO(code=401, message="登录失败").to_dict()

        orders = self.fetch_orders()
        grouped_orders = {}  # 按门店 -> 仓库 分组

        for row in orders:
            order_id = row.get('id')
            if not order_id:
                continue
            order_detail = self.get_order_details(order_id)
            if order_detail:
                shop_name = order_detail.get("门店")
                creator = order_detail.get("仓库")
                order_info = {
                    "订单编号": order_detail["订单编号"],
                    "订单内容": order_detail["订单内容"]
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
                        "订单列表": orders_list
                    }
                    for creator, orders_list in creators.items()
                ]
            }
            result_data.append(shop_entry)

        if not result_data:
            return ResultVO(code=200, message="无符合条件的订单", data=[]).to_dict()

        return ResultVO(code=200, message="成功获取订单并按门店和仓库分组", data=result_data).to_dict()


# 主程序入口
if __name__ == "__main__":
    fetcher = OrderFetcher()
    result = fetcher.get_filtered_orders()
    print(json.dumps(result, indent=2, ensure_ascii=False))
