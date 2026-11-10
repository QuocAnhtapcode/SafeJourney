# SafeJourney — kiểm thử tải 1.000 xe

**Cập nhật: 10/11/2026.** Bộ test nằm trong load_tests/. Lượt gần nhất 1.000 xe trong Conda đạt 14/14 ngưỡng trên bản có bộ lọc hàng đợi và module vận hành, run-id **run-20261109-234632-edee**. Xem [07](07-ket-qua-kiem-thu-va-tai.md) và JSON nguyên bản. Đây là tải GPS normal/HTTP, chưa phải bài tải playbook, SOS, phản hồi người nhận hoặc solver/LLM/OSRM vận hành đồng thời. Benchmark TLC ngoại tuyến được hướng dẫn riêng ở [10](10-du-lieu-thuc-va-benchmark.md).

## 1. Bài test đo điều gì?

1.000 tài xế đăng nhập qua `/api/login`, mỗi người có một chuyến riêng. Mỗi xe gửi một bản tin GPS mỗi 3 giây: tải ổn định mục tiêu **1.000 / 3 = 333,33 request telemetry/giây**. Đăng nhập diễn ra trước khoảng đo tải.

Mặc định runner bổ sung **5 phiên đọc kiểu nhân viên**: mỗi giây mỗi phiên gọi danh sách vị trí, sự cố và cụm sự cố — thêm khoảng 15 GET/giây. Các phiên dùng token operator thật. Đây là tải HTTP mô phỏng dashboard; không mở 5 trình duyệt và không đo render/WebSocket.

Lịch gửi là open-loop: thời điểm bản tin tiếp theo không chờ request trước hoàn tất. Nếu máy sinh tải không theo kịp hoặc chạm giới hạn request đang chờ, báo cáo ghi `dropped_late`/`dropped_capacity` và đánh trượt. Nhờ vậy không báo đạt bằng cách âm thầm gửi ít hơn mục tiêu.

Bộ sinh tải kiểm tra lại đồng hồ sau mỗi lần hẹn giờ, tránh gửi sớm do timer Windows thức dậy trước hạn. HTTP viewers lấy chuyến ACTIVE và không lấy hình học tuyến, giống dashboard mặc định. Báo cáo schema 3 lưu fingerprint nguồn; code thay đổi trong lúc chạy sẽ làm gate tương ứng thất bại.

GPS mô phỏng chuyển động trên tuyến hợp lệ, không dừng, không vượt tốc độ. Tất cả xe dùng cùng hình học tuyến để đo pipeline; đây không phải dữ liệu giao thông thực tế. Mặc định không bật LLM thật hoặc tạo bão SOS.

## 2. Môi trường tách biệt

| Thành phần | Địa chỉ |
|---|---|
| API test | `http://127.0.0.1:18000` |
| PostgreSQL/PostGIS | `127.0.0.1:25432`, database `safejourney_loadtest` |
| Redis | `127.0.0.1:26379`, DB 0 |
| Compose project | `safejourney-loadtest` |
| Dữ liệu giả | Prefix `sjlt-<run-id>-` |
| Báo cáo | `load_tests/reports/<run-id>.json` |
| Log dịch vụ | `.work/loadtest/<run-id>/` |

Lệnh seed và sinh tải từ chối host bên ngoài, database khác, API port khác hoặc thiếu cờ `--allow-local-loadtest`. Có kiểm tra token đầu tiên thực sự nằm trong database test trước khi gửi đăng nhập toàn đội xe. Bộ test không dùng mật khẩu demo của bạn và không ghi password/token vào báo cáo.

## 3. Chuẩn bị

Mở Docker Desktop và **Anaconda PowerShell Prompt**. Nếu chưa tạo môi trường project, chạy từ gốc:

```powershell
Set-Location 'D:\SafeJourney'
conda env create -f environment.yml
conda activate safejourney
python --version
```

Nếu safejourney đã có, chỉ cần conda activate safejourney. environment.yml đã cài load_tests/requirements.txt, gồm backend, pytest và aiohttp; khi file requirements được cập nhật, chạy python -m pip install -r .\load_tests\requirements.txt trong đúng môi trường này. Docker runtime không cài aiohttp của bộ sinh tải. Máy cần đủ RAM cho Windows, Docker và Python; đo trên máy dùng chung với trình sinh tải sẽ có tranh chấp tài nguyên.

Nếu terminal biết lệnh conda nhưng chưa activate được, thay tiền tố python bằng conda run --no-capture-output -n safejourney python; vẫn giữ đúng thư mục làm việc và env test. Không gọi Python trong .venv.

Transport mặc định dùng [aiohttp ClientSession](https://docs.aiohttp.org/en/stable/client_reference.html) với pool kết nối và cookie được gắn riêng theo tài xế. Bộ chạy thủ công vẫn nhận `--http-client httpx` để so sánh ảnh hưởng của trình sinh tải; trường `configuration.http_client` trong báo cáo ghi transport thực tế.

## 4. Chạy nhanh để kiểm tra cài đặt

```powershell
python -m load_tests.local --vehicles 20 --ramp 3 --warmup 3 --duration 9 --operator-viewers 2 --allow-local-loadtest
```

Runner dùng sys.executable để các tiến trình con chạy đúng Python Conda của nó. Runner tự khởi động database/Redis test, áp dụng migration, tạo run-id và mật khẩu ngẫu nhiên trong bộ nhớ, seed, bật API/Detector/Planner, chạy bài thử và ghi báo cáo. Sau bài thử, các tiến trình API/Detector/Planner do runner tạo sẽ dừng; database, Redis và dữ liệu đo được giữ để xem lại.

## 5. Chạy 1.000 xe

Cấu hình đã đo đạt trong Conda ngày 10/11/2026 dùng **hai API workers**, theo lệnh dưới đây. Nếu không truyền --api-workers, runner mặc định một API; cấu hình đó chưa được đo lại trong lần rà soát hiện tại. Kết quả trên máy khác phải đọc từ báo cáo thực tế.

```powershell
python -m load_tests.local --api-workers 2 --allow-local-loadtest
```

Thông số mặc định, ngoại trừ số API được chọn rõ bằng --api-workers:

| Thông số | Giá trị |
|---|---|
| Xe/chuyến/tài xế | 1.000 |
| Chu kỳ GPS | 3 giây |
| Ramp | 30 giây |
| Warmup | 30 giây |
| Khoảng đo steady | 120 giây |
| Đợi xử lý tồn đọng | Tối đa 60 giây |
| API / Detector / Planner | Lệnh trên: 2 / 1 / 1; API mặc định CLI: 1 |
| Pool mỗi tiến trình | Min 2, max 16 |
| Lô telemetry | Tối đa 200 bản tin |
| Đồng thời đăng nhập | 4 |
| Timeout mỗi lần đăng nhập trước khoảng đo | 30 giây |
| Timeout request trong khoảng đo | 5 giây |
| Request telemetry đang chờ | Tối đa 256 |
| Phiên đọc nhân viên | 5, mỗi phiên 3 GET/giây |

Thời gian chạy thực tế còn có khởi động dịch vụ và đăng nhập. Với cấu hình này, khoảng steady dự kiến có **40.000 bản tin GPS**; báo cáo còn chứa dữ liệu ramp/warmup.

Muốn thử một API, giữ nguyên các thông số khác và đọc kết quả mới:

```powershell
python -m load_tests.local --api-workers 1 --allow-local-loadtest
```

Muốn đo 600 giây ở cấu hình một API: chạy riêng `python -m load_tests.local --duration 600 --allow-local-loadtest`. Đổi duy nhất một yếu tố mỗi lần để biết nguyên nhân thay đổi. Chạy dài hơn tiêu thụ dung lượng PostgreSQL; dữ liệu không tự xóa sau bài test.

## 6. Đọc báo cáo

| Trường | Ý nghĩa |
|---|---|
| `target_steady_requests_per_second` | Tải GPS dự kiến |
| `observed_steady_sent_per_second` | Số request thực sự đã phát trên khoảng steady |
| `observed_steady_accepted_per_second` | Số phản hồi durable thành công trên khoảng steady |
| `http.steady.request_latency_ms` | p50/p95/p99/max của HTTP, gồm chờ connection phía client |
| `schedule_to_response_ms` | Độ trễ tính từ lịch dự kiến, bao gồm chậm của bộ sinh tải |
| `scheduling_lag_ms` | Máy sinh tải chậm bao lâu so với lịch |
| `dropped_*` | Bản tin theo lịch chưa được gửi; không được bỏ qua chỉ số này |
| `database.*.received_to_processed_ms` | Từ khi server ghi nhận đến lúc Detector đánh dấu xử lý trong transaction |
| `processing_results` | APPLIED, STALE, OUT_OF_ORDER, INACTIVE hoặc pending |
| `incidents_by_kind` | Sự cố phát sinh trong đội xe của lần thử; kịch bản bình thường mong đợi rỗng |
| `backlog_samples` | Số lượng và tuổi bản tin chưa xử lý theo thời gian |
| `operator_http` | Độ trễ/lỗi/dropped của các GET nhân viên mô phỏng |
| `gates` và `passed` | Điều kiện đạt riêng lẻ và kết quả tổng |
| `service_configuration` | Số tiến trình và các cấu hình do runner áp dụng |
| `measured_source` | SHA-256 và số file nguồn tại đầu bài đo |
| `source_unchanged_during_run` | Gate fingerprint đầu/cuối khớp; không sửa code khi đang đo |

`processed_at` được ghi bằng `clock_timestamp()` ở cuối xử lý lô, trước commit. Chỉ các dòng đã commit mới được truy vấn thấy; số đo chưa bao gồm chính xác toàn bộ thời gian commit/fsync và không bao gồm truyền tới trình duyệt. Không gọi đây là độ trễ cảnh báo end-to-end.

Request timeout có thể đã commit ở server. Bộ sinh tải không tự retry, nên số database nhận có thể lớn hơn số phản hồi thành công; báo cáo giữ sự khác biệt này. Khoảng steady của HTTP dựa trên lịch gửi, còn khoảng steady của database dựa trên thời gian server nhận, vì vậy tập mẫu có thể lệch ở ranh giới.

Trong khi chạy, monitor chỉ lấy count, backlog và tuổi bản tin; phân vị chi tiết được tính sau giai đoạn phát tải/drain để giảm truy vấn nặng lặp lại. Fingerprint đọc các file nguồn được chọn trong common.py, không đọc .env, dữ liệu hay báo cáo. Fingerprint không thay cho Git commit, dependency lock hoặc mô tả tài nguyên máy.

## 7. Ngưỡng đạt mặc định

- Có request steady; lỗi HTTP không quá 0,1%.
- Không bỏ bản tin theo lịch vì trễ hoặc quá nhiều request chờ.
- HTTP p95 không quá 250 ms; Detector processing p95 không quá 2.000 ms.
- Backlog cuối bài bằng 0; số dòng đã nhận không thấp hơn số phản hồi durable thành công.
- Mọi bản tin đã nhận có kết quả APPLIED, không chỉ có `processed_at`.
- Kịch bản bình thường không phát sinh sự cố cho đội xe đang thử.
- Nếu có phiên nhân viên: không dropped GET, lỗi không quá 0,1%, p95 không quá 250 ms.
- Không có lỗi lấy mẫu database; fingerprint nguồn đầu/cuối không đổi.

Đây là **ngưỡng kỹ thuật ban đầu cho bài thực hành**, không phải SLA đã cam kết. Exit code 0 là PASS, 1 là không đạt một ngưỡng, 2 là bài chạy bị hủy ở công cụ sinh tải. Nếu bộ sinh tải bị hủy sau khi khởi động, runner local giữ báo cáo `status: ABORTED` và `passed: false`; đây không phải số đo tải hoàn chỉnh. Nếu lỗi xảy ra ngay lúc khởi tạo, có thể chưa có JSON. Đọc log dịch vụ và `runner.log` khi có; không có báo cáo không có nghĩa đã đạt.

## 8. Chạy thủ công để điều chỉnh sâu

Mỗi terminal Python phải kích hoạt safejourney rồi nạp biến môi trường test. Ví dụ chuẩn bị schema:

```powershell
Set-Location 'D:\SafeJourney'
conda activate safejourney
docker compose -f .\load_tests\compose.yaml up -d --wait
. .\load_tests\env.ps1
Set-Location backend
python -m app.db
```

Mở **ba terminal mới**, mỗi terminal đều chạy các dòng chuẩn bị sau:

```powershell
Set-Location 'D:\SafeJourney'
conda activate safejourney
. .\load_tests\env.ps1
Set-Location backend
```

Sau đó chạy đúng một lệnh tương ứng ở mỗi terminal:

| Terminal | Lệnh |
|---|---|
| API test | `python -m uvicorn app.main:app --host 127.0.0.1 --port 18000 --no-access-log` |
| Detector test | `python -m app.worker` |
| Planner test | `python -m app.planner` |

Tại **terminal thứ tư**, quay về root, tạo một mật khẩu chỉ cho fixture và giữ nguyên trong terminal seed/run:

```powershell
Set-Location 'D:\SafeJourney'
conda activate safejourney
. .\load_tests\env.ps1
$env:LOADTEST_PASSWORD = [guid]::NewGuid().ToString()
$runId = 'manual-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
python -m load_tests.seed --run-id $runId --vehicles 1000 --allow-local-loadtest
python -m load_tests.run --run-id $runId --vehicles 1000 --operator-viewers 5 --viewer-interval 1 --allow-local-loadtest
```

Không tái sử dụng run-id: seed không ghi đè fixture; runner chỉ kích hoạt chuyến PLANNED của lần chạy mới. Khi kết thúc, các chuyến đó thành FINISHED. Nếu bài chạy bị ngắt đột ngột, kiểm tra đúng run-id và chỉ kết thúc các chuyến giả của lần đó trước khi chạy lại.

**Phục hồi sau khi ngắt bài test:** dừng API/Detector/Planner test bằng Ctrl+C ở đúng terminal. Lấy run-id từ dòng `Created 1000 synthetic trips; run-id=...` hoặc tên thư mục `.work/loadtest/`. Thay giá trị ví dụ dưới bằng run-id đó; lệnh đầu chỉ đọc:

```powershell
Set-Location 'D:\SafeJourney'
conda activate safejourney
. .\load_tests\env.ps1
$runId = 'run-YYYYMMDD-HHMMSS-xxxx' # Thay bằng run-id thực tế, không giữ nguyên ví dụ.
python -m load_tests.recover --run-id $runId --allow-local-loadtest
# Sau khi đối chiếu đúng lần thử, kết thúc riêng các chuyến ACTIVE của nó:
python -m load_tests.recover --run-id $runId --finish --allow-local-loadtest
```

Công cụ từ chối database ngoài stack local, không xóa dữ liệu và chỉ cập nhật prefix đúng run-id. Chuyến PLANNED của lần lỗi trước bước phát tải không chặn lần chạy mới. Không dùng tiện ích này cho fixture integration hoặc prefix khác. Integration sử dụng database riêng theo mục 12.2 tài liệu 02.

## 9. Kiểm thử bộ sinh tải và hồi quy

Từ root, sau conda activate safejourney:

```powershell
python -m pytest .\load_tests\tests -q
```

Để chạy integration test backend, dừng API/Detector/Planner test trước. Nạp env test, đặt mật khẩu ngẫu nhiên cho tài khoản demo trong database test, migrate và seed rồi bật `RUN_DEMO_TESTS=1`. Chi tiết đã được cập nhật ở mục 12.2 tài liệu 02. Không chạy backend integration đồng thời với bài tải vì chúng thay đổi dữ liệu thử.

## 10. Giới hạn và bài thử tiếp theo

- Bài này đo đường GPS bình thường và HTTP đọc, chưa đo độ chính xác phân loại, bão SOS, hành động khẩn hay chất lượng LLM.
- Chưa đo 1.000 WebSocket, render Mapbox, mạng di động, packet loss, retry/offline upload hoặc failover Redis/PostgreSQL.
- Một máy cùng chạy API, worker, Docker và bộ sinh tải chỉ cho baseline local. Muốn khẳng định năng lực production cần staging và máy sinh tải riêng, cấu hình tài nguyên cố định, nhiều lần chạy và soak test.
- Dữ liệu các lần chạy trước vẫn nằm trong database test. HTTP viewers dùng active_only=true, giống dashboard; API giữ lựa chọn xem tất cả chuyến. Các bảng sự cố/inbox/checkpoint vẫn tích lũy, nên kết quả trên database dùng lại khác baseline sạch. Không xóa volume chứa dữ liệu cần giữ.
- Nếu muốn dừng hai dịch vụ test sau khi xem kết quả: `docker compose -f load_tests/compose.yaml stop` từ gốc project. Lệnh này giữ volume và không dừng Compose demo.

Harness hiện giới hạn tối đa 10.000 xe local; đây là giới hạn công cụ, không phải công suất đã xác nhận của ứng dụng. Quy mô 100.000–1.000.000 cần harness staging phân tán riêng, không chỉ tăng tham số hoặc bỏ guard. Xem [phân tích một triệu xe trong báo cáo 07](07-ket-qua-kiem-thu-va-tai.md#million-vehicles) cho giả định, giới hạn code và điều kiện kiểm chứng từng mốc.
