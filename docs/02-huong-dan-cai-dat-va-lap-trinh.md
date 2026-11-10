# SafeJourney — hướng dẫn cài đặt và lập trình

**Cập nhật: 10/11/2026.** Đây là hướng dẫn cho mã nguồn hiện tại trong **D:\SafeJourney**. Bạn sử dụng trực tiếp các file của project; tài liệu không chứa bản sao toàn bộ source để chép đè. Các đoạn lệnh dưới đây dành cho **Anaconda PowerShell Prompt trên Windows**, hoặc PowerShell đã nạp Conda. Project dùng môi trường **safejourney, Python 3.12**.

Mục tiêu sau khi thực hành: tự chạy dashboard, gửi GPS/SOS giả, kiểm tra kịch bản cước/pin/phân xe, hiểu đường đi của dữ liệu, sửa một chức năng, chạy kiểm thử và chuẩn bị triển khai. Mọi SMS/cuộc gọi/cứu hộ trong project đều là **mô phỏng**. Phương án vận hành chưa tạo giao dịch tiền hoặc phân xe thật; chi tiết ở [09](09-dieu-phoi-van-hanh-va-cong-cu-xac-dinh.md), dữ liệu thực ngoại tuyến ở [10](10-du-lieu-thuc-va-benchmark.md).

## Mục lục

1. [Hiểu các thành phần](#g01)
2. [Cài công cụ](#g02)
3. [Thư mục và cách dùng terminal](#g03)
4. [Cài thư viện và cấu hình](#g04)
5. [Khởi tạo dữ liệu](#g05)
6. [Chạy ứng dụng](#g06)
7. [Đăng nhập và sử dụng dashboard](#g07)
8. [Thử GPS, SOS và HITL](#g08)
9. [Đọc và sửa backend](#g09)
10. [Đọc và sửa frontend](#g10)
11. [Mapbox và LLM tùy chọn](#g11)
12. [Chạy kiểm thử](#g12)
13. [Đo tải 1.000 xe](#g13)
14. [Docker và Fly.io](#g14)
15. [Xử lý lỗi thường gặp](#g15)
16. [Quy trình phát triển tiếp](#g16)
17. [Tiêu chí hoàn thành](#g17)

<a id="g01"></a>
## 1. Hiểu các thành phần

| Thành phần | Nói đơn giản | Chạy bằng gì? |
|---|---|---|
| Frontend | Trang web nhân viên/tài xế/hành khách sử dụng | React + Vite |
| API | Cổng đăng nhập, nhận GPS/SOS và xử lý quyết định | FastAPI |
| PostgreSQL/PostGIS | Lưu tài khoản, chuyến, tọa độ, sự cố, nhật ký | Docker local |
| Redis | Hàng chờ thông báo có bản tin GPS cần xử lý | Docker local |
| Detector | Đọc GPS, áp dụng luật, tạo cảnh báo | Tiến trình Python riêng |
| Planner | Tự chạy playbook thường, chờ xác nhận; chuyển HITL khi khẩn | Python + LangGraph |
| Simulator | Tạo tín hiệu của một xe để thực hành | Python tại gốc project |
| Bộ sinh tải | Tạo 1.000 tài xế/chuyến giả và đo hiệu năng | Thư mục load_tests |
| Kiểm tra vận hành | LangGraph chạy công cụ tuyến/cước/pin/sạc/nhu cầu/phân xe theo kịch bản | Trong API, module app/operations; không có tiến trình riêng |
| Benchmark dữ liệu thực | Đánh giá TLC theo vùng–giờ và đối soát thành phần tiền | Thư mục research_benchmarks; chạy ngoại tuyến |

Đường GPS: **Simulator → API → PostgreSQL → Redis → Detector → sự cố → agent tự xử lý → HITL khi khẩn**. API lưu bền vững trước khi trả thành công. SOS tạo sự cố trực tiếp trong PostgreSQL, không chờ Detector hoặc LLM.

Detector không cần LLM để phát hiện. Planner mặc định dùng câu gợi ý định sẵn, nên bạn có thể học toàn bộ quy trình mà chưa cài mô hình.

<a id="g02"></a>
## 2. Cài công cụ

### 2.1. Những thứ cần có

- Windows có PowerShell, quyền cài ứng dụng và đủ dung lượng cho Docker.
- Anaconda đã cài, dùng Conda quản lý môi trường **safejourney** với Python **3.12**.
- Node.js **24 LTS** được khuyến nghị; project yêu cầu Node 22.12 trở lên.
- Docker Desktop chạy Linux containers, thường dùng WSL 2.
- Trình sửa code như VS Code hoặc editor trong môi trường làm việc hiện có.

Không cần cài PostgreSQL/Redis trực tiếp lên Windows. Hai dịch vụ này nằm trong Compose để giảm khác biệt môi trường. Conda quản lý Python và thư viện; Docker quản lý hai dịch vụ dữ liệu.

### 2.2. Kiểm tra Anaconda đang có

Bạn đã dùng Anaconda nên không cần cài thêm trình quản lý môi trường Python. Mở **Anaconda PowerShell Prompt** trong Start Menu nếu bản Anaconda của bạn có mục này, hoặc PowerShell đã nạp Conda, rồi kiểm tra:

~~~powershell
conda --version
conda env list
~~~

Tài liệu dùng Set-Location và $env:, nên không dán nguyên lệnh vào Anaconda Prompt chạy cmd.exe. Nếu chỉ có **Anaconda Prompt**, nhập powershell tại cửa sổ đó để mở PowerShell kế thừa đường dẫn Anaconda, rồi nạp Conda cho riêng cửa sổ mới:

~~~powershell
$PSNativeCommandArgumentPassing = 'Legacy'
(& conda.exe shell.powershell hook) | Out-String | Invoke-Expression
conda --version
~~~

Legacy xử lý cách truyền tham số của Conda 24.11.3 đang có trên máy khi dùng PowerShell mới. Đã kiểm tra kích hoạt thành công bằng cách này; không sửa profile, execution policy hay cài đặt base. Nếu Anaconda PowerShell Prompt đã dùng được conda activate thì bỏ qua đoạn nạp này.

Môi trường base dùng để quản lý Conda; tạo môi trường safejourney riêng ở mục 4 để thư viện project không ảnh hưởng những project Python khác. Không cần nâng hoặc hạ Python của base. Cách tạo/kích hoạt môi trường được mô tả trong [hướng dẫn quản lý môi trường của Conda](https://docs.conda.io/projects/conda/en/stable/user-guide/tasks/manage-environments.html).

### 2.3. Cài Node và Docker

Cài Node 24 LTS từ [trang tải Node.js](https://nodejs.org/en/download). Cài Docker Desktop theo [hướng dẫn Windows](https://docs.docker.com/desktop/setup/install/windows-install/), làm theo yêu cầu WSL/khởi động lại mà bộ cài hiển thị. Sau đó mở Docker Desktop và chờ engine hoạt động.

Kiểm tra trong terminal mới:

~~~powershell
node --version
npm.cmd --version
docker version
docker compose version
~~~

Dùng npm.cmd để tránh lỗi PowerShell chặn npm.ps1. Nếu docker version chỉ thấy Client rồi báo không kết nối Server, hãy mở Docker Desktop trước khi chạy project.

<a id="g03"></a>
## 3. Thư mục và cách dùng terminal

~~~text
D:\SafeJourney\
  backend\
    app\api\             Router theo nghiệp vụ
    app\                 Database, bảo mật, rule, worker, planner
    migrations\          Nâng cấp database có checksum
    tests\               Test backend
  frontend\
    src\                 Giao diện React
    tests\               Test logic giao diện
  load_tests\            Stack riêng và bộ sinh tải
  tests\                 Test simulator
  research_benchmarks\    Đánh giá TLC ngoại tuyến; dữ liệu raw được Git bỏ qua
  docs\                  Tài liệu 01–10
  environment.yml        Khai báo môi trường Conda
  simulator.py
  compose.yaml
  Dockerfile
  fly.toml.example
~~~

Mỗi terminal có thư mục hiện tại và biến môi trường riêng. Lệnh dưới đây đưa bạn về đúng chỗ:

~~~powershell
Set-Location 'D:\SafeJourney'
Get-Location
~~~

Sau khi chạy conda activate safejourney, lệnh python sử dụng môi trường đó dù bạn đang ở root hay backend. Tuy vậy, vẫn phải đứng đúng thư mục để Python tìm module app hoặc load_tests. Không đổi vị trí simulator.py vì đường dẫn tới backend/.env dựa trên cấu trúc này.

<a id="g04"></a>
## 4. Cài thư viện và cấu hình

### 4.1. Tạo môi trường Conda và cài frontend

Ở lần đầu, chạy từ **gốc project** để đường dẫn requirements trong [environment.yml](../environment.yml) được giải quyết đúng:

~~~powershell
Set-Location 'D:\SafeJourney'
conda env create -f environment.yml
conda activate safejourney
python --version
python -c "import sys; print(sys.executable)"
python -m pip check
Set-Location .\frontend
npm.cmd ci
Set-Location ..
~~~

Kết quả mong đợi: Python 3.12.x, đường dẫn interpreter thuộc môi trường safejourney, pip check không báo xung đột. File environment.yml dùng kênh conda-forge và nodefaults, cài Python/pip rồi dùng pip đọc load_tests/requirements.txt và research_benchmarks/requirements.txt. Bộ thư viện gồm backend runtime (cả H3 và OR-Tools), pytest, aiohttp cho bộ sinh tải và PyArrow cho benchmark TLC ngoại tuyến; sau bước này bạn có thư viện cho API, simulator, test và đánh giá dữ liệu.

**Conda và pip có vai trò khác nhau:** Conda tạo môi trường và quản lý Python; pip cài các thư viện ứng dụng theo bộ requirements hiện có. Giữ requirements làm nguồn chung giúp máy phát triển và Docker dùng cùng các phiên bản thư viện trực tiếp. Luôn dùng python -m pip khi đã activate để cài đúng môi trường, không dùng pip của base hoặc --user. npm ci vẫn dùng package-lock.json riêng cho frontend.

Nếu đã tạo môi trường safejourney cho project này, bỏ qua conda env create; kích hoạt và cập nhật thư viện từ root khi requirements thay đổi:

~~~powershell
Set-Location 'D:\SafeJourney'
conda activate safejourney
python -m pip install -r .\load_tests\requirements.txt -r .\research_benchmarks\requirements.txt
python -m pip check
~~~

Không chạy conda update --all chỉ để đồng bộ project. Khi thay đổi lớn phần Python/thư viện do Conda quản lý, ưu tiên tạo một môi trường riêng từ environment.yml và kiểm chứng trước khi thay môi trường đang dùng.

**Chuyển từ môi trường cũ:** dừng API, Detector, Planner và simulator đang chạy; mở terminal mới rồi thực hiện các lệnh Conda trên. Thư mục .venv cũ có thể giữ lại để đối chiếu, nhưng không dùng interpreter của nó cho project nữa. Không cần chép thư viện từ môi trường cũ, xóa dữ liệu Docker hoặc tạo lại .env.

Trong editor, chọn Python interpreter của môi trường safejourney; kiểm tra bằng sys.executable nếu có nhiều Python. Nếu làm thử bằng notebook, chọn kernel dùng cùng môi trường này; notebook không phải cách khởi chạy API/worker trong hướng dẫn.

**Mỗi terminal Python mới đều phải chạy conda activate safejourney.** Nếu terminal nhận lệnh conda nhưng chưa kích hoạt được shell, có thể chạy một lệnh trực tiếp qua môi trường:

~~~powershell
Set-Location 'D:\SafeJourney'
conda run --no-capture-output -n safejourney python --version
conda run --no-capture-output -n safejourney python -m load_tests.local --help
~~~

Cách này không cần sửa PowerShell profile hoặc execution policy. Với module app, chuyển vào backend trước khi dùng conda run. Kết thúc làm việc có thể dùng conda deactivate; lệnh này chỉ thoát môi trường trong terminal hiện tại.

### 4.2. Tạo file cấu hình ở lần đầu

~~~powershell
if (-not (Test-Path .\backend\.env)) {
    Copy-Item .\backend\.env.example .\backend\.env
}
if (-not (Test-Path .\frontend\.env)) {
    Copy-Item .\frontend\.env.example .\frontend\.env
}
# Nếu dùng conda
if not exist backend\.env copy backend\.env.example backend\.env
if not exist frontend\.env copy frontend\.env.example frontend\.env
~~~

Mở backend/.env bằng editor và đặt **DEMO_PASSWORD** ít nhất 12 ký tự. Không giữ trống. Đây là mật khẩu chung cho năm tài khoản học tập được seed. Không dùng mật khẩu tài khoản cá nhân.

| Biến backend | Ý nghĩa khi chạy local |
|---|---|
| DATABASE_URL | Kết nối PostgreSQL; mẫu trỏ 127.0.0.1:5432/journey |
| REDIS_URL | Redis; mẫu trỏ 127.0.0.1:6379/0 |
| ALLOWED_ORIGINS | Mẫu: http://localhost:5173; phải khớp địa chỉ trình duyệt |
| COOKIE_SECURE | false trên HTTP local; true khi dùng HTTPS triển khai |
| DEMO_PASSWORD | Mật khẩu để seed/đăng nhập demo |
| LLM_MODE | mock để bắt đầu; ollama khi chủ động bật mô hình |
| DB_POOL_MIN / MAX | Pool từng tiến trình, mặc định 2 / 16 |
| TELEMETRY_BATCH_SIZE | Tối đa 200 GPS mỗi lô |
| TELEMETRY_FRESH_SECONDS | Mặc định 30 giây để đánh giá thời gian quan sát |
| WATCHDOG_INTERVAL_SECONDS | Mặc định 5 giây giữa các lượt kiểm tra mất GPS |

Trong file mẫu, STOP_SECONDS=15, DEVIATION_SECONDS=12, SPEED_SECONDS=9, GPS_LOST_SECONDS=45 để quan sát demo nhanh. Những giá trị này **không phải ngưỡng vận hành thực tế**. Nếu bỏ biến, một số giá trị mặc định trong config.py khác file .env.example; hãy dùng cấu hình mẫu đầy đủ.

Frontend/.env chỉ có cấu hình công khai như VITE_MAPBOX_TOKEN. Mọi biến VITE đều có thể xuất hiện trong mã trình duyệt; không đặt DATABASE_URL, mật khẩu hay khóa LLM ở đây.

Các file .env được bỏ qua trong Git; môi trường Conda thường nằm ngoài repository. environment.yml được lưu cùng code để tạo lại môi trường. Biến đặt bằng $env: trong terminal được ưu tiên hơn .env. Sau khi test, mở terminal mới và activate safejourney để quay về demo, tránh vô tình giữ cấu hình database test.

<a id="g05"></a>
## 5. Khởi tạo dữ liệu

Từ gốc project, khi Docker Desktop đã sẵn sàng:

~~~powershell
Set-Location 'D:\SafeJourney'
conda activate safejourney
docker compose up -d --wait
Set-Location .\backend
python -m app.db
python -m app.seed
~~~

Kết quả mong đợi: thông báo schema/migration sẵn sàng và các tài khoản đã được seed.

- app.db tạo bảng nền và áp dụng các migration theo thứ tự, lưu checksum.
- app.seed tạo operator, driver, passenger, driver2, passenger2 và trip-001/trip-002.
- Chạy seed lại cập nhật mật khẩu năm tài khoản theo DEMO_PASSWORD; không xóa dữ liệu hay đặt lại toàn bộ sự cố.
- Trip-001 thuộc driver/passenger; trip-002 thuộc driver2/passenger2.

Khi nâng cấp code, dừng API/Detector/Planner, sao lưu dữ liệu cần giữ rồi chạy app.db trước khi bật lại. **Không sửa nội dung migration đã áp dụng** để vượt lỗi checksum; tạo file số tiếp theo nếu cần thay đổi schema.

Bản hiện tại có [migration 007](../backend/migrations/007_operations_assessments.sql) lưu snapshot và lịch sử báo cáo vận hành. API mới cần migration này trước khi sử dụng khu vực **Agent kiểm tra vận hành**. Trình tự cập nhật cho người đã cài project nằm ở [09, mục 2](09-dieu-phoi-van-hanh-va-cong-cu-xac-dinh.md#2-cập-nhật-project-đã-cài-từ-trước).

<a id="g06"></a>
## 6. Chạy ứng dụng

Mở **bốn terminal**. Ba terminal Python đều kích hoạt safejourney; terminal frontend chỉ cần Node/npm. Mỗi terminal chạy đúng thành phần của nó và để cửa sổ chạy mở.

**Terminal 1 — API:**

~~~powershell
Set-Location 'D:\SafeJourney\backend'
conda activate safejourney
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
~~~

**Terminal 2 — Detector:**

~~~powershell
Set-Location 'D:\SafeJourney\backend'
conda activate safejourney
python -m app.worker
~~~

**Terminal 3 — Planner:**

~~~powershell
Set-Location 'D:\SafeJourney\backend'
conda activate safejourney
python -m app.planner
~~~

**Terminal 4 — Frontend:**

~~~powershell
Set-Location 'D:\SafeJourney\frontend'
npm.cmd run dev
~~~

Mở **http://localhost:5173**. API health ở **http://127.0.0.1:8000/api/health**, giao diện Swagger ở **http://127.0.0.1:8000/docs**.

Vite chuyển tiếp /api và /ws sang backend. Browser chỉ cần truy cập cổng 5173; không tự thêm URL API vào frontend. Với cấu hình mẫu, dùng đúng localhost:5173, tránh thay bằng 127.0.0.1:5173 vì Origin khác.

Chỉ chạy **một Detector và một Planner** cho cùng database. Hai tiến trình có khóa chống chạy trùng. API có thể chạy nhiều worker khi đo tải; không dùng --reload trong bài đo.

Dừng mỗi tiến trình bằng Ctrl+C tại terminal của nó. Dừng database/Redis demo bằng docker compose stop ở gốc project; dữ liệu trong volume được giữ.

<a id="g07"></a>
## 7. Đăng nhập và sử dụng dashboard

| Tài khoản | Quyền |
|---|---|
| operator, operator2 | Xem các chuyến/sự cố, tiếp nhận, duyệt/từ chối, đóng sự cố, xem nhật ký/cụm và chạy kiểm tra vận hành mô phỏng |
| driver, driver2 | Xem chuyến được phân công, gửi GPS của mình và SOS |
| passenger, passenger2 | Xem chuyến của mình, gửi SOS và xem biên nhận SOS do mình gửi |

Các tài khoản dùng DEMO_PASSWORD bạn đã đặt và seed. Muốn mở đồng thời operator và passenger, dùng hai hồ sơ trình duyệt hoặc một cửa sổ riêng tư để không dùng chung cookie.

Dashboard mặc định lấy chuyến ACTIVE. Có lựa chọn xem tất cả chuyến được cấp quyền, tìm theo mã/tên và phân trang 50 dòng. Nút Xem tuyến tải chi tiết tuyến riêng; danh sách vị trí không tải lại tất cả hình học tuyến.

Độ mới GPS là tuổi của **thời điểm thiết bị quan sát**, không phải dự đoán vị trí hiện tại. Tuổi danh sách cho biết lần lấy vị trí thành công gần nhất. Cả hai đồng hồ vẫn tăng khi mạng lỗi. WebSocket chỉ báo có thay đổi; dữ liệu thực lấy từ API có phân quyền.

Nếu chưa có Mapbox token, dashboard vẫn có danh sách, SOS, sự cố và xử lý HITL. Banner mô phỏng luôn hiện để tránh nhầm với trung tâm cứu hộ thật.

Ở **Agent kiểm tra vận hành**, chọn chuyến và một trong năm kịch bản rồi bấm chạy. Agent tự tính lộ trình, cước/hoàn tiền, pin/sạc và phân bổ; mở phần giả định để biết nguồn đầu vào và xem lịch sử để đọc báo cáo đã lưu. Phần này dùng đội xe/pin/nhu cầu mẫu gắn với tuyến đã lưu, không phải dữ liệu pin/thời tiết live của chuyến. Xem [09](09-dieu-phoi-van-hanh-va-cong-cu-xac-dinh.md) để thực hành đầy đủ; hồ sơ khẩn vẫn được duyệt ở khu vực sự cố.

<a id="g08"></a>
## 8. Thử GPS, SOS và HITL

### 8.1. GPS bình thường

Terminal thứ năm tại root:

~~~powershell
Set-Location 'D:\SafeJourney'
conda activate safejourney
python .\simulator.py --scenario normal --seconds 60
~~~

Simulator đọc mật khẩu từ backend/.env, đăng nhập driver và gửi trip-001 mỗi khoảng 3 giây. Mỗi bản tin có UUID riêng và timestamp UTC. API thành công nghĩa là đã lưu; Detector sẽ cập nhật vị trí sau đó.

### 8.2. Các tình huống bất thường

Trong terminal simulator đã activate safejourney và đang ở root, chạy **từng lệnh riêng**, không phát nhiều kịch bản vào cùng chuyến đồng thời:

~~~powershell
python .\simulator.py --scenario stop --seconds 30
python .\simulator.py --scenario deviation --seconds 30
python .\simulator.py --scenario speed --seconds 30
python .\simulator.py --scenario sos
~~~

Sau mỗi kịch bản, xem bằng chứng và đóng sự cố đã xác minh để phân biệt lượt thử tiếp theo. Để thử GPS_LOST, dừng simulator và chờ quá GPS_LOST_SECONDS cộng thời gian watchdog; không cần dừng API/worker.

Các luật STOP/DEVIATION/SPEED cần nhiều mẫu liên tục có accuracy phù hợp. Dữ liệu kém, trễ hoặc mất quãng không được tính như xe đang an toàn. Trip-002 seed cũng đang ACTIVE nhưng không có simulator, nên có thể phát sinh GPS_LOST của chuyến đó; xem mã chuyến trên thẻ sự cố.

### 8.3. Agent liên hệ và người nhận xác nhận

1. Chạy simulator stop/speed/deviation đủ lâu để rule phát hiện. Chuyến thử không nên có hồ sơ mức 3 đang mở vì nhánh khẩn sẽ chặn liên hệ thường.
2. Đăng nhập operator và chọn hàng đợi **Agent tự xử lý** để quan sát. SMS được tạo tự động; không bấm nhận/duyệt cho hồ sơ thường.
3. Dùng một hồ sơ trình duyệt khác đăng nhập driver. Yêu cầu liên hệ hiển thị nội dung mô phỏng; chỉ thao tác khi đã dừng an toàn.
4. Chọn đã an toàn: agent chờ 60 giây, kiểm tra GPS mới nhất rồi tự đóng nếu đủ điều kiện. Cần tiếp tục gửi GPS bình thường; tắt simulator sẽ làm thiếu bằng chứng phục hồi.
5. Chọn **Tôi cần hỗ trợ**: chuyển ngay mức 3, gói khẩn chưa được thực thi.
6. Không phản hồi: sau 120 giây chuyển từ SMS sang cuộc gọi mô phỏng; sau 120 giây nữa chuyển HITL. Các thời hạn được kiểm tra bởi Planner, không phải thời gian cam kết tuyệt đối.

Trong demo hiện tại, người nhận của playbook thường là tài xế. Passenger vẫn có nút SOS nhưng không trả lời thay yêu cầu tài xế. SMS/cuộc gọi chỉ là bản ghi DB và màn hình xác nhận, không tới điện thoại thật. “Đã gửi mô phỏng” không đồng nghĩa người nhận đã trả lời.

### 8.4. SOS và nhánh khẩn cần HITL

1. Đăng nhập passenger, bấm SOS mô phỏng ở trip-001, hoặc dùng simulator SOS.
2. Đăng nhập operator, mở hàng đợi mặc định **Cần nhân viên**.
3. Chọn hồ sơ, **Nhận xử lý khẩn**, xem nội dung/người nhận đã chuẩn bị rồi **Duyệt gói xử lý mô phỏng** hoặc **Từ chối**. Nếu người khác đang giữ quyền, bạn chỉ xem được.
4. Backend kiểm tra owner, phiên, hạn và revision gói; action cùng audit được ghi một lần. Duyệt không tự đóng hồ sơ và không gửi cứu hộ thật.
5. Sau xác minh, chọn kết quả từ danh sách rồi **Xác nhận và đóng sự cố**. Chỉ chọn “trường hợp đặc biệt” khi cần nhập riêng. Bàn giao cũng chọn lý do có sẵn rồi xác nhận.

Đề xuất khẩn hết hạn sau 15 phút. Bấm **Yêu cầu đề xuất mới** khi hết hạn; gói mới phải đọc và duyệt lại. Nếu cần sửa thông điệp, mở chức năng ngoại lệ, lưu bản sửa rồi duyệt revision mới. Không sửa bản đã thực thi.

Hồ sơ và nội dung đang nhập vẫn được giữ khi đổi trang/hàng đợi. **Bỏ chọn hồ sơ** chỉ đóng khung xem. Quyền phụ trách mặc định 5 phút (INCIDENT_LEASE_SECONDS=300), gia hạn khi hồ sơ được chọn và tab hiển thị. Hết quyền phải nhận lại; phiên cũ bị chặn. Hồ sơ khẩn thiếu người phụ trách được nhắc ca trực mô phỏng sau 30/60 giây.

Để thử nhiều người, dùng operator/operator2 trong hai hồ sơ trình duyệt độc lập. Chi tiết API, deadline, nâng cấp database và giới hạn ở [08](08-quy-trinh-operator-va-phan-cong.md).

<a id="g09"></a>
## 9. Đọc và sửa backend

### 9.1. Đọc theo luồng thay vì đọc tất cả cùng lúc

| Câu hỏi | File nên mở |
|---|---|
| Ứng dụng được ghép thế nào? | [main.py](../backend/app/main.py) |
| Dữ liệu request hợp lệ là gì? | [schemas.py](../backend/app/schemas.py) |
| Đăng nhập và phạm vi quyền? | [auth.py](../backend/app/api/auth.py), [security.py](../backend/app/security.py) |
| API nhận GPS/SOS ra sao? | [trips.py](../backend/app/api/trips.py) |
| Lưu và nâng cấp database? | [db.py](../backend/app/db.py), [schema.sql](../backend/schema.sql), [migrations](../backend/migrations/) |
| Dữ liệu cũ/trùng/thứ tự sai? | [telemetry_policy.py](../backend/app/telemetry_policy.py) |
| Khi nào rule báo động? | [rules.py](../backend/app/rules.py) |
| Relay, batch và GPS watchdog? | [worker.py](../backend/app/worker.py) |
| LangGraph và nhánh HITL? | [planner.py](../backend/app/planner.py) |
| Playbook SMS/gọi và phản hồi? | [autoplaybooks.py](../backend/app/autoplaybooks.py), [response_playbooks.py](../backend/app/response_playbooks.py), [contacts.py](../backend/app/api/contacts.py) |
| Quyết định/đóng/nhật ký? | [incidents.py](../backend/app/api/incidents.py) |
| Realtime và metric? | [realtime.py](../backend/app/realtime.py), [monitoring.py](../backend/app/api/monitoring.py) |
| Nhóm agent vận hành và công cụ? | [workflow.py](../backend/app/operations/workflow.py), [calculations.py](../backend/app/operations/calculations.py), [optimizer.py](../backend/app/operations/optimizer.py), [spatial.py](../backend/app/operations/spatial.py) |
| Snapshot và chống nhấn chạy lặp? | [operations.py](../backend/app/api/operations.py), [scenarios.py](../backend/app/operations/scenarios.py) |
| Đánh giá dữ liệu TLC thật? | [tlc.py](../research_benchmarks/tlc.py), [demand.py](../research_benchmarks/demand.py) |

### 9.2. Ví dụ hiểu một bản tin GPS

~~~json
{
  "event_id": "ed864036-50c2-4bc4-bc8e-4e405f84a4af",
  "seq": 1,
  "lat": 10.78,
  "lon": 106.7,
  "accuracy_m": 10,
  "speed_kmh": 25,
  "event_time": "2026-10-24T07:00:00+00:00"
}
~~~

Đây chỉ là cấu trúc minh họa. Khi gửi thử, dùng thời gian hiện tại và UUID mới do simulator tạo; timestamp cố định sẽ trở thành dữ liệu cũ.

event_id là khóa chống xử lý lặp. Gửi lại cùng UUID/cùng nội dung trả duplicate; cùng UUID nhưng nội dung khác trả 409. seq được lưu nhưng thời điểm event_time quyết định thứ tự áp dụng trong MVP.

API khóa chuyến, xác nhận quyền, ghi inbox/outbox trong một transaction. Detector lấy sự kiện theo lô, khóa chuyến theo thứ tự ổn định, áp dụng policy rồi mới sửa vị trí. HTTP durable chưa đồng nghĩa processing_result=APPLIED; sự kiện trễ có thể là STALE, đảo thứ tự là OUT_OF_ORDER.

### 9.3. Bài tập sửa nhỏ: đổi ngưỡng dừng

1. Đọc evaluate() trong rules.py và test_rules.py.
2. Đổi STOP_SECONDS trong backend/.env từ 15 sang giá trị bạn muốn thử.
3. Khởi động lại Detector để nạp env.
4. Chạy scenario stop lâu hơn ngưỡng đó.
5. Đối chiếu thời gian các mẫu với thời gian tạo cảnh báo.

Nếu thêm loại rule mới, tách phần tính toán thuần vào rules.py hoặc module riêng, viết test có mẫu trước/sát/sau ngưỡng, rồi nối vào worker và bổ sung cách hiển thị. Tránh nhét LLM vào endpoint GPS hoặc dùng mô hình để tự quyết định quyền duyệt.

### 9.4. Khi cần đổi database

Đọc schema và các migration hiện có, tạo migration số kế tiếp. Bản hiện tại đã có 007_operations_assessments.sql, nên ví dụ thay đổi tiếp theo là 008_ten_thay_doi.sql nếu số đó chưa được dùng. Thử app.db trên database test, kiểm tra dữ liệu cũ vẫn đọc được rồi cập nhật API/frontend tương ứng. Không chỉ sửa schema.sql mà bỏ migration, vì người có database sẵn sẽ thiếu thay đổi.

<a id="g10"></a>
## 10. Đọc và sửa frontend

| File | Nhiệm vụ |
|---|---|
| [App.jsx](../frontend/src/App.jsx) | Login/dashboard, lựa chọn chuyến, sự cố, form quyết định |
| [IncidentFilters.jsx](../frontend/src/IncidentFilters.jsx), [incidentFilters.js](../frontend/src/incidentFilters.js) | Bộ lọc nhóm xử lý/phụ trách/trạng thái, chuyển lịch sử và query server |
| [OperatorAssist.jsx](../frontend/src/OperatorAssist.jsx) | Gói xử lý, sửa ngoại lệ, chọn kết quả thay gõ tay |
| [OperationsPanel.jsx](../frontend/src/OperationsPanel.jsx), [operationsPanel.js](../frontend/src/operationsPanel.js) | Chọn kịch bản, đọc báo cáo công cụ/lịch sử, giữ UUID retry và chặn response cũ |
| [api.js](../frontend/src/api.js) | Fetch JSON, giữ mã lỗi HTTP, kiểm tra response danh sách |
| [refreshQueue.js](../frontend/src/refreshQueue.js) | Gộp refresh, bảo đảm có lượt chạy tiếp khi thay đổi đến lúc đang tải |
| [journeyData.js](../frontend/src/journeyData.js) | Giữ tham chiếu dữ liệu không đổi, GeoJSON, tuổi GPS, UUID SOS retry |
| [LiveMap.jsx](../frontend/src/LiveMap.jsx) | Nguồn vị trí và tuyến riêng, màu dữ liệu cũ |
| [style.css](../frontend/src/style.css) | Bố cục và kiểu hiển thị |
| [vite.config.js](../frontend/vite.config.js) | Cổng dev và proxy API/WebSocket |

Ví dụ muốn thêm cột vào bảng chuyến: xác định dữ liệu đó có trong TripView/backend chưa, thêm vào response hợp lệ nếu cần, rồi thêm tiêu đề/ô tương ứng trong App.jsx. Nếu trường mới ảnh hưởng so sánh dữ liệu, cập nhật reconcileTrips và test liên quan.

Luôn hiển thị lỗi gần vùng liên quan. Lỗi nhật ký/cụm không nên biến mất chỉ vì danh sách chuyến refresh thành công. Sau thay đổi logic gọi API, chạy npm.cmd test; sau thay đổi JSX/config, chạy npm.cmd run build.

<a id="g11"></a>
## 11. Mapbox và LLM tùy chọn

### 11.1. Mapbox

Đặt token công khai dành cho browser vào VITE_MAPBOX_TOKEN trong frontend/.env. Dùng token có phạm vi phù hợp và giới hạn URL từ tài khoản Mapbox của bạn. Khởi động lại Vite. Nếu dùng Docker, truyền giá trị lúc build; thay env runtime không thay bundle đã tạo.

Bản đồ dùng một nguồn điểm cho đội xe và một nguồn tuyến cho chuyến đang chọn. Tuổi GPS đổi màu theo đồng hồ. Không tạo 1.000 HTML marker riêng. Mapbox là gói tải riêng khi bật bản đồ, nhưng vẫn lớn; build có thể cảnh báo kích thước chunk. Chưa có số đo render 1.000 xe trong trình duyệt.

### 11.2. Ollama

Sau khi chạy ổn chế độ mock, cài Ollama theo [tài liệu chính thức](https://docs.ollama.com/quickstart), tải model:

~~~powershell
ollama pull qwen2.5:3b
~~~

Sửa backend/.env:

~~~dotenv
LLM_MODE=ollama
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:3b
LLM_TIMEOUT_SECONDS=60
~~~

Khởi động lại **riêng Planner** sau khi sửa .env: nhấn Ctrl+C ở terminal Planner cũ, rồi chạy lại python -m app.planner trong backend khi đã activate safejourney. Không chạy thêm một Planner song song. Tạo sự cố mới, hoặc yêu cầu đề xuất mới cho hồ sơ có proposal đã hết hạn; đề xuất đã lưu không tự đổi theo cấu hình mới.

Model local cần thời gian nạp trước khi trả lời. Lượt kiểm tra ngày 01/11 ghi nhận timeout với cấu hình 8 giây; khi cho phép 60 giây, cùng yêu cầu trả về hợp lệ sau khoảng 41 giây (nạp model khoảng 19 giây). Khi model đã nạp, hai yêu cầu SPEED/SOS trả lời trong khoảng 3 giây. Đây là kiểm tra adapter trên máy local, không phải SLA hoặc đánh giá chất lượng AI.

Adapter có timeout kết nối tối đa 3 giây và timeout đọc theo LLM_TIMEOUT_SECONDS, mặc định 60 giây; đây không phải deadline tổng tuyệt đối của toàn lượt gọi. Request Ollama không kế thừa proxy từ môi trường terminal. Không bỏ giới hạn thời gian để chờ vô hạn; một lane Planner vẫn có thể bận trong lúc LLM chạy. Detector và tiếp nhận SOS không chờ LLM.

Planner gửi loại/mức sự cố, bằng chứng đã lọc và các lựa chọn xác minh cho adapter. Chỉ chuyển số đo cần thiết: tốc độ, độ chính xác GPS, ngưỡng/thời gian phát hiện, trạng thái ngoài tuyến hoặc vai trò gửi SOS. Không chuyển tọa độ, định danh chuyến/người, số điện thoại, thời điểm chi tiết hay văn bản SOS tự do.

Đề xuất gồm ba phần: **Căn cứ phát hiện**, **Cần xác minh**, **Giới hạn**. Backend trình bày số đo/ngưỡng từ hồ sơ; LLM chọn và sắp xếp bước xác minh trong playbook bằng evidence_keys/check_ids theo JSON schema. Khóa do model trả về phải có trong danh sách cho phép và không lặp; model không được tự thêm lời kể, số đo hay hành động. Bước kiểm tra nền tảng luôn được backend giữ lại, riêng SOS ưu tiên kênh liên hệ an toàn.

Ví dụ SPEED có thể ghi: tốc độ 105 km/h, ngưỡng luật >90 km/h, điều kiện kéo dài 12 giây so với ngưỡng 9 giây; tiếp theo là kiểm tra chuỗi tốc độ/chất lượng GPS và chọn kênh liên hệ an toàn. Đây là giải thích điều kiện phát cảnh báo, chưa phải kết luận nguyên nhân thực tế. Hồ sơ cũ chưa lưu ngưỡng/thời gian sẽ ghi rõ thiếu dữ liệu; không lấy ngưỡng cấu hình mới để lấp chỗ trống.

Nếu model lỗi, JSON sai, tham chiếu ngoài danh sách hoặc quá thời gian chờ, hệ thống vẫn giữ phần bằng chứng và dùng bước xác minh dự phòng theo loại. Xem phần đầu nội dung proposal:

| Tiền tố | Ý nghĩa |
|---|---|
| [LLM đề xuất; nhân viên cần kiểm tra] | Model chọn bước xác minh hợp lệ; số đo do backend trình bày |
| [Mẫu dự phòng, chưa dùng LLM] | Planner chưa chạy LLM_MODE=ollama |
| [LLM lỗi/quá hạn; dùng mẫu] | Gọi model hoặc kiểm tra câu trả lời thất bại |

Khi fallback, terminal Planner ghi reason=timeout, connection, http_status hoặc invalid_response_or_config, kèm error_type, HTTP status nếu có và thời gian đã chờ. Log không ghi URL, prompt, nội dung phản hồi hay bằng chứng sự cố. Kiểm tra model bằng ollama list; API danh sách model hoạt động chưa chứng minh sinh lời khuyên thành công.

LLM chỉ chọn bước xác minh trong playbook. Loại hành động, trạng thái, hạn duyệt và quyền thực thi do code backend quyết định. Đã gọi model local trên 5 tình huống mẫu; vẫn cần bộ dữ liệu đánh giá chất lượng lựa chọn và precision/recall riêng trước vận hành thực tế.

<a id="g12"></a>
## 12. Chạy kiểm thử

### 12.1. Test nhanh không cần database

~~~powershell
Set-Location 'D:\SafeJourney\backend'
conda activate safejourney
python -m pytest tests/test_rules.py tests/test_telemetry_policy.py tests/test_scheduler.py tests/test_worker_resilience.py tests/test_planner_llm.py tests/test_planner_context.py tests/test_response_playbooks.py -q
python -m pytest tests/test_operations_tools.py tests/test_operations_workflow.py -q
Set-Location ..
python -m pip install -r .\load_tests\requirements.txt -r .\research_benchmarks\requirements.txt
python -m pytest tests load_tests/tests research_benchmarks/tests -q
Set-Location .\frontend
npm.cmd test
npm.cmd run build
~~~

Các bài này kiểm tra rule, thời gian, lịch Planner, phục hồi Redis bằng giả lập, công cụ/graph vận hành, simulator, bộ sinh tải, benchmark dữ liệu và logic frontend. OSRM/LLM trong test tương ứng được giả lập; chưa chứng minh đã gọi dịch vụ thật. Chạy pytest toàn backend mà không bật RUN_DEMO_TESTS sẽ **skip** integration; không coi skip là đã kiểm thử database.

### 12.2. Integration trên database riêng

**Dừng API/Detector/Planner test và không chạy bài tải cùng lúc.** Test tự gọi app bằng TestClient và gọi worker/planner theo tình huống; không cần mở ba tiến trình dịch vụ.

Mở Anaconda PowerShell Prompt mới ở root, kích hoạt safejourney và khởi động stack test riêng. Tạo database safejourney_test nếu chưa có:

~~~powershell
Set-Location 'D:\SafeJourney'
conda activate safejourney
docker compose -f .\load_tests\compose.yaml up -d --wait
$testDbExists = docker compose -f .\load_tests\compose.yaml exec -T db psql -U loadtest -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='safejourney_test'"
if (("$testDbExists").Trim() -ne '1') {
    docker compose -f .\load_tests\compose.yaml exec -T db createdb -U loadtest safejourney_test
}
. .\load_tests\env.ps1
$env:DATABASE_URL = 'postgresql://loadtest:local_loadtest_only@127.0.0.1:25432/safejourney_test'
$env:CHECKPOINT_DATABASE_URL = $env:DATABASE_URL
$env:REDIS_URL = 'redis://127.0.0.1:26379/1'
$env:DEMO_PASSWORD = [guid]::NewGuid().ToString()
$env:RUN_DEMO_TESTS = '1'
Set-Location .\backend
python -m app.db
python -m app.seed
python -m pytest tests -q
~~~

Nếu Docker báo lỗi ở bước truy vấn, xử lý kết nối trước khi tiếp tục. Giữ nguyên cửa sổ từ seed đến test để mật khẩu ngẫu nhiên khớp.

Guard chỉ chấp nhận database local tên safejourney_test/safejourney_loadtest và Redis local khi RUN_DEMO_TESTS=1. Hướng dẫn dùng **safejourney_test + Redis DB1** để tách fixture khỏi bài tải dùng DB0. Không bỏ guard để chạy trên dữ liệu thật.

Đọc số passed/failed/skipped cuối lệnh. Kết quả thực tế của lần rà soát hiện tại được ghi ở [07](07-ket-qua-kiem-thu-va-tai.md); nếu bạn sửa code, phải kiểm thử lại phần ảnh hưởng.

<a id="g13"></a>
## 13. Đo tải 1.000 xe

Đọc đầy đủ [06 — kiểm thử tải](06-kiem-thu-tai-1000-xe.md) trước khi chạy. Từ root, sau khi dừng các tiến trình test trên cổng 18000:

~~~powershell
Set-Location 'D:\SafeJourney'
conda activate safejourney
python -m pip install -r .\load_tests\requirements.txt
python -m load_tests.local --api-workers 2 --allow-local-loadtest
~~~

Runner tạo stack riêng, 1.000 tài xế/chuyến giả, chạy GPS mỗi 3 giây và 5 phiên HTTP nhân viên. Khoảng đo chính 120 giây tương ứng 40.000 bản tin theo lịch. Đăng nhập/khởi động/ramp/warmup nằm ngoài 120 giây đó nên tổng thời gian dài hơn.

Không chỉ nhìn chữ PASS: kiểm tra dropped, lỗi HTTP, p95, backlog, APPLIED và fingerprint nguồn. Giữ cả báo cáo FAIL; không sửa ngưỡng để làm đẹp kết quả. Local PASS không chứng minh năng lực trên Fly.io hay độ chính xác cảnh báo.

<a id="g14"></a>
## 14. Docker và Fly.io

### 14.1. Kiểm tra đóng gói local

~~~powershell
Set-Location 'D:\SafeJourney'
docker build -t safejourney:local .
~~~

Docker build frontend rồi chép bundle vào image Python. Container dùng Python 3.12 và cài backend/requirements.txt trực tiếp bằng pip, không cần Conda hay Anaconda bên trong image. Runtime chạy với user 10001, không gồm pytest, source test hay .env. Đây là kiểm tra đóng gói; không tự đưa ứng dụng lên mạng.

Image dùng cổng 8080, phục vụ frontend và API cùng origin. DATABASE_URL/REDIS_URL trong container phải truy cập được database/Redis; 127.0.0.1 bên trong container không phải Windows host. Không dùng nguyên URL loopback demo cho một container độc lập.

### 14.2. Chuẩn bị triển khai

Project có [fly.toml.example](../fly.toml.example); chưa có deployment được xác nhận. Trước khi triển khai cần:

1. Tài khoản Fly.io, flyctl và app name riêng.
2. PostgreSQL có PostGIS, Redis được bảo vệ, kết nối phù hợp.
3. DATABASE_URL và CHECKPOINT_DATABASE_URL trỏ đúng cùng dữ liệu ứng dụng; checkpoint/khóa singleton cần kết nối PostgreSQL trực tiếp, tránh transaction pooler cho khóa phiên.
4. ALLOWED_ORIGINS đúng HTTPS domain, COOKIE_SECURE=true.
5. Tách cấu hình công khai Mapbox lúc build khỏi backend secrets.
6. Sao lưu và có kế hoạch phục hồi dữ liệu.

Copy fly.toml.example thành fly.toml nếu chưa có; thay tên app ở cả app và ALLOWED_ORIGINS. File này khai báo ba process group web, detector, planner. [Fly chạy mỗi process group trên Machine riêng](https://docs.fly.io/launch/processes), nên không coi chúng là ba tiến trình trong cùng một máy local.

Tạo app theo hướng dẫn flyctl/tài khoản của bạn. Nhập backend secrets bằng cơ chế quản lý secret. Có thể dùng file tạm **.env.fly.local** ở root đã được Git bỏ qua theo mẫu .env*, chứa NAME=VALUE rồi:

~~~powershell
Get-Content .\.env.fly.local | fly secrets import --stage
~~~

Theo [fly secrets import](https://docs.fly.io/flyctl/cmd/fly_secrets_import), lệnh đọc các cặp tên/giá trị từ stdin. Không đưa file chứa secret vào tài liệu, ảnh chụp hoặc Git.

MVP chỉ cho một Detector và một Planner. Khi triển khai chọn chiến lược không chạy chồng hai bản singleton:

~~~powershell
fly deploy --ha=false --strategy immediate
fly scale count web=1 detector=1 planner=1
fly status
~~~

Các tùy chọn được mô tả tại [fly deploy](https://docs.fly.io/flyctl/cmd/fly_deploy). immediate có thể gián đoạn dịch vụ; không phải triển khai không downtime. Với app đã tồn tại, kiểm tra số Machine thực tế và tránh giữ bản worker cũ. Cấu hình một web trong ví dụ chưa được đo tải 1.000 xe trên Fly.

release_command chạy app.db. Sau deploy, cần seed hoặc provision tài khoản có kiểm soát trong môi trường đó, kiểm tra health, ba process group và toàn bộ luồng đăng nhập/GPS/SOS/HITL. Không tự seed tài khoản demo dùng chung mật khẩu vào hệ thống thật.

<a id="g15"></a>
## 15. Xử lý lỗi thường gặp

| Hiện tượng | Kiểm tra / cách xử lý |
|---|---|
| conda không được nhận diện | Mở Anaconda PowerShell Prompt hoặc PowerShell đã nạp Conda; không thêm ngẫu nhiên nhiều đường dẫn Python vào PATH |
| conda activate lỗi invalid choice với tham số rỗng | Trong PowerShell hiện tại đặt $PSNativeCommandArgumentPassing = 'Legacy' rồi thử lại; xem mục 2.2. Không cần nâng Conda/base chỉ để chạy project |
| conda activate không hoạt động nhưng conda --version được | Dùng terminal Conda đã cấu hình; có thể chạy conda.exe run --no-capture-output -n safejourney python ... để gọi executable trực tiếp |
| EnvironmentNameNotFound | Kiểm tra conda env list; tạo môi trường từ environment.yml ở root nếu chưa có |
| Python sai phiên bản / ModuleNotFoundError | Activate safejourney, kiểm tra python --version và sys.executable; chạy python -m pip install -r .\load_tests\requirements.txt từ root |
| Editor/notebook dùng Python khác terminal | Chọn interpreter/kernel của safejourney và đối chiếu sys.executable |
| Pip báo xung đột thư viện | Chạy python -m pip check trong safejourney; không sửa bằng cách cài thêm vào base hoặc dùng --user |
| npm.ps1 bị chặn | Dùng npm.cmd |
| Docker không kết nối | Mở Docker Desktop, chờ engine, kiểm tra docker version |
| Cổng 5432/6379 đã dùng | Dừng dịch vụ trùng hoặc đặt DB_PORT/REDIS_PORT cho Compose, sửa URL tương ứng |
| Login thất bại | DEMO_PASSWORD có đúng giá trị đã seed; seed có chạy trên đúng database |
| Login 429 | Giới hạn 10 lần/10 phút theo tài khoản+IP; chờ cửa sổ giới hạn, không tắt bảo vệ |
| Origin không được phép / WebSocket lỗi | Dùng đúng localhost:5173 và ALLOWED_ORIGINS; khởi động lại API sau đổi env |
| Không thấy chuyến | Vai trò/phạm vi, chuyến ACTIVE hay FINISHED, lựa chọn danh sách |
| API nhận GPS nhưng vị trí không đổi | Detector đã chạy, Redis sẵn sàng, timestamp/accuracy hợp lệ, xem processing_result |
| Nhiều GPS_LOST ngay khi mở | Chuyến ACTIVE nhưng chưa gửi GPS, ngưỡng demo ngắn |
| Không có đề xuất | Planner đã chạy, app.db đã áp dụng, xem terminal Planner |
| Duyệt trả 409 | Proposal đã hết hạn/đã xử lý/sự cố đã đóng; làm mới, tạo đề xuất mới nếu đủ điều kiện |
| Detector/Planner khác đang chạy | Dừng bản cũ của cùng database; không bỏ khóa singleton |
| Migration checksum mismatch | File migration đã áp dụng bị đổi; khôi phục đúng nội dung rồi thêm migration mới |
| Tải bị ABORTED/FAIL | Đọc JSON và .work/loadtest/<run-id>; xem mục phục hồi trong tài liệu 06 |
| Mapbox trắng | Token/domain/mạng/WebGL; vẫn dùng danh sách, đừng bỏ qua lỗi GPS |
| Chạy demo lại trỏ database test | Mở terminal mới hoặc xóa các env test đã đặt; .env không ghi đè env terminal |

Không dùng docker compose down -v như cách “sửa nhanh” vì xóa volume sẽ mất dữ liệu. Khi cần reset, xác định chính xác dữ liệu thử nào có thể bỏ và sao lưu phần cần giữ.

<a id="g16"></a>
## 16. Quy trình phát triển tiếp

1. Chọn một hành vi cụ thể, ví dụ bộ lọc sự cố hoặc adapter thông báo.
2. Đọc module liên quan và test hiện có.
3. Giữ hợp đồng bảo mật/idempotency/HITL; thêm migration mới nếu đổi dữ liệu.
4. Sửa ít file cần thiết, viết test cho tình huống có rủi ro thực.
5. Chạy test liên quan và build; chỉ đo lại tải khi đường tải bị ảnh hưởng.
6. Cập nhật tài liệu mô tả hành vi cuối cùng và kết quả đã đo.
7. Dùng Git để lưu mốc ổn định; không commit secret hay dữ liệu vị trí thật.

Lộ trình mở rộng ở [03](03-lo-trinh-phat-trien.md); ranh giới module và điểm thay thế ở [05](05-ra-soat-kien-truc-mvp.md). Tách provider thật chỉ sau khi có cơ chế xác nhận, timeout, đối soát và chặn hành động khẩn chưa được người duyệt.

<a id="g17"></a>
## 17. Tiêu chí hoàn thành bản thực hành

- Bạn tự bật được bốn terminal và đăng nhập đúng vai trò.
- GPS bình thường cập nhật vị trí; thử được từng rule và đọc bằng chứng.
- SOS có biên nhận; chỉ operator xem nội dung xử lý và thực hiện quyết định.
- Playbook thường tự chạy SMS/gọi mô phỏng; chỉ đúng người nhận xác nhận, operator không trả lời thay.
- Nhánh khẩn chờ duyệt không tạo action; duyệt lặp không tạo action thứ hai.
- Proposal hết hạn tạo lại được và cần duyệt mới.
- Chạy được năm kịch bản vận hành, đọc đúng nguồn tuyến/pin/cước và hiểu vì sao phương án bị chặn hoặc chưa phục vụ đủ yêu cầu.
- Chạy benchmark TLC theo [10](10-du-lieu-thuc-va-benchmark.md); không dùng số đo forecast để tuyên bố độ chính xác cảnh báo hoặc sức chịu tải API.
- Test không fail; build thành công; hiểu test nào còn skip hoặc chưa đo.
- Bài tải có JSON, ngưỡng và giới hạn được ghi rõ.
- Không dùng dữ liệu demo để tuyên bố đã đạt an toàn thực tế.

Đọc [báo cáo kiểm chứng hiện tại](07-ket-qua-kiem-thu-va-tai.md) để phân biệt code đã có, hành vi đã chạy kiểm thử và phần còn cần xác nhận.

