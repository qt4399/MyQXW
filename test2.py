from qq_api_reference.napcat_api import NapCatAPI

with NapCatAPI() as api:
    api.upload_private_file(
        user_id=1139674593,
        file="/home/qintao/agent/hl/MyQXW/1.jpg",
    )
