# 10. Dữ liệu thực và benchmark

Ngày cập nhật: **09/11/2026**. Tài liệu này mô tả bộ đánh giá ngoại tuyến trong [research_benchmarks](../research_benchmarks/), tách biệt với [kiểm thử tải API](06-kiem-thu-tai-1000-xe.md). Kết quả thực hiện tại dùng **NYC TLC Green Taxi tháng 01/2025**. Những nguồn khác được phân biệt rõ bên dưới; không coi tài liệu tham chiếu là bằng chứng đã tải hoặc đã đánh giá.

## 1. Phạm vi đã hoàn thành

- Tải Parquet từ địa chỉ chính thức, lưu nguồn tải, thời gian, kích thước và SHA-256.
- Đọc từng batch bằng PyArrow, tổng hợp lượt đón khách theo **taxi zone × giờ**.
- Huấn luyện baseline theo lịch tuần; đánh giá trên tuần cuối chưa dùng để huấn luyện, so sánh với cùng giờ hôm trước và tuần trước.
- Tính MAE, RMSE, WAPE, sai lệch có dấu, số mẫu và số ô không có lượt đón; tách giờ cao điểm theo định nghĩa chỉ dùng tập huấn luyện.
- Đối soát tổng tiền với các thành phần bằng `Decimal`, giữ nguyên đơn vị **USD**.
- Lưu [báo cáo JSON thực](benchmarks/tlc-green-202501-20261109.json), kiểm tra dấu vân tay mã nguồn và dữ liệu trước/sau chạy.

TLC cung cấp thời gian, vùng đón/trả và thông tin chuyến/cước. Các bản ghi này không phải chuỗi GPS của một xe. TLC cũng lưu ý dữ liệu do bên cung cấp công nghệ gửi và không bảo đảm độ chính xác. Vì vậy benchmark không tự tạo tọa độ từ mã vùng và không tạo nhãn SOS/gian lận. [Nguồn TLC](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page), [từ điển Green Taxi](https://www.nyc.gov/assets/tlc/downloads/pdf/data_dictionary_trip_records_green.pdf).

## 2. Chạy bằng Anaconda

Mở **Anaconda Prompt**, vào thư mục dự án và kích hoạt môi trường:

```powershell
cd D:\SafeJourney
conda activate safejourney
```

Nếu chưa có môi trường, tạo từ thư mục gốc:

```powershell
conda env create -f environment.yml
conda activate safejourney
```

Nếu đã có môi trường từ trước khi bổ sung benchmark, cập nhật theo cấu hình hiện tại:

```powershell
conda env update -n safejourney -f environment.yml
python -m pip check
```

[environment.yml](../environment.yml) nạp [requirements riêng của benchmark](../research_benchmarks/requirements.txt), hiện ghim `pyarrow==26.0.1`. HTTP client và pytest có trong bộ phụ thuộc phát triển của dự án. Không cài vào môi trường `base`. Benchmark không cần Docker, API, Redis, khóa LLM hay Mapbox.

### 2.1. Tải dữ liệu

```powershell
python -m research_benchmarks.tlc download --taxi green --month 2025-01
```

Hai file được tạo trong `research_benchmarks/data/`:

- `green_tripdata_2025-01.parquet`: dữ liệu gốc.
- `green_tripdata_2025-01.source.json`: nguồn tải và mã kiểm tra nội dung.

Trên máy đang phát triển, hai file này **đã có**. Bỏ qua bước tải và chạy đánh giá. Lệnh tải từ chối ghi đè; khi cần tải độc lập để kiểm tra nguồn, dùng thư mục mới:

```powershell
python -m research_benchmarks.tlc download --taxi green --month 2025-01 --directory research_benchmarks/data/recheck
```

Downloader chỉ tạo URL `green/yellow_tripdata_YYYY-MM.parquet` trên host TLC đã định sẵn, không nhận URL tùy ý, không theo redirect, không dùng thông tin xác thực hoặc proxy từ môi trường. Giới hạn tải **128 MiB**, timeout kết nối 5 giây, timeout đọc 20 giây; kiểm tra thời gian tổng 180 giây giữa các khối dữ liệu. Một lần đọc đang chờ vẫn chịu timeout đọc riêng. Kiểm tra dấu hiệu đầu/cuối Parquet trước khi đổi tên file. Nếu tải lỗi, file `.partial` được giữ lại để kiểm tra; dùng thư mục mới cho lần thử tiếp theo.

Dữ liệu thô và manifest ở `data/` được Git bỏ qua; JSON kết quả vẫn được lưu làm bằng chứng. SHA-256 kiểm tra tính nhất quán của file cục bộ, không phải chữ ký của nhà xuất bản. Nếu dùng file tự cung cấp không có manifest, báo cáo ghi rõ nguồn chưa được xác minh bằng manifest của downloader.

### 2.2. Chạy đánh giá

Chọn tên kết quả mới mỗi lần chạy để giữ bằng chứng cũ:

```powershell
python -m research_benchmarks.tlc evaluate --taxi green --month 2025-01 --input research_benchmarks/data/green_tripdata_2025-01.parquet --output docs/benchmarks/tlc-green-202501-local-01.json
```

Lệnh không ghi dữ liệu lên hệ thống SafeJourney và không gọi LLM. File kết quả có sẵn sẽ bị từ chối ghi đè. Nếu đổi mã tính toán, hãy chạy lại và dùng kết quả mới; không sửa số đo trong JSON bằng tay.

### 2.3. Chạy test riêng

```powershell
python -m pytest research_benchmarks/tests -q
```

Lần xác minh 09/11/2026: **17 passed in 2.02s** trên môi trường `safejourney`. Test dùng HTTP giả lập và Parquet nhỏ tạo cục bộ, kiểm tra rò rỉ dữ liệu tương lai, ô không có lượt đón, tiền thập phân, giới hạn downloader, dữ liệu không hợp lệ và manifest sai. Đây là test bộ benchmark; không thay thế test DB/API hoặc kiểm thử tải của hệ thống.

## 3. Quy trình đánh giá và tránh rò rỉ dữ liệu

### 3.1. Đầu vào và bộ lọc

Mã thực thi: [tlc.py](../research_benchmarks/tlc.py). Bản hiện tại nhận Green/Yellow Taxi theo tháng, giới hạn 10 triệu hàng và 128 MiB; tháng lớn hơn phải có pipeline khác, không âm thầm chỉ đọc một phần. Mỗi batch mặc định 32.768 hàng; chỉ đọc cột cần dùng. Bộ đếm tổng hợp lưu theo vùng/giờ, không giữ toàn bộ bản ghi chuyến trong bộ nhớ.

Một lượt đón được chấp nhận khi:

1. Thời gian đón là `datetime` địa phương không kèm múi giờ và thuộc đúng tháng yêu cầu.
2. `PULocationID` là số nguyên trong khoảng **1–263**. Các mã ngoài phạm vi này không được coi là vùng địa lý đã biết.

Không lọc theo cước, số khách, khoảng cách hoặc thời lượng, vì mục tiêu ở đây là đếm bản ghi đón khách. Bản ghi có tiền thiếu vẫn tham gia đếm nhu cầu nhưng có thể không tham gia đối soát tiền. Không tự xóa bản ghi trùng hình thức vì đầu vào không cung cấp khóa sự kiện duy nhất. Số bị loại được lưu trong `coverage.excluded_rows`, theo lý do đầu tiên gặp; tổng hàng nhận và loại phải bằng tổng hàng đọc.

Với dữ liệu hiện tại, một ô giờ không có bản ghi được gán số lượt đón bằng 0. Đây là giả định về độ đầy đủ của file đã công bố; không có nghĩa dữ liệu streaming bị mất hoặc chưa đến cũng phải được gán 0. Mã từ chối tháng có đổi giờ mùa hè ở New York để tránh tự quyết định giờ bị lặp/bị thiếu trong timestamp địa phương.

### 3.2. Chia tập theo thời gian

| Tập | Khoảng thời gian New York | Số giờ | Lượt đón hợp lệ |
| --- | --- | ---: | ---: |
| Huấn luyện | 01/01/2025 00:00 đến trước 25/01/2025 00:00 | 576 | 36.693 |
| Kiểm thử | 25/01/2025 00:00 đến trước 01/02/2025 00:00 | 168 | 11.467 |

Luôn giữ **7 ngày cuối** để kiểm thử và ít nhất 21 ngày trước đó để huấn luyện. Tháng 01 có 24 ngày huấn luyện. Không chia ngẫu nhiên các hàng và không chọn lại tuần kiểm thử sau khi xem kết quả.

Tập vùng gồm sẵn 263 vùng, độc lập với nhu cầu trong tuần kiểm thử. Lưới đầy đủ có **151.488 ô vùng-giờ huấn luyện** và **44.184 ô kiểm thử**, kể cả ô bằng 0. Có 202 vùng xuất hiện lượt đón trong tập huấn luyện và 172 vùng trong tập kiểm thử.

### 3.3. Mô hình và cao điểm

Mã thuần tính toán: [demand.py](../research_benchmarks/demand.py).

| Mô hình | Dự báo tại vùng z, giờ t |
| --- | --- |
| `seasonal_mean` | Trung bình số lượt đón cùng vùng, thứ trong tuần và giờ, chỉ dùng tập huấn luyện; mô hình đóng băng trước 25/01 |
| `lag_24h` | Số lượt đón quan sát tại z, t−24 giờ |
| `lag_168h` | Số lượt đón quan sát tại z, t−168 giờ |
| `zero` | Luôn dự báo 0, để cho thấy ảnh hưởng của dữ liệu thưa |

Đây là đánh giá dự báo **mỗi giờ tiếp theo**, không phải dự báo toàn bộ 7 ngày ở một thời điểm. `lag_24h` có thể dùng số liệu ngày kiểm thử trước đó đã xảy ra; không mô hình nào dùng số đếm của chính giờ đích hoặc tương lai. Nguồn TLC là file hoàn chỉnh sau kỳ báo cáo, nên thí nghiệm chưa mô phỏng độ trễ đến của bản ghi trong vận hành.

Cao điểm được chọn bằng trung bình tổng lượt đón toàn thành phố trong **tập huấn luyện**: lấy 34 tổ hợp thứ/giờ cao nhất trong 168 tổ hợp, hòa thì xếp theo thứ rồi giờ. Không dùng tuần kiểm thử để quyết định giờ nào là cao điểm. Các tổ hợp cụ thể nằm trong `protocol.peak_weekday_hours`.

### 3.4. Chỉ số

- **MAE**: trung bình độ lệch tuyệt đối, đơn vị lượt đón/ô. Ô có số đếm 0 vẫn được tính.
- **RMSE**: căn trung bình bình phương sai số, nhạy hơn với sai lệch lớn.
- **WAPE**: `100 × tổng |dự báo − thực tế| / tổng thực tế`; nếu mẫu không có lượt đón thì trả `null`, không tự gán 0%.
- **Bias**: trung bình `dự báo − thực tế`; số âm là dự báo thiếu.

Báo cáo cả mức vùng-giờ và tổng toàn thành phố theo giờ. Sai số nhỏ ở mức thành phố có thể che việc dự báo lệch giữa các vùng; không dùng riêng chỉ số thành phố để kết luận phân bổ xe tốt.

## 4. Kết quả dữ liệu thực ngày 09/11/2026

Nguồn dữ liệu: [Green Taxi tháng 01/2025 trên máy chủ TLC](https://d37ci6vzurychx.cloudfront.net/trip-data/green_tripdata_2025-01.parquet). Bằng chứng đầy đủ: [tlc-green-202501-20261109.json](benchmarks/tlc-green-202501-20261109.json).

| Thông tin | Giá trị thực đo |
| --- | --- |
| Kích thước file | 1.178.451 byte |
| SHA-256 dữ liệu | `84f3a121667157efcbf012c3566a6065df6f8e0312c678cb2f29cd72cc9c0f10` |
| Thời gian tải UTC | 2026-11-09 10:20:53 |
| Thời gian hoàn thành đánh giá UTC | 2026-11-09 15:17:38 |
| Python / PyArrow | 3.12.15 / 26.0.1 |
| SHA-256 mã benchmark, 3 file Python | `5c547085826f02f55de4f9d9b809c0de9e8741dac899361e596cbea98de6d22a` |
| Hàng đọc / lượt đón hợp lệ | 48.326 / 48.160 |
| Loại vì thời gian ngoài tháng | 43 |
| Loại vì vùng không hợp lệ hoặc thiếu | 123 |
| Ô kiểm thử có số đếm 0 | 41.076 / 44.184 |

Kết quả toàn bộ 44.184 ô vùng-giờ kiểm thử:

| Mô hình | MAE | RMSE | WAPE | Bias |
| --- | ---: | ---: | ---: | ---: |
| Seasonal mean | **0,143412** | **0,636877** | **55,258568%** | −0,020713 |
| Cùng giờ hôm trước | 0,175878 | 1,004032 | 67,768379% | −0,000158 |
| Cùng giờ tuần trước | 0,162932 | 0,888891 | 62,780152% | −0,020980 |
| Luôn bằng 0 | 0,259528 | 1,891073 | 100,000000% | −0,259528 |

Chi tiết của seasonal mean:

| Phạm vi | Số ô | Lượt đón | Ô có số đếm 0 | MAE | RMSE | WAPE |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Cao điểm, vùng-giờ | 8.942 | 4.404 | 8.061 | 0,214410 | 0,872262 | 43,534287% |
| Ngoài cao điểm, vùng-giờ | 35.242 | 7.063 | 33.015 | 0,125397 | 0,561676 | 62,569022% |
| Toàn thành phố theo giờ | 168 | 11.467 | 0 | 8,986111 | 12,125972 | 13,165315% |

Trong **tuần kiểm thử này**, seasonal mean tốt hơn hai baseline độ trễ theo ba chỉ số sai số chính. WAPE vùng-giờ vẫn khoảng 55,26%; MAE thấp một phần do nhiều ô bằng 0. Chưa có cơ sở khẳng định mô hình đủ tốt để điều xe thật hoặc luôn thắng ở tháng khác. Không đặt ngưỡng sau khi đo để biến kết quả này thành một bài kiểm tra “PASS”.

## 5. Đối soát tiền là kiểm tra chất lượng dữ liệu

Phép tính: `total_amount − tổng thành phần`, với mỗi giá trị chuyển qua `Decimal` và làm tròn tới cent theo `HALF_EVEN`. Các thành phần được dùng là `fare_amount`, `extra`, `mta_tax`, `tip_amount`, `tolls_amount`, `improvement_surcharge`, `congestion_surcharge`, `cbd_congestion_fee`. Nếu file có `airport_fee`, mã đưa cột đó vào phép cộng. Cột CBD được yêu cầu từ dữ liệu năm 2025. Nếu thiếu cột cần thiết, báo cáo ghi `NOT_AVAILABLE` thay vì coi cột thiếu bằng 0. [Thay đổi schema do TLC công bố](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page).

Trên 48.160 lượt đón hợp lệ:

| Kiểm tra | Số đo |
| --- | ---: |
| Đủ giá trị để đối soát | 46.324 hàng |
| Thiếu, không hữu hạn hoặc trị tuyệt đối tiền trên 1.000.000 USD | 1.836 hàng |
| Sai lệch tuyệt đối không quá 0,01 USD | 40.250 hàng |
| Sai lệch tuyệt đối lớn hơn 0,01 USD | 6.074 hàng |
| Có ít nhất một thành phần hoặc tổng âm, trong nhóm đối soát được | 152 hàng |
| Tổng trị tuyệt đối sai lệch | 10.764,10 USD |
| Sai lệch tuyệt đối lớn nhất | 4,50 USD |
| Sai lệch tuyệt đối trung bình, làm tròn cent | 0,23 USD |

Các nhóm “tiền âm” và “lệch tổng” có thể chồng nhau. Số hàng không đối soát được được ghi thành một nhóm tổng hợp; kết quả hiện tại không phân tách 1.836 hàng theo từng nguyên nhân hoặc cột.

Đây là kiểm tra tính nhất quán của các cột tiền **USD**, không chạy biểu giá demo **VND**, không đổi tỷ giá, không khẳng định hoàn tiền sai hoặc gian lận. Các sai lệch cần được điều tra theo định nghĩa cột/nhà cung cấp; không biến chúng thành nhãn đúng để chấm precision/recall cho agent. Giá trị thiếu cũng không được tự thay bằng 0 để làm đẹp tỷ lệ đối soát.

## 6. Dùng đúng từng nguồn tham chiếu

| Nguồn/công cụ | Trạng thái trong đánh giá này | Vai trò phù hợp và điều kiện |
| --- | --- | --- |
| [NYC TLC](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page) | **Đã tải và đo** Green Taxi 01/2025 | Đếm lượt đón theo vùng/giờ, kiểm tra cột cước; tải công khai không cần tài khoản. Lưu nguồn, kiểm tra điều khoản nhà xuất bản trước khi phân phối lại dữ liệu thô. |
| [DiDi GAIA / trang dataset hiện tại](https://outreach.didichuxing.com/opendata/datasets) | **Chưa tải/chưa đo** | Trang hiện tại mô tả **Ride-Hailing Synthetic Dataset** và nói dữ liệu hiển thị là tổng hợp. Không được gắn nhãn “GPS vận hành thực” cho dataset đó. Nếu sử dụng bộ quỹ đạo GAIA lịch sử, phải xác minh đúng bản dữ liệu, quyền truy cập/điều khoản và schema trước khi nhập. |
| [ACN-Data](https://ev.caltech.edu/dataset.html) | **Chưa tải/chưa đo** | Dữ liệu phiên sạc có thời gian kết nối/ngắt và kWh. API yêu cầu đăng ký để lấy token; token phải nằm ngoài Git. Có thể đánh giá năng lượng/thời lượng phiên sạc; không mặc định có nhãn thời gian chờ trước khi cắm sạc. Kiểm tra điều kiện sử dụng của bản dữ liệu được chọn. |
| [NASA Battery](https://data.nasa.gov/dataset/li-ion-battery-aging-datasets) | **Chưa tải/chưa đo** | Dữ liệu thí nghiệm lão hóa cell pin, phù hợp nghiên cứu suy giảm dung lượng. Không tương đương SOC của cả xe hoặc hàng chờ trạm sạc. Trang catalog hiện ghi chưa nêu giấy phép và không có tài nguyên tải trực tiếp; cần xác minh nguồn gốc/điều khoản của bản lấy từ kho liên quan. |
| [Uber H3](https://h3geo.org/docs/) | Không dùng cho file TLC này | Thư viện chỉ mục không gian, không phải bộ dữ liệu hành trình. Chỉ tạo ô H3 từ tọa độ thực hợp lệ; không biến tâm taxi zone thành vị trí khách. H3 công bố giấy phép Apache 2.0 cho thư viện. |
| [OSRM](https://project-osrm.org/docs/v5.24.0/api/) | Chưa đo độ chính xác tuyến trên TLC | Công cụ định tuyến/matching trên mạng đường. Cần tọa độ, bản đồ/profile có phiên bản và nguồn quỹ đạo đối chiếu; điều kiện sử dụng dữ liệu bản đồ/tầng dịch vụ được quản lý riêng. |
| [GTFS Schedule](https://gtfs.org/documentation/schedule/reference/) | Chưa nhập feed | Định dạng lịch, trạm và tuyến giao thông công cộng. Không thay OSRM để tính đường ô tô. Quyền sử dụng tùy feed của đơn vị vận tải, không suy ra từ việc feed dùng GTFS. |

Không có dữ liệu thời tiết trong lần chạy này. Không thể dùng kết quả một tháng TLC để chứng minh mô hình đã hiểu tác động thời tiết, đã học pin hay đã nhận diện SOS.

## 7. Kết nối với hệ thống agent và hướng mở rộng

Hàm `fit_seasonal_mean(rows, cutoff)` nhận bộ ba `(datetime đầu giờ, mã vùng dạng chuỗi, số đếm nguyên không âm)` đã tổng hợp, đã bổ sung ô 0 theo chính sách dữ liệu. Hàm trả về các trung bình tổng hợp cùng mốc huấn luyện; `predict_seasonal(model, timestamp, zone)` trả số lượt dự kiến. Đây là baseline tham chiếu cho công cụ dự báo xác định; LLM không tự tính các số trong báo cáo.

Module nghiên cứu không tự xuất kết quả sang DB vận hành và không được dùng như nguồn telemetry realtime. Khi nâng cấp, adapter dữ liệu cần công bố rõ đơn vị không gian, múi giờ, độ trễ dữ liệu, phiên bản mô hình và phạm vi tin cậy. Taxi zone của New York và H3 ở Việt Nam là hai hệ phân vùng khác nhau, không dùng lẫn khóa.

Các bước đánh giá tiếp theo:

1. Thêm nhiều tháng/thành phố; chốt tập kiểm thử trước, đánh giá cuốn chiếu theo thời gian. Giữ các kỳ thất bại để nhận biết thay đổi phân bố, không chỉ chọn tháng mô hình thắng.
2. Với dữ liệu GPS được phép sử dụng, chuẩn hóa mã xe giả danh, timestamp UTC có timezone, tọa độ và độ chính xác; giữ nguồn và lý do loại hàng. Chia tập theo xe/hành trình/thời gian phù hợp trước khi tinh chỉnh ngưỡng. Chưa có importer CSV quỹ đạo trong module hiện tại.
3. Đánh giá nhận diện sự cố bằng nhãn được kiểm tra độc lập: precision/recall theo loại sự cố, số báo giả/1.000 giờ xe, thời gian phát hiện, tỷ lệ tự xử lý và tỷ lệ leo thang. Dữ liệu giả lập chỉ chứng minh kịch bản chạy đúng, không cung cấp độ chính xác ngoài thực tế.
4. Với ACN/NASA, tách bài toán phiên sạc và suy giảm pin; không lấy chu kỳ của cùng một cell rải ngẫu nhiên vào cả train/test. Ràng buộc an toàn pin vẫn phải được công cụ xác định kiểm tra trước khi agent đề xuất hành động.
5. Đánh giá chất lượng dự báo và sức chịu tải riêng. **48.326 bản ghi chuyến không phải 48.326 xe đồng thời**, và benchmark ngoại tuyến này không chứng minh vận hành 1.000.000 xe. Năng lực đó cần kiểm thử pipeline, phân vùng, DB/stream, độ trễ, chi phí và sự cố hạ tầng theo kế hoạch tải của dự án.

Mọi benchmark mở rộng phải ghi nguồn, thời điểm tải, phiên bản, checksum, bộ lọc, mẫu bị loại, chính sách thiếu dữ liệu và độ bao phủ. Giữ ràng buộc sản phẩm: phát hiện không chờ LLM, hành động khẩn cần HITL, liên hệ trong demo chỉ được giả lập, phản hồi của người nhận phải được xác thực.
