"""Update appstore_agent.py script in MongoDB via SCP + remote mongosh."""
import subprocess

KEY = r"C:\Users\xiong\Downloads\ios ranking system.pem"
HOST = "ubuntu@13.215.194.223"
SSH = ["ssh", "-o", "StrictHostKeyChecking=no", "-i", KEY, HOST]
SCP = ["scp", "-o", "StrictHostKeyChecking=no", "-i", KEY]
DB = "ios_ranking"
SCRIPT_ID = "69bccf342ab3aac5f6a531fa"

# Step 1: Upload script file to server
print("1. Uploading appstore_agent.py to server ...")
r = subprocess.run(SCP + ["appstore_agent.py", f"{HOST}:/tmp/appstore_agent.py"],
                   capture_output=True, text=True, errors="replace")
if r.returncode != 0:
    print("   SCP failed:", r.stderr[:300])
    exit(1)
print("   OK")

# Step 2: Copy file into MongoDB container
print("2. Copying into MongoDB container ...")
r = subprocess.run(
    SSH + ["docker cp /tmp/appstore_agent.py iosagent-mongodb-1:/tmp/appstore_agent.py"],
    capture_output=True, text=True, errors="replace",
)
if r.returncode != 0:
    print("   docker cp failed:", r.stderr[:300])
    exit(1)
print("   OK")

# Step 3: Write JS update script on server
print("3. Writing JS update script ...")
js_content = """var fs = require("fs");
var code = fs.readFileSync("/tmp/appstore_agent.py", "utf8");
var r = db.script_versions.updateOne(
  {script_id: ObjectId("SCRIPT_ID"), version: 1},
  {$set: {python_code: code}}
);
printjson(r);
""".replace("SCRIPT_ID", SCRIPT_ID)

r = subprocess.run(
    SSH + [f"cat > /tmp/update_mongo.js << 'ENDJS'\n{js_content}\nENDJS"],
    capture_output=True, text=True, errors="replace",
)

# Step 4: Execute JS in mongosh
print("4. Updating MongoDB ...")
r = subprocess.run(
    SSH + [f"docker exec -i iosagent-mongodb-1 mongosh --quiet {DB} < /tmp/update_mongo.js"],
    capture_output=True, text=True, errors="replace",
)
out = r.stdout.strip()
if "modifiedCount: 1" in out or "modifiedCount: 0" in out:
    print("   SUCCESS:", out[-200:])
else:
    print("   Output:", out[:300])
    if r.stderr:
        print("   ERR:", r.stderr.strip()[:300])
