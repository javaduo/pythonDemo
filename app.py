from flask import Flask, request
import hashlib

app = Flask(__name__)
WECHAT_TOKEN = 'liuzs'  # 必须与公众号后台完全一致

@app.route('/wechat', methods=['GET', 'POST'])
def handle_wechat():
    if request.method == 'GET':
        # 验证签名
        signature = request.args.get('signature', '')
        timestamp = request.args.get('timestamp', '')
        nonce = request.args.get('nonce', '')
        echostr = request.args.get('echostr', '')

        tmp_list = sorted([WECHAT_TOKEN, timestamp, nonce])
        tmp_str = ''.join(tmp_list).encode('utf-8')
        calc_sig = hashlib.sha1(tmp_str).hexdigest()

        if calc_sig == signature:
            return echostr
        else:
            return '签名验证失败', 403

    # POST 消息处理（原有逻辑）
    return 'success'

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80)
