# SafeJourney — điều phối vận hành và công cụ tính toán xác định

**Cập nhật: 10/11/2026.** Phần này mở rộng bài toán an toàn sang kiểm tra lộ trình, cước, pin, trạm sạc và phân xe. Mã chạy tại [operations/](../backend/app/operations/), API tại [api/operations.py](../backend/app/api/operations.py), giao diện tại [OperationsPanel.jsx](../frontend/src/OperationsPanel.jsx). Kết quả kiểm thử mới nhất được ghi riêng ở [07](07-ket-qua-kiem-thu-va-tai.md).

## 1. Hiện tại làm được gì?

Operator chọn một chuyến và một kịch bản, rồi bấm **Agent kiểm tra vận hành**. Hệ thống tự lấy tuyến đã lưu, dựng bộ đầu vào mô phỏng, chạy các bước kiểm tra, tính phương án và lưu lịch sử. Không cần gõ thông số hoặc viết câu lệnh cho LLM trong luồng thường.

Đây là **bộ phân tích và đề xuất mô phỏng**. Nó chưa tự thay đổi tuyến chuyến, giao đơn cho tài xế, đặt chỗ sạc hoặc tạo giao dịch hoàn tiền. Trạng thái `COMPLETED` chỉ nói lượt kiểm tra đã hoàn tất theo các điều kiện của nó; không phải phê duyệt hành động ngoài hệ thống.

Hai quy trình cùng tồn tại:

| Quy trình | Khi nào chạy? | Quyền thực thi |
|---|---|---|
| Giám sát sự cố | Detector/rule/SOS phát hiện; Planner tự chạy playbook thường | SMS → gọi mô phỏng, chờ đúng người nhận trả lời; hành động khẩn cần HITL theo [08](08-quy-trinh-operator-va-phan-cong.md) |
| Kiểm tra vận hành | Operator chọn kịch bản và bấm chạy | Chỉ tính toán, giải thích và lưu báo cáo; không cấp quyền cho hành động sự cố |

Phần vận hành không chạy trên từng bản tin GPS. Khi OSRM hoặc LLM của phần này bị lỗi, các luật phát hiện sự cố vẫn chạy theo đường xử lý riêng. Tuy vậy API vẫn chia sẻ tài nguyên máy/database; cần đo thêm tải hỗn hợp trước khi cho nhiều lượt tối ưu chạy đồng thời.

## 2. Cập nhật project đã cài từ trước

Dừng các terminal API/Detector/Planner đang chạy. Mở **Anaconda PowerShell Prompt**, vào đúng thư mục và cập nhật môi trường:

```powershell
Set-Location 'D:\SafeJourney'
conda activate safejourney
conda env update -n safejourney -f environment.yml
python -m pip check
```

Nếu chỉ cập nhật các thư viện pip đã được khai báo, có thể dùng hai file requirements trực tiếp trong môi trường đang kích hoạt:

```powershell
python -m pip install -r .\load_tests\requirements.txt -r .\research_benchmarks\requirements.txt
python -m pip check
```

Hai cách trên phục vụ cùng cấu hình hiện tại; không cần chạy cả hai mỗi lần. H3/OR-Tools nằm trong [backend/requirements.txt](../backend/requirements.txt); PyArrow phục vụ benchmark ngoại tuyến nằm trong [requirements riêng](../research_benchmarks/requirements.txt). Không cài vào `base`.

Khởi động dữ liệu và áp dụng migration bằng cấu hình database demo của bạn:

```powershell
docker compose up -d --wait
Set-Location backend
python -m app.db
Set-Location ..\frontend
npm.cmd ci
npm.cmd run build
```

[007_operations_assessments.sql](../backend/migrations/007_operations_assessments.sql) thêm bảng `operations_runs` và index lịch sử/giới hạn tác vụ. Migration không thay nội dung proposal, phản hồi hoặc quy trình khẩn cũ. Không sửa migration đã áp dụng, không xóa volume để nâng cấp. Sau đó khởi động lại API, Detector, Planner và frontend theo [hướng dẫn 02](02-huong-dan-cai-dat-va-lap-trinh.md#g06).

## 3. Chạy thử bằng giao diện

1. Đăng nhập bằng tài khoản **operator** hoặc **operator2**. Driver/passenger không có quyền mở phần này.
2. Tìm khu vực **Agent kiểm tra vận hành** ở dashboard.
3. Chọn chuyến có tuyến đã lưu, rồi chọn kịch bản.
4. Bấm **Agent kiểm tra vận hành**. Chờ kết quả đã lưu; đọc các điểm cần xác minh trước khi xem từng thẻ số liệu.
5. Mở **Các bước agent và giả định tính toán** để biết dữ liệu nào được dùng và giới hạn của mô hình.
6. Mở **Lịch sử gần đây của chuyến này** để xem lại báo cáo đã chụp tại thời điểm chạy. Lịch sử không tự tính lại theo vị trí/pin hiện tại.

| Kịch bản | Đầu vào thay đổi | Điều cần quan sát |
|---|---|---|
| Vận hành bình thường | Tốc độ mẫu 30 km/h, nhu cầu nền 4 yêu cầu/giờ | Cước, pin và phân bổ; một xe mẫu có pin thấp nên có thể còn yêu cầu chưa phục vụ |
| Giờ cao điểm | Nhu cầu nhân 2,5; tốc độ 18 km/h; thêm 10 phút chờ | 10 yêu cầu so với đội xe mẫu 4 chiếc; thời gian và năng lượng tăng |
| Mưa và tăng thời gian di chuyển | Nhu cầu nhân 1,5; tốc độ 22 km/h; thêm 10 phút chờ | Đây là hệ số giả định được ghi rõ, chưa là dự báo thời tiết thực |
| Pin thấp / trạm sạc có hàng chờ | SOC mẫu 15,1%, mức dự trữ 15%; hàng chờ dài hơn | Xe có thể không đủ pin đến đích/trạm; thời gian sạc chỉ có ý nghĩa nếu đã đưa xe tới trạm |
| Đối soát cước / hoàn tiền mô phỏng | Số tiền mẫu đã thu cao hơn cước tính lại 50.000 VND | Công cụ tính mức hoàn, không chuyển tiền và không kết luận gian lận |

Nếu chuyến có sự cố đang mở mức 3 tại lúc chụp đầu vào, báo cáo chặn phân xe mô phỏng và nhắc ưu tiên hồ sơ khẩn. Xử lý khẩn vẫn ở khu vực sự cố với quyền phụ trách và phê duyệt của backend.

## 4. Nguồn đầu vào và giới hạn dữ liệu

[scenarios.py](../backend/app/operations/scenarios.py) có phiên bản `operations-demo-v1`. Một lượt chạy dùng:

- ID, phiên bản, trạng thái và tuyến chuyến đọc từ PostgreSQL. PostGIS lấy điểm đầu/cuối và chiều dài tuyến theo mét bằng `geography`.
- Đội xe **4 chiếc** do kịch bản tạo; vị trí được đặt quanh điểm bắt đầu tuyến. Đây không phải các xe live đã được phân công trong hệ thống.
- Dung lượng pin, SOC, SOH, mức dự trữ, mức tiêu thụ, trạm sạc, hàng chờ, lịch nhu cầu, thời tiết và khoản cước đã thu đều là dữ liệu mô phỏng.
- Trạm mẫu nằm ở đích của tuyến. Chưa tìm trạm gần nhất, chưa kiểm tra đầu cắm, đặt chỗ hoặc trạng thái trạm thật.

Điểm đầu tuyến không phải vị trí hiện tại của xe. `captured_at` và `trip_version` trong báo cáo giúp nhận biết thời điểm đầu vào được chụp; báo cáo là bản ghi lịch sử. Trước khi thực thi một hành động thật trong tương lai, backend phải đọc lại dữ liệu mới và kiểm tra lại các ràng buộc.

## 5. Các agent phối hợp như thế nào?

[workflow.py](../backend/app/operations/workflow.py) xây một LangGraph với bảy vai trò. Chúng hiện là **các node chuyên trách trong cùng tiến trình**, không phải bảy dịch vụ độc lập hoặc bảy LLM tự trị.

| Vai trò | Công việc | Nguồn số liệu |
|---|---|---|
| Điều phối | Chọn ưu tiên pin, cước hoặc nhu cầu | Policy mặc định; có thể bật LLM chọn một giá trị hợp lệ |
| Không gian / lộ trình | Tính đường tham chiếu; gọi OSRM nếu cấu hình | PostGIS, phép đo khoảng cách, OSRM |
| Cước / hoàn tiền | Tính từng thành phần cước và trần hoàn | Công cụ Decimal, policy có phiên bản |
| Pin / sạc | Tính năng lượng, dự trữ, khả năng đến trạm, hàng chờ | Mô hình năng lượng tuyến tính và hàng chờ xác định |
| Nhu cầu | Xác định ô H3 và nhu cầu kịch bản | Trung bình lịch mẫu nhân hệ số được khai báo |
| Phân xe | Tối ưu số yêu cầu phục vụ, rồi thời gian đón | OR-Tools, ma trận tuyến, pin, ghế và thời gian chờ |
| Kiểm chứng | Kiểm tra kết quả không vi phạm các điều kiện chính | Quy tắc backend; không coi đây là phê duyệt |

Ưu tiên pin làm bước pin chạy trước bước cước. Mọi nhánh vẫn phải chạy đủ các công cụ bắt buộc trước khi lưu kết quả. LLM không trả số tiền, dung lượng, tuyến tùy ý hoặc lệnh gọi cứu hộ. Nhật ký báo cáo ghi đủ vai trò và kết quả; danh sách vai trò là tóm tắt, không phải bản đo thời gian từng node.

## 6. Các phép tính xác định

### 6.1. Cước và hoàn tiền

[calculations.py](../backend/app/operations/calculations.py) dùng `Decimal`. Policy `safejourney-demo-v1` là **biểu giá thực hành bằng VND**, không phải giá hợp đồng hay biểu giá TLC:

```text
Cước trước giảm = 15.000 + km × 10.000
                   + phút di chuyển × 500 + phút chờ × 500 + phụ phí
Cước cuối = max(0, cước trước giảm − giảm giá), làm tròn HALF_UP tới 1 VND
Hoàn dự kiến = min(số đã trả − số đã hoàn,
                   max(0, số đã trả − cước đúng − số đã hoàn))
```

Khoản hoàn làm tròn xuống tới 1 VND để không vượt số tiền còn được hoàn. Đầu vào âm, số không hữu hạn và khoản đã hoàn vượt khoản đã trả bị từ chối. Báo cáo lưu policy, đầu vào và từng thành phần; `money_moved=false` luôn được giữ trong luồng này.

### 6.2. Pin và mức dự trữ

SOC là phần trăm pin hiện có; SOH là phần trăm dung lượng còn hữu dụng so với thiết kế. Công cụ dùng:

```text
Dung lượng hữu dụng = dung lượng thiết kế × SOH / 100
Năng lượng hiện có = dung lượng hữu dụng × SOC / 100
Dự trữ tối thiểu = dung lượng hữu dụng × phần trăm dự trữ / 100
Năng lượng cần = mét × Wh/km / 1.000.000 + giây × phụ tải kW / 3.600
Hợp lệ khi năng lượng hiện có − năng lượng cần ≥ dự trữ tối thiểu
```

Kiểm tra dùng giá trị Decimal trước khi làm tròn để hiển thị. `available_kwh` nghĩa là năng lượng có thể dùng **sau khi trừ dự trữ**, khác `current_kwh` là toàn bộ năng lượng hiện có. Phân xe kiểm tra cả đoạn tới điểm đón và hành trình; phụ tải cũng tính trong thời gian chờ mẫu.

Mô hình chưa được hiệu chuẩn cho loại xe, nhiệt độ, dốc đường, tái sinh hoặc suy hao động. Kết quả “đủ pin” chỉ đúng theo đầu vào và giả định này.

### 6.3. Hàng chờ và sạc

Công suất hiệu dụng bằng `min(công suất trạm, giới hạn xe) × hiệu suất`. Thời gian sạc bằng năng lượng cần bổ sung chia công suất. Bộ tính hàng chờ FCFS đặt từng xe phía trước vào cổng rảnh sớm nhất, dựa trên thời gian còn lại của từng cổng và thời lượng phiên giả định.

Thời gian sạc không bao gồm di chuyển tới trạm. Công cụ dùng SOC dự kiến khi tới đích; nếu xe không đủ pin giữ dự trữ tới trạm, giao diện nêu rõ kết quả sạc **chỉ có điều kiện sau khi xe đã được đưa tới trạm**. Không dùng phép tính sạc để khuyến nghị xe tự chạy thêm khi không đủ năng lượng.

### 6.4. H3 và nhu cầu

H3 chuyển tọa độ sang ô lục giác; trong dashboard dùng độ phân giải 8 để định danh khu vực điểm đón. H3 tự nó không dự báo nhu cầu. Nhu cầu hiện tại là trung bình bảy số đếm mẫu `[3, 5, 4, 4, 6, 2, 4]`, nhân hệ số kịch bản rồi làm tròn lên.

Benchmark TLC ở [10](10-du-lieu-thuc-va-benchmark.md) dùng **taxi zone × giờ** và đánh giá ngoại tuyến trên dữ liệu thực. Model và mã vùng TLC chưa được nối vào dashboard H3 ở Việt Nam. Không đổi mã taxi zone thành tọa độ giả hoặc coi hệ số mưa mẫu là kết quả đã huấn luyện.

### 6.5. OR-Tools phân xe

[optimizer.py](../backend/app/operations/optimizer.py) giải bài toán ghép một xe với tối đa một yêu cầu bằng min-cost flow:

1. Loại cặp không đáp ứng: xe không sẵn sàng, cạnh không đi được, không đủ ghế, thời gian đón quá giới hạn hoặc không đủ pin giữ dự trữ.
2. Ưu tiên phục vụ được nhiều yêu cầu nhất.
3. Trong các phương án có cùng số yêu cầu phục vụ, giảm tổng thời gian đón. Chi phí solver làm tròn lên tới giây cho mỗi cạnh; kiểm tra pin và giới hạn chờ dùng số đo chưa làm tròn.
4. Trả danh sách ghép xe/yêu cầu và các yêu cầu chưa phục vụ kèm lý do.

Công cụ giới hạn tối đa 100 xe và 100 yêu cầu mỗi lần gọi; UI hiện chỉ dùng 4 xe và tối đa 10 yêu cầu mẫu. Đây chưa là tối ưu cả ca làm việc, ghép nhiều khách, tuyến nhiều điểm hoặc điều xe toàn thành phố.

## 7. OSRM và LLM là tùy chọn

### 7.1. Định tuyến

Mặc định `OSRM_URL` để trống. Chiều dài hành trình dùng tuyến lưu trong PostGIS; thời gian dùng tốc độ mẫu. Đoạn xe tới điểm đón dùng khoảng cách đường chim bay. Báo cáo đánh dấu **chưa xác minh đường bộ**; phân xe chỉ có ý nghĩa minh họa.

Muốn dùng OSRM, trước tiên cần một dịch vụ do bạn quản lý, có bản đồ bao phủ khu vực của các chuyến. Đặt địa chỉ dịch vụ đó trong `backend/.env`, rồi khởi động lại API:

```dotenv
OSRM_URL=http://127.0.0.1:5000
OSRM_TIMEOUT_SECONDS=3
```

Địa chỉ trên là ví dụ nếu bạn đã có OSRM chạy ở cổng 5000; Compose hiện tại **không dựng OSRM**. Không có host OSRM công cộng mặc định. Tọa độ tuyến và điểm đón được gửi tới host đã cấu hình; không đưa địa chỉ hoặc khóa OSRM vào biến frontend `VITE_*`.

[spatial.py](../backend/app/operations/spatial.py) gọi `route` và `table`, kiểm tra số đo hữu hạn, kích thước ma trận, tọa độ, hình học đầu/cuối và khoảng cách ghép vào đường. Mỗi lượt HTTP có deadline toàn lượt, mặc định 3 giây và giới hạn 2 MB. Không tự theo redirect, dùng proxy môi trường hoặc coi cạnh ước lượng là tuyến được xác minh. `null` trong ma trận là không đi được.

Nếu cấu hình OSRM nhưng gọi lỗi, backend giữ số tham chiếu hình học để giải thích và **chặn phân xe**; không âm thầm đổi sang đường chim bay rồi gắn nhãn đã xác minh. `verified=true` chỉ có nghĩa phản hồi bộ định tuyến đã qua kiểm tra, không chứng minh an toàn đường hoặc giao thông hiện tại. Kịch bản mưa/cao điểm vẫn nhân thời gian theo giả định riêng được ghi trong báo cáo.

### 7.2. LLM chọn ưu tiên

Mặc định `OPERATIONS_LLM_MODE=mock`; policy backend chọn ưu tiên. Muốn thử model Ollama đã cài theo [02](02-huong-dan-cai-dat-va-lap-trinh.md#g11), đặt:

```dotenv
OPERATIONS_LLM_MODE=ollama
OPERATIONS_LLM_TIMEOUT_SECONDS=8
```

Phần này dùng chung `OLLAMA_URL`/`OLLAMA_MODEL` hiện có. Prompt chỉ gồm loại kịch bản, cờ pin thấp và cờ nhu cầu cao; không gửi ID chuyến hoặc tọa độ. JSON chỉ chấp nhận khóa `focus` với một trong `energy`, `fare`, `demand`. Lượt HTTP có deadline toàn lượt mặc định 8 giây, cấu hình tối đa 15 giây và giới hạn phản hồi 32 KiB. Model không dùng được hoặc trả sai schema thì quay về policy backend. Trạng thái `model_used` trong báo cáo cho biết model có thực sự được dùng hay không. Kiểm thử mock không chứng minh chất lượng hoặc tốc độ LLM thật.

## 8. API, chống nhấn lặp và bộ nhớ

| API | Hành vi |
|---|---|
| `GET /api/operations/scenarios` | Danh mục kịch bản cố định |
| `POST /api/operations/plans` | Nhận `request_id` UUID, `trip_id`, `scenario_id`; tính và lưu một lượt |
| `GET /api/operations/plans?trip_id=...&limit=10` | Lịch sử mới nhất; giới hạn tối đa 50 dòng |
| `GET /api/operations/plans/{id}` | Xem báo cáo đã lưu |

Tất cả API yêu cầu operator. Backend tự dựng đầu vào; client không được bổ sung số tiền/pin hoặc URL công cụ. Trong mô hình quyền hiện tại operator có quyền xem các chuyến; chưa có phân tách tổ chức/tenant. Không trả raw snapshot và định danh người tạo trong response báo cáo công khai, nhưng kết quả có thông tin tuyến nên vẫn là dữ liệu cần bảo vệ.

Một UUID gắn với người tạo, chuyến và kịch bản. Gửi lại cùng nội dung sau khi hoàn tất trả kết quả đã lưu; thay người tạo/nội dung với UUID cũ bị chặn. Giao diện giữ UUID khi lỗi để retry không tạo thêm lượt. Mỗi lượt có snapshot, token thực thi và lease 90 giây; worker cũ không ghi đè kết quả khi lượt đó đã được nhận lại với token mới. Lượt lỗi hoặc lease hết hạn được thử lại trên snapshot cũ; muốn đánh giá đầu vào mới phải tạo lượt mới.

Tính toán diễn ra ngoài transaction giữ khóa database. Mỗi API process nhận tối đa 2 lượt tính đồng thời; mỗi tài khoản có tối đa 1 lượt còn lease và 10 yêu cầu **mới** mỗi phút. Giới hạn mới/phút không phải quota toàn cụm cho mọi retry. `429` nghĩa bận hoặc đạt giới hạn, `409` là xung đột/đang chạy, `503` là chưa tính xong; không coi những mã này là hành động đã thực thi. Lịch sử có `RUNNING`/`FAILED` để đối chiếu; đây chưa là job queue nền tự retry sau restart.

## 9. Kiểm chứng và bước mở rộng tiếp theo

Test công cụ/graph không cần database, chạy trong thư mục `backend` sau khi kích hoạt Conda:

```powershell
python -m pytest tests/test_operations_tools.py tests/test_operations_workflow.py -q
```

Test quyền, snapshot, retry và token nằm ở [test_operations_integration.py](../backend/tests/test_operations_integration.py). Trước khi chạy, làm đầy đủ [mục 12.2 hướng dẫn 02](02-huong-dan-cai-dat-va-lap-trinh.md#g12): database test riêng, Redis DB1, `RUN_DEMO_TESTS=1`, seed mật khẩu cùng terminal, không chạy integration trong lúc đo tải. Test frontend ở [operationsPanel.test.js](../frontend/tests/operationsPanel.test.js). Số pass, bằng chứng DB/browser và những gì chưa kiểm chứng xem [07](07-ket-qua-kiem-thu-va-tai.md).

Các bước tiếp theo để dùng dữ liệu vận hành thật:

- Thay `scenarios.py` bằng nguồn đơn hàng/xe/pin/trạm sạc có thời điểm quan sát, độ mới, đơn vị và quyền truy cập rõ ràng; giữ kịch bản mô phỏng để test.
- Huấn luyện và đánh giá forecast theo vùng/thời gian bằng dữ liệu phù hợp; kiểm tra trôi dữ liệu, zero-demand, giờ cao điểm và thời tiết. Giữ đánh giá trên thời gian chưa dùng để huấn luyện.
- Cấu hình OSRM với bản đồ/profile phù hợp; kiểm chứng map matching, đường cấm và dữ liệu giao thông nếu bổ sung.
- Trước dispatch/hoàn tiền thật, xây policy thực thi, kiểm tra lại snapshot mới, quota, idempotency với provider và đối soát trạng thái không chắc chắn. Chỉ quy trình khẩn dùng HITL theo yêu cầu sản phẩm; không biến phép tính thành quyền tự gọi công an/cứu hộ.
- Với 1.000.000 xe, chia ô/vùng và cửa sổ thời gian, lọc ứng viên trước solver; không tạo ma trận một triệu × một triệu hoặc gọi LLM cho mỗi GPS. Cần queue/lease phân tán, ngân sách toàn cụm, đo tải hỗn hợp và ưu tiên SOS. Đây là kiến trúc đích, chưa là năng lực đã đo của code hiện tại; xem [07](07-ket-qua-kiem-thu-va-tai.md#million-vehicles).

Tham chiếu kỹ thuật: [H3 Python API](https://uber.github.io/h3-py/api_quick.html), [OSRM HTTP API](https://github.com/Project-OSRM/osrm-backend/blob/master/docs/http.md), [OR-Tools min-cost flow assignment](https://developers.google.com/optimization/flow/assignment_min_cost_flow). Các nguồn dữ liệu thực và phạm vi áp dụng nằm trong [10](10-du-lieu-thuc-va-benchmark.md).
