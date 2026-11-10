# SafeJourney

AI Agent giám sát sự cố và an toàn hành trình realtime — project học tập dùng FastAPI, React, PostgreSQL/PostGIS, Redis Streams và LangGraph.

**Thư mục chính: D:\SafeJourney. Cập nhật: 10/11/2026.** Mã nguồn đã có sẵn; bắt đầu từ hướng dẫn dưới đây để chạy và phát triển tiếp.

## Bắt đầu đọc

| Tài liệu | Dùng khi nào? |
|---|---|
| [02 — Cài đặt và lập trình](docs/02-huong-dan-cai-dat-va-lap-trinh.md) | Người mới: cài máy, chạy từng thành phần, học code, test và triển khai |
| [01 — Phân tích giải pháp](docs/01-phan-tich-giai-phap.md) | Hiểu bài toán, kiến trúc và ràng buộc |
| [03 — Lộ trình phát triển](docs/03-lo-trinh-phat-trien.md) | Phân biệt phần đã có và phần cần xây tiếp |
| [04 — Làm việc với Codex](docs/04-lam-viec-voi-codex.md) | Quy ước tổ chức công việc trong project |
| [05 — Kiến trúc MVP và điểm mở rộng](docs/05-ra-soat-kien-truc-mvp.md) | Hiểu các module, tối ưu và cách nâng cấp |
| [06 — Test tải 1.000 xe](docs/06-kiem-thu-tai-1000-xe.md) | Chạy lại bài tải bằng dữ liệu giả, đọc ngưỡng PASS/FAIL |
| [07 — Kiểm chứng và khả năng mở rộng](docs/07-ket-qua-kiem-thu-va-tai.md) | Kết quả đã đo; phân tích kiến trúc tới 1.000.000 xe |
| [08 — Agent tự xử lý và HITL](docs/08-quy-trinh-operator-va-phan-cong.md) | Playbook SMS/gọi, xác nhận người nhận, duyệt khẩn và phân công |
| [09 — Công cụ và điều phối vận hành](docs/09-dieu-phoi-van-hanh-va-cong-cu-xac-dinh.md) | Chạy kịch bản lộ trình, cước, pin, sạc và phân xe |
| [10 — Dữ liệu thực và benchmark](docs/10-du-lieu-thuc-va-benchmark.md) | Tải TLC, đánh giá dự báo và đọc giới hạn dữ liệu |

Tài liệu chỉ mô tả bản hiện tại, không còn phụ lục source cũ để chép đè. Những khả năng nâng cao chưa có được đánh dấu rõ.

## Hiện có gì?

- Đăng nhập theo vai trò; giới hạn chuyến và dữ liệu SOS được phép xem.
- GPS được lưu bền vững, xử lý theo lô; luật dừng/lệch tuyến/tốc độ và watchdog mất GPS.
- Agent tự chạy SMS → gọi mô phỏng cho ca thường, chờ người nhận xác nhận và đối chiếu GPS; HITL khi chuyển khẩn. LangGraph và deadline được lưu bền vững.
- Dashboard lọc riêng nhóm xử lý/phụ trách/trạng thái ở server trước phân trang, tìm chuyến, tải tuyến riêng, đồng hồ độ mới GPS và Mapbox tùy chọn; danh sách sự cố cuộn riêng, giữ hồ sơ đang xem sau khi nhận xử lý hoặc đổi hàng đợi.
- Nhật ký sự cố, tiếp nhận/đóng sự cố, nhắc ca trực và cụm khu vực.
- Hồ sơ khẩn có gói nội dung/người nhận sẵn; operator nhận và duyệt, chọn kết quả đóng/bàn giao. Chỉ ngoại lệ cần nhập tay; owner/phiên/revision chặn thao tác cũ.
- LangGraph phối hợp bảy vai trò; công cụ Decimal kiểm tra cước/hoàn, pin/SOH/dự trữ và hàng chờ sạc; H3, OSRM tùy chọn và OR-Tools phân xe. Operator chỉ chọn chuyến/kịch bản rồi bấm chạy, có lịch sử bất biến.
- Benchmark TLC thật ngoại tuyến theo vùng–giờ, có chia tập theo thời gian, đối chứng và provenance.
- Migration có checksum, pool giới hạn và bộ đo tải open-loop độc lập.

**SMS, cuộc gọi và cứu hộ đều là mô phỏng.** LLM không có quyền tự phê duyệt. Chưa triển khai Fly.io, chưa đánh giá độ chính xác cảnh báo trên dữ liệu thực tế.

## Kiểm chứng hiện tại

**Ngày 10/11: 237/237 test PASS, không skip** — 165 backend, 17 simulator/bộ tải, 17 benchmark TLC, 38 frontend. Frontend và Docker build/runtime đạt; Chrome kiểm tra các kịch bản vận hành và lịch sử trên API thật, dữ liệu giả riêng.

Bài **1.000 xe, 2 API + 1 Detector + 1 Planner**, 5 phiên đọc HTTP, 120 giây steady đạt **14/14 ngưỡng**: 40.000/40.000 GPS, HTTP p95 **19,034 ms**, Detector p95 **44,706 ms**, tồn đọng cuối **0**. [Báo cáo 07](docs/07-ket-qua-kiem-thu-va-tai.md) lưu cấu hình, JSON và fingerprint hiện tại. Chưa đo tải solver/LLM đồng thời với GPS hoặc một triệu xe.

TLC thực: 48.326 hàng, giữ 48.160 lượt đón. Seasonal mean WAPE 55,26% theo vùng–giờ, 13,17% tổng thành phố trên tuần cuối. [Tài liệu 10](docs/10-du-lieu-thuc-va-benchmark.md) giải thích phương pháp và giới hạn; TLC không có chuỗi GPS/SOS, không chứng minh độ chính xác cảnh báo an toàn.

**Pin/trạm/thời tiết/fleet trong dashboard là mô phỏng; phương án vận hành chưa phân xe hay chuyển tiền thật.** OSRM mặc định chưa cấu hình, tuyến được ghi rõ chưa xác minh đường bộ. Phân tích 1.000.000 xe và đường mở rộng nằm trong [07](docs/07-ket-qua-kiem-thu-va-tai.md#million-vehicles).

Nếu đã cài bản trước: dừng API/Detector/Planner, cập nhật Conda từ `environment.yml`, chạy `python -m app.db` trong backend và `npm.cmd ci` trong frontend, rồi khởi động lại. Migration **007** thêm memory vận hành, giữ các migration và hồ sơ cũ. Làm theo [hướng dẫn nâng cấp 09](docs/09-dieu-phoi-van-hanh-va-cong-cu-xac-dinh.md#2-cập-nhật-project-đã-cài-từ-trước).

## Chạy lần đầu

Dùng Anaconda đang có, Node 24 LTS và Docker Desktop theo [mục 2 hướng dẫn](docs/02-huong-dan-cai-dat-va-lap-trinh.md#g02). Mở **Anaconda PowerShell Prompt**:

~~~powershell
Set-Location 'D:\SafeJourney'
conda env create -f environment.yml
conda activate safejourney
python --version
if (-not (Test-Path .\backend\.env)) { Copy-Item .\backend\.env.example .\backend\.env }
if (-not (Test-Path .\frontend\.env)) { Copy-Item .\frontend\.env.example .\frontend\.env }
~~~

Lệnh tạo môi trường chỉ chạy lần đầu; nếu safejourney đã có, dùng conda activate safejourney. [environment.yml](environment.yml) cài Python 3.12 và đầy đủ thư viện backend, simulator, test và đo tải từ các file requirements. Không cài vào môi trường base. Sửa backend/.env, đặt DEMO_PASSWORD ít nhất 12 ký tự. Sau đó:

~~~powershell
docker compose up -d --wait
Set-Location .\backend
python -m app.db
python -m app.seed
Set-Location ..\frontend
npm.cmd ci
~~~

Mở bốn terminal riêng. Trong **mỗi terminal chạy Python**, thực hiện conda activate safejourney trước lệnh ở bảng:

| Thành phần | Thư mục | Lệnh |
|---|---|---|
| API | D:\SafeJourney\backend | python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 |
| Detector | D:\SafeJourney\backend | python -m app.worker |
| Planner | D:\SafeJourney\backend | python -m app.planner |
| Giao diện | D:\SafeJourney\frontend | npm.cmd run dev |

Mở **http://localhost:5173**, đăng nhập operator bằng mật khẩu đã seed. Simulator chạy trong terminal thứ năm:

~~~powershell
Set-Location 'D:\SafeJourney'
conda activate safejourney
python .\simulator.py --scenario normal --seconds 60
~~~

Kiểm tra đúng Python bằng python -c "import sys; print(sys.executable)"; đường dẫn phải thuộc môi trường safejourney. Các kịch bản khác: stop, deviation, speed, sos. Không có Mapbox token vẫn sử dụng được danh sách/SOS/HITL.

## Cấu trúc cần giữ

~~~text
environment.yml      Môi trường Conda safejourney / Python 3.12
backend/app/          API, bảo mật, dữ liệu, detector, planner
backend/migrations/  SQL nâng cấp theo thứ tự; không sửa file đã áp dụng
backend/tests/       Unit và integration
frontend/src/        React và Mapbox
frontend/tests/      Logic giao diện
load_tests/          Stack riêng 25432/26379/18000 và runner
research_benchmarks/ TLC ngoại tuyến, raw data được Git bỏ qua
tests/               Test simulator
docs/                Tài liệu 01–10 và bằng chứng kiểm chứng
simulator.py         GPS/SOS giả lập, giữ tại root
compose.yaml         PostgreSQL/Redis demo local
Dockerfile           Image ứng dụng, user không phải root
fly.toml.example     Mẫu ba process group, chưa deploy
~~~

Secrets chỉ ở file .env bị Git bỏ qua. Không chạy integration/load trên database thật. Hướng dẫn test tại [mục 12](docs/02-huong-dan-cai-dat-va-lap-trinh.md#g12).

Chạy lại bài 1.000 xe sau khi đọc tài liệu 06:

~~~powershell
Set-Location 'D:\SafeJourney'
conda activate safejourney
python -m load_tests.local --api-workers 2 --allow-local-loadtest
~~~

