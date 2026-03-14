from napcat_api_reference.napcat_api import NapCatAPI
api = NapCatAPI()
api.connect()
api.send_private_msg(user_id="1139674593", message="你好")
api.close()
