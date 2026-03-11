import json

# 1. Read the raw cookies from the Brave extension
with open('raw_cookies.json', 'r') as file:
    raw_data = json.load(file)

# 2. Extract only the names and values
twikit_cookies = {}
for item in raw_data:
    name = item.get("name")
    value = item.get("value")
    if name and value:
        twikit_cookies[name] = value

# 3. Save it as cookies.json for Twikit to use
with open('cookies.json', 'w') as file:
    json.dump(twikit_cookies, file, indent=4)

print("Successfully converted cookies.json!")
