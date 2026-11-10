# Dot-source this file in every load-test terminal: . .\load_tests\env.ps1
# These are local synthetic-test credentials, never production credentials.
$env:LOADTEST_DATABASE_URL = 'postgresql://loadtest:local_loadtest_only@127.0.0.1:25432/safejourney_loadtest'
$env:DATABASE_URL = $env:LOADTEST_DATABASE_URL
$env:CHECKPOINT_DATABASE_URL = $env:LOADTEST_DATABASE_URL
$env:REDIS_URL = 'redis://127.0.0.1:26379/0'
$env:ALLOWED_ORIGINS = 'http://localhost:5173'
$env:COOKIE_SECURE = 'false'
$env:LLM_MODE = 'mock'
$env:GPS_LOST_SECONDS = '60'
$env:STOP_SECONDS = '180'
$env:DEVIATION_SECONDS = '45'
$env:SPEED_SECONDS = '10'
