import os
from .db import connect
from .security import hash_password

def main():
    password = os.environ.get('DEMO_PASSWORD', '')
    if len(password) < 12:
        raise SystemExit('Đặt DEMO_PASSWORD ít nhất 12 ký tự trong backend/.env')
    with connect() as conn:
        for name, role in [('operator','operator'),('operator2','operator'),('driver','driver'),('passenger','passenger'),('driver2','driver'),('passenger2','passenger')]:
            conn.execute('INSERT INTO users(id,username,password_hash,role) VALUES (%s,%s,%s,%s) ON CONFLICT (id) DO UPDATE SET password_hash=excluded.password_hash', (name, name, hash_password(password), role))
        for trip_id, driver, passenger in [('trip-001','driver','passenger'),('trip-002','driver2','passenger2')]:
            conn.execute("INSERT INTO trips(id,label,driver_id,passenger_id,route_geom) VALUES (%s,%s,%s,%s,ST_GeomFromText('LINESTRING(106.7000 10.7700,106.7000 10.7900)',4326)) ON CONFLICT DO NOTHING", (trip_id, trip_id, driver, passenger))
    print('Seed ready: operator, operator2, driver, passenger, driver2, passenger2; password from DEMO_PASSWORD')

if __name__ == '__main__':
    main()
