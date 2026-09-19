"""One-off script: activate a LimeSurvey survey via its RPC API,
bypassing the broken browser-based activation page entirely."""

import requests

URL = "http://localhost:8080/index.php/admin/remotecontrol"
USERNAME = "admin"
PASSWORD = "Escalent_Capstone_2026"
SURVEY_ID = 900001

def call(method, params):
    response = requests.post(URL, json={
        "method": method,
        "params": params,
        "id": 1
    })
    return response.json()["result"]

# Step 1: log in, get a session key
session_key = call("get_session_key", [USERNAME, PASSWORD])
print("Session key obtained:", session_key)

# Step 2: activate the survey
result = call("activate_survey", [session_key, SURVEY_ID])
print("Activation result:", result)

# Step 3: release the session
call("release_session_key", [session_key])
