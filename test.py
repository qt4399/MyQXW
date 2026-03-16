from qq_api_reference.napcat_api import NapCatAPI

with NapCatAPI() as api:
    # 发送图片（支持三种方式）
    
    # 1. 本地文件路径
    message = [
        {"type": "image", "data": {"file": "/home/qintao/agent/hl/MyQXW/1.jpg"}},
        {"type": "text", "data": {"text": "这是一张图片"}}
    
    ]

    # # 3. Base64 编码
    # message = [{"type": "image", "data": {"file": "base64://iVBORw0KGgo..."}}]
    
    api.send_private_msg(user_id="1139674593", message=message)