# LEGACY — Architecture Report (Initial Design)

> **Status**: LEGACY. Original: `reports/BaoCao_KienTruc_AIoT.docx` (converted
> 2026-08-08). This is an **idea-stage document** from the beginning of the
> project. It does **not** reflect the current architecture — read it only for
> the initial inspiration and the teacher-review reasoning. The current
> architecture is `../ARCHITECTURE.md`; the hub is `../README.md`.
>
> Key decisions that changed since this report: PIR GPIO hardware -> OpenCV
> MOG2 software motion detector; edge MediaPipe detection -> cloud-only AI;
> dlib ResNet -> InsightFace `buffalo_l`; ESP32 actuator -> MQTT control plane
> + audit logging; web UI -> not implemented (future work); Kafka -> MQTT
> multi-topic + SQLite logging service (kept).

---

BÁO CÁO KIẾN TRÚC HỆ THỐNG

Đồ án AIoT: Hệ thống nhận diện khuôn mặt (Pi-based)

Kiến trúc Edge–Cloud với MQTT (control plane) và RTSP (data plane)

## 1. Mục tiêu và bối cảnh đồ án

Đồ án môn học kỳ hè, thực hiện theo nhóm 2 người, thời hạn 4 tuần (giờ thì còn 3 tuần). Hệ thống xây dựng một pipeline nhận diện khuôn mặt trên nền tảng AIoT, gồm một thiết bị edge (Raspberry Pi) thu hình và một tầng cloud xử lý AI, kèm giao diện web hiển thị kết quả trực tiếp (live).

Kiến trúc ban đầu (bản nháp đầu tiên, sau buổi review với giảng viên):

- Edge: Raspberry Pi 3 + Pi Camera, chạy MediaPipe để phát hiện khuôn mặt tại chỗ, publish frame đã crop qua MQTT.
- Cloud: Flask API nhận frame, chạy embedding bằng dlib ResNet, so khớp bằng FAISS index, kết quả publish ngược qua MQTT broker (Mosquitto) tới ESP32/actuator.

Giảng viên phản hồi và gợi ý cân nhắc Kafka cho dữ liệu lớn/liên tục (video) và cân nhắc task offloading ở edge. Từ đó, nhóm đã thảo luận và tinh chỉnh lại kiến trúc thành phiên bản hiện tại — bao gồm các điểm đã cân nhắc, quyết định cuối cùng và lý do đằng sau mỗi quyết định.

*(Figure: original white board sketch — ảnh chụp bảng vẽ, không extract được từ bản docx.)*

## 2. Kiến trúc tổng quan (phiên bản hiện tại)

Nguyên tắc thiết kế cốt lõi: tách rõ data plane (video, nặng, liên tục) khỏi control plane (sự kiện, nhẹ, rời rạc), thay vì dồn tất cả qua một giao thức duy nhất.

*(Figure: sơ đồ kiến trúc tổng quan — không extract được.)*

Toàn bộ hệ thống chỉ cần 2 thiết bị vật lý: Raspberry Pi 4 (edge) và một laptop (cloud tier, gồm cả pipeline AI, MQTT broker, và web server). Web UI không phải một thiết bị riêng — chỉ là trình duyệt mở trên máy bất kỳ trong mạng LAN.

## 3. Các quyết định kiến trúc và lý do

### 3.1. Task split edge/cloud: vì sao không giữ face detect ở edge

Quyết định: Edge chỉ đảm nhiệm streaming video (qua RTSP) và MQTT client (control/status). Toàn bộ pipeline detect + recognition chạy ở cloud.

Lý do: nhóm nâng cấp thiết bị edge từ Raspberry Pi 3 lên Raspberry Pi 4 để có đủ sức mạnh xử lý cho việc encode RTSP liên tục ổn định. Với deadline 4 tuần và team 2 người, việc chạy đồng thời MediaPipe detect và RTSP encode trên cùng một board làm tăng đáng kể độ phức tạp khi debug và tối ưu hiệu năng — dồn phần AI nặng (detect + recognition) về cloud giúp đơn giản hoá phần firmware edge và tận dụng tài nguyên tính toán mạnh hơn sẵn có ở laptop.

Đánh đổi đã nhận biết: cách làm này bỏ qua lợi ích "lọc sớm" của việc detect ngay tại edge (chỉ gửi lên cloud khi có mặt người). Đánh đổi này được bù lại bằng PIR motion sensor (xem mục 3.3) — vẫn giữ được tinh thần lọc sơ bộ ở edge trước khi kích hoạt luồng nặng, chỉ là ở mức thô (có chuyển động) thay vì mức chi tiết (có khuôn mặt).

### 3.2. Vì sao tách RTSP riêng khỏi MQTT

Quyết định: video từ edge lên cloud đi qua kênh RTSP riêng biệt, không đi qua MQTT.

Lý do: MQTT được thiết kế cho message nhỏ, gọn — không phù hợp để mang payload lớn liên tục như frame video. Nếu ép video qua MQTT sẽ phải chunk từng frame, tăng overhead, dễ nghẽn broker và dễ mất gói khi mạng chập chờn. RTSP là giao thức chuyên cho streaming liên tục, có cơ chế buffering/timing phù hợp hơn nhiều. Việc tách kênh giúp mỗi giao thức làm đúng vai trò của nó: RTSP lo data plane, MQTT lo control plane.

### 3.3. Vai trò MQTT sau khi tách RTSP, và vai trò của PIR sensor

Sau khi RTSP đảm nhiệm việc truyền video, vai trò của MQTT được định nghĩa lại thay vì bị loại bỏ:

- Edge → Cloud: heartbeat/status của Pi4 (tình trạng camera, bitrate, fps), báo lỗi luồng RTSP, sự kiện "motion/detected" khi PIR sensor phát hiện chuyển động.
- Cloud → Edge: lệnh điều khiển (bật/tắt stream, đổi resolution, chụp snapshot riêng).
- Cloud → các consumer: publish kết quả nhận diện ("recognition/result") sau khi pipeline xử lý xong một khuôn mặt — tần suất thấp hơn nhiều so với video, phù hợp với đặc tính của MQTT.

PIR sensor (gắn GPIO trên Pi4) đóng vai trò kích hoạt: chỉ khi có chuyển động, Pi4 mới bật RTSP stream và publish sự kiện kích hoạt qua MQTT. Cách này khôi phục lại tinh thần "lọc sớm ở edge" mà giảng viên gợi ý ban đầu, dùng phần cứng rẻ và ít tốn compute (PIR) thay vì chạy face detection nặng ngay tại edge.

*(Triển khai thực tế: PIR thay bằng OpenCV MOG2 software motion detector — xem `../ARCHITECTURE.md` mục 4.)*

### 3.4. Vì sao không dùng Kafka, dùng MQTT đa kênh + logging service

Quyết định: không setup Kafka. Thay vào đó, cấu hình MQTT với nhiều topic/kênh theo loại sự kiện, và viết thêm một logging service subscribe các topic cần thiết để ghi lại audit trail.

Lý do và giới hạn đã cân nhắc: MQTT topic-based pub/sub tự nó đã cho khả năng fan-out (nhiều subscriber cùng nhận 1 topic), đáp ứng được nhu cầu routing message tới nhiều nơi. Tuy nhiên MQTT (kể cả với retained message) không có log durable — retained chỉ giữ message mới nhất của mỗi topic, không replay được lịch sử, nên tự thân MQTT không đủ cho audit trail.

Do đó nhóm bù lại bằng một logging service tự viết: subscribe các topic cần audit (recognition/result, error/*, motion/detected...), ghi xuống SQLite/Postgres. Việc này đạt được mục tiêu audit trail mà không cần triển khai và vận hành một Kafka cluster — hợp lý với quy mô đồ án (1 camera, demo ngắn hạn) và giới hạn thời gian 4 tuần.

Nguyên tắc đặt topic: tách theo loại sự kiện (recognition/result, system/status, motion/detected, error/*) thay vì gộp chung 1 topic rồi phân loại trong payload, vì mỗi loại cần QoS/độ ưu tiên khác nhau, và cho phép logging service subscribe theo wildcard nhóm (ví dụ +/error) khi cần mở rộng.

### 3.5. Vì sao bỏ actuator, dùng web UI hiển thị live

Quyết định: không làm actuator vật lý (ví dụ mở cửa qua ESP32). Thay vào đó, cloud host một web server nhận diện xong sẽ vẽ overlay (bounding box) lên frame và stream trực tiếp ra giao diện web.

Lý do lựa chọn cloud vẽ overlay (thay vì để web server/browser tự vẽ từ dữ liệu bbox riêng):

- Đơn giản hoá vai trò của web server — chỉ cần pass-through video đã annotate, không cần đồng bộ 2 luồng dữ liệu (video + tọa độ bbox) theo đúng frame.
- Tránh bài toán đồng bộ timestamp phức tạp giữa video và bbox coordinates ở phía client, vốn không cần thiết cho mục tiêu demo hiện tại (chỉ cần hiển thị, không cần tương tác kiểu click-để-xem-chi-tiết).
- Cloud đã cầm cả frame gốc và kết quả detect cùng lúc trong quá trình xử lý, nên việc vẽ overlay (OpenCV rectangle/text) gần như không tốn thêm chi phí đáng kể so với phần detect/recognition.

Kết quả nhận diện (tên, độ tin cậy, thời gian) vẫn được publish qua MQTT topic "recognition/result" để logging service ghi audit — chỉ là không còn đường đi tới actuator vật lý, mà tới web UI và audit log.

### 3.6. Vì sao gộp web server vào cùng cloud tier

Quyết định: web server chạy chung trên laptop cloud, cùng nơi với pipeline detect + recognition.

Lý do: tránh thêm một network hop (cloud pipeline → server riêng → browser), tránh encode video hai lần (một lần để gửi sang máy khác, một lần để serve ra browser). Với team 2 người, gộp chung giúp giảm số thành phần hạ tầng cần dựng và bảo trì — pipeline (Python, dlib/FAISS) và web server (Flask/FastAPI) có thể chạy chung một process, tận dụng luôn Flask API sẵn có cho phần embedding để mở thêm route WebSocket/MJPEG phục vụ UI live.

Đánh đổi đã nhận biết: máy cloud giờ gánh cả AI compute lẫn việc serve video cho các client xem cùng lúc. Ở quy mô đồ án (1 camera, vài người xem demo) mức tải này không đáng kể, nhưng cần đo đạc thực tế trước khi bảo vệ.

## 4. Sơ đồ publisher/consumer MQTT theo thiết bị vật lý

*(Figure: sơ đồ luồng message — không extract được.)*

Điểm đáng chú ý: cả 4 service phần mềm ở cloud tier (broker, AI pipeline, web server, logger) đều chạy trên cùng một laptop — không tách máy riêng, nên latency giữa chúng gần như không đáng kể. Chỉ có 2 thiết bị vật lý trong toàn hệ thống.

| Thành phần | Vai trò | Topic publish | Topic subscribe | Chạy trên |
|---|---|---|---|---|
| Camera + PIR | Publisher | motion/detected | — | Pi4 (edge) |
| MQTT client | Pub + sub | system/status, error/rtsp | control/* (lệnh từ cloud) | Pi4 (edge) |
| MQTT broker | Broker/infra | — (định tuyến) | — (định tuyến) | Laptop (cloud) |
| AI pipeline | Publisher | recognition/result, error/pipeline | control/* (lệnh từ web/thao tác vận hành) | Laptop (cloud) |
| Web server | Subscriber | — | recognition/result | Laptop (cloud) |
| Logger service | Subscriber | — | recognition/result, motion/detected, error/* | Laptop (cloud) |

Lưu ý: tên topic cụ thể (recognition/result, motion/detected, error/*...) là quy ước đặt tên do nhóm tự thiết kế theo nguyên tắc đã nêu ở mục 3.4 (tách theo loại sự kiện), có thể điều chỉnh khi triển khai thực tế miễn giữ đúng nguyên tắc phân loại.

## 5. Hạ tầng thiết bị và đo đạc tải

| Thiết bị | Vai trò | Thành phần chạy trên đó |
|---|---|---|
| Raspberry Pi 4 | Edge | PIR sensor (GPIO), Pi Camera, RTSP encoder, MQTT client |
| Laptop | Cloud | Face detect + recognition pipeline (dlib ResNet, FAISS), MQTT broker (Mosquitto), Web server (Flask/FastAPI + WebSocket/MJPEG), Logging service |
| Bất kỳ máy nào trong LAN | Web client | Chỉ là trình duyệt mở web UI — không phải hạ tầng cần chuẩn bị riêng |

Việc gộp broker + pipeline + web server trên cùng một laptop là quyết định có chủ đích, không phải bỏ sót. Mosquitto rất nhẹ (event-driven, tốn rất ít CPU/RAM khi idle), không đáng để tách ra máy riêng ở quy mô 1 camera. Trước buổi bảo vệ, nhóm nên chạy demo và ghi lại số liệu CPU/RAM thực tế (htop, hoặc nvidia-smi nếu có GPU) trong lúc pipeline + web server + broker chạy đồng thời.

## 6. Dự kiến câu hỏi của giảng viên và gợi ý trả lời

Phần này tổng hợp các điểm dễ bị hỏi vặn nhất trong buổi bảo vệ, dựa trên các đánh đổi đã đưa ra ở mục 3.

**Câu hỏi: Vì sao không giữ face detection ở edge như kiến trúc gốc, trong khi đó là hướng offloading thầy gợi ý?**

Gợi ý trả lời: Nhóm đã cân nhắc và giữ tinh thần lọc sớm ở edge, nhưng thay bằng PIR motion sensor thay vì face detection đầy đủ — vừa giảm tải tính toán cho Pi4, vừa vẫn tránh gửi luồng video liên tục lên cloud khi không có ai. Việc chạy MediaPipe detect song song với RTSP encode trên cùng một board làm tăng độ phức tạp không tương xứng với thời gian 4 tuần của nhóm 2 người.

**Câu hỏi: Dồn cả broker, pipeline AI, và web server lên một máy laptop — nếu tải tăng thì sao?**

Gợi ý trả lời: Ở quy mô đồ án (1 camera, vài client xem demo), việc gộp không gây nghẽn — nhóm có đo CPU/RAM thực tế trong lúc chạy đồng thời để chứng minh. Kiến trúc đã tách rõ theo vai trò (RTSP cho data plane, MQTT cho control plane, HTTP/WebSocket cho web) nên khi cần scale, từng phần có thể tách sang container hoặc máy riêng mà không cần redesign lại luồng dữ liệu — đây là vấn đề triển khai (deployment), không phải giới hạn của kiến trúc.

**Câu hỏi: Vì sao không dùng Kafka như đã gợi ý, mà quay lại dùng MQTT?**

Gợi ý trả lời: MQTT vẫn được giữ và mở rộng thành đa kênh (nhiều topic theo loại sự kiện) để tận dụng khả năng fan-out sẵn có, kết hợp thêm một logging service ghi audit trail xuống DB. Cách này đạt được mục tiêu audit trail và phân phối sự kiện tới nhiều nơi mà không phải vận hành một Kafka cluster — phù hợp với quy mô 1 camera và thời gian thực hiện giới hạn. Nhóm hiểu rõ giới hạn của hướng đi này: nếu hệ thống mở rộng nhiều camera/nhiều consumer group cần replay độc lập, Kafka sẽ là bước nâng cấp hợp lý tiếp theo.

**Câu hỏi: Vì sao không có actuator vật lý (mở cửa, cảnh báo) như đề xuất access-control ban đầu?**

Gợi ý trả lời: Nhóm chuyển hướng sang một web UI hiển thị nhận diện trực tiếp (live), phù hợp hơn với mục tiêu trình diễn kết quả AI của đồ án so với việc tích hợp thêm phần cứng điều khiển. Luồng dữ liệu vẫn giữ nguyên tính real-time — kết quả nhận diện publish qua MQTT ngay khi có, chỉ khác điểm đến cuối cùng là UI thay vì actuator.

**Câu hỏi: Vì sao cloud tự vẽ bounding box lên video rồi mới gửi ra web, thay vì gửi tọa độ để browser tự vẽ?**

Gợi ý trả lời: Cách này tránh phải đồng bộ hai luồng dữ liệu riêng biệt (video thô và tọa độ bounding box) theo đúng từng frame ở phía client — một bài toán không cần thiết cho mục tiêu hiện tại (chỉ hiển thị, không cần tương tác). Cloud đã có sẵn cả frame gốc và kết quả detect trong lúc xử lý, nên vẽ overlay tại đó gần như không tốn thêm chi phí và đảm bảo khớp tuyệt đối giữa video và box.

**Câu hỏi: Vì sao web server và logger cùng subscribe topic recognition/result thay vì tách riêng?**

Gợi ý trả lời: Đây là ưu điểm sẵn có của mô hình pub/sub: nhiều subscriber có thể cùng nhận một topic mà không cần AI pipeline biết hay quan tâm ai đang lắng nghe. Web server dùng dữ liệu đó để cập nhật UI, logger dùng để ghi audit — hai mục đích khác nhau nhưng dùng chung một nguồn phát, không cần AI pipeline publish hai lần hay biết trước danh sách consumer.

## 7. Tổng kết

Kiến trúc hiện tại là kết quả của một chuỗi quyết định có chủ đích, mỗi quyết định đều đi kèm đánh đổi được nhận biết rõ và có hướng giải quyết hoặc lý do chấp nhận đánh đổi đó trong phạm vi đồ án. Điểm mấu chốt cần truyền đạt khi bảo vệ: đây không phải là các lựa chọn tối giản vì thiếu thời gian, mà là các quyết định cân bằng giữa đúng nguyên lý kiến trúc (tách data plane/control plane, dùng đúng giao thức cho đúng việc) và ràng buộc thực tế (team 2 người, 4 tuần, quy mô demo 1 camera).
