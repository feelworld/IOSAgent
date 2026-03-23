import base64

DB = "ios_ranking"
SCRIPT_ID = "69bccf342ab3aac5f6a531fa"

with open("appstore_agent.py", "r", encoding="utf-8") as f:
    code = f.read()

b64 = base64.b64encode(code.encode("utf-8")).decode("ascii")
js = f'var code = Buffer.from("{b64}", "base64").toString("utf8"); printjson(db.script_versions.updateOne({{script_id: ObjectId("{SCRIPT_ID}"), version: 1}}, {{$set: {{python_code: code}}}}));'

with open("_tmp_update.js", "w", encoding="utf-8") as f:
    f.write(js)

print(f"JS file written: {len(js)} bytes")
