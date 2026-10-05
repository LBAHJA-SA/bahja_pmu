import sys
sys.path.insert(0, r'C:\bahja-pmu\backend')
from app import app
with app.test_client() as c:
    resp = c.post('/api/auth/login', json={'phone':'admin','password':'admin','device_id':'test'})
    print('Status:', resp.status_code)
    print('Response:', resp.get_json())