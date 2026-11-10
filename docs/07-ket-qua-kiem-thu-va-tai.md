# SafeJourney — kết quả kiểm chứng và khả năng mở rộng

**Cập nhật: 10/11/2026.** Báo cáo hiện hành cho phần an toàn tự động và module kiểm tra vận hành. Bằng chứng cũ được giữ nguyên để đối chiếu, không thay cho số đo của mã hiện tại.

## 1. Kết quả hiện tại

**237/237 test PASS, không skip:** 165 backend, 17 simulator/bộ tải, 17 benchmark TLC, 38 frontend. Frontend build và Docker build/runtime đều đạt. Integration dùng PostgreSQL/Redis local thật với dữ liệu giả; các cuộc gọi LLM/OSRM trong test được giả lập.

Bài tải **1.000 xe, 2 API + 1 Detector + 1 Planner, 5 phiên đọc HTTP** đạt **14/14 ngưỡng** trên source hiện tại. Steady xác nhận 40.000/40.000 GPS, toàn bài 55.005 APPLIED và tồn đọng cuối 0. Source fingerprint đầu/cuối khớp.

Benchmark dữ liệu thật NYC TLC Green Taxi 01/2025 đã chạy ngày 09/11, đọc 48.326 hàng và giữ 48.160 lượt đón hợp lệ theo tháng/vùng. Baseline seasonal mean có WAPE **55,26% theo vùng–giờ**, **13,17% tổng thành phố** trên tuần cuối; phương pháp, đối chứng và giới hạn ở [10](10-du-lieu-thuc-va-benchmark.md). Đây là đánh giá dự báo lượt đón/đối soát tiền, không đo độ chính xác cảnh báo an toàn.

**Mọi liên hệ và hành động hỗ trợ vẫn mô phỏng; phương án vận hành chỉ là đề xuất. Chưa kiểm chứng 1.000.000 xe, chưa deploy Fly.io.**

## 2. Kiểm thử chức năng và giao diện

| Phạm vi | Kết quả | Điều đã xác nhận |
|---|---|---|
| Backend Conda Python 3.12 | 165 passed, 0 skipped | Rule/GPS/SOS, quyền, ownership, AUTO/HITL, phản hồi; công cụ tiền/pin/sạc, OSRM, solver và graph |
| Simulator + harness | 17 passed | Lịch open-loop, payload, guard, gates, fingerprint |
| Benchmark ngoại tuyến | 17 passed | Chia thời gian, zero-fill, metrics, tiền Decimal, giới hạn tải và provenance |
| Frontend | 38 passed; build đạt | Bộ lọc, trạng thái UI, quyền, retry UUID, kết quả khác chuyến/kịch bản/mã yêu cầu, lịch sử |
| Operations trên DB thật | PASS | Operator-only; snapshot bất biến; retry; quota; lease/token chặn ghi đè; SOS đang mở chặn phân xe; không tác động chuyến/hành động |
| HTTP qua 2 API process | PASS | Năm kịch bản; 12 request cùng UUID chỉ tạo 1 dòng, retry trả kết quả đã lưu; driver không xem lịch sử |
| Chrome trên API thật | PASS cho các luồng đã nêu | Pin thấp 0/4 phân bổ, cao điểm 3/10, hoàn mẫu 50.000 VND, chi tiết cước và mở lại lịch sử |
| Docker Linux | Build + graph smoke PASS | Import ứng dụng, H3/OR-Tools native, graph pin thấp, UID 10001, không cần mạng khi chạy smoke |

Integration dùng **safejourney_test**, PostgreSQL 25432, Redis 26379/DB1, `RUN_DEMO_TESTS=1`; không có Detector/Planner background hoặc bài tải đồng thời. JUnit ở `.work/operations-20261110/backend.xml` và `tools.xml`. Migration 007 được áp dụng trên database thử; migration cũ giữ checksum.

HTTP/browser dùng database riêng **safejourney_operations_ui_20261110**, Redis DB3, API 18000 với hai workers, LLM mock và OSRM chưa cấu hình. Không chạy Detector/Planner trong lượt UI vận hành này. [JSON HTTP](benchmarks/operations-http-20261110.json) ghi các kịch bản và phản hồi giới hạn đồng thời: 8/12 request burst nhận 429, 4 trả 200, chỉ một kết quả mới; không coi đây là phép đo throughput. [Ảnh Chrome](benchmarks/operations-low-battery-20261110.png) thể hiện cảnh báo thiếu pin và tính chất mô phỏng.

Lượt HTTP phát triển đầu gặp truy vấn nhầm tên bảng kiểm tra; sửa helper sang `mock_actions`. Lượt thử lại quá sớm nhận 429 đúng quota; lượt cuối đợi cửa sổ giới hạn rồi đạt. Không giảm quota hoặc sửa ngưỡng để đạt. Lượt unit đầu của công cụ từng phát hiện giới hạn chữ số thập phân làm từ chối số đo PostGIS; đã sửa giữ số hữu hạn/range và thêm hồi quy.

Luồng browser AUTO/HITL và bộ lọc đã có bằng chứng riêng ngày 02/11: [playbook](benchmarks/autonomous-playbooks-20261102.json), [bộ lọc](benchmarks/queue-filters-20261102.json). Hồi quy backend hiện tại vẫn kiểm tra chúng; không tuyên bố đã chạy lại toàn bộ luồng browser cũ ngày 10/11.

Bundle chính **197,95 KB**, gzip **63,35 KB**. Mapbox tải riêng **1.918,76 KB**, gzip **541,95 KB**, còn cảnh báo kích thước. Vite đã lên 6.4.6; `npm audit` không có lỗ hổng được báo tại lúc kiểm tra. Docker có cảnh báo tên ARG/ENV VITE_MAPBOX_TOKEN; đây là token công khai frontend, không dùng secret server ở đó. Chưa đo FPS/bộ nhớ bản đồ 1.000 điểm. Docker smoke không chứng minh triển khai Fly hoặc kết nối provider thật.

## 3. Cấu hình tải được đo

| Tham số | Giá trị |
|---|---|
| Run-id | run-20261109-234632-edee |
| Ngày local | 10/11/2026, UTC+7; run-id và thời gian gốc trong JSON dùng UTC |
| Xe/chuyến/tài xế giả | 1.000 |
| Lịch | Open-loop, GPS mỗi 3 giây, mục tiêu 333,33 request/giây |
| Ramp / warmup / steady | 30 / 30 / 120 giây |
| API / Detector / Planner | 2 / 1 / 1 |
| Pool max mỗi process / batch GPS | 16 / 200 |
| Người xem | 5 phiên HTTP, mỗi phiên 3 GET/giây; không phải 5 browser |
| LLM | mock; normal không tạo sự cố chủ động |
| Hạ tầng | PostgreSQL/PostGIS 25432, Redis 26379/DB0; máy sinh tải và dịch vụ chung máy local |
| Python | Conda safejourney, 3.12.15 |

Fingerprint **d6e7fac802d1a3a28160b0843435222c982a6b92a141dd33cfe2bbfe202c6817**, 67 file. Không sửa source trong lượt đo, không chạy integration/build/browser/model cùng bài tải. Database từ các lượt trước được giữ, không xóa volume.

## 4. Số liệu tải và ngưỡng

| Chỉ số steady | Kết quả | Ngưỡng/ý nghĩa |
|---|---:|---|
| GPS theo lịch / được xác nhận | 40.000 / 40.000 | Đủ lịch |
| Lỗi HTTP GPS | 0 | ≤0,1% |
| Dropped late / capacity | 0 / 0 | 0 |
| HTTP GPS p95 | 19,034 ms | ≤250 ms |
| HTTP GPS p99 / max | 29,344 / 128,792 ms | Không phải ngưỡng p95 |
| Nhận → Detector xử lý p95 | 44,706 ms | ≤2.000 ms |
| GET nhân viên thành công / theo lịch | 1.800 / 1.800 | Không dropped |
| GET nhân viên p95 | 26,096 ms | ≤250 ms |
| Tồn đọng cuối toàn bài | 0 | 0 |

Toàn bài: **55.005 nhận, 55.005 xử lý, 55.005 APPLIED**; không phát sinh sự cố trong đội xe normal. **14/14 gate PASS**, không có lỗi monitor database. [JSON gốc](benchmarks/run-20261109-234632-edee.json) giữ đầy đủ ramp/warmup, backlog và phân vị.

## 5. Diễn giải và giới hạn

HTTP latency gồm chờ connection của client. Processing latency là `received_at` đến `processed_at`, ghi cuối lô trước commit; chưa bao gồm chính xác toàn bộ fsync/commit, WebSocket và render. HTTP steady phân theo lịch gửi; DB steady phân theo thời gian server nhận. Không cộng p95 các bước thành p95 đầu cuối.

Bài tải này chỉ gửi GPS normal và GET nhân viên; **không gọi operations solver/OSRM/LLM đồng thời với GPS**. Năm kịch bản vận hành dùng 4 xe mẫu và tối đa 10 yêu cầu, không đại diện cho điều phối 1.000 xe. Cần bài tải hỗn hợp có dự báo, tối ưu, SOS, xác nhận và timeout trước khi công bố năng lực đó.

OSRM đã kiểm tra bằng HTTP mock cho phản hồi đúng/sai/timeout; chưa chạy engine bản đồ thực. LLM vận hành được kiểm tra schema/fallback/deadline với mock, chưa đánh giá model thật. Pin, trạm, thời tiết và fleet trong dashboard là mô phỏng; forecast TLC ngoại tuyến chưa nối runtime H3. Không có nhãn tai nạn/SOS/gian lận thực để báo precision/recall. Một chênh lệch thành phần tiền TLC không chứng minh gian lận hay mức hoàn hợp lệ.

Chưa thử soak dài, bão cảnh báo, provider thật, failover, backup/restore hoặc Fly.io. Auto-close vẫn kiểm tra mẫu GPS mới nhất cuối khoảng theo dõi, không chứng minh tín hiệu liên tục 60 giây. Liên hệ mẫu gửi tài xế, chưa có quota chung theo chuyến/người; LLM sự cố còn nằm trước liên hệ đầu tiên. Lộ trình xử lý tiếp ở [03](03-lo-trinh-phat-trien.md), [08](08-quy-trinh-operator-va-phan-cong.md), [09](09-dieu-phoi-van-hanh-va-cong-cu-xac-dinh.md).

## 6. Tái chạy và giữ bằng chứng

Đọc [06](06-kiem-thu-tai-1000-xe.md), dùng Anaconda PowerShell Prompt:

~~~powershell
Set-Location 'D:\SafeJourney'
conda activate safejourney
python -m load_tests.local --api-workers 2 --allow-local-loadtest
~~~

Không chạy integration đồng thời, không sửa source hoặc giảm ngưỡng. JSON trong docs/benchmarks được sao chép nguyên byte từ load_tests/reports, SHA-256 **0f9c7c9f3c996a7a1141592dadd42e9b588fbb1fa4dcda2c289fe481cd4d5b62**. Log ở `.work/loadtest/run-20261109-234632-edee/`. Các JSON cũ kể cả FAIL vẫn được giữ làm bằng chứng lịch sử.

<a id="million-vehicles"></a>

## 7. Khả năng mở rộng tới 1.000.000 xe — phân tích, chưa đo thực tế

**Hiện chưa thể công bố SafeJourney phục vụ được 1.000.000 xe đồng thời.** Bài tải 1.000 xe xác nhận đúng cấu hình và kịch bản ở mục 3–5; không cho phép nhân kết quả lên 1.000 lần để suy ra số máy hoặc chi phí. Phần này là tính toán nhu cầu, rà soát giới hạn trong code và đề xuất đường phát triển. Các thành phần phân tán bên dưới **chưa được triển khai trong MVP**.

### 7.1. Một triệu xe đăng ký khác một triệu xe hoạt động đồng thời

Gọi N là tổng xe, a là tỷ lệ đang hoạt động và T là chu kỳ GPS tính bằng giây:

~~~text
R = N × a / T                      sự kiện GPS/giây
Số sự kiện/ngày = R × 86.400        nếu tải đó duy trì liên tục 24 giờ
~~~

Một triệu xe đăng ký nhưng chỉ 10% hoạt động, gửi mỗi 3 giây, tạo khoảng **33.333 sự kiện/giây**. Một triệu xe cùng hoạt động tạo nhu cầu sau:

| Chu kỳ GPS | Sự kiện/giây | Sự kiện/ngày, hoạt động 24 giờ |
|---|---:|---:|
| 1 giây | 1.000.000 | 86,4 tỷ |
| 3 giây | 333.333,33 | 28,8 tỷ |
| 5 giây | 200.000 | 17,28 tỷ |
| 10 giây | 100.000 | 8,64 tỷ |

Để đối chiếu với benchmark hiện tại, các tính toán tiếp theo dùng **1.000.000 xe đồng thời, GPS mỗi 3 giây**. Tần suất gửi có thể thích ứng theo tình huống, nhưng phải đánh giá lại khả năng phát hiện của rule; không giảm tần suất chỉ để làm bài tải đạt.

### 7.2. Băng thông, lưu trữ và tồn đọng

Kích thước 500 B và 1 KB bên dưới là **hai giả định thiết kế**, chưa đo kích thước lưu thực tế của bản tin hiện tại. Dùng đơn vị thập phân: 1 KB = 1.000 B, 1 MB = 10⁶ B, 1 TB = 10¹² B.

| Payload mỗi sự kiện | Payload đầu vào | Băng thông payload | Payload/ngày | Payload/30 ngày |
|---|---:|---:|---:|---:|
| 500 B | 166,7 MB/giây | 1,33 Gbit/giây | 14,4 TB | 432 TB |
| 1 KB | 333,3 MB/giây | 2,67 Gbit/giây | 28,8 TB | 864 TB |

Đây chưa gồm HTTP/TLS, index, WAL, bản sao ở các tầng, replica, checkpoint, backup hoặc truy vấn dashboard; cũng chưa giả định tỷ lệ nén. Nếu riêng payload 30 ngày được lưu ba bản, dung lượng tương ứng đã là **1,296 PB hoặc 2,592 PB**. Không dùng con số payload này làm dự toán dung lượng PostgreSQL hay báo giá hạ tầng.

Một triệu sự kiện không nhất thiết cần một triệu kết nối đồng thời: số kết nối phụ thuộc giao thức, keep-alive, batching và thời gian request. MVP hiện gửi một GPS trong một HTTP request; thiết kế batch có thể giảm overhead, nhưng phải giữ timestamp, UUID, kiểm tra quyền và kết quả riêng của từng sự kiện.

Nếu Detector dừng **5 phút** trong khi API vẫn nhận đủ tải:

~~~text
Backlog = 333.333,33 × 300 ≈ 100.000.000 sự kiện
Payload backlog ≈ 50–100 GB

Muốn xử lý hết backlog trong 10 phút và vẫn nhận tải mới:
Năng lực xử lý ≥ R + backlog / 600
              ≈ 500.000 sự kiện/giây
~~~

Phép tính chưa gồm dự phòng hoặc partition lệch tải. Dung lượng queue và thời gian phục hồi phải được thiết kế cùng nhau. “Nhận được GPS” chưa có nghĩa “cảnh báo kịp thời”.

### 7.3. Giới hạn cụ thể của code hiện tại

| Thành phần và source | Hiện trạng | Điều cần thay trước khi công bố quy mô lớn |
|---|---|---|
| [API GPS](../backend/app/api/trips.py) | Mỗi GPS kiểm tra phiên/quyền, khóa chuyến, ghi inbox/outbox và cập nhật thời điểm nhận | Đo CPU, khóa, WAL, I/O; batch có giới hạn; định tuyến dữ liệu theo shard |
| [Detector](../backend/app/worker.py) | Một process giữ khóa singleton; relay, batch và watchdog chung vòng lặp | Chia ownership theo chuyến; bàn giao trạng thái và phục hồi có kiểm chứng |
| Redis Streams | Một Stream dùng chung, consumer detector-1 | Chia Stream/partition có chủ đích; tăng Redis node không tự chia một key |
| [Dữ liệu GPS](../backend/schema.sql) | Inbox giữ lịch sử/chống trùng; chưa có retention tự động | Tách dữ liệu vận hành và lịch sử, phân vùng và thời hạn lưu |
| GPS watchdog | Tối đa 1.000 chuyến/lượt, cách khoảng 5 giây sau khi hoàn tất lượt trước | Lịch hết hạn theo partition, tránh quét toàn đội xe và chậm hàng loạt |
| [Planner](../backend/app/planner.py) | Singleton, một lane khẩn và một lane thường; timer tối đa 100 hồ sơ đến hạn/lượt | Claim job/lease, timer chia tải, quota và tài nguyên ưu tiên; kiểm thử bão SOS/phản hồi |
| [Realtime](../backend/app/realtime.py) | Mỗi WebSocket kiểm tra phiên/version mỗi giây; operator cộng version toàn bảng trips | Fanout theo phạm vi, snapshot/delta, không quét bảng cho từng người xem |
| GET /api/trips | Trả toàn bộ tập chuyến thuộc phạm vi; 50 dòng/trang chỉ là phía browser | Phân trang và bộ lọc server; API bản đồ theo vùng |
| [Cụm sự cố](../backend/app/api/incidents.py) | DBSCAN theo request, phép chiếu cố định EPSG:32648 | Tính nền theo vùng/thời gian, lựa chọn phép chiếu phù hợp địa bàn |
| [Bộ sinh tải](../load_tests/run.py) | Local tối đa 10.000 xe; giữ mẫu latency trong RAM | Harness phân tán riêng cho 100.000–1.000.000 xe |

Ví dụ mất GPS đồng loạt: một triệu chuyến đủ điều kiện, mỗi lượt chỉ chọn 1.000 chuyến, cần 1.000 lượt. Với khoảng nghỉ 5 giây, riêng các khoảng nghỉ đã gần **83 phút**, chưa tính truy vấn và ghi sự cố. Đây là suy luận từ cấu hình cho tình huống cực đoan, **không phải số đo**.

Redis Cluster chia key vào hash slot; một Stream key vẫn thuộc một slot. Vì vậy, nếu giữ Redis Streams, ứng dụng phải định tuyến sang nhiều Stream. Redis Cluster còn dùng replication bất đồng bộ, có cửa sổ mất bản ghi đã xác nhận khi failover; không được thay nơi lưu bền vững hiện tại bằng Redis rồi mặc nhiên giữ nguyên cam kết dữ liệu. [Redis Cluster specification](https://redis.io/docs/latest/operate/oss_and_stack/reference/cluster-spec/)

### 7.4. Kiến trúc đích và cách chuyển dần từ MVP

Luồng đề xuất, chưa triển khai:

~~~text
Thiết bị
   │
   ▼
Gateway + API nhận GPS/SOS có xác thực và quota
   ├── GPS → nơi lưu bền vững chia partition → Detector theo chuyến
   │                                           ├── trạng thái mới nhất → realtime theo phạm vi
   │                                           └── sự cố → Planner → HITL → action outbox
   └── SOS → ghi sự cố bền vững, ưu tiên → nhân viên / playbook

Lịch sử GPS → lưu theo thời gian / kho lưu trữ dài hạn
Nhật ký và quyết định → kho nghiệp vụ có quyền truy cập và audit
~~~

**Bước đầu: giữ hợp đồng, chia quyền sở hữu.** Bổ sung tenant_id và schema_version bên cạnh event_id, trip_id, event_time, received_at và seq. Tenant mới phải đi xuyên API, lưu trữ, truy vấn, job và realtime; kiểm tra quyền từ danh tính đã xác thực, không tin tenant_id do client tự gửi.

Chọn partition theo **(tenant_id, trip_id)** để dữ liệu cùng chuyến đi về cùng nơi xử lý. Chia chỉ theo tenant có thể làm một đơn vị lớn chiếm trọn một shard. Cần partition logic ổn định và định tuyến có phiên bản; đổi số worker không được làm trạng thái chuyến đổi chủ tùy ý. Thứ tự tới queue cũng không thay thế policy event_time: thiết bị vẫn có thể gửi dữ liệu trễ hoặc sai thứ tự.

Trước khi bỏ khóa singleton cần có lease, heartbeat và **fencing token**: mã thế hệ cho phép tầng ghi từ chối worker cũ đã mất quyền. Checkpoint phải gắn trạng thái rule, vị trí đã xử lý và phiên bản cấu hình. Test phải chứng minh crash, replay, rebalance và worker cũ sống lại không tạo sự cố hoặc tác động lặp.

**Bước tiếp: đo từng phương án lưu bền vững.** Có thể bắt đầu bằng nhiều shard inbox/outbox PostgreSQL cùng Detector tương ứng. Khi giới hạn ghi/relay được chứng minh bằng số đo, đánh giá durable log phân tán như Kafka. Kafka có partition giữ thứ tự và phân công consumer trong group, nhưng tác động xuống DB/provider vẫn cần giao dịch hoặc idempotency phù hợp. [Apache Kafka — Design](https://kafka.apache.org/41/design/design/)

Nếu đổi nơi lưu bền vững, phải xác định lại chính xác thời điểm API trả “durable”: dữ liệu đã nằm ở đâu, có bao nhiêu bản sao cần xác nhận, phục hồi được sau loại lỗi nào. Thử timeout sau commit, mất kết nối sau ghi, retry trùng và chết tiến trình trước checkpoint. Không đổi nghĩa API chỉ bằng cách thay adapter queue.

Chuyển từng partition/nhóm chuyến, có đối chiếu và rollback. Có thể chạy Detector mới ở chế độ quan sát để so kết quả, nhưng chỉ một owner được tạo hiệu ứng nghiệp vụ. Chưa cần thay toàn bộ FastAPI, React hoặc LangGraph; ưu tiên đổi các điểm giới hạn đã đo và giữ schema/quyền/HITL.

### 7.5. Dữ liệu, thời hạn lưu và cảnh báo mất tín hiệu

Tách ba nhóm:

| Nhóm | Dữ liệu | Hướng lưu trữ đề xuất |
|---|---|---|
| Trạng thái mới nhất | Vị trí, tuổi GPS, trạng thái rule theo chuyến | Store/cache có version, khả năng dựng lại; owner theo partition |
| Nghiệp vụ cần đối soát | Chuyến, SOS, sự cố, proposal, approval, action và audit | PostgreSQL/PostGIS được chia phạm vi khi cần; giao dịch trong ranh giới rõ ràng |
| Lịch sử khối lượng lớn | GPS thô, dữ liệu phục vụ phân tích | Phân vùng thời gian; kho object dạng cột như Parquet khi phù hợp; truy vấn tách khỏi đường realtime |

PostgreSQL partition giúp quản lý dữ liệu theo thời gian, nhưng không tự phân tán ghi sang nhiều máy. **Không thể chỉ partition inbox theo ngày rồi giữ nguyên giả định event_id duy nhất toàn cục**: PostgreSQL 16 yêu cầu khóa UNIQUE/PRIMARY KEY của bảng partition chứa các cột partition key. Cần thiết kế dedupe/routing riêng hoặc schema phù hợp, rồi thử lại UUID trùng qua ranh giới ngày. [PostgreSQL 16 — giới hạn partition](https://www.postgresql.org/docs/16/ddl-partitioning.html#DDL-PARTITIONING-DECLARATIVE-LIMITATIONS)

Thời hạn giữ khóa chống trùng phải bao phủ khoảng retry/offline/replay được cam kết. Nếu đã xóa dữ liệu dedupe, phải có policy từ chối hoặc cách kiểm chứng bản tin quá cũ; không để replay sau retention trở thành hành động mới. Mọi thay đổi schema dùng migration số tiếp theo, không sửa migration đã áp dụng.

Watchdog nên có lịch hết hạn theo partition, cập nhật khi nhận GPS hợp lệ, thay vì quét toàn bảng. Mất tín hiệu diện rộng cần gom thành sự kiện vận hành để nhân viên hiểu nguyên nhân chung, đồng thời giữ bằng chứng của từng chuyến và không che SOS riêng lẻ.

Retention là yêu cầu sản phẩm cần chốt theo mục đích sử dụng và quyền truy cập; 30 ngày ở bảng tính chỉ là ví dụ. Cần quyền theo tenant, TLS, mã hóa lưu trữ, audit việc xem vị trí/SOS và cơ chế xử lý dữ liệu trong backup theo chính sách đã thống nhất.

### 7.6. SOS, LLM, HITL và năng lực nhân viên

SOS hiện được API tạo sự cố trực tiếp, không chờ Detector hoặc LLM. Giữ đặc tính đó khi mở rộng; dành tài nguyên tiếp nhận và đường thông báo ưu tiên cho SOS. Tách hàng đợi mà vẫn chung connection pool hoặc khóa đang nghẽn sẽ chưa bảo vệ được độ trễ khẩn.

LLM chỉ xử lý **sự cố đã được phát hiện**, không gọi trên mỗi GPS. Cần quota theo tenant, giới hạn đồng thời/token, timeout, circuit breaker và playbook dự phòng. Cảnh báo cơ bản đến nhân viên phải hoạt động khi LLM chậm hoặc ngừng.

Agent tự thực hiện ca thường theo policy. Nhánh khẩn có phê duyệt do backend kiểm tra, gắn với đúng nội dung, phiên bản, người nhận, hành động và hạn. Provider thật cần action outbox, khóa idempotency, trạng thái UNKNOWN và đối soát; replay không được tự gửi lại hành động khẩn. **Quy mô lớn không làm mất yêu cầu HITL.** Các action hiện tại vẫn mô phỏng.

Agent giảm số hồ sơ operator phải mở bằng tự liên hệ, xác nhận và đối chiếu tín hiệu. Hiệu quả này phải được đo qua tỷ lệ tự hoàn tất và tỷ lệ chuyển HITL, không chỉ số lượng nút bấm ít hơn.

Ví dụ giả định **0,1% số xe tạo một hồ sơ/giờ**: một triệu xe sinh 1.000 hồ sơ/giờ. Gọi e là tỷ lệ cần HITL sau tự động hóa, thời gian xử lý người 2 phút/hồ sơ và mức sử dụng mục tiêu 70%:

~~~text
Vị trí trực đồng thời ≈ ceil(1.000 × e × 2 / (60 × 0,7))
~~~

| Tỷ lệ cần HITL e, giả định | Hồ sơ người/giờ | Vị trí trực theo công thức |
|---|---:|---:|
| 10% | 100 | 5 |
| 50% | 500 | 24 |
| 100% | 1.000 | 48 |

Đây là mô hình minh họa, **chưa phải kết quả đo hoặc định biên**; chưa gồm ca nghỉ, kỹ năng, bão sự cố và thời gian xác minh khác nhau. Không tối ưu tỷ lệ tự đóng bằng cách coi thiếu dữ liệu là an toàn. Cần đo phản hồi sai/an toàn giả, nguy cơ bỏ sót, tỷ lệ chuyển khẩn, thời gian chờ operator, tuổi timer quá hạn và số lần liên hệ trên từng chuyến/người.

Policy hiện giới hạn hai liên hệ thường mỗi hồ sơ, nên ví dụ 1.000 hồ sơ/giờ có thể tạo tối đa 2.000 liên hệ thường/giờ nếu tất cả đi qua hai bước. Đây không bao gồm retry nhà cung cấp, hồ sơ khẩn hoặc nhiều hồ sơ của cùng một tài xế. Cần quota/cooldown chung, gộp diễn biến liên quan, ưu tiên SOS và kênh người nhận an toàn trước khi gắn provider thật.

Với một triệu hồ sơ cùng đến hạn, LIMIT 100 cần ít nhất 10.000 lượt bảo trì; nhịp danh nghĩa 2 giây đã tương ứng khoảng 5,6 giờ, chưa tính thời gian xử lý. Đây là **suy luận tình huống cực đoan từ code**, không phải số đo. Cần timer theo partition, lease/fencing, hàng đợi có ưu tiên và đo backlog; không tăng nhiều Planner khi còn khóa singleton.

LLM vẫn chạy trước bước liên hệ đầu tiên và mỗi lane chỉ xử lý một job cùng lúc. Phải đo incident-to-first-contact với model thật, giới hạn ngân sách và cân nhắc đường playbook mặc định chạy sớm khi model chậm. Bài tải GPS normal không kiểm chứng đường này.

Tỷ lệ trên tính theo hồ sơ/xe/giờ. Nếu tạo cảnh báo giả trên 0,1% của 333.333 bản tin/giây thì có khoảng 333 cảnh báo/giây. Vì vậy phải chống trùng, gộp trong cùng hồ sơ và đánh giá precision/recall theo chuyến/hồ sơ, không chỉ throughput.

### 7.7. Dashboard theo phạm vi và phép đo độ trễ đầu cuối

Không gửi danh sách một triệu vị trí tới mọi màn hình. Đề xuất phân trang server, tìm kiếm/bộ lọc tại DB, subscription theo tenant/vùng/chuyến, snapshot có giới hạn rồi delta có cursor. Khi reconnect hoặc thiếu delta phải lấy lại snapshot đúng quyền.

Bản đồ tổng quan nhận cụm theo ô địa lý, phóng to mới lấy xe trong vùng. Gộp vị trí trung gian trên đường hiển thị sau khi Detector đã xử lý dữ liệu cần thiết; không bỏ mẫu trước Detector nếu làm mất dấu hiệu rủi ro. Cụm sự cố tính nền theo vùng và cửa sổ thời gian, có xử lý biên giữa các ô.

Lưu lượng dashboard gần đúng:

~~~text
người xem × xe trong phạm vi × byte/cập nhật × cập nhật/giây
~~~

Cần đo riêng thiết bị → API xác nhận, nhận → Detector/sự cố, sự cố → màn hình, nhân viên tiếp nhận/phê duyệt và provider thực hiện. Không cộng p95 từng bước để gọi đó là p95 đầu cuối; dùng event_id/trace để đo trực tiếp. Dashboard cần thể hiện dữ liệu cũ và backlog, tránh làm vị trí cũ trông như đang realtime.

### 7.8. Số shard, dự phòng và chi phí

Gọi q là năng lực một shard **đã đo bền vững** với đúng schema, lưu trữ và ngưỡng độ trễ; u là tỷ lệ sử dụng mục tiêu để chừa dự phòng, ví dụ giả định 0,6; R_peak là tải đỉnh theo kịch bản:

~~~text
P ≥ ceil(R_peak / (q × u))

Nếu phải chịu được mất một shard:
(P − 1) × q × u ≥ R_peak
~~~

Ví dụ burst gấp ba tải trung bình sẽ yêu cầu R_peak = **1.000.000 sự kiện/giây**. Burst là giả định cần thử; benchmark hiện tại không xác nhận mức này. q phải là năng lực toàn đường xử lý tương ứng, không lấy tốc độ hàm rule trong RAM làm năng lực DB/API.

P là số shard logic theo giả định phân phối đều, **không phải số server**. Cần kiểm chứng partition nóng, giới hạn DB/broker, replay và tài nguyên còn lại khi mất cả vùng hạ tầng. Với multi-AZ phải đặt mục tiêu RPO (dữ liệu có thể mất) và RTO (thời gian phục hồi), sau đó thử lỗi đúng phạm vi cam kết; replication không thay thế backup.

Chưa có căn cứ đưa một cấu hình CPU/RAM hoặc chi phí tháng đủ cho một triệu xe. Dự toán cần cộng compute, DB/WAL/IOPS, broker, lưu trữ nóng/lạnh, replica/backup, băng thông, Mapbox, LLM theo số hồ sơ, giám sát và ca trực. Dùng số đo và báo giá của cấu hình được chọn; không lấy cấu hình Fly mẫu làm công suất production.

### 7.9. Lộ trình kiểm chứng 10.000 → 100.000 → 1.000.000 xe

| Mốc đồng thời, GPS mỗi 3 giây | Tải mục tiêu | Điều kiện trước khi công bố đạt |
|---|---:|---|
| 10.000 xe | 3.333,33 sự kiện/giây | Đo nút thắt; máy sinh tải đủ dư; soak 30–60 phút; tăng người xem, burst, GPS_LOST và SOS; sửa giới hạn được đo |
| 100.000 xe | 33.333,33 sự kiện/giây | Máy sinh tải tách riêng/phân tán; shard/ownership/retention hoạt động; thử tenant lệch tải, rebalance, replay và mất worker/broker/DB |
| 1.000.000 xe | 333.333,33 sự kiện/giây | Harness phân tán; chạy liên tục nhiều giờ rồi 24 giờ; dữ liệu lịch sử đủ lớn; thử burst, backlog recovery, mất vùng hạ tầng và tải realtime/ca trực |

Các mốc này là kế hoạch, chưa chạy. Có thể phải bổ sung partition ngay ở mốc 10.000 nếu số đo yêu cầu; không mặc định kiến trúc hiện tại đủ 10.000 chỉ vì harness nhận tham số đó.

Trước mỗi mốc, chốt tài nguyên, dữ liệu, tỷ lệ hoạt động, tần suất GPS, số người xem, sự cố/giờ, SLO và thời gian phục hồi. Với kịch bản normal tương ứng, giữ các ngưỡng hiện tại: lỗi HTTP ≤0,1%, GPS HTTP p95 ≤250 ms, nhận → xử lý p95 ≤2.000 ms, không dropped, mọi bản tin hợp lệ APPLIED, drain về 0 và không có sự cố ngoài dự kiến. Bổ sung ngưỡng p99, SOS đến màn hình, LLM timeout/fallback, quyền tenant và không lặp tác động. Bài có chủ đích gây lỗi phải công bố riêng tiêu chí chấp nhận/phục hồi trước khi chạy, không trộn vào kết quả normal.

Harness lớn cần namespace/UUID không trùng giữa máy, lịch open-loop, theo dõi CPU/mạng/scheduling lag của generator và đối soát từ bản tin được xác nhận tới kết quả xử lý. Dùng histogram hợp nhất để tính percentile, không lấy trung bình p95 của nhiều máy. Đồng bộ thời gian máy cho phép đo xuyên máy; dùng monotonic cho lịch gửi.

Bộ thử local hiện chỉ cho tối đa 10.000 xe và cổng riêng. **Không gỡ guard rồi gửi một triệu xe từ máy cá nhân.** Xây harness staging riêng, giới hạn endpoint và phạm vi được phép rõ ràng. Giữ PASS/FAIL, source/build/dependency identity, tài nguyên, số liệu và lỗi phục hồi. Chỉ ghi “đạt 1.000.000 xe” sau khi bài thử đúng quy mô đó đáp ứng các tiêu chí đã công bố.


### 7.10. Dự báo và tối ưu vận hành ở quy mô một triệu xe

Phần mới tạo ranh giới công cụ để mở rộng, chưa tạo năng lực phân tán. Solver giới hạn 100 xe × 100 yêu cầu, UI hiện dùng 4 xe. Hai slot mỗi API process và một lease mỗi operator chỉ là bảo vệ MVP, không phải bộ lập lịch toàn cụm. Lịch sử operations_runs chưa có retention tự động.

Một ma trận dày một triệu xe × một triệu yêu cầu có 10¹² ô. Nếu mỗi ô là số 64 bit, riêng một ma trận cần khoảng 8 TB; hai ma trận khoảng cách/thời gian khoảng 16 TB, chưa gồm solver/object/replica. Đây là phép tính giả định, không phải mức RAM đã đo. Không gửi ma trận đó cho một OR-Tools process.

Thiết kế tiếp theo: tổng hợp demand theo ô H3 và cửa sổ thời gian; chia vùng có cơ chế xử lý biên; lọc ứng viên theo độ gần/ghế/pin/độ mới trước khi gọi route table và solver. Mỗi tác vụ có giới hạn kích thước/thời gian, priority, lease/fencing và quota toàn cụm. Dự báo/solver chạy nền theo thay đổi có ý nghĩa hoặc lịch định kỳ, không theo từng GPS. OSRM cache phải có phiên bản bản đồ/profile/thời gian hết hạn; không dùng tuyến cũ cho quyết định mới mà không kiểm tra.

Trước thực thi, đọc lại trạng thái xe/đơn/pin, đặt quyền sở hữu giao dịch để hai vùng không phân cùng xe, rồi dùng outbox/idempotency cho provider. Pin đến trạm, tương thích đầu cắm và chỗ sạc cần nguồn live; dự báo TLC không cung cấp các tín hiệu đó. Giữ tài nguyên ưu tiên riêng cho SOS và HITL khẩn; đo độ trễ sự cố khi forecast/solver quá tải.

Nghiệm thu cần thêm tỷ lệ phục vụ, thời gian đón, vi phạm dự trữ, độ đúng thời gian chờ sạc, độ mới đầu vào, forecast error theo vùng/cao điểm và chi phí mỗi lượt; so với heuristic trên cùng dữ liệu, giới hạn thời gian và máy. Chưa có các số đo quy mô lớn này; kết quả TLC một tuần và GPS 1.000 xe không thay thế chúng.
