# macOS CoreML Recognition Support Plan

> **Status**: Approved plan (not yet implemented). Extends the InsightFace/FAISS
> recognition pipeline to macOS Apple Silicon using `CoreMLExecutionProvider`
> (GPU/Neural Engine/CPU via `MLComputeUnits=ALL`), preserving Windows AMD64
> CUDA behavior. Part of the [documentation hub](../README.md).

> Source context: macOS Apple Silicon dùng `CoreMLExecutionProvider` với
> `MLComputeUnits=ALL`; `CPUExecutionProvider` vẫn là fallback. `--require-gpu`
> được giữ để tương thích CLI và chỉ thành công khi CoreML được bind vào cả
> SCRFD lẫn ArcFace; điều này không khẳng định mọi operator chạy riêng trên GPU
> vì CoreML có thể chọn GPU, Neural Engine hoặc CPU.

## Batch 1 — Runtime contract và dependency macOS

- [x] #1 Tạo cấu hình recognition runtime thuần Python cho Windows AMD64 và macOS Apple Silicon
  DoD: `get_recognition_runtime(system=None, machine=None)` trả về Windows với thứ tự `CUDAExecutionProvider, CPUExecutionProvider`; trả về Darwin ARM64 với thứ tự `CoreMLExecutionProvider, CPUExecutionProvider` và options `MLComputeUnits=ALL`, `RequireStaticInputShapes=0`; mọi nền tảng/kiến trúc khác phát sinh `RuntimeError` rõ ràng mà không import OpenCV, ONNX Runtime hoặc InsightFace.
  Tag: [judgment]
  File: aiot/recognition/runtime.py (new)

- [x] #2 Kiểm thử đầy đủ ma trận nền tảng của recognition runtime
  DoD: Unit tests cover `Windows/AMD64`, `Windows/x86_64`, `Darwin/arm64`, `Darwin/aarch64`, đồng thời từ chối `Windows/ARM64`, `Darwin/x86_64`, `Linux/x86_64` và `Linux/aarch64`; test xác nhận chính xác provider order và CoreML provider options.
  Tag: [mechanical]
  File: tests/test_face_engine.py:1-77

- [x] #3 Thêm bộ dependency riêng cho recognition trên macOS Apple Silicon
  DoD: File requirements mới kế thừa `requirements.txt`, pin `onnxruntime==1.28.0` và `faiss-cpu==1.14.3`, đồng thời chứa các recognition dependencies tương đương bản Windows nhưng không cài `onnxruntime-gpu`, `onnxruntime-silicon`, `onnxruntime-coreml` hoặc `insightface` có dependencies.
  Tag: [judgment]
  File: requirements-recognition-macos.txt (new)

## Batch 2 — Tích hợp CoreML vào FaceEngine

- [x] #4 Cho `FaceEngine` nhận runtime config tùy chọn và xây dựng danh sách ONNX providers theo nền tảng
  DoD: `FaceEngine()` tự lấy runtime config mặc định; tests có thể inject config; Windows gửi CUDA trước CPU; macOS gửi tuple CoreML cùng options trước CPU; chỉ provider có trong `ort.get_available_providers()` được chuyển cho `FaceAnalysis`; `requested_providers` tiếp tục là danh sách tên provider để giữ tương thích.
  Tag: [judgment]
  File: aiot/recognition/face_engine.py:42-92

- [x] #5 Giữ CoreML sau bước `InsightFace.prepare()` bằng `ctx_id` không âm
  DoD: `FaceAnalysis.prepare()` nhận `ctx_id=0` khi CUDA hoặc CoreML accelerator có sẵn và nhận `ctx_id=-1` chỉ khi chạy CPU; test chứng minh CoreML không đi qua nhánh `ctx_id<0` vốn ép SCRFD và ArcFace về `CPUExecutionProvider`.
  Tag: [judgment]
  File: aiot/recognition/face_engine.py:73-78

- [x] #6 Tổng quát hóa provider status từ CUDA sang accelerator của runtime
  DoD: `engine.accelerator_provider` là CUDA trên Windows và CoreML trên macOS; trạng thái active chỉ true khi provider đó xuất hiện trong session providers của cả detector và recognition model; warning nêu đúng provider bị fallback và không còn đưa hướng dẫn CUDA DLL cho lỗi CoreML; giữ nguyên các field `gpu_requested` và `gpu_active` để tránh thay đổi API ngoài phạm vi.
  Tag: [judgment]
  File: aiot/recognition/face_engine.py:33-39,85-99,194-221

- [x] #7 Kiểm thử đường khởi tạo CoreML thành công cho cả hai model
  DoD: Mocked constructor test xác nhận `FaceAnalysis` nhận CoreML options cùng CPU fallback, `prepare(ctx_id=0)` được gọi, detector và recognition session đều báo `CoreMLExecutionProvider`, `gpu_active=True`, và không tạo provider warning.
  Tag: [mechanical]
  File: tests/test_face_engine.py:8-77

- [x] #8 Kiểm thử CoreML fallback và hồi quy CUDA
  DoD: Tests xác nhận CoreML thiếu khỏi ORT availability sẽ chọn CPU và không báo accelerator active; CoreML chỉ có trên một trong hai model khiến `gpu_active=False`; Windows vẫn ưu tiên CUDA, dùng `ctx_id=0`, và chỉ active khi cả SCRFD lẫn ArcFace dùng CUDA.
  Tag: [mechanical]
  File: tests/test_face_engine.py:8-77

## Batch 3 — CLI và fail-fast behavior

- [x] #9 Thay Windows-only gate bằng recognition runtime gate
  DoD: `recognize_stream.main()` cho phép đúng Windows AMD64 và macOS Apple Silicon, truyền cùng runtime config vào `FaceEngine`, từ chối Linux, Intel Mac và Windows ARM64 trước khi import recognition dependencies nặng, in lỗi ra stderr và trả exit code `1`.
  Tag: [judgment]
  File: recognize_stream.py:1-7,857-879

- [x] #10 Tổng quát hóa help text, startup diagnostics và `--require-gpu`
  DoD: Help mô tả `--require-gpu` là yêu cầu platform accelerator; startup in provider của SCRFD và ArcFace cùng tên accelerator; Windows giữ CUDA behavior hiện tại; macOS chỉ tiếp tục với `--require-gpu` khi cả hai model bind CoreML và trả exit code `1` với lỗi nêu `CoreMLExecutionProvider` nếu không đạt.
  Tag: [judgment]
  File: recognize_stream.py:1,111-144,889-903

- [x] #11 Bổ sung regression tests cho platform gate và CLI contract
  DoD: Tests xác nhận `--require-gpu` vẫn parse như trước, help text đề cập CUDA và CoreML, unsupported runtime khiến `main()` trả `1` trước khi khởi tạo `FaceEngine`, và stderr không còn thông báo “Windows only”.
  Tag: [mechanical]
  File: tests/test_recognize_stream.py:31-84

## Batch 4 — CLI reference

- [x] #12 Cập nhật metadata platform cho recognition CLIs
  DoD: Generator mô tả `recognize_stream.py` và `recognize_image.py` hỗ trợ “Windows AMD64 (CUDA) and macOS Apple Silicon (CoreML)” mà không thay đổi metadata của các command khác.
  Tag: [mechanical]
  File: scripts/generate_cli_reference.py:51-62

- [x] #13 Regenerate CLI reference và cập nhật capability matrix
  DoD: Auto-generated section khớp hoàn toàn với parser mới; `--require-gpu` có mô tả accelerator mới; platform matrix đánh dấu recognition trên macOS là CoreML với CPU fallback; `tests/test_cli_reference.py` không báo drift.
  Tag: [mechanical]
  File: docs/CLI_REFERENCE.md:13-124,289-312

## Batch 5 — Tài liệu cài đặt và vận hành

- [x] #14 Cập nhật phạm vi hỗ trợ và hướng dẫn cài recognition trên macOS
  DoD: README nêu rõ macOS Apple Silicon/macOS 14+/Python 3.12, cài `requirements-recognition-macos.txt` rồi `insightface==1.0.1 --no-deps`, dùng official `onnxruntime` wheel, và cảnh báo không cài song song các biến thể ONNX Runtime khác hoặc để InsightFace thay thế `opencv-contrib-python`.
  Tag: [judgment]
  File: README.md:1-8,40-50,106-130

- [x] #15 Thêm quy trình chạy và xử lý lỗi CoreML vào README
  DoD: Realtime section có lệnh macOS dùng `--require-gpu`, expected logs cho cả SCRFD và ArcFace chứa CoreML, lệnh kiểm tra `ort.get_available_providers()`, lệnh kiểm tra `FaceEngine.provider_status.gpu_active`, giải thích `MLComputeUnits=ALL`, CoreML partial fallback, first-run model compilation và troubleshooting khi chỉ thấy CPU.
  Tag: [judgment]
  File: README.md:312-362,444-448,510-517,550-588

- [x] #16 Cập nhật role matrix và fresh setup trong runbook
  DoD: Cloud consumer role bao gồm Windows CUDA và macOS CoreML; fresh setup có command riêng cho macOS recognition, yêu cầu macOS 14+, Python 3.12 và bước `pip check`; các bước Windows hiện có không bị thay đổi về dependency.
  Tag: [mechanical]
  File: docs/RUNBOOK.md:1-42

- [x] #17 Thêm command vận hành macOS và troubleshooting CoreML vào runbook
  DoD: Cloud consumer sections có Bash command tương đương PowerShell flow, sử dụng `--require-gpu`, expected provider logs cho hai model, hướng dẫn phân biệt CoreML unavailable với model fallback, và không tuyên bố session binding đồng nghĩa toàn bộ operator chạy trên GPU.
  Tag: [judgment]
  File: docs/RUNBOOK.md:174-225,361-383,420-433

- [x] #18 Cập nhật kiến trúc cloud recognition thành đa nền tảng
  DoD: Architecture mô tả Windows CUDA và macOS CoreML, provider order, CPU fallback, điều kiện fail-fast cho cả SCRFD lẫn ArcFace, và giữ nguyên các invariants latest-frame, tracking, embedding budget, FAISS cosine similarity và MQTT.
  Tag: [judgment]
  File: docs/ARCHITECTURE.md:22-38,127-140,182-193

## Batch 6 — Contributor contract và trạng thái dự án

- [x] #19 Cập nhật contributor guide cho macOS CoreML
  DoD: Scope, setup, recognition workflow và accelerator requirements đề cập cả Windows CUDA lẫn macOS CoreML; guide vẫn yêu cầu `insightface --no-deps`, provider verification cho cả hai model và giữ Linux recognition ngoài phạm vi.
  Tag: [mechanical]
  File: AGENTS.md:5-19

- [x] #20 Cập nhật recognition optimization invariants và validation protocol
  DoD: `--require-gpu` invariant dùng platform accelerator thay vì CUDA-only; real-model validation và benchmark protocol có nhánh macOS CoreML, yêu cầu cả SCRFD và ArcFace bind CoreML, nhưng không thay đổi scheduling, tracking hoặc embedding contracts.
  Tag: [judgment]
  File: docs/plans/RECOGNITION_OPTIMIZATION_PLAN.md:40-54,142-185

- [x] #21 Cập nhật implementation review theo capability mới
  DoD: Progress table ghi nhận code support Windows/macOS nhưng phân biệt rõ trạng thái hardware validation; CUDA verification gap cũ được thay bằng yêu cầu kiểm tra cả detector và recognizer trên từng platform; không đánh dấu macOS “validated” trước khi Batch 8 hoàn tất.
  Tag: [judgment]
  File: docs/plans/IMPLEMENTATION_REVIEW.md:14-26,72-100

- [x] #22 Thêm backlog item cho CoreML hardware evidence và benchmark
  DoD: Backlog có item riêng để ghi macOS model/session providers, static recognition result, live `--require-gpu` run, warm-up latency, detector latency, embedding latency và CPU/GPU/ANE observations; chỉ đánh dấu hoàn tất sau Batch 8.
  Tag: [mechanical]
  File: BACKLOG.md:208-229

## Batch 7 — Automated verification

- [x] #23 Chạy targeted provider, CLI và generated-reference tests
  DoD: `python -m unittest tests.test_face_engine tests.test_recognize_stream tests.test_cli_reference -v` trả exit code `0`, và chạy lại `python scripts/generate_cli_reference.py` không tạo thêm diff.
  Tag: [mechanical]
  File: tests/test_face_engine.py, tests/test_recognize_stream.py, tests/test_cli_reference.py, docs/CLI_REFERENCE.md

- [x] #24 Chạy toàn bộ unit test suite
  DoD: `python -m unittest discover -s tests -v` trả exit code `0`; chỉ các integration tests được tài liệu hóa mới được phép skip; không có regression ở streaming, tracking, FAISS, MQTT hoặc dashboard.
  Tag: [mechanical]
  File: tests/

- [x] #25 Kiểm tra hygiene của thay đổi
  DoD: `git diff --check` không báo whitespace error; `git status --short` chỉ liệt kê các file trong plan; diff không chứa enrollment images, FAISS index, SQLite database, model files, CoreML cache, certificates hoặc secrets.
  Tag: [mechanical]
  File: repository working tree

## Batch 8 — Hardware validation

- [x] #26 Xác minh môi trường macOS Apple Silicon có CoreML EP
  DoD: Trên macOS 14+ ARM64, clean Python 3.12 venv cài thành công requirements chung, requirements macOS và `insightface==1.0.1 --no-deps`; `pip check` thành công; `ort.get_available_providers()` chứa `CoreMLExecutionProvider`; không có package ONNX Runtime cạnh tranh trong môi trường.
  Tag: [judgment]
  File: External validation — macOS Apple Silicon host

- [x] #27 Xác minh SCRFD và ArcFace cùng bind CoreML
  DoD: Khởi tạo `FaceEngine` với model `buffalo_l` thành công; detector và recognition session providers đều chứa `CoreMLExecutionProvider` trước `CPUExecutionProvider`; `engine.provider_status.gpu_active` là true; không có log cho thấy `prepare()` đã reset session về CPU.
  Tag: [judgment]
  File: External validation — macOS Apple Silicon host and ~/.insightface/models/buffalo_l/

- [x] #28 Xác minh enrollment và static recognition trên macOS
  DoD: `python build_index.py` tạo index từ một local one-face dataset; `python recognize_image.py <known-image>` hoàn tất và trả đúng enrolled identity; embedding có dtype `float32`, norm xấp xỉ `1.0`, và index vẫn là `IndexFlatIP`.
  Tag: [judgment]
  File: External validation — macOS Apple Silicon host with local dataset/ and database/

- [x] #29 Xác minh realtime recognition bắt buộc CoreML trên macOS
  DoD: `python recognize_stream.py --recognition-fps 2 --profile --require-gpu` chạy ít nhất 120 giây trên RTSP source thật, startup logs cho thấy CoreML trên cả SCRFD và ArcFace, không fallback toàn bộ sang CPU, profile tiếp tục báo detection/embedding cycles, và ít nhất một enrolled face được nhận diện.
  Tag: [judgment]
  File: External validation — macOS Apple Silicon host and RTSP camera source

- [ ] #30 Chạy hồi quy CUDA trên Windows AMD64
  DoD: Windows recognition venv vẫn cài từ requirements Windows; cả SCRFD và ArcFace dùng `CUDAExecutionProvider`; `--require-gpu` chạy thành công; build-index, static-image và realtime recognition không thay đổi kết quả hoặc provider order so với trước.
  Tag: [judgment]
  File: External validation — Windows AMD64 CUDA host

## Global Definition of Done

1. Batch 2 chỉ bắt đầu sau khi runtime contract và dependency pins ở Batch 1 được chốt; Batch 3 phụ thuộc API của Batch 2; documentation chỉ được regenerate sau khi CLI behavior ổn định.
2. Automated support hoàn tất khi Batches 1–7 pass; tuyên bố “macOS CoreML validated” chỉ được dùng sau khi toàn bộ Batch 8 pass.
3. Windows CUDA behavior, CPU fallback mặc định, RTSP TCP, latest-frame pipeline, một embedding mặc định mỗi cycle, normalized embeddings và FAISS cosine search không được thay đổi.
4. Trên macOS, `--require-gpu` chỉ bảo đảm CoreML EP được bind vào cả hai ONNX sessions; tài liệu không được diễn giải điều này thành GPU-only execution.

## Out of scope

- Cấm toàn bộ CPU operator fallback bằng `session.disable_cpu_ep_fallback`.
- Ép CoreML chỉ dùng GPU hoặc chỉ dùng Neural Engine; quyết định hiện tại là `MLComputeUnits=ALL`.
- Đổi tên hoặc xóa `--require-gpu` và các field `gpu_requested`/`gpu_active`.
- Thêm CLI chọn provider hoặc compute units.
- CoreML compiled-model cache, model conversion, quantization hoặc custom ONNX Runtime build.
- Recognition trên Linux ARM64, Intel Mac hoặc Windows ARM64.
- Thay model `buffalo_l`, tracker, embedding scheduler, FAISS implementation hoặc threshold calibration.
- Gộp các backlog fixes không liên quan đến macOS CoreML support.
