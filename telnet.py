# wechat_final_fix.py
import hashlib
import time
from flask import Flask, request
import logging
import sys

# 简化日志，只记录关键信息
logging.basicConfig(level=logging.INFO,
                   format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# 必须与微信公众平台配置的Token完全一致
TOKEN = '111111'

def check_signature(signature, timestamp, nonce):
    """
    验证微信服务器签名
    """
    if not all([signature, timestamp, nonce]):
        return False

    try:
        # 将token、timestamp、nonce按字典序排序
        params = [TOKEN, timestamp, nonce]
        params.sort()

        # 拼接字符串并进行sha1加密
        raw_string = ''.join(params)
        sha1 = hashlib.sha1()
        sha1.update(raw_string.encode('utf-8'))
        hashcode = sha1.hexdigest()

        logger.info(f"Token: {TOKEN}")
        logger.info(f"Params: {params}")
        logger.info(f"Raw string: {raw_string}")
        logger.info(f"Calculated signature: {hashcode}")
        logger.info(f"Received signature: {signature}")

        return hashcode == signature
    except Exception as e:
        logger.error(f"Signature check error: {e}")
        return False

@app.route('/wechat', methods=['GET', 'POST'])
def wechat():
    """
    处理微信公众号的GET和POST请求
    """
    # 获取微信服务器发送的参数
    signature = request.args.get('signature', '')
    timestamp = request.args.get('timestamp', '')
    nonce = request.args.get('nonce', '')
    echostr = request.args.get('echostr', '')

    logger.info(f"Request method: {request.method}")
    logger.info(f"Request args: {request.args}")

    # 验证签名
    if not check_signature(signature, timestamp, nonce):
        logger.warning("Signature verification failed")
        # 微信服务器期望在验证失败时也返回空内容或特定内容
        return "", 400

    # 处理GET请求（验证服务器）
    if request.method == 'GET':
        logger.info(f"GET request - returning echostr: {echostr}")
        # 必须原样返回echostr参数，不能添加任何额外内容
        if echostr:
            return echostr
        else:
            return "", 400

    # 处理POST请求（处理消息）
    elif request.method == 'POST':
        logger.info("POST request received")
        try:
            # 获取POST数据
            data = request.data
            logger.info(f"POST data length: {len(data)}")
            if data:
                logger.info(f"POST data preview: {data[:200]}...")
        except Exception as e:
            logger.error(f"Error reading POST data: {e}")

        # 返回success表示收到消息
        return "success"

# 健康检查端点
@app.route('/')
def index():
    return f"""
    <h1>WeChat Server is Running</h1>
    <p>Current Token: {TOKEN}</p>
    <p>Server Time: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>
    <p><a href='/wechat'>Test WeChat Endpoint</a></p>
    """, 200

if __name__ == '__main__':
    # 检查端口参数
    port = 80
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass

    print(f"Starting WeChat server on port {port}")
    print(f"Token: {TOKEN}")
    print("Make sure this server is accessible from the internet via ngrok or other tunneling service")

    app.run(host='0.0.0.0', port=port, debug=False)
