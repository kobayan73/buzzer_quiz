import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

raw_url = os.environ["SUPABASE_URL"].strip()
key = os.environ["SUPABASE_SERVICE_ROLE_KEY"].strip()

# supabase-py の create_client には、https://xxxxx.supabase.co だけを渡します。
# .env に /rest/v1 まで入れてしまうと、/rest/v1/rest/v1/... のようになり、
# PGRST125: Invalid path specified in request URL が出ることがあります。
url = raw_url.rstrip("/")
if url.endswith("/rest/v1"):
    url = url[: -len("/rest/v1")]

print("SUPABASE_URL check:", url)
print("KEY check:", key[:12] + "..." + key[-6:])

supabase = create_client(url, key)

result = supabase.table("questions").select("id").limit(3).execute()

print("Supabase connection OK")
print(result.data)